# contracts.py
"""Shared contracts for content inspection and document availability."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
SCREENING_FIELD = "content_screening"
SCOPE_TYPES = frozenset({"personal", "group", "public"})
AVAILABLE_STATES = frozenset({"cleared", "approved_with_flags"})
HELD_STATES = frozenset({
    "pending_scan", "scanning", "scan_error", "incomplete", "pending_review",
    "remediating", "publishing", "rejected", "deleting", "deleted",
})
INSPECTION_STATUSES = frozenset({"pass", "findings", "incomplete", "error"})
MAX_UNIT_CHARACTERS = 64000
MAX_POLICY_RULES = 100
MAX_FINDINGS = 1000
CONTENT_METADATA_FIELDS = (
    "file_name", "title", "abstract", "keywords", "authors", "organization",
    "publication_date", "vision_analysis", "tags", "document_classification",
)


class ScreeningError(Exception):
    """An error with a stable, non-sensitive public message."""

    code = "screening_error"
    status_code = 503
    retryable = True
    public_message = "Content screening could not complete. The document remains unavailable."

    def __init__(self, message=None, *, code=None):
        super().__init__(message or self.public_message)
        if code:
            self.code = code


class ScreeningValidationError(ScreeningError, ValueError):
    code = "invalid_screening_request"
    status_code = 400
    retryable = False
    public_message = "The content screening request is invalid."


class ScreeningConfigurationError(ScreeningError):
    code = "screening_configuration_required"
    retryable = False
    public_message = "Content screening requires a valid policy and configured Enhanced Citations."


class ScreeningPolicyRequiredError(ScreeningConfigurationError):
    code = "screening_policy_required"
    status_code = 400
    public_message = (
        "The saved content screening policy is unavailable. Save Content Screening "
        "settings again to initialize a missing policy. Existing holds are unchanged."
    )


class ScreeningChecksRequiredError(ScreeningConfigurationError):
    code = "screening_policy_empty"
    status_code = 400
    public_message = (
        "No active checks are configured for this workspace. Add and save a rule or "
        "AI check before starting a scan. An empty policy can stay enabled; existing holds are unchanged."
    )


class ScreeningCitationsRequiredError(ScreeningConfigurationError):
    code = "screening_citations_required"
    status_code = 400
    public_message = (
        "Enable Enhanced Citations under Chat > Citations > Enhanced and configure its storage first. "
        "Azure AI Content Safety is a separate feature and is not required."
    )


class ScreeningConflictError(ScreeningError):
    code = "screening_revision_conflict"
    status_code = 409
    retryable = False
    public_message = "The document or review changed. Refresh it before trying again."


class DocumentHeldError(ScreeningError):
    code = "document_under_review"
    status_code = 409
    retryable = False
    public_message = "This document is unavailable until content screening and review are complete."


class SourceAuthorityUnavailableError(ScreeningError):
    """Current source authority could not be reached; no access decision was made."""

    code = "source_authority_unavailable"
    public_message = "Current source access could not be verified because an authority service is unavailable. Try again."


class SourceAuthorityUnverifiedError(ScreeningError):
    """Authority returned malformed data or has a non-transient configuration failure."""

    code = "source_authority_unverified"
    retryable = False
    public_message = "Current source access could not be verified. The source authority requires attention."


def hash_payload(value: Any) -> str:
    """Hash canonical JSON without exposing source content in identifiers."""
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def text_fingerprint(text: str) -> str:
    if not isinstance(text, str):
        raise ScreeningValidationError("Content must be text.")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def metadata_fingerprint(document: Mapping[str, Any]) -> str:
    return hash_payload({name: document.get(name) for name in CONTENT_METADATA_FIELDS})


def normalize_identifier(value: Any, field_name: str = "identifier") -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ScreeningValidationError(f"A valid {field_name} is required.")
    normalized = str(value).strip()
    if not normalized or len(normalized) > 512 or any(ord(char) < 32 for char in normalized):
        raise ScreeningValidationError(f"A valid {field_name} is required.")
    return normalized


@dataclass(frozen=True)
class Subject:
    scope_type: str
    scope_id: str
    document_id: str
    source_revision: str
    kind: str = "workspace_document"

    def __post_init__(self):
        if self.kind != "workspace_document" or self.scope_type not in SCOPE_TYPES:
            raise ScreeningValidationError("This content scope is not supported.")
        for name in ("scope_id", "document_id", "source_revision"):
            object.__setattr__(self, name, normalize_identifier(getattr(self, name), name))

    @property
    def key(self) -> str:
        return hash_payload(self.to_dict())

    @property
    def scope_key(self) -> str:
        return f"{self.scope_type}:{self.scope_id}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Subject":
        if not isinstance(value, Mapping):
            raise ScreeningValidationError("A content subject is required.")
        return cls(
            scope_type=value.get("scope_type"),
            scope_id=value.get("scope_id"),
            document_id=value.get("document_id"),
            source_revision=value.get("source_revision"),
            kind=value.get("kind", "workspace_document"),
        )


def subject_from_document(document: Mapping[str, Any]) -> Subject:
    if not isinstance(document, Mapping):
        raise ScreeningValidationError("A document is required.")
    if document.get("public_workspace_id"):
        scope_type, scope_id = "public", document["public_workspace_id"]
    elif document.get("group_id"):
        scope_type, scope_id = "group", document["group_id"]
    else:
        scope_type, scope_id = "personal", document.get("user_id")
    return Subject(scope_type, scope_id, document.get("id"), _document_revision(document))


def _document_revision(document):
    version = document.get("version")
    if version is None:
        return "1"
    if (
        isinstance(version, bool)
        or not isinstance(version, (str, int))
        or not str(version).isascii() or not str(version).isdigit()
        or int(version) < 1
    ):
        raise ScreeningValidationError("The document revision is invalid.")
    return str(version)


@dataclass(frozen=True)
class ContentUnit:
    unit_id: str
    text: str
    locator: dict = field(default_factory=dict)
    normalization_version: int = 1

    def __post_init__(self):
        object.__setattr__(self, "unit_id", normalize_identifier(self.unit_id, "unit_id"))
        if not isinstance(self.text, str):
            raise ScreeningValidationError("Content units must contain text.")
        if not isinstance(self.locator, dict):
            raise ScreeningValidationError("A content locator must be an object.")
        if self.normalization_version != 1 or isinstance(self.normalization_version, bool):
            raise ScreeningValidationError("The content normalization version is unsupported.")
        object.__setattr__(self, "locator", dict(self.locator))

    @property
    def content_hash(self) -> str:
        return text_fingerprint(self.text)

    def to_dict(self) -> dict:
        return {**asdict(self), "content_hash": self.content_hash, "offset_encoding": "unicode_codepoints"}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContentUnit":
        if not isinstance(value, Mapping):
            raise ScreeningValidationError("A content unit is required.")
        unit = cls(
            unit_id=value.get("unit_id"),
            text=value.get("text"),
            locator=value.get("locator", {}),
            normalization_version=value.get("normalization_version", 1),
        )
        if value.get("content_hash") not in (None, unit.content_hash):
            raise ScreeningConflictError()
        if value.get("offset_encoding", "unicode_codepoints") != "unicode_codepoints":
            raise ScreeningValidationError("The content offset encoding is unsupported.")
        return unit


def content_fingerprint(units: Sequence[ContentUnit]) -> str:
    return hash_payload([unit.to_dict() for unit in units])


def normalize_units(values: Sequence[Any]) -> list[ContentUnit]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ScreeningValidationError("No extracted content is available to inspect.")
    units = [value if isinstance(value, ContentUnit) else ContentUnit.from_dict(value) for value in values]
    identifiers = [unit.unit_id for unit in units]
    if len(identifiers) != len(set(identifiers)):
        raise ScreeningValidationError("Content unit identifiers must be unique.")
    if not any(unit.text.strip() for unit in units):
        raise ScreeningValidationError("No extracted content is available to inspect.")
    return units


@dataclass(frozen=True)
class Finding:
    rule_id: str
    unit_id: str
    category: str
    severity: str
    reason: str
    start: int | None = None
    end: int | None = None
    evidence: str = ""
    source: str = "deterministic"
    confidence: float | None = None

    def __post_init__(self):
        normalize_identifier(self.rule_id, "rule_id")
        normalize_identifier(self.unit_id, "unit_id")
        if self.severity not in {"low", "medium", "high", "critical"}:
            raise ScreeningValidationError("Finding severity is invalid.")
        if self.source not in {"deterministic", "model"}:
            raise ScreeningValidationError("Finding source is invalid.")
        if (self.start is None) != (self.end is None):
            raise ScreeningValidationError("Finding offsets must be supplied together.")
        if self.start is not None:
            if (
                type(self.start) is not int or type(self.end) is not int
                or self.start < 0 or self.end <= self.start
            ):
                raise ScreeningValidationError("Finding offsets are invalid.")
        if self.confidence is not None:
            if type(self.confidence) not in (int, float) or not 0 <= self.confidence <= 1:
                raise ScreeningValidationError("Finding confidence is invalid.")

    @property
    def finding_id(self) -> str:
        return hash_payload({
            "rule_id": self.rule_id, "unit_id": self.unit_id,
            "start": self.start, "end": self.end, "evidence": self.evidence, "source": self.source,
        })

    def to_dict(self) -> dict:
        return {**asdict(self), "finding_id": self.finding_id}


@dataclass
class DetectorResult:
    status: str
    findings: list[Finding] = field(default_factory=list)
    required_units: int = 0
    completed_units: int = 0
    required_windows: int = 0
    completed_windows: int = 0
    error_code: str | None = None
    usage: dict = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return (
            self.status in {"pass", "findings"}
            and self.required_units > 0
            and self.completed_units == self.required_units
            and self.completed_windows == self.required_windows
            and not self.error_code
        )

    def to_dict(self) -> dict:
        result = asdict(self)
        result["findings"] = [finding.to_dict() for finding in self.findings]
        return result


@dataclass
class InspectionResult:
    status: str
    content_fingerprint: str
    policy_fingerprint: str
    findings: list[Finding] = field(default_factory=list)
    detectors: list[dict] = field(default_factory=list)
    units_total: int = 0
    error_code: str | None = None
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["schema_version"] = SCHEMA_VERSION
        result["findings"] = [finding.to_dict() for finding in self.findings]
        return result


def document_is_available(document: Mapping[str, Any]) -> bool:
    """Check persisted eligibility; the caller must still prove object access."""
    if not isinstance(document, Mapping):
        return False
    if SCREENING_FIELD not in document:
        return True
    marker = document.get(SCREENING_FIELD)
    if not isinstance(marker, dict) or marker.get("state") not in AVAILABLE_STATES:
        return False
    try:
        version = _document_revision(document)
    except ScreeningValidationError:
        return False
    if str(marker.get("source_revision", "")) != version:
        return False
    return bool(marker.get("content_fingerprint") and marker.get("scan_id"))


def require_document_available(document: Mapping[str, Any]) -> None:
    if not document_is_available(document):
        raise DocumentHeldError()


def public_screening_summary(document: Mapping[str, Any]) -> dict | None:
    if SCREENING_FIELD not in document:
        return None
    marker = document.get(SCREENING_FIELD)
    if not isinstance(marker, dict):
        return {"state": "scan_error", "available": False, "finding_count": 0}
    count = marker.get("finding_count", 0)
    return {
        "state": marker.get("state") if marker.get("state") in AVAILABLE_STATES | HELD_STATES else "scan_error",
        "available": document_is_available(document),
        "finding_count": count if type(count) is int and count >= 0 else 0,
        "scan_id": marker.get("scan_id"),
        "review_id": marker.get("review_id"),
        "updated_at": marker.get("updated_at"),
    }
