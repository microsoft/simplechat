# functions_analysis_deliverables.py
"""Versioned Analyze/Search deliverable contracts and pure validators."""

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Mapping

from functions_tabular_transformations import normalize_tabular_transformation_spec


def log_event(*args, **kwargs):
    """Lazily resolve telemetry logging so functional tests do not require Azure packages."""
    try:
        from functions_appinsights import log_event as _log_event_impl
    except ImportError:
        return None
    return _log_event_impl(*args, **kwargs)


ANALYSIS_DELIVERABLE_CONTRACT_VERSION = "analysis-deliverables-v3"
ANALYSIS_DELIVERABLE_LEGACY_CONTRACT_VERSIONS = frozenset({
    "analysis-deliverables-v1",
    "analysis-deliverables-v2",
})

ANALYSIS_DELIVERABLE_ACTION_ANALYZE = "analyze"
ANALYSIS_DELIVERABLE_ACTION_SEARCH = "search"
ANALYSIS_DELIVERABLE_ACTION_COMPARE = "compare"
ANALYSIS_DELIVERABLE_ACTION_CHAT = "chat"
ANALYSIS_DELIVERABLE_ACTION_WORKFLOW = "workflow"
ANALYSIS_DELIVERABLE_ACTION_UNKNOWN = "unknown"
ANALYSIS_DELIVERABLE_ACTION_MODES = frozenset({
    ANALYSIS_DELIVERABLE_ACTION_ANALYZE,
    ANALYSIS_DELIVERABLE_ACTION_SEARCH,
    ANALYSIS_DELIVERABLE_ACTION_COMPARE,
    ANALYSIS_DELIVERABLE_ACTION_CHAT,
    ANALYSIS_DELIVERABLE_ACTION_WORKFLOW,
    ANALYSIS_DELIVERABLE_ACTION_UNKNOWN,
})

ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS = "primary_analysis"
ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT = "requested_output"
ANALYSIS_ARTIFACT_ROLE_SUPPORTING_OUTPUT = "supporting_output"
ANALYSIS_ARTIFACT_ROLES = frozenset({
    ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS,
    ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
    ANALYSIS_ARTIFACT_ROLE_SUPPORTING_OUTPUT,
})

ANALYSIS_DELIVERABLE_FORMATS = frozenset({
    "csv",
    "docx",
    "json",
    "md",
    "pdf",
    "xls",
    "xlsm",
    "xlsx",
    "xml",
})

ANALYSIS_TRANSFORMATION_MODE_PASSTHROUGH = "passthrough"
ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC = "deterministic"
ANALYSIS_TRANSFORMATION_MODE_SEMANTIC = "semantic"
ANALYSIS_TRANSFORMATION_MODE_HYBRID = "hybrid"
ANALYSIS_TRANSFORMATION_MODES = frozenset({
    ANALYSIS_TRANSFORMATION_MODE_PASSTHROUGH,
    ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC,
    ANALYSIS_TRANSFORMATION_MODE_SEMANTIC,
    ANALYSIS_TRANSFORMATION_MODE_HYBRID,
})

ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW = "one_per_source_row"
ANALYSIS_ROW_CARDINALITY_NOT_APPLICABLE = "not_applicable"
ANALYSIS_ROW_CARDINALITIES = frozenset({
    ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW,
    ANALYSIS_ROW_CARDINALITY_NOT_APPLICABLE,
})

ANALYSIS_ORDERING_SOURCE_ORDER = "source_order"
ANALYSIS_ORDERING_NOT_APPLICABLE = "not_applicable"
ANALYSIS_ORDERINGS = frozenset({
    ANALYSIS_ORDERING_SOURCE_ORDER,
    ANALYSIS_ORDERING_NOT_APPLICABLE,
})

ANALYSIS_VALIDATION_PROFILE_ARTIFACT_SET = "artifact_set"
ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA = "exact_rows_schema"
ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES = "exact_rows_schema_and_rules"
ANALYSIS_VALIDATION_PROFILES = frozenset({
    ANALYSIS_VALIDATION_PROFILE_ARTIFACT_SET,
    ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA,
    ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES,
})

ANALYSIS_PUBLICATION_POLICY_ALL_REQUIRED_ARTIFACTS = "all_required_artifacts"
ANALYSIS_PUBLICATION_POLICY_NO_REQUIRED_ARTIFACTS = "no_required_artifacts"
ANALYSIS_PUBLICATION_POLICIES = frozenset({
    ANALYSIS_PUBLICATION_POLICY_ALL_REQUIRED_ARTIFACTS,
    ANALYSIS_PUBLICATION_POLICY_NO_REQUIRED_ARTIFACTS,
})

ANALYSIS_DELIVERABLE_EVENT_PLANNED = "planned"
ANALYSIS_DELIVERABLE_EVENT_FINALIZED = "finalized"
ANALYSIS_DELIVERABLE_EVENT_VALIDATED = "validated"
ANALYSIS_DELIVERABLE_EVENT_NAMES = frozenset({
    ANALYSIS_DELIVERABLE_EVENT_PLANNED,
    ANALYSIS_DELIVERABLE_EVENT_FINALIZED,
    ANALYSIS_DELIVERABLE_EVENT_VALIDATED,
})
ANALYSIS_DELIVERABLE_CONTRACT_MODES = frozenset({"off", "observe", "shadow"})
ANALYSIS_DELIVERABLE_CONTRACT_OBSERVATION_MODES = frozenset({"observe", "shadow"})

ANALYSIS_INTERNAL_LINEAGE_FIELD_NAMES = frozenset({
    "source_row_number",
    "source_row_identity",
})
ANALYSIS_DEFAULT_LINEAGE_SCHEMA = (
    "source_row_number",
    "source_row_identity",
)
ANALYSIS_INTERNAL_LINEAGE_FIELD_PREFIX = "__simplechat"

ANALYSIS_DELIVERABLE_MAX_ARTIFACTS = 12
ANALYSIS_DELIVERABLE_MAX_SCHEMA_FIELDS = 200
ANALYSIS_DELIVERABLE_MAX_FIELD_NAME_LENGTH = 128
ANALYSIS_DELIVERABLE_MAX_ARTIFACT_ID_LENGTH = 96
ANALYSIS_DELIVERABLE_MAX_METADATA_BYTES = 32768


@dataclass(frozen=True)
class AnalysisDeliverableArtifact:
    """Serializable artifact descriptor for an analysis deliverable contract."""

    artifact_id: str
    role: str
    format: str
    required: bool = True
    request_order: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AnalysisDeliverableContract:
    """Serializable server-owned deliverable plan."""

    contract_version: str = ANALYSIS_DELIVERABLE_CONTRACT_VERSION
    action_mode: str = ANALYSIS_DELIVERABLE_ACTION_UNKNOWN
    analysis_required: bool = False
    primary_artifact_role: str = ""
    requested_artifacts: tuple = field(default_factory=tuple)
    public_output_schema: tuple = field(default_factory=tuple)
    internal_checkpoint_schema: tuple = field(default_factory=tuple)
    lineage_schema: tuple = field(default_factory=tuple)
    row_cardinality: str = ANALYSIS_ROW_CARDINALITY_NOT_APPLICABLE
    ordering: str = ANALYSIS_ORDERING_NOT_APPLICABLE
    transformation_mode: str = ANALYSIS_TRANSFORMATION_MODE_SEMANTIC
    transformation_spec: dict = field(default_factory=dict)
    validation_profile: str = ANALYSIS_VALIDATION_PROFILE_ARTIFACT_SET
    publication_policy: str = ANALYSIS_PUBLICATION_POLICY_NO_REQUIRED_ARTIFACTS
    source_fingerprint: str = ""
    request_fingerprint: str = ""

    def to_dict(self):
        payload = asdict(self)
        payload["requested_artifacts"] = [
            artifact.to_dict() if isinstance(artifact, AnalysisDeliverableArtifact) else dict(artifact)
            for artifact in self.requested_artifacts
        ]
        payload["public_output_schema"] = list(self.public_output_schema)
        payload["internal_checkpoint_schema"] = list(self.internal_checkpoint_schema)
        payload["lineage_schema"] = list(self.lineage_schema)
        payload["transformation_spec"] = dict(self.transformation_spec or {})
        return payload


@dataclass(frozen=True)
class AnalysisDeliverableValidationReport:
    """Safe validator result with counts and reason codes only."""

    valid: bool
    reason_codes: tuple = field(default_factory=tuple)
    counts: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "valid": self.valid,
            "reason_codes": list(self.reason_codes),
            "counts": dict(self.counts),
        }


def _safe_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _safe_int(value, default=0, minimum=None, maximum=None):
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default
    if minimum is not None:
        parsed_value = max(minimum, parsed_value)
    if maximum is not None:
        parsed_value = min(maximum, parsed_value)
    return parsed_value


def _normalize_reason_code(value):
    normalized_value = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower())
    normalized_value = re.sub(r"_+", "_", normalized_value).strip("_")
    return normalized_value[:80] or "unknown"


def _normalize_dimension_value(value):
    dimension_text = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", dimension_text):
        return _normalize_reason_code(dimension_text)
    first_token = re.split(r"[:/\\\s]+", dimension_text, maxsplit=1)[0]
    return _normalize_reason_code(first_token)


def _normalize_action_mode(action_mode):
    normalized_mode = str(action_mode or "").strip().lower()
    if normalized_mode in ANALYSIS_DELIVERABLE_ACTION_MODES:
        return normalized_mode
    return ANALYSIS_DELIVERABLE_ACTION_UNKNOWN


def normalize_analysis_artifact_role(role):
    """Return a supported artifact role or raise for unknown roles."""
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in ANALYSIS_ARTIFACT_ROLES:
        raise ValueError(f"Unsupported analysis artifact role: {role}")
    return normalized_role


def _normalize_artifact_format(artifact_format):
    normalized_format = str(artifact_format or "").strip().lower().lstrip(".")
    if normalized_format not in ANALYSIS_DELIVERABLE_FORMATS:
        raise ValueError(f"Unsupported analysis artifact format: {artifact_format}")
    return normalized_format


def _normalize_bounded_mode(value, allowed_values, default_value, label):
    normalized_value = str(value or default_value).strip().lower()
    if normalized_value not in allowed_values:
        raise ValueError(f"Unsupported {label}: {value}")
    return normalized_value


def _normalize_artifact_id(artifact_id, role, artifact_format, request_order):
    normalized_id = str(artifact_id or "").strip()
    if not normalized_id:
        normalized_id = f"{role}-{artifact_format}-{_safe_int(request_order, minimum=0)}"
    normalized_id = re.sub(r"[^A-Za-z0-9_.:-]+", "-", normalized_id).strip("-")
    if not normalized_id:
        raise ValueError("Analysis artifact id is empty")
    if len(normalized_id) > ANALYSIS_DELIVERABLE_MAX_ARTIFACT_ID_LENGTH:
        raise ValueError("Analysis artifact id exceeds the bounded metadata limit")
    return normalized_id


def _normalize_public_output_schema(public_output_schema=None):
    normalized_schema = []
    seen_fields = set()
    for field_name in list(public_output_schema or []):
        normalized_field = str(field_name or "").strip()
        if not normalized_field:
            raise ValueError("Analysis public output schema contains an empty field name")
        if len(normalized_field) > ANALYSIS_DELIVERABLE_MAX_FIELD_NAME_LENGTH:
            raise ValueError("Analysis public output schema field exceeds the bounded metadata limit")
        if _is_internal_lineage_field(normalized_field):
            raise ValueError("Analysis public output schema cannot include reserved internal fields")
        if normalized_field in seen_fields:
            raise ValueError("Analysis public output schema contains duplicate fields")
        seen_fields.add(normalized_field)
        normalized_schema.append(normalized_field)
    if len(normalized_schema) > ANALYSIS_DELIVERABLE_MAX_SCHEMA_FIELDS:
        raise ValueError("Analysis public output schema exceeds the bounded metadata limit")
    return tuple(normalized_schema)


def _normalize_lineage_schema(lineage_schema=None):
    normalized_schema = []
    seen_fields = set()
    raw_schema = list(lineage_schema or ANALYSIS_DEFAULT_LINEAGE_SCHEMA)
    for field_name in raw_schema:
        normalized_field = str(field_name or "").strip()
        if not normalized_field:
            raise ValueError("Analysis lineage schema contains an empty field name")
        if len(normalized_field) > ANALYSIS_DELIVERABLE_MAX_FIELD_NAME_LENGTH:
            raise ValueError("Analysis lineage schema field exceeds the bounded metadata limit")
        if not _is_internal_lineage_field(normalized_field):
            raise ValueError("Analysis lineage schema can only include reserved internal fields")
        if normalized_field in seen_fields:
            raise ValueError("Analysis lineage schema contains duplicate fields")
        seen_fields.add(normalized_field)
        normalized_schema.append(normalized_field)
    return tuple(normalized_schema)


def _normalize_internal_checkpoint_schema(
    public_output_schema=None,
    internal_checkpoint_schema=None,
    lineage_schema=None,
):
    normalized_public_schema = tuple(public_output_schema or [])
    normalized_lineage_schema = _normalize_lineage_schema(lineage_schema)
    if internal_checkpoint_schema is None:
        return tuple(list(normalized_lineage_schema) + list(normalized_public_schema))

    normalized_schema = []
    seen_fields = set()
    for field_name in list(internal_checkpoint_schema or []):
        normalized_field = str(field_name or "").strip()
        if not normalized_field:
            raise ValueError("Analysis internal checkpoint schema contains an empty field name")
        if len(normalized_field) > ANALYSIS_DELIVERABLE_MAX_FIELD_NAME_LENGTH:
            raise ValueError("Analysis internal checkpoint schema field exceeds the bounded metadata limit")
        if normalized_field in seen_fields:
            raise ValueError("Analysis internal checkpoint schema contains duplicate fields")
        seen_fields.add(normalized_field)
        normalized_schema.append(normalized_field)

    expected_schema = tuple(list(normalized_lineage_schema) + list(normalized_public_schema))
    if tuple(normalized_schema) != expected_schema:
        raise ValueError("Analysis internal checkpoint schema must be lineage fields followed by public fields")
    return tuple(normalized_schema)


def build_analysis_deliverable_artifact(
    artifact_id,
    role,
    artifact_format,
    required=True,
    request_order=0,
):
    """Build one bounded artifact descriptor."""
    normalized_role = normalize_analysis_artifact_role(role)
    normalized_format = _normalize_artifact_format(artifact_format)
    normalized_order = _safe_int(request_order, default=0, minimum=0)
    return AnalysisDeliverableArtifact(
        artifact_id=_normalize_artifact_id(
            artifact_id,
            normalized_role,
            normalized_format,
            normalized_order,
        ),
        role=normalized_role,
        format=normalized_format,
        required=bool(required),
        request_order=normalized_order,
    )


def _coerce_artifact_descriptor(artifact):
    if isinstance(artifact, AnalysisDeliverableArtifact):
        return artifact
    artifact_payload = dict(artifact or {}) if isinstance(artifact, Mapping) else {}
    return build_analysis_deliverable_artifact(
        artifact_payload.get("artifact_id"),
        artifact_payload.get("role"),
        artifact_payload.get("format"),
        required=artifact_payload.get("required", True),
        request_order=artifact_payload.get("request_order", 0),
    )


def _normalize_artifact_descriptors(artifacts=None):
    descriptors = tuple(_coerce_artifact_descriptor(artifact) for artifact in list(artifacts or []))
    if len(descriptors) > ANALYSIS_DELIVERABLE_MAX_ARTIFACTS:
        raise ValueError("Analysis deliverable artifact count exceeds the bounded metadata limit")
    artifact_ids = [artifact.artifact_id for artifact in descriptors]
    if len(set(artifact_ids)) != len(artifact_ids):
        raise ValueError("Analysis deliverable artifact ids must be unique")
    return descriptors


def _fingerprint_payload(payload):
    serialized_payload = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def build_analysis_deliverable_contract(
    action_mode=None,
    requested_output_format=None,
    requested_output_formats=None,
    requested_artifacts=None,
    public_output_schema=None,
    internal_checkpoint_schema=None,
    lineage_schema=None,
    row_cardinality=None,
    ordering=None,
    transformation_mode=None,
    transformation_spec=None,
    validation_profile=None,
    publication_policy=None,
    analysis_required=None,
    primary_artifact_role=None,
    source_fingerprint="",
    request_fingerprint="",
):
    """Build a versioned, JSON-serializable deliverable plan."""
    normalized_action = _normalize_action_mode(action_mode)
    normalized_analysis_required = _safe_bool(
        normalized_action == ANALYSIS_DELIVERABLE_ACTION_ANALYZE
        if analysis_required is None
        else analysis_required
    )
    normalized_schema = _normalize_public_output_schema(public_output_schema)
    normalized_lineage_schema = _normalize_lineage_schema(lineage_schema)
    normalized_internal_checkpoint_schema = _normalize_internal_checkpoint_schema(
        public_output_schema=normalized_schema,
        internal_checkpoint_schema=internal_checkpoint_schema,
        lineage_schema=normalized_lineage_schema,
    )

    if requested_artifacts is None:
        artifact_descriptors = []
        request_order = 0
        output_formats = list(requested_output_formats or [])
        if requested_output_format and not output_formats:
            output_formats = [requested_output_format]
        if normalized_analysis_required:
            artifact_descriptors.append(build_analysis_deliverable_artifact(
                "analysis",
                ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS,
                "md",
                required=True,
                request_order=request_order,
            ))
            request_order += 1
        seen_output_formats = set()
        for output_format in output_formats:
            normalized_output_format = _normalize_artifact_format(output_format)
            if normalized_analysis_required and normalized_output_format == "md":
                continue
            if normalized_output_format in seen_output_formats:
                continue
            seen_output_formats.add(normalized_output_format)
            artifact_descriptors.append(build_analysis_deliverable_artifact(
                f"requested-{normalized_output_format}",
                ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
                normalized_output_format,
                required=True,
                request_order=request_order,
            ))
            request_order += 1
    else:
        artifact_descriptors = list(requested_artifacts or [])

    normalized_artifacts = _normalize_artifact_descriptors(artifact_descriptors)
    normalized_primary_role = str(primary_artifact_role or "").strip().lower()
    if normalized_analysis_required:
        normalized_primary_role = normalize_analysis_artifact_role(
            normalized_primary_role or ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS
        )
    elif normalized_primary_role:
        normalized_primary_role = normalize_analysis_artifact_role(normalized_primary_role)

    normalized_row_cardinality = _normalize_bounded_mode(
        row_cardinality,
        ANALYSIS_ROW_CARDINALITIES,
        ANALYSIS_ROW_CARDINALITY_NOT_APPLICABLE,
        "row cardinality",
    )
    normalized_ordering = _normalize_bounded_mode(
        ordering,
        ANALYSIS_ORDERINGS,
        ANALYSIS_ORDERING_NOT_APPLICABLE,
        "ordering",
    )
    normalized_transformation_mode = _normalize_bounded_mode(
        transformation_mode,
        ANALYSIS_TRANSFORMATION_MODES,
        ANALYSIS_TRANSFORMATION_MODE_SEMANTIC,
        "transformation mode",
    )
    normalized_transformation_spec = normalize_tabular_transformation_spec(
        transformation_spec,
        public_output_schema=normalized_schema,
    )
    normalized_validation_profile = _normalize_bounded_mode(
        validation_profile,
        ANALYSIS_VALIDATION_PROFILES,
        ANALYSIS_VALIDATION_PROFILE_ARTIFACT_SET,
        "validation profile",
    )
    normalized_publication_policy = _normalize_bounded_mode(
        publication_policy,
        ANALYSIS_PUBLICATION_POLICIES,
        (
            ANALYSIS_PUBLICATION_POLICY_ALL_REQUIRED_ARTIFACTS
            if any(artifact.required for artifact in normalized_artifacts)
            else ANALYSIS_PUBLICATION_POLICY_NO_REQUIRED_ARTIFACTS
        ),
        "publication policy",
    )

    contract = AnalysisDeliverableContract(
        action_mode=normalized_action,
        analysis_required=normalized_analysis_required,
        primary_artifact_role=normalized_primary_role,
        requested_artifacts=normalized_artifacts,
        public_output_schema=normalized_schema,
        internal_checkpoint_schema=normalized_internal_checkpoint_schema,
        lineage_schema=normalized_lineage_schema,
        row_cardinality=normalized_row_cardinality,
        ordering=normalized_ordering,
        transformation_mode=normalized_transformation_mode,
        transformation_spec=normalized_transformation_spec,
        validation_profile=normalized_validation_profile,
        publication_policy=normalized_publication_policy,
        source_fingerprint=str(source_fingerprint or "").strip()[:64],
        request_fingerprint=str(request_fingerprint or "").strip()[:64],
    )
    serialized_contract = json.dumps(contract.to_dict(), sort_keys=True, separators=(",", ":"))
    if len(serialized_contract.encode("utf-8")) > ANALYSIS_DELIVERABLE_MAX_METADATA_BYTES:
        raise ValueError("Analysis deliverable contract exceeds the bounded metadata limit")
    return contract


def coerce_analysis_deliverable_contract(contract):
    """Load a persisted contract and ignore unknown additive fields."""
    if isinstance(contract, AnalysisDeliverableContract):
        return contract
    payload = dict(contract or {}) if isinstance(contract, Mapping) else {}
    if payload.get("contract_version") not in {
        None,
        "",
        ANALYSIS_DELIVERABLE_CONTRACT_VERSION,
        *ANALYSIS_DELIVERABLE_LEGACY_CONTRACT_VERSIONS,
    }:
        raise ValueError("Unsupported analysis deliverable contract version")
    return build_analysis_deliverable_contract(
        action_mode=payload.get("action_mode"),
        requested_artifacts=payload.get("requested_artifacts") or [],
        public_output_schema=payload.get("public_output_schema") or [],
        internal_checkpoint_schema=payload.get("internal_checkpoint_schema"),
        lineage_schema=payload.get("lineage_schema"),
        row_cardinality=payload.get("row_cardinality"),
        ordering=payload.get("ordering"),
        transformation_mode=payload.get("transformation_mode"),
        transformation_spec=payload.get("transformation_spec"),
        validation_profile=payload.get("validation_profile"),
        publication_policy=payload.get("publication_policy"),
        analysis_required=payload.get("analysis_required", False),
        primary_artifact_role=payload.get("primary_artifact_role"),
        source_fingerprint=payload.get("source_fingerprint", ""),
        request_fingerprint=payload.get("request_fingerprint", ""),
    )


def _build_report(reason_codes=None, counts=None):
    normalized_reasons = tuple(sorted({_normalize_reason_code(reason) for reason in list(reason_codes or []) if reason}))
    normalized_counts = {
        _normalize_reason_code(key): _safe_int(value, default=0, minimum=0)
        for key, value in dict(counts or {}).items()
    }
    return AnalysisDeliverableValidationReport(
        valid=not normalized_reasons,
        reason_codes=normalized_reasons,
        counts=normalized_counts,
    )


def _actual_artifact_key(artifact):
    artifact_id = str((artifact or {}).get("artifact_id") or "").strip()
    role = str((artifact or {}).get("role") or "").strip().lower()
    artifact_format = str((artifact or {}).get("format") or (artifact or {}).get("output_format") or "").strip().lower()
    if artifact_id:
        return artifact_id
    return f"{role}:{artifact_format}"


def _expected_artifact_key(artifact):
    if isinstance(artifact, AnalysisDeliverableArtifact):
        return artifact.artifact_id
    return _actual_artifact_key(artifact)


def _artifact_is_completed(artifact):
    if _safe_bool((artifact or {}).get("valid", False)):
        return True
    status = str((artifact or {}).get("status") or "").strip().lower()
    return status in {"completed", "published", "valid"}


def validate_analysis_artifact_set(contract, artifacts=None):
    """Validate that an artifact set satisfies a deliverable contract."""
    normalized_contract = coerce_analysis_deliverable_contract(contract)
    expected_artifacts = list(normalized_contract.requested_artifacts)
    actual_artifacts = [dict(artifact or {}) for artifact in list(artifacts or []) if isinstance(artifact, Mapping)]
    expected_by_key = {_expected_artifact_key(artifact): artifact for artifact in expected_artifacts}
    actual_by_key = {_actual_artifact_key(artifact): artifact for artifact in actual_artifacts}
    reason_codes = []
    counts = {
        "required_artifact_count": sum(1 for artifact in expected_artifacts if artifact.required),
        "expected_artifact_count": len(expected_artifacts),
        "actual_artifact_count": len(actual_artifacts),
        "missing_artifact_count": 0,
        "invalid_required_artifact_count": 0,
        "extra_artifact_count": 0,
        "artifact_role_mismatch_count": 0,
        "artifact_format_mismatch_count": 0,
        "required_artifact_completion_count": 0,
        "primary_artifact_count": 0,
    }

    for expected_key, expected_artifact in expected_by_key.items():
        actual_artifact = actual_by_key.get(expected_key)
        if expected_artifact.required and actual_artifact is None:
            counts["missing_artifact_count"] += 1
            reason_codes.append("missing_required_artifact")
            continue
        if expected_artifact.required and actual_artifact is not None and not _artifact_is_completed(actual_artifact):
            counts["invalid_required_artifact_count"] += 1
            reason_codes.append("required_artifact_not_valid")
        if expected_artifact.required and actual_artifact is not None and _artifact_is_completed(actual_artifact):
            counts["required_artifact_completion_count"] += 1
        if actual_artifact is not None:
            actual_role = str(actual_artifact.get("role") or "").strip().lower()
            actual_format = str(
                actual_artifact.get("format") or actual_artifact.get("output_format") or ""
            ).strip().lower().lstrip(".")
            if actual_role and actual_role != expected_artifact.role:
                counts["artifact_role_mismatch_count"] += 1
                reason_codes.append("artifact_role_mismatch")
            if actual_format and actual_format != expected_artifact.format:
                counts["artifact_format_mismatch_count"] += 1
                reason_codes.append("artifact_format_mismatch")

    for actual_key in actual_by_key:
        if actual_key not in expected_by_key:
            counts["extra_artifact_count"] += 1
            reason_codes.append("extra_artifact")

    if normalized_contract.primary_artifact_role:
        primary_role = normalized_contract.primary_artifact_role
        counts["primary_artifact_count"] = sum(
            1
            for artifact in actual_artifacts
            if str(artifact.get("role") or "").strip().lower() == primary_role
        )
        if counts["primary_artifact_count"] != 1:
            reason_codes.append("wrong_primary_artifact_role")

    return _build_report(reason_codes, counts)


def _is_internal_lineage_field(field_name):
    normalized_field = str(field_name or "").strip()
    return (
        normalized_field in ANALYSIS_INTERNAL_LINEAGE_FIELD_NAMES
        or normalized_field.startswith(ANALYSIS_INTERNAL_LINEAGE_FIELD_PREFIX)
    )


def is_analysis_internal_lineage_field(field_name):
    """Return whether a field name is reserved for server lineage metadata."""
    return _is_internal_lineage_field(field_name)


def project_structured_deliverable_row(row, public_output_schema, require_all_fields=True):
    """Project one internal generated row to the persisted public schema."""
    if not isinstance(row, Mapping):
        raise ValueError("Structured deliverable row must be an object")
    normalized_schema = _normalize_public_output_schema(public_output_schema)
    if not normalized_schema:
        raise ValueError("Structured deliverable projection requires a public output schema")
    if require_all_fields:
        missing_fields = [field_name for field_name in normalized_schema if field_name not in row]
        if missing_fields:
            raise ValueError("Structured deliverable row is missing required public fields")
    return {field_name: row.get(field_name) for field_name in normalized_schema}


def project_structured_deliverable_rows(rows, public_output_schema, require_all_fields=True):
    """Project internal generated rows to the exact user-facing schema and order."""
    return [
        project_structured_deliverable_row(
            row,
            public_output_schema,
            require_all_fields=require_all_fields,
        )
        for row in list(rows or [])
    ]


def _row_identity(row, identity_field):
    if not identity_field or not isinstance(row, Mapping):
        return None
    return str(row.get(identity_field) or "").strip()


def _field_sequence(rows):
    for row in rows:
        if isinstance(row, Mapping):
            return list(row.keys())
    return []


def validate_structured_deliverable_rows(
    contract,
    output_rows=None,
    source_rows=None,
    expected_rows=None,
    identity_field=None,
):
    """Validate public structured rows without logging row values."""
    normalized_contract = coerce_analysis_deliverable_contract(contract)
    rows = list(output_rows or [])
    sources = list(source_rows or [])
    expected = list(expected_rows or [])
    expected_schema = list(normalized_contract.public_output_schema)
    actual_schema = _field_sequence(rows)
    reason_codes = []
    counts = {
        "output_row_count": len(rows),
        "source_row_count": len(sources),
        "expected_row_count": len(expected),
        "public_schema_field_count": len(expected_schema),
        "actual_schema_field_count": len(actual_schema),
        "missing_field_count": 0,
        "extra_field_count": 0,
        "extra_internal_field_count": 0,
        "row_schema_mismatch_count": 0,
        "duplicate_row_identity_count": 0,
        "deterministic_mismatch_count": 0,
        "deterministic_mismatched_row_count": 0,
    }

    non_object_count = sum(1 for row in rows if not isinstance(row, Mapping))
    if non_object_count:
        counts["row_not_object_count"] = non_object_count
        reason_codes.append("row_not_object")

    if expected_schema:
        expected_field_set = set(expected_schema)
        actual_field_set = set(actual_schema)
        missing_fields = expected_field_set - actual_field_set
        extra_fields = actual_field_set - expected_field_set
        counts["missing_field_count"] = len(missing_fields)
        counts["extra_field_count"] = len(extra_fields)
        counts["extra_internal_field_count"] = len([
            field_name for field_name in extra_fields if _is_internal_lineage_field(field_name)
        ])
        if missing_fields or extra_fields:
            reason_codes.append("schema_mismatch")
        elif actual_schema != expected_schema:
            reason_codes.append("schema_order_mismatch")
        if counts["extra_internal_field_count"]:
            reason_codes.append("extra_internal_fields")

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if set(row.keys()) != expected_field_set:
                counts["row_schema_mismatch_count"] += 1
        if counts["row_schema_mismatch_count"]:
            reason_codes.append("row_schema_mismatch")

    if (
        normalized_contract.row_cardinality == ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW
        and sources
        and len(rows) != len(sources)
    ):
        reason_codes.append("row_count_mismatch")

    if identity_field and sources and rows:
        source_identities = [_row_identity(row, identity_field) for row in sources]
        output_identities = [_row_identity(row, identity_field) for row in rows]
        output_identity_set = set(output_identities)
        counts["duplicate_row_identity_count"] = len(output_identities) - len(output_identity_set)
        if counts["duplicate_row_identity_count"]:
            reason_codes.append("duplicate_row_identity")
        if set(source_identities) != output_identity_set:
            reason_codes.append("row_identity_mismatch")
        elif normalized_contract.ordering == ANALYSIS_ORDERING_SOURCE_ORDER and source_identities != output_identities:
            reason_codes.append("row_order_mismatch")

    if expected:
        if len(rows) != len(expected):
            reason_codes.append("deterministic_row_count_mismatch")
        deterministic_fields = expected_schema or _field_sequence(expected)
        mismatched_rows = 0
        mismatch_count = 0
        for row, expected_row in zip(rows, expected):
            if not isinstance(row, Mapping) or not isinstance(expected_row, Mapping):
                continue
            row_mismatch_found = False
            for field_name in deterministic_fields:
                if row.get(field_name) != expected_row.get(field_name):
                    mismatch_count += 1
                    row_mismatch_found = True
            if row_mismatch_found:
                mismatched_rows += 1
        counts["deterministic_mismatch_count"] = mismatch_count
        counts["deterministic_mismatched_row_count"] = mismatched_rows
        if mismatch_count:
            reason_codes.append("deterministic_value_mismatch")

    return _build_report(reason_codes, counts)


def is_analysis_deliverable_telemetry_enabled(settings):
    """Return whether Phase 1 deliverable-contract shadow telemetry is enabled."""
    normalized_settings = settings if isinstance(settings, Mapping) else {}
    contract_mode = str(normalized_settings.get("analysis_deliverable_contract_mode") or "off").strip().lower()
    if contract_mode not in ANALYSIS_DELIVERABLE_CONTRACT_MODES:
        contract_mode = "off"
    return (
        _safe_bool(normalized_settings.get("enable_analysis_deliverable_contract_telemetry", False))
        and contract_mode in ANALYSIS_DELIVERABLE_CONTRACT_OBSERVATION_MODES
    )


def build_safe_analysis_deliverable_event_properties(
    event_name,
    contract=None,
    validation_report=None,
    metrics=None,
    dimensions=None,
):
    """Build telemetry dimensions that exclude prompts, row values, and storage locations."""
    normalized_contract = coerce_analysis_deliverable_contract(contract) if contract else None
    contract_payload = normalized_contract.to_dict() if normalized_contract else {}
    report_payload = (
        validation_report.to_dict()
        if isinstance(validation_report, AnalysisDeliverableValidationReport)
        else dict(validation_report or {})
    )
    report_counts = dict(report_payload.get("counts") or {})
    metric_payload = dict(metrics or {})
    required_completion_count = report_counts.get("required_artifact_completion_count")
    if required_completion_count is None:
        required_completion_count = metric_payload.get("required_artifact_completion_count")
    requested_artifacts = list(contract_payload.get("requested_artifacts") or [])
    requested_formats = sorted({
        str(artifact.get("format") or "").strip().lower()
        for artifact in requested_artifacts
        if str(artifact.get("format") or "").strip()
    })
    public_schema = list(contract_payload.get("public_output_schema") or [])
    properties = {
        "event_name": event_name if event_name in ANALYSIS_DELIVERABLE_EVENT_NAMES else "unknown",
        "contract_version": str(contract_payload.get("contract_version") or "")[:64],
        "action_mode": _normalize_action_mode(contract_payload.get("action_mode")),
        "analysis_required": bool(contract_payload.get("analysis_required")),
        "requested_artifact_count": len(requested_artifacts),
        "required_artifact_count": sum(1 for artifact in requested_artifacts if bool(artifact.get("required"))),
        "requested_artifact_formats": ",".join(requested_formats)[:80],
        "public_schema_field_count": len(public_schema),
        "public_schema_internal_field_count": len([
            field_name for field_name in public_schema if _is_internal_lineage_field(field_name)
        ]),
        "row_cardinality": str(contract_payload.get("row_cardinality") or "")[:64],
        "ordering": str(contract_payload.get("ordering") or "")[:64],
        "transformation_mode": str(contract_payload.get("transformation_mode") or "")[:64],
        "validation_profile": str(contract_payload.get("validation_profile") or "")[:64],
        "publication_policy": str(contract_payload.get("publication_policy") or "")[:64],
        "primary_artifact_role": str(contract_payload.get("primary_artifact_role") or "")[:64],
        "source_fingerprint": str(contract_payload.get("source_fingerprint") or "").strip()[:24],
        "request_fingerprint": str(contract_payload.get("request_fingerprint") or "").strip()[:24],
        "validation_valid": bool(report_payload.get("valid", True)),
        "validation_reason_count": len(report_payload.get("reason_codes") or []),
        "structural_mismatch_count": _safe_int(report_counts.get("row_schema_mismatch_count"))
        + _safe_int(report_counts.get("missing_field_count"))
        + _safe_int(report_counts.get("extra_field_count")),
        "extra_internal_field_count": _safe_int(report_counts.get("extra_internal_field_count")),
        "deterministic_mismatch_count": _safe_int(report_counts.get("deterministic_mismatch_count")),
        "required_artifact_completion_count": _safe_int(required_completion_count),
    }
    for key, value in metric_payload.items():
        properties[f"metric_{_normalize_reason_code(key)}"] = _safe_int(value)
    for key, value in dict(dimensions or {}).items():
        safe_key = _normalize_reason_code(key)
        if isinstance(value, bool):
            properties[f"dimension_{safe_key}"] = value
        elif isinstance(value, (int, float)):
            properties[f"dimension_{safe_key}"] = value
        else:
            properties[f"dimension_{safe_key}"] = _normalize_dimension_value(value)
    return properties


def emit_analysis_deliverable_contract_event(
    settings,
    event_name,
    contract=None,
    validation_report=None,
    metrics=None,
    dimensions=None,
    level=logging.INFO,
):
    """Emit a gated shadow deliverable-contract event."""
    if not is_analysis_deliverable_telemetry_enabled(settings):
        return None
    properties = build_safe_analysis_deliverable_event_properties(
        event_name,
        contract=contract,
        validation_report=validation_report,
        metrics=metrics,
        dimensions=dimensions,
    )
    log_event(
        "[ANALYSIS_DELIVERABLE_CONTRACT] Analysis deliverable contract observation event.",
        properties,
        level=level,
        debug_only=True,
    )
    return properties
