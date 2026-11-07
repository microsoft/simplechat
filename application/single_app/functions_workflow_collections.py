# functions_workflow_collections.py
"""
Bounded, immutable complete-record collections over the existing result transport.
Version: 0.261.117
Implemented in: 0.261.117

Callers authorize sources and commit their aggregate manifest last. This module
only checks storage integrity; it does not create Analyze metadata or authorize
the producer. Callbacks retain responsibility for transport digest verification.

Leaves use ordinary result envelopes. An index envelope has kind ``record_tree``
and value {version, record_kind, level, offset, record_count, children}. Each
child is {output_name, level, offset, count, result_ref}; leaves have level zero.
Names bind a child's level and first ordinal to its collection. Only finish()
writes the root envelope under the collection's actual output name.
"""

import heapq
import json
import re
from collections.abc import Mapping


RECORD_PAGE_SIZE = 100
RECORD_PAGE_BYTES = 128 * 1024
RECORD_INDEX_FANOUT = 100
COLLECTION_MATERIALIZATION_BYTES = 8 * 1024 * 1024
MAX_RECORD_TREE_LEVEL = 32
MAX_RECORD_COUNT = (1 << 63) - 1
MAX_IDENTITY_RUN_LEVELS = 64
_IDENTITY_BYTES = RECORD_PAGE_BYTES // 4
_RECORD_KINDS = frozenset({"records", "document_results"})
_ENVELOPE_FIELDS = frozenset({"contract_version", "producer", "output_name", "kind", "value"})
_INDEX_FIELDS = frozenset({"version", "record_kind", "level", "offset", "record_count", "children"})
_CHILD_FIELDS = frozenset({"output_name", "level", "offset", "count", "result_ref"})
_OUTPUT_FIELDS = frozenset({"kind", "storage_kind", "result_ref", "record_count"})
_REFERENCE_FIELDS = frozenset({"storage", "schema_version", "sha256", "size_bytes", "chunk_count"})
_COMPACT_REFERENCE_FIELDS = frozenset({"sha256", "size_bytes"})
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")


class CollectionIntegrityError(ValueError):
    """A complete-record envelope, range, or immutable reference is invalid."""


class CollectionSizeError(ValueError):
    """A collection exceeds a materialization or cumulative storage bound."""


def _integer(value, minimum=0, maximum=MAX_RECORD_COUNT):
    return type(value) is int and minimum <= value <= maximum


def _encode(value, max_bytes):
    encoder = json.JSONEncoder(
        ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"),
    )
    payload = bytearray()
    try:
        for fragment in encoder.iterencode(value):
            if len(payload) + len(fragment) > max_bytes:
                raise CollectionSizeError("The collection section exceeds its complete-record byte limit.")
            payload.extend(fragment.encode("ascii"))
    except CollectionSizeError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise CollectionIntegrityError("Collection data must contain valid JSON values.") from exc
    return bytes(payload)


def _identifier(value):
    if not isinstance(value, str) or not value:
        raise CollectionIntegrityError("Collection names and contract versions must be nonempty strings.")
    _encode(value, 1024)
    return value


def _producer(identity):
    if not isinstance(identity, Mapping) or not identity:
        raise CollectionIntegrityError("A collection requires its exact producer identity.")
    encoded = _encode(dict(identity), _IDENTITY_BYTES)
    copied = json.loads(encoded)
    if copied != identity:
        raise CollectionIntegrityError("The producer identity must contain JSON values without coercion.")
    return copied, encoded


def _reference(reference, max_bytes=COLLECTION_MATERIALIZATION_BYTES):
    # Small callback-only transports may omit backend metadata. Production
    # references must retain the complete existing five-field transport shape.
    if not isinstance(reference, Mapping) or set(reference) not in (
        _REFERENCE_FIELDS, _COMPACT_REFERENCE_FIELDS,
    ):
        raise CollectionIntegrityError("The collection result reference is invalid.")
    if (
        not isinstance(reference.get("sha256"), str)
        or _DIGEST_PATTERN.fullmatch(reference["sha256"]) is None
        or not _integer(reference.get("size_bytes"), 1)
    ):
        raise CollectionIntegrityError("The collection result digest or byte count is invalid.")
    if reference["size_bytes"] > max_bytes:
        raise CollectionSizeError("A saved collection section exceeds its materialization byte limit.")
    if "storage" in reference:
        storage = reference["storage"]
        count = reference["chunk_count"]
        if (
            storage not in ("blob", "cosmos")
            or type(reference["schema_version"]) is not int or reference["schema_version"] != 1
            or type(count) is not int
            or (count != 0 if storage == "blob" else not _integer(count, 1))
        ):
            raise CollectionIntegrityError("The collection storage reference is invalid.")
    return dict(reference)


def _child_name(name, level, offset):
    return f"{name}:leaf:{offset}" if level == 0 else f"{name}:index:{level}:{offset}"


class CollectionWriteBudget:
    """One cumulative quota for records, lineage, coverage, keys, and indexes.

    Share this object across all writers for an aggregate. save_section() also
    charges noncollection sections and the final manifest. Failed writes are
    never refunded: the transport might have persisted data before failing.
    """

    def __init__(self, max_bytes):
        if not _integer(max_bytes, 1):
            raise ValueError("The collection byte quota must be a positive integer.")
        self.max_bytes = max_bytes
        self.used_bytes = 0
        self._failed = False

    @property
    def remaining_bytes(self):
        return self.max_bytes - self.used_bytes

    def consume(self, size_bytes):
        """Charge externally persisted bytes against this same aggregate quota."""
        if self._failed:
            raise CollectionSizeError("The collection write budget is unavailable after a failed write.")
        if not _integer(size_bytes, 1):
            raise ValueError("The collection byte charge must be a positive integer.")
        if size_bytes > self.remaining_bytes:
            self._failed = True
            raise CollectionSizeError("The complete collection exceeds its cumulative byte quota.")
        self.used_bytes += size_bytes

    def _save_encoded(self, encoded, save_section, max_section_bytes):
        try:
            self.consume(len(encoded))
            reference = _reference(save_section(json.loads(encoded)), max_section_bytes)
            if reference["size_bytes"] < len(encoded):
                raise CollectionIntegrityError("The collection reference underreports its serialized byte count.")
            if reference["size_bytes"] > len(encoded):
                self.consume(reference["size_bytes"] - len(encoded))
            return reference
        except Exception:
            self._failed = True
            raise

    def save_section(self, section, save_section, *, max_section_bytes=COLLECTION_MATERIALIZATION_BYTES):
        """Save a caller-owned section without giving it a separate full quota."""
        if not _integer(max_section_bytes, 1, COLLECTION_MATERIALIZATION_BYTES):
            raise ValueError("The section materialization bound is invalid.")
        encoded = _encode(section, max_section_bytes)
        return self._save_encoded(encoded, save_section, max_section_bytes)


class RecordTreeWriter:
    """Append exact JSON objects with one leaf and at most 100 refs per level.

    Index height is explicitly bounded, rather than hiding an all-page ledger.
    The supported ordinal range is signed 64-bit; even its worst case fits well
    inside the tree depth bound. A failed writer cannot subsequently finish.
    """

    def __init__(
        self, identity, output_name, kind, save_section, *,
        max_result_bytes, contract_version="workflow-result-v2", budget=None,
    ):
        self._identity, _ = _producer(identity)
        self.output_name = _identifier(output_name)
        self.contract_version = _identifier(contract_version)
        if not isinstance(kind, str) or kind not in _RECORD_KINDS:
            raise ValueError("A record tree requires records or document_results.")
        if not callable(save_section):
            raise ValueError("A collection section writer is required.")
        if not _integer(max_result_bytes, 1):
            raise ValueError("The collection byte quota must be a positive integer.")
        if budget is not None and not isinstance(budget, CollectionWriteBudget):
            raise ValueError("A shared CollectionWriteBudget is required.")
        self.kind = kind
        self.max_result_bytes = max_result_bytes
        self.budget = budget if budget is not None else CollectionWriteBudget(max_result_bytes)
        self._save_section = save_section
        self._page = []
        self._page_bytes = 0
        self._page_offset = 0
        self._levels = []
        self._record_count = 0
        self._written_bytes = 0
        self._descriptor = None
        self._failed = False

    @property
    def record_count(self):
        return self._record_count

    @property
    def written_bytes(self):
        return self._written_bytes

    @property
    def descriptor(self):
        return None if self._descriptor is None else json.loads(json.dumps(self._descriptor))

    @property
    def buffered_record_count(self):
        return len(self._page)

    @property
    def buffered_record_bytes(self):
        return self._page_bytes

    @property
    def buffered_index_entries(self):
        return sum(len(entries) for entries in self._levels)

    @property
    def index_level_count(self):
        return len(self._levels)

    def _require_open(self):
        if self._failed:
            raise CollectionIntegrityError("A failed collection writer cannot produce a completed descriptor.")
        if self._descriptor is not None:
            raise CollectionIntegrityError("The immutable collection has already finished.")

    def _envelope(self, name, kind, value):
        return {
            "contract_version": self.contract_version, "producer": self._identity,
            "output_name": name, "kind": kind, "value": value,
        }

    def _persist(self, section, max_section_bytes):
        encoded = _encode(section, max_section_bytes)
        if len(encoded) > self.max_result_bytes - self._written_bytes:
            raise CollectionSizeError("The complete collection exceeds its cumulative byte quota.")
        before = self.budget.used_bytes
        reference = self.budget._save_encoded(encoded, self._save_section, max_section_bytes)
        self._written_bytes += self.budget.used_bytes - before
        if self._written_bytes > self.max_result_bytes:
            raise CollectionSizeError("The complete collection exceeds its cumulative byte quota.")
        return reference

    def append(self, record):
        self._require_open()
        try:
            if not isinstance(record, Mapping):
                raise CollectionIntegrityError("Every collection record must be a JSON object.")
            encoded = _encode(dict(record), COLLECTION_MATERIALIZATION_BYTES)
            copied = json.loads(encoded)
            if copied != record:
                raise CollectionIntegrityError("Collection records must contain JSON values without coercion.")
            if self._record_count == MAX_RECORD_COUNT:
                raise CollectionSizeError("The collection exceeds its supported ordinal range.")
            if self._page and self._page_bytes + len(encoded) + 1 > RECORD_PAGE_BYTES:
                self._flush_page()
            if not self._page:
                self._page_offset = self._record_count
                self._page_bytes = len(_encode(self._envelope(
                    _child_name(self.output_name, 0, self._page_offset), self.kind, [],
                ), COLLECTION_MATERIALIZATION_BYTES))
            next_bytes = self._page_bytes + len(encoded) + int(bool(self._page))
            if next_bytes > COLLECTION_MATERIALIZATION_BYTES:
                raise CollectionSizeError("A complete record exceeds the materialization byte limit.")
            self._page.append(copied)
            self._page_bytes = next_bytes
            self._record_count += 1
            if len(self._page) == RECORD_PAGE_SIZE or self._page_bytes >= RECORD_PAGE_BYTES:
                self._flush_page()
        except Exception:
            self._failed = True
            raise

    def _flush_page(self):
        if not self._page:
            return
        count = len(self._page)
        name = _child_name(self.output_name, 0, self._page_offset)
        reference = self._persist(
            self._envelope(name, self.kind, self._page),
            COLLECTION_MATERIALIZATION_BYTES if count == 1 else RECORD_PAGE_BYTES,
        )
        entry = {
            "output_name": name, "level": 0, "offset": self._page_offset,
            "count": count, "result_ref": reference,
        }
        self._page = []
        self._page_bytes = 0
        self._push(entry)

    def _write_index(self, entries, level, *, root=False):
        if not _integer(level, 1, MAX_RECORD_TREE_LEVEL):
            raise CollectionSizeError("The collection index exceeds its supported depth.")
        offset = entries[0]["offset"] if entries else 0
        count = sum(entry["count"] for entry in entries)
        name = self.output_name if root else _child_name(self.output_name, level, offset)
        value = {
            "version": 1, "record_kind": self.kind, "level": level,
            "offset": offset, "record_count": count, "children": entries,
        }
        reference = self._persist(self._envelope(name, "record_tree", value), RECORD_PAGE_BYTES)
        return {
            "output_name": name, "level": level, "offset": offset,
            "count": count, "result_ref": reference,
        }

    def _push(self, entry):
        level = entry["level"]
        if level >= MAX_RECORD_TREE_LEVEL:
            raise CollectionSizeError("The collection index exceeds its supported depth.")
        while len(self._levels) <= level:
            self._levels.append([])
        entries = self._levels[level]
        entries.append(entry)
        if len(entries) == RECORD_INDEX_FANOUT:
            parent = self._write_index(entries, level + 1)
            self._levels[level] = []
            self._push(parent)

    def finish(self):
        if self._descriptor is not None:
            return self.descriptor
        self._require_open()
        try:
            self._flush_page()
            for level in range(len(self._levels)):
                entries = self._levels[level]
                if entries and any(self._levels[level + 1:]):
                    parent = self._write_index(entries, level + 1)
                    self._levels[level] = []
                    self._push(parent)
            occupied = [(level, entries) for level, entries in enumerate(self._levels) if entries]
            if len(occupied) > 1:
                raise CollectionIntegrityError("The collection index could not be sealed.")
            level, entries = occupied[0] if occupied else (0, [])
            root = self._write_index(entries, level + 1, root=True)
            if root["offset"] != 0 or root["count"] != self._record_count:
                raise CollectionIntegrityError("The collection root count does not match its records.")
            self._descriptor = {
                "kind": self.kind, "storage_kind": "record_tree",
                "result_ref": root["result_ref"], "record_count": self._record_count,
            }
            self._levels = []
            return self.descriptor
        except Exception:
            self._failed = True
            raise


class _RecordTreeReader:
    def __init__(self, manifest, name, load_section):
        if not isinstance(manifest, Mapping) or not isinstance(manifest.get("outputs"), Mapping):
            raise CollectionIntegrityError("A record tree requires a result manifest.")
        self.name = _identifier(name)
        self.contract_version = _identifier(manifest.get("contract_version"))
        self.identity, self._identity_bytes = _producer(manifest.get("identity"))
        output = manifest["outputs"].get(name)
        if (
            not isinstance(output, Mapping) or set(output) != _OUTPUT_FIELDS
            or output.get("storage_kind") != "record_tree"
            or not isinstance(output.get("kind"), str) or output["kind"] not in _RECORD_KINDS
            or not _integer(output.get("record_count"))
        ):
            raise CollectionIntegrityError("The requested output is not a valid record tree.")
        if not callable(load_section):
            raise ValueError("A collection section reader is required.")
        self.kind = output["kind"]
        self.total_count = output["record_count"]
        self._load_section = load_section
        self._root_ref = _reference(output["result_ref"], RECORD_PAGE_BYTES)
        self._root_children = self._load_index(
            self._root_ref, self.name, 0, self.total_count, None, {self._root_ref["sha256"]},
        )

    def _load(self, reference, name, kind, max_bytes):
        section = self._load_section(dict(reference))
        if (
            not isinstance(section, Mapping) or set(section) != _ENVELOPE_FIELDS
            or section.get("contract_version") != self.contract_version
            or section.get("output_name") != name or section.get("kind") != kind
            or not isinstance(section.get("producer"), Mapping)
            or _encode(dict(section["producer"]), _IDENTITY_BYTES) != self._identity_bytes
        ):
            raise CollectionIntegrityError("The saved collection section does not match its exact envelope.")
        if len(_encode(dict(section), max_bytes)) > reference["size_bytes"]:
            raise CollectionIntegrityError("The collection reference underreports its serialized byte count.")
        return section["value"]

    def _load_index(self, reference, name, offset, count, level, ancestors):
        value = self._load(reference, name, "record_tree", RECORD_PAGE_BYTES)
        if (
            not isinstance(value, Mapping) or set(value) != _INDEX_FIELDS
            or type(value.get("version")) is not int or value["version"] != 1
            or value.get("record_kind") != self.kind
            or not _integer(value.get("level"), 1, MAX_RECORD_TREE_LEVEL)
            or level is not None and value["level"] != level
            or not _integer(value.get("offset")) or value["offset"] != offset
            or not _integer(value.get("record_count")) or value["record_count"] != count
            or offset + count > MAX_RECORD_COUNT
            or count > RECORD_PAGE_SIZE * RECORD_INDEX_FANOUT ** value["level"]
        ):
            raise CollectionIntegrityError("The saved collection index range, kind, or count is invalid.")
        children = value["children"]
        if (
            not isinstance(children, list) or len(children) > RECORD_INDEX_FANOUT
            or (count > 0 and not children)
            or (count == 0 and (children or level is not None or value["level"] != 1))
        ):
            raise CollectionIntegrityError("The saved collection index fanout or empty range is invalid.")
        expected_offset = offset
        seen = set()
        for child in children:
            if (
                not isinstance(child, Mapping) or set(child) != _CHILD_FIELDS
                or not _integer(child.get("level"), 0, MAX_RECORD_TREE_LEVEL - 1)
                or child["level"] != value["level"] - 1
                or not _integer(child.get("offset")) or child["offset"] != expected_offset
                or not _integer(child.get("count"), 1)
                or child.get("output_name") != _child_name(self.name, child["level"], expected_offset)
                or child["count"] > RECORD_PAGE_SIZE * RECORD_INDEX_FANOUT ** child["level"]
            ):
                raise CollectionIntegrityError("The saved collection index contains a gap or invalid child.")
            bound = (
                COLLECTION_MATERIALIZATION_BYTES
                if child["level"] == 0 and child["count"] == 1 else RECORD_PAGE_BYTES
            )
            child_ref = _reference(child["result_ref"], bound)
            token = child_ref["sha256"]
            if token in ancestors or token in seen:
                raise CollectionIntegrityError("The saved collection index contains a cycle or duplicate reference.")
            seen.add(token)
            expected_offset += child["count"]
            if expected_offset > offset + count:
                raise CollectionIntegrityError("The saved collection index count does not match its children.")
        if expected_offset != offset + count:
            raise CollectionIntegrityError("The saved collection index contains an incomplete ordinal range.")
        return children

    def _walk(self, children, start, end, ancestors):
        for child in children:
            offset = child["offset"]
            child_end = offset + child["count"]
            if child_end <= start or offset >= end:
                continue
            reference = child["result_ref"]
            if child["level"] == 0:
                rows = self._load(
                    reference, child["output_name"], self.kind,
                    COLLECTION_MATERIALIZATION_BYTES if child["count"] == 1 else RECORD_PAGE_BYTES,
                )
                if (
                    not isinstance(rows, list) or len(rows) != child["count"]
                    or any(not isinstance(row, Mapping) for row in rows)
                ):
                    raise CollectionIntegrityError("The saved collection leaf count or record shape is invalid.")
                for index in range(max(start - offset, 0), min(end - offset, len(rows))):
                    yield rows[index]
            else:
                token = reference["sha256"]
                if token in ancestors:
                    raise CollectionIntegrityError("The saved collection index contains a cycle.")
                ancestors.add(token)
                try:
                    descendants = self._load_index(
                        reference, child["output_name"], offset, child["count"], child["level"], ancestors,
                    )
                    yield from self._walk(descendants, start, end, ancestors)
                finally:
                    ancestors.remove(token)

    def records(self, start, end):
        yield from self._walk(self._root_children, start, end, {self._root_ref["sha256"]})


def read_record_tree(manifest, name, load_section, *, offset=0, limit=RECORD_PAGE_SIZE):
    """Read complete records, checking visited indexes but not unrelated leaves.

    None retains the old reader's explicit whole-value operation, bounded by
    eight MiB. Any requested range exceeding that bound fails, never truncates.
    iter_record_tree() verifies every subtree without materializing the result.
    """
    if not _integer(offset) or limit is not None and not _integer(limit, 1):
        raise ValueError("The record range is invalid.")
    reader = _RecordTreeReader(manifest, name, load_section)
    if offset > reader.total_count:
        raise CollectionIntegrityError("The record offset exceeds the collection.")
    end = reader.total_count if limit is None else min(reader.total_count, offset + limit)
    records = []
    materialized_bytes = 2
    for record in reader.records(offset, end):
        materialized_bytes += len(_encode(record, COLLECTION_MATERIALIZATION_BYTES)) + int(bool(records))
        if materialized_bytes > COLLECTION_MATERIALIZATION_BYTES:
            raise CollectionSizeError("This collection requires explicit record batches; it was not truncated.")
        records.append(record)
    if len(records) != end - offset:
        raise CollectionIntegrityError("The requested collection range could not be reconstructed completely.")
    return records, reader.total_count


def iter_record_tree(manifest, name, load_section):
    """Traverse once with one leaf and one bounded index node per tree level."""
    reader = _RecordTreeReader(manifest, name, load_section)
    yield from reader.records(0, reader.total_count)


class RecordIdentityValidator:
    """Validate optional business keys with bounded sorted runs and binary merges.

    Accept (field, writer, loader), or (field, identity, saver, loader) with an
    explicit max_result_bytes and the aggregate's shared budget. The transport
    form defaults its sidecar output_name to "identity".

    add() does not append to the record writer or change payloads. All key runs,
    merge intermediates, and the final identity index share that writer's budget.
    finish() returns only missing/duplicate counts (duplicates count occurrences
    after the first). index_descriptor exposes the optional sorted sidecar under
    output_name. A None identity field performs no deduplication and writes none.
    """

    def __init__(
        self, identity_field, identity, save_section=None, load_section=None, *,
        max_result_bytes=None, budget=None, contract_version=None, output_name=None,
    ):
        if identity_field is not None:
            _identifier(identity_field)
            if not identity_field.strip():
                raise ValueError("The business identity field must not be blank.")
        if isinstance(identity, RecordTreeWriter):
            writer = identity
            if load_section is None:
                load_section = save_section
            elif save_section is not None:
                raise ValueError("Writer-based business-key validation requires only one section reader.")
            if (
                budget is not None and budget is not writer.budget
                or max_result_bytes is not None and (
                    not _integer(max_result_bytes, 1) or max_result_bytes != writer.max_result_bytes
                )
                or contract_version is not None and contract_version != writer.contract_version
            ):
                raise ValueError("Business-key validation must use the same writer budget, quota, and contract.")
            if output_name is None:
                output_name = f"{writer.output_name}:identity"
        else:
            if max_result_bytes is None:
                raise ValueError("Transport-based business-key validation requires an explicit byte quota.")
            if output_name is None:
                output_name = "identity"
            writer = RecordTreeWriter(
                identity, output_name, "records", save_section,
                max_result_bytes=max_result_bytes, budget=budget,
                contract_version=contract_version if contract_version is not None else "workflow-result-v2",
            )
        if not callable(load_section):
            raise ValueError("Business-key validation requires a section reader.")
        self.identity_field = identity_field
        self.output_name = _identifier(output_name)
        self._writer = writer
        self._load_section = load_section
        self._keys = []
        self._key_bytes = 0
        self._runs = []
        self._next_run = 0
        self._missing = 0
        self._counts = None
        self._index_descriptor = None
        self._failed = False

    @property
    def index_descriptor(self):
        return None if self._index_descriptor is None else json.loads(json.dumps(self._index_descriptor))

    @property
    def buffered_key_count(self):
        return len(self._keys)

    @property
    def buffered_key_bytes(self):
        return self._key_bytes

    @property
    def buffered_run_count(self):
        return sum(run is not None for run in self._runs)

    def _require_open(self):
        if self._failed or self._counts is not None:
            raise CollectionIntegrityError("The business-key validator is failed or already finished.")

    def _new_writer(self, name=None):
        if name is None:
            name = f"{self.output_name}:run:{self._next_run}"
            self._next_run += 1
        return RecordTreeWriter(
            self._writer._identity, name, "records", self._writer._save_section,
            max_result_bytes=self._writer.max_result_bytes,
            contract_version=self._writer.contract_version, budget=self._writer.budget,
        )

    def add(self, record):
        self._require_open()
        try:
            if self.identity_field is None:
                return
            identity = record.get(self.identity_field) if isinstance(record, Mapping) else None
            if type(identity) not in {str, int} or isinstance(identity, str) and not identity.strip():
                self._missing += 1
                return
            token = _encode(identity, COLLECTION_MATERIALIZATION_BYTES).decode("ascii")
            row = {"key": token}
            size = len(_encode(row, COLLECTION_MATERIALIZATION_BYTES)) + 1
            if self._keys and self._key_bytes + size > RECORD_PAGE_BYTES:
                self._flush_keys()
            self._keys.append(row)
            self._key_bytes += size
            if len(self._keys) == RECORD_PAGE_SIZE or self._key_bytes >= RECORD_PAGE_BYTES:
                self._flush_keys()
        except Exception:
            self._failed = True
            raise

    def _run(self, writer):
        return {"name": writer.output_name, "descriptor": writer.finish()}

    def _iter_keys(self, run):
        manifest = {
            "identity": self._writer._identity, "contract_version": self._writer.contract_version,
            "outputs": {run["name"]: run["descriptor"]},
        }
        previous = None
        for row in iter_record_tree(manifest, run["name"], self._load_section):
            if (
                set(row) != {"key"} or not isinstance(row["key"], str)
                or previous is not None and row["key"] < previous
            ):
                raise CollectionIntegrityError("The saved business-key run is not sorted or has an invalid key.")
            previous = row["key"]
            yield row

    def _merge(self, left, right):
        writer = self._new_writer()
        for row in heapq.merge(self._iter_keys(left), self._iter_keys(right), key=lambda item: item["key"]):
            writer.append(row)
        return self._run(writer)

    def _flush_keys(self):
        if not self._keys:
            return
        self._keys.sort(key=lambda row: row["key"])
        writer = self._new_writer()
        for row in self._keys:
            writer.append(row)
        run = self._run(writer)
        self._keys = []
        self._key_bytes = 0
        for level in range(MAX_IDENTITY_RUN_LEVELS):
            if len(self._runs) <= level:
                self._runs.append(None)
            if self._runs[level] is None:
                self._runs[level] = run
                return
            run = self._merge(self._runs[level], run)
            self._runs[level] = None
        raise CollectionSizeError("The business-key index exceeds its supported depth.")

    def finish(self):
        if self._counts is not None:
            return dict(self._counts)
        self._require_open()
        try:
            duplicates = 0
            if self.identity_field is not None:
                self._flush_keys()
                merged = None
                for level, run in enumerate(self._runs):
                    if run is not None:
                        merged = run if merged is None else self._merge(merged, run)
                        self._runs[level] = None
                writer = self._new_writer(self.output_name)
                previous = None
                if merged is not None:
                    for row in self._iter_keys(merged):
                        key = row["key"]
                        if key == previous:
                            duplicates += 1
                        previous = key
                        writer.append(row)
                self._index_descriptor = writer.finish()
            self._counts = {
                "missing_identity_count": self._missing,
                "duplicate_identity_count": duplicates,
            }
            self._runs = []
            return dict(self._counts)
        except Exception:
            self._failed = True
            raise
