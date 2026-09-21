# functions_orchestration_result_contracts.py
"""Opt-in retained-result contracts, independent of application startup and v1 plans."""

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields
from typing import ClassVar


TASK_RESULT_VERSION = "orchestration-task-result-v1"
RESULT_REF_VERSION = "orchestration-result-ref-v1"
INPUT_BINDING_VERSION = "orchestration-input-binding-v1"
COMPLETENESS_VERSION = "orchestration-completeness-v1"
RESULT_MANIFEST_VERSION = "orchestration-result-manifest-v2"
RESULT_RECEIPT_VERSION = "orchestration-result-receipt-v1"
EXTERNAL_SOURCE_VERSION = "orchestration-external-source-v1"
EXTERNAL_LINEAGE_VERSION = "orchestration-lineage-v2"
EXTERNAL_SOURCE_TYPES = frozenset({"web", "url", "deep_research", "agent", "action", "fact_memory"})
MAX_EXTERNAL_SOURCES = 64
RESULT_KINDS = frozenset({
    "records-v1", "text-v1", "markdown-v1", "structured-v1",
    "evidence-set-v1", "source-set-v1", "comparison-v1",
})
RESULT_STATES = frozenset({"pending", "partial", "complete", "invalid", "cancelled", "failed", "unavailable"})
RESULT_ROLES = frozenset({"gather", "reason", "render"})
REASON_CAPABILITIES = frozenset({"document_analyze", "document_compare", "tabular_analyze"})
MAX_OUTPUTS = 32
MAX_COLUMNS = 256
MAX_BINDING_STEPS = 64
MAX_DESCRIPTOR_BYTES = 128 * 1024
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_COLUMN_TYPES = frozenset({"string", "integer", "number", "boolean", "object", "array", "json"})
_OPAQUE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")


class ResultContractError(ValueError):
    """Invalid data is never repaired into a different successful result."""

    def __init__(self, code="result_contract_invalid"):
        self.code = code
        super().__init__("The orchestration result or input binding is invalid.")


class ResultNotReadyError(ResultContractError):
    def __init__(self):
        super().__init__("result_not_ready")


def identifier(value, *, limit=1024):
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ResultContractError("result_identity_invalid")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise ResultContractError("result_identity_invalid") from exc
    if size > limit:
        raise ResultContractError("result_identity_invalid")
    return value


def output_name(value):
    if type(value) is not str or _NAME.fullmatch(value) is None:
        raise ResultContractError("result_name_invalid")
    return value


def digest(value):
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ResultContractError("result_digest_invalid")
    return value


def integer(value, *, minimum=0):
    if type(value) is not int or not minimum <= value < 2 ** 63:
        raise ResultContractError("result_count_invalid")
    return value


def choice(value, options):
    if type(value) is not str or value not in options:
        raise ResultContractError()
    return value


def validate_json(value, depth=0):
    if depth > 64:
        raise ResultContractError("result_json_invalid")
    if value is None or type(value) in (str, bool, int):
        if type(value) is str:
            try:
                value.encode("utf-8")
            except UnicodeError as exc:
                raise ResultContractError("result_json_invalid") from exc
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for child in value:
            validate_json(child, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for key, child in value.items():
            validate_json(key, depth + 1)
            validate_json(child, depth + 1)
        return
    raise ResultContractError("result_json_invalid")


def canonical_bytes(value):
    validate_json(value)
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("ascii")


def canonical_digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _tuple(value, item_type, *, maximum):
    if type(value) is not tuple or len(value) > maximum or any(type(item) is not item_type for item in value):
        raise ResultContractError()


def _list(value):
    if type(value) is not list:
        raise ResultContractError()
    return value


def _wire(value):
    if isinstance(value, _Contract):
        return value.to_dict()
    if type(value) is tuple:
        return [_wire(item) for item in value]
    return value


class _Contract:
    VERSION: ClassVar[str | None] = None

    def to_dict(self):
        value = {field.name: _wire(getattr(self, field.name)) for field in fields(self)}
        if self.VERSION is not None:
            value = {"version": self.VERSION, **value}
        return value

    @classmethod
    def _values(cls, value):
        expected = {field.name for field in fields(cls)}
        if cls.VERSION is not None:
            expected.add("version")
        if type(value) is not dict or set(value) != expected:
            raise ResultContractError()
        if cls.VERSION is not None and value["version"] != cls.VERSION:
            raise ResultContractError("result_version_unsupported")
        return {key: item for key, item in value.items() if key != "version"}


@dataclass(frozen=True)
class ProducerIdentity(_Contract):
    user_id: str
    conversation_id: str
    run_id: str
    attempt_index: int
    step_id: str
    capability_id: str
    contract_version: str

    def __post_init__(self):
        for name in ("user_id", "conversation_id", "run_id", "step_id", "capability_id", "contract_version"):
            identifier(getattr(self, name))
        integer(self.attempt_index, minimum=1)

    @classmethod
    def from_dict(cls, value):
        return cls(**cls._values(value))


def result_receipt_binding(producer, input_fingerprint):
    if type(producer) is not ProducerIdentity:
        raise ResultContractError("result_producer_invalid")
    digest(input_fingerprint)
    return {
        "version": RESULT_RECEIPT_VERSION, "producer": producer.to_dict(),
        "input_fingerprint": input_fingerprint,
    }


@dataclass(frozen=True)
class ExternalSourceRef(_Contract):
    source_type: str
    capability_id: str
    reference_id: str
    audience: str
    content_sha256: str | None = None
    source_revision: str | None = None
    VERSION = EXTERNAL_SOURCE_VERSION

    def __post_init__(self):
        choice(self.source_type, EXTERNAL_SOURCE_TYPES)
        for value in (self.capability_id, self.reference_id, self.audience):
            if type(value) is not str or _OPAQUE_REFERENCE.fullmatch(value) is None:
                raise ResultContractError("result_external_identity_invalid")
        if self.content_sha256 is None and self.source_revision is None:
            raise ResultContractError("result_external_snapshot_required")
        if self.content_sha256 is not None:
            digest(self.content_sha256)
        if self.source_revision is not None:
            identifier(self.source_revision, limit=256)
            if any(ord(character) < 32 or ord(character) == 127 for character in self.source_revision):
                raise ResultContractError("result_external_snapshot_invalid")

    @classmethod
    def from_dict(cls, value):
        return cls(**cls._values(value))

    def identity(self):
        return self.source_type, self.capability_id, self.reference_id, self.audience


def validate_result_role(producer, role):
    if type(producer) is not ProducerIdentity:
        raise ResultContractError("result_producer_invalid")
    choice(role, RESULT_ROLES)
    if producer.capability_id in REASON_CAPABILITIES and role != "reason":
        raise ResultContractError("result_role_mismatch")


@dataclass(frozen=True)
class Coverage(_Contract):
    expected: int | None
    completed: int
    unit: str

    def __post_init__(self):
        integer(self.completed)
        if self.expected is not None:
            integer(self.expected)
            if self.completed > self.expected:
                raise ResultContractError("result_coverage_invalid")
        choice(self.unit, {"sources", "work_units", "records", "items"})

    @classmethod
    def from_dict(cls, value):
        return cls(**cls._values(value))


@dataclass(frozen=True)
class Completeness(_Contract):
    status: str
    expected_count: int | None
    actual_count: int
    coverage: Coverage
    validation: str
    checks: tuple[str, ...]
    limitations: tuple[str, ...]
    preview: bool = False
    VERSION = COMPLETENESS_VERSION

    def __post_init__(self):
        choice(self.status, RESULT_STATES)
        choice(self.validation, {"valid", "partial", "invalid", "pending", "not_validated"})
        integer(self.actual_count)
        if self.expected_count is not None:
            integer(self.expected_count)
            if self.actual_count > self.expected_count:
                raise ResultContractError("result_count_invalid")
        if type(self.coverage) is not Coverage or type(self.preview) is not bool:
            raise ResultContractError()
        for value in (self.checks, self.limitations):
            _tuple(value, str, maximum=32)
            for item in value:
                identifier(item, limit=1024)
        if self.status == "complete" and (
            self.preview or self.validation != "valid" or not self.checks
            or self.expected_count != self.actual_count or self.coverage.expected is None
            or self.coverage.expected != self.coverage.completed
        ):
            raise ResultContractError("result_incomplete")
        if self.status == "partial" and (
            self.preview or self.validation not in {"valid", "partial"} or not self.limitations
        ):
            raise ResultContractError("result_partial_unqualified")

    def require_readable(self, *, allow_partial=False):
        if type(allow_partial) is not bool:
            raise ResultContractError()
        if self.preview or self.status not in ({"complete", "partial"} if allow_partial else {"complete"}):
            raise ResultNotReadyError()

    @classmethod
    def from_dict(cls, value):
        values = cls._values(value)
        values["coverage"] = Coverage.from_dict(values["coverage"])
        values["checks"] = tuple(_list(values["checks"]))
        values["limitations"] = tuple(_list(values["limitations"]))
        return cls(**values)


@dataclass(frozen=True)
class RecordColumn(_Contract):
    name: str
    value_type: str
    nullable: bool = False

    def __post_init__(self):
        identifier(self.name, limit=256)
        choice(self.value_type, _COLUMN_TYPES)
        if type(self.nullable) is not bool:
            raise ResultContractError("result_schema_invalid")

    @classmethod
    def from_dict(cls, value):
        return cls(**cls._values(value))


def validate_columns(columns, kind):
    _tuple(columns, RecordColumn, maximum=MAX_COLUMNS)
    if (kind == "records-v1" and not columns) or (kind != "records-v1" and columns):
        raise ResultContractError("result_schema_invalid")
    if len({column.name for column in columns}) != len(columns):
        raise ResultContractError("result_schema_invalid")


def validate_record(record, columns):
    if type(record) is not dict or set(record) != {column.name for column in columns}:
        raise ResultContractError("result_schema_invalid")
    validate_json(record)
    types = {
        "string": (str,), "integer": (int,), "number": (int, float),
        "boolean": (bool,), "object": (dict,), "array": (list,),
        "json": (str, int, float, bool, dict, list),
    }
    for column in columns:
        value = record[column.name]
        if value is None:
            if not column.nullable:
                raise ResultContractError("result_schema_invalid")
        elif type(value) not in types[column.value_type]:
            raise ResultContractError("result_schema_invalid")


@dataclass(frozen=True)
class ResultRef(_Contract):
    producer: ProducerIdentity
    output_name: str
    kind: str
    manifest_sha256: str
    content_sha256: str
    size_bytes: int
    item_count: int
    completeness: Completeness
    columns: tuple[RecordColumn, ...] = ()
    character_count: int | None = None
    VERSION = RESULT_REF_VERSION

    def __post_init__(self):
        if type(self.producer) is not ProducerIdentity or type(self.completeness) is not Completeness:
            raise ResultContractError()
        output_name(self.output_name)
        choice(self.kind, RESULT_KINDS)
        digest(self.manifest_sha256)
        digest(self.content_sha256)
        integer(self.size_bytes)
        integer(self.item_count)
        if self.completeness.actual_count != self.item_count:
            raise ResultContractError("result_count_invalid")
        validate_columns(self.columns, self.kind)
        if self.kind in {"text-v1", "markdown-v1"}:
            integer(self.character_count)
            if not self.character_count <= self.size_bytes <= 4 * self.character_count:
                raise ResultContractError("result_count_invalid")
        elif self.character_count is not None:
            raise ResultContractError("result_count_invalid")
        if len(canonical_bytes(self.to_dict())) > MAX_DESCRIPTOR_BYTES:
            raise ResultContractError("result_descriptor_too_large")

    @classmethod
    def from_dict(cls, value):
        values = cls._values(value)
        values["producer"] = ProducerIdentity.from_dict(values["producer"])
        values["completeness"] = Completeness.from_dict(values["completeness"])
        values["columns"] = tuple(RecordColumn.from_dict(item) for item in _list(values["columns"]))
        return cls(**values)


@dataclass(frozen=True)
class TaskResult(_Contract):
    producer: ProducerIdentity
    role: str
    status: str
    outputs: tuple[ResultRef, ...]
    VERSION = TASK_RESULT_VERSION

    def __post_init__(self):
        if type(self.producer) is not ProducerIdentity:
            raise ResultContractError()
        validate_result_role(self.producer, self.role)
        choice(self.status, RESULT_STATES)
        _tuple(self.outputs, ResultRef, maximum=MAX_OUTPUTS)
        if any(reference.producer != self.producer for reference in self.outputs):
            raise ResultContractError("result_producer_mismatch")
        if len({reference.output_name for reference in self.outputs}) != len(self.outputs):
            raise ResultContractError("result_duplicate_output")
        if len({reference.manifest_sha256 for reference in self.outputs}) > 1:
            raise ResultContractError("result_manifest_mismatch")
        if self.status == "complete" and (
            not self.outputs or any(reference.completeness.status != "complete" for reference in self.outputs)
        ):
            raise ResultContractError("result_incomplete")
        if len(canonical_bytes(self.to_dict())) > MAX_DESCRIPTOR_BYTES:
            raise ResultContractError("result_descriptor_too_large")

    def output(self, name):
        output_name(name)
        for reference in self.outputs:
            if reference.output_name == name:
                return reference
        raise ResultContractError("result_output_missing")

    @classmethod
    def from_dict(cls, value):
        values = cls._values(value)
        values["producer"] = ProducerIdentity.from_dict(values["producer"])
        values["outputs"] = tuple(ResultRef.from_dict(item) for item in _list(values["outputs"]))
        return cls(**values)


@dataclass(frozen=True)
class InputBinding(_Contract):
    step_id: str | None = None
    output_name: str | None = None
    existing_result: str | None = None
    VERSION = INPUT_BINDING_VERSION

    def __post_init__(self):
        if self.existing_result is not None:
            output_name(self.existing_result)
            if self.step_id is not None or self.output_name is not None:
                raise ResultContractError("result_binding_invalid")
        else:
            identifier(self.step_id)
            output_name(self.output_name)

    @classmethod
    def from_dict(cls, value):
        return cls(**cls._values(value))


@dataclass(frozen=True)
class InputSpec:
    name: str
    binding: InputBinding
    kinds: tuple[str, ...]
    allow_partial: bool = False

    def __post_init__(self):
        output_name(self.name)
        if type(self.binding) is not InputBinding or type(self.allow_partial) is not bool:
            raise ResultContractError()
        _tuple(self.kinds, str, maximum=len(RESULT_KINDS))
        if not self.kinds or len(set(self.kinds)) != len(self.kinds):
            raise ResultContractError()
        for kind in self.kinds:
            choice(kind, RESULT_KINDS)


@dataclass(frozen=True)
class OutputSpec:
    name: str
    kind: str

    def __post_init__(self):
        output_name(self.name)
        choice(self.kind, RESULT_KINDS)


@dataclass(frozen=True)
class StepBindings:
    step_id: str
    enabled: bool
    outputs: tuple[OutputSpec, ...] = ()
    inputs: tuple[InputSpec, ...] = ()
    depends_on: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.step_id)
        if type(self.enabled) is not bool:
            raise ResultContractError()
        _tuple(self.outputs, OutputSpec, maximum=MAX_OUTPUTS)
        _tuple(self.inputs, InputSpec, maximum=MAX_OUTPUTS)
        _tuple(self.depends_on, str, maximum=MAX_BINDING_STEPS)
        for collection in (self.outputs, self.inputs):
            if len({item.name for item in collection}) != len(collection):
                raise ResultContractError("result_duplicate_binding")
        for step_id in self.depends_on:
            identifier(step_id)
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ResultContractError("result_duplicate_dependency")


def validate_input_bindings(steps, *, existing_results=None, max_steps=MAX_BINDING_STEPS):
    """Return inferred dependencies without modifying, sorting, or repairing a v1 plan.

    Input/output specifications and the existing-result alias catalog are supplied
    by the server, not by a model. Resolving an alias still requires current access.
    """
    integer(max_steps, minimum=1)
    if max_steps > MAX_BINDING_STEPS or type(steps) not in (list, tuple) or len(steps) > max_steps:
        raise ResultContractError("result_step_limit")
    if any(type(step) is not StepBindings for step in steps):
        raise ResultContractError()
    by_id = {step.step_id: step for step in steps}
    if len(by_id) != len(steps):
        raise ResultContractError("result_duplicate_step")
    catalog = {} if existing_results is None else existing_results
    if type(catalog) is not dict:
        raise ResultContractError()
    for alias, reference in catalog.items():
        output_name(alias)
        if type(reference) is not ResultRef:
            raise ResultContractError("result_reference_untrusted")
    dependencies = {}
    for step in steps:
        required = list(step.depends_on)
        for spec in step.inputs:
            binding = spec.binding
            if binding.existing_result is not None:
                reference = catalog.get(binding.existing_result)
                if reference is None:
                    raise ResultContractError("result_reference_untrusted")
                reference.completeness.require_readable(allow_partial=spec.allow_partial)
                kind = reference.kind
            else:
                producer = by_id.get(binding.step_id)
                if producer is None:
                    raise ResultContractError("result_producer_missing")
                kind = next((output.kind for output in producer.outputs if output.name == binding.output_name), None)
                if kind is None:
                    raise ResultContractError("result_output_missing")
                if binding.step_id not in required:
                    required.append(binding.step_id)
            if kind not in spec.kinds:
                raise ResultContractError("result_kind_incompatible")
        for dependency in required:
            if dependency not in by_id:
                raise ResultContractError("result_producer_missing")
            if not by_id[dependency].enabled:
                raise ResultContractError("result_producer_disabled")
        dependencies[step.step_id] = tuple(required)
    visiting, visited = set(), set()

    def visit(step_id):
        if step_id in visiting:
            raise ResultContractError("result_binding_cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in dependencies[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step in steps:
        visit(step.step_id)
    return dependencies
