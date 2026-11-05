# functions_excel_inventory.py
"""Version-bound, paged Excel inventories in the existing private artifact store."""

import base64
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import logging
import os
import tempfile
from threading import RLock
from uuid import uuid4

from azure.core.exceptions import AzureError, ResourceNotFoundError

from content_screening.contracts import ScreeningError, Subject, subject_from_document
from functions_appinsights import log_event
from functions_excel_accessibility import extract_excel_accessibility_metadata
from excel_workbook_reader import EXCEL_WORKBOOK_SCHEMA_VERSION


EXCEL_INVENTORY_FIELD = "excel_native_inventory"
EXCEL_INVENTORY_SECTIONS = frozenset({
    "comments", "objects", "tables", "defined_names", "hyperlinks", "validations",
    "property_records", "custom_properties", "extended_properties",
    "image_analyses",
})
EXCEL_INVENTORY_PART_BYTES = 256 * 1024
EXCEL_INVENTORY_PART_RECORDS = 100
EXCEL_INVENTORY_PAGE_BYTES = 14000
EXCEL_INVENTORY_CACHE_BYTES = 16 * 1024 * 1024
_CACHE = OrderedDict()
_CACHE_LOCK = RLock()


class ExcelInventoryPersistenceError(ScreeningError):
    code = "excel_inventory_unavailable"
    public_message = "The workbook inspection could not be stored. Retry the operation."


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _source_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for data in iter(lambda: source.read(65536), b""):
            digest.update(data)
    return digest.hexdigest()


def _cache_key(subject, source_digest, storage, cache_namespace=None):
    namespace = cache_namespace if cache_namespace is not None else id(storage)
    return subject.key, source_digest, EXCEL_WORKBOOK_SCHEMA_VERSION, namespace


def _remember(key, manifest, reference):
    size = len(_encoded(manifest))
    if size > EXCEL_INVENTORY_CACHE_BYTES:
        return
    with _CACHE_LOCK:
        _CACHE.pop(key, None)
        while _CACHE and (
            len(_CACHE) >= 16
            or sum(entry[2] for entry in _CACHE.values()) + size > EXCEL_INVENTORY_CACHE_BYTES
        ):
            _CACHE.popitem(last=False)
        _CACHE[key] = (deepcopy(manifest), deepcopy(reference), size)


def clear_excel_inventory_cache(subject=None):
    with _CACHE_LOCK:
        for key in list(_CACHE):
            if subject is None or key[0] == subject.key:
                del _CACHE[key]


class ExcelInventoryWriter:
    """Write bounded immutable pages, then atomically publish their manifest."""

    def __init__(self, storage, subject, source_digest, capture=None):
        if not isinstance(subject, Subject):
            raise TypeError("An authorized workbook subject is required.")
        self.storage = storage
        self.subject = subject
        self.source_digest = source_digest
        self.capture = capture
        self.scan_id = f"excel-native:{EXCEL_WORKBOOK_SCHEMA_VERSION}:{source_digest}:{uuid4().hex}"
        self.pages = []
        self.buffers = {}
        self.sizes = {}
        self.counts = {}

    def _write(self, name, value):
        try:
            return self.storage.write_json(self.subject, self.scan_id, name, value)
        except (AzureError, ScreeningError, OSError, RuntimeError, ValueError, TypeError) as error:
            log_event(
                "[DOCUMENT_METADATA] Excel inventory persistence failed.",
                level=logging.ERROR,
                extra={"document_id": self.subject.document_id, "error_type": type(error).__name__},
            )
            raise ExcelInventoryPersistenceError() from error

    def add(self, collection, record):
        if collection not in EXCEL_INVENTORY_SECTIONS or not isinstance(record, dict):
            raise ValueError("An Excel inventory record is invalid.")
        payload = _encoded(record)
        if self.capture is not None:
            self.capture.add_supplement(payload.decode("utf-8"), kind="excel_native")
        records = self.buffers.setdefault(collection, [])
        if records and (
            self.sizes.get(collection, 0) + len(payload) > EXCEL_INVENTORY_PART_BYTES
            or len(records) >= EXCEL_INVENTORY_PART_RECORDS
        ):
            self._flush(collection)
            records = self.buffers[collection]
        records.append(record)
        self.sizes[collection] = self.sizes.get(collection, 0) + len(payload)
        self.counts[collection] = self.counts.get(collection, 0) + 1

    def _flush(self, collection):
        records = self.buffers.get(collection) or []
        if not records:
            return
        first = self.counts[collection] - len(records)
        reference = self._write(f"excel-{collection}-{first}", records)
        self.pages.append({
            "section": collection, "first": first, "count": len(records), "reference": reference,
        })
        self.buffers[collection] = []
        self.sizes[collection] = 0

    def finish(self, metadata):
        metadata.pop("image_locations", None)
        for collection in list(self.buffers):
            self._flush(collection)
        complete = (
            metadata.get("coverage") != "failed"
            and not metadata.get("incomplete_sheets")
            and metadata.get("sheet_count") == metadata.get("scanned_sheet_count", len(metadata.get("sheets") or []))
        )
        metadata["inventory_storage"] = {
            "schema_version": EXCEL_WORKBOOK_SCHEMA_VERSION, "source_sha256": self.source_digest,
            "status": "ready" if complete else "partial",
            "counts": dict(self.counts), "page_count": len(self.pages),
        }
        manifest = {
            "schema_version": EXCEL_WORKBOOK_SCHEMA_VERSION, "subject": self.subject.to_dict(),
            "source_sha256": self.source_digest, "metadata": metadata,
            "complete": complete, "counts": dict(self.counts), "pages": self.pages,
        }
        manifest_reference = self._write("excel-manifest", manifest)
        reference = {
            "schema_version": EXCEL_WORKBOOK_SCHEMA_VERSION,
            "source_sha256": self.source_digest, "manifest": manifest_reference,
        }
        _remember(_cache_key(self.subject, self.source_digest, self.storage), manifest, reference)
        return reference


def persist_excel_inventory(file_path, extension, *, subject, storage, capture=None, enrich=None):
    digest = _source_digest(file_path)
    writer = ExcelInventoryWriter(storage, subject, digest, capture=capture)
    metadata, evidence = extract_excel_accessibility_metadata(
        file_path, extension, record_sink=writer.add,
        progress_callback=capture.heartbeat if capture is not None else None,
    )
    if enrich is not None:
        enrich(metadata, evidence, writer.add)
    reference = writer.finish(metadata)
    return metadata, evidence, reference


def _validate_manifest(manifest, subject, digest):
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != EXCEL_WORKBOOK_SCHEMA_VERSION
        or manifest.get("subject") != subject.to_dict()
        or manifest.get("source_sha256") != digest
        or not isinstance(manifest.get("metadata"), dict)
        or not isinstance(manifest.get("counts"), dict)
        or not isinstance(manifest.get("pages"), list)
        or type(manifest.get("complete")) is not bool
    ):
        raise ValueError("The Excel inventory does not match the authorized source.")
    counts = {}
    for page in manifest["pages"]:
        section = page.get("section")
        if (
            section not in EXCEL_INVENTORY_SECTIONS
            or type(page.get("first")) is not int or page["first"] < 0
            or type(page.get("count")) is not int or not 1 <= page["count"] <= EXCEL_INVENTORY_PART_RECORDS
            or page["first"] != counts.get(section, 0)
            or not isinstance(page.get("reference"), dict)
        ):
            raise ValueError("The Excel inventory page mapping is invalid.")
        counts[section] = counts.get(section, 0) + page["count"]
    if counts != manifest["counts"]:
        raise ValueError("The Excel inventory counts are invalid.")


def open_excel_inventory(document, source_bytes, extension, *, storage, authorize, cache_namespace=None):
    """The caller supplies freshly authorized, active-representation bytes."""
    if not callable(authorize) or not isinstance(source_bytes, bytes):
        raise TypeError("Authorized source bytes and a source check are required.")
    authorize()
    subject = subject_from_document(document)
    digest = hashlib.sha256(source_bytes).hexdigest()
    key = _cache_key(subject, digest, storage, cache_namespace)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            manifest, reference = deepcopy(cached[:2])
        else:
            manifest = reference = None
    if manifest is None:
        stored = document.get(EXCEL_INVENTORY_FIELD)
        if (
            isinstance(stored, dict)
            and stored.get("schema_version") == EXCEL_WORKBOOK_SCHEMA_VERSION
            and stored.get("source_sha256") == digest
            and isinstance(stored.get("manifest"), dict)
            and stored["manifest"].get("subject_key") == subject.key
        ):
            try:
                manifest = storage.read_json(stored["manifest"], subject)
                reference = stored
            except ResourceNotFoundError:
                log_event(
                    "[DOCUMENT_METADATA] Rebuilding an unavailable derived Excel inventory.",
                    level=logging.INFO, extra={"document_id": subject.document_id},
                )
        if manifest is None:
            with tempfile.TemporaryDirectory(prefix="simplechat_excel_inventory_") as folder:
                path = os.path.join(folder, "source" + extension)
                with open(path, "wb") as source:
                    source.write(source_bytes)
                _, _, reference = persist_excel_inventory(path, extension, subject=subject, storage=storage)
            manifest = storage.read_json(reference["manifest"], subject)
        _validate_manifest(manifest, subject, digest)
        _remember(key, manifest, reference)
    _validate_manifest(manifest, subject, digest)
    authorize()
    return ExcelInventoryReader(storage, subject, manifest, reference, authorize)


def open_stored_excel_inventory(document, *, storage, authorize):
    """Read an immutable revision inventory without downloading its workbook again."""
    authorize()
    reference = document.get(EXCEL_INVENTORY_FIELD)
    if not isinstance(reference, dict) or reference.get("schema_version") != EXCEL_WORKBOOK_SCHEMA_VERSION:
        return None
    subject = subject_from_document(document)
    digest = reference.get("source_sha256")
    stored = reference.get("manifest")
    if (
        not isinstance(digest, str) or len(digest) != 64
        or not isinstance(stored, dict) or stored.get("subject_key") != subject.key
    ):
        return None
    active = (document.get("content_screening") or {}).get("active_blob") or {}
    if active.get("content_hash") and active["content_hash"] != digest:
        return None
    manifest = storage.read_json(stored, subject)
    _validate_manifest(manifest, subject, digest)
    authorize()
    return ExcelInventoryReader(storage, subject, manifest, reference, authorize)


class ExcelInventoryReader:
    def __init__(self, storage, subject, manifest, reference, authorize):
        self.storage = storage
        self.subject = subject
        self.manifest = manifest
        self.reference = reference
        self.authorize = authorize

    @property
    def metadata(self):
        self.authorize()
        return deepcopy(self.manifest["metadata"])

    def _cursor(self, section, offset, fragment=0):
        return base64.urlsafe_b64encode(_encoded({
            "subject": self.subject.key, "source": self.manifest["source_sha256"],
            "section": section, "offset": offset, "fragment": fragment,
        })).decode("ascii").rstrip("=")

    def _parse_cursor(self, token, section):
        if not isinstance(token, str) or not token or len(token) > 1024:
            raise ValueError("The Excel inspection cursor is invalid.")
        try:
            value = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True))
        except (ValueError, UnicodeError) as error:
            raise ValueError("The Excel inspection cursor is invalid.") from error
        if (
            not isinstance(value, dict) or set(value) != {"subject", "source", "section", "offset", "fragment"}
            or value["subject"] != self.subject.key or value["source"] != self.manifest["source_sha256"]
            or value["section"] != section
            or any(type(value[key]) is not int or value[key] < 0 for key in ("offset", "fragment"))
        ):
            raise ValueError("The Excel inspection cursor belongs to a different source or section.")
        return value["offset"], value["fragment"]

    def page(self, section="comments", *, cursor=None, page_size=100, max_bytes=EXCEL_INVENTORY_PAGE_BYTES):
        if section not in EXCEL_INVENTORY_SECTIONS:
            raise ValueError("The requested Excel inventory section is invalid.")
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise ValueError("The Excel inventory page size must be between 1 and 200.")
        if type(max_bytes) is not int or not 2048 <= max_bytes <= 65536:
            raise ValueError("The Excel inventory response budget is invalid.")
        self.authorize()
        offset, fragment = self._parse_cursor(cursor, section) if cursor else (0, 0)
        total = self.manifest["counts"].get(section, 0)
        if offset > total or offset == total and fragment:
            raise ValueError("The Excel inspection cursor is outside the inventory.")
        records, used, next_offset, next_fragment = [], 0, offset, 0
        record_budget = max_bytes - 1024
        for page in self.manifest["pages"]:
            if page["section"] != section or page["first"] + page["count"] <= offset:
                continue
            self.authorize()
            values = self.storage.read_json(page["reference"], self.subject)
            if not isinstance(values, list) or len(values) != page["count"] or any(not isinstance(value, dict) for value in values):
                raise ValueError("The Excel inventory page failed its record check.")
            self.authorize()
            for index in range(max(offset - page["first"], 0), len(values)):
                record = values[index]
                encoded = _encoded(record)
                if records and (len(records) >= page_size or used + len(encoded) > record_budget):
                    break
                if not records and (len(encoded) > record_budget or fragment):
                    serialized = encoded.decode("utf-8")
                    if fragment >= len(serialized):
                        raise ValueError("The Excel record continuation is invalid.")
                    low, high = 1, min(len(serialized) - fragment, record_budget)
                    result = None
                    while low <= high:
                        middle = (low + high) // 2
                        candidate = {
                            "sheet": record.get("sheet"), "cell": record.get("cell"), "id": record.get("id"),
                            "record_json_fragment": serialized[fragment:fragment + middle],
                            "fragment_offset": fragment, "record_characters": len(serialized),
                            "record_fragment": True,
                        }
                        if len(_encoded(candidate)) <= record_budget:
                            result = candidate
                            low = middle + 1
                        else:
                            high = middle - 1
                    if result is None:
                        raise ValueError("The Excel record cannot fit the requested response budget.")
                    piece = result["record_json_fragment"]
                    end = fragment + len(piece)
                    records.append(result)
                    if end < len(serialized):
                        next_offset, next_fragment = page["first"] + index, end
                    else:
                        next_offset = page["first"] + index + 1
                    break
                records.append(record)
                used += len(encoded)
                next_offset = page["first"] + index + 1
            if next_fragment or len(records) >= page_size or next_offset < page["first"] + page["count"]:
                break
        self.authorize()
        has_more = next_offset < total or bool(next_fragment)
        return {
            "section": section, "records": records, "total_records": total,
            "returned_records": len(records), "start_record": offset,
            "complete": bool(self.manifest["complete"] and not has_more and offset == 0),
            "inventory_complete": self.manifest["complete"], "has_more": has_more,
            "next_cursor": self._cursor(section, next_offset, next_fragment) if has_more else None,
            "source_sha256": self.manifest["source_sha256"],
        }
