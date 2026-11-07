# functions_analysis_access.py
"""Source checks for Analyze inputs, and the error raised when an analysis can't be used.

Only reading a document as an input checks it. A saved or generated result takes its access
from the conversation, workflow or run that holds it, and keeps its sources as provenance.
"""

from collections import defaultdict
import math
import re

from content_screening.access import raise_source_authority_error, strict_source_authority_enabled
from content_screening.contracts import SourceAuthorityUnverifiedError

from functions_mixed_source_orchestration import (
    AUTHORIZATION_STATUS_AUTHORIZED,
    SOURCE_MANIFEST_MAX_SOURCES,
    SOURCE_SCOPES,
    compare_reauthorized_source_manifests,
    resolve_authorized_source_manifest,
)

ANALYSIS_SOURCE_ACCESS_VERSION = "analysis-source-access-v1"

# Each code is classified by what its raise sites check, not by its name. A raise site whose
# code is shared with another family passes ``family=`` instead. Every code raised in
# application/single_app must be classified: functional_tests/
# test_analysis_unavailable_message_families.py scans the raise sites and fails otherwise.
ANALYSIS_UNAVAILABLE_SOURCE = "source"
ANALYSIS_UNAVAILABLE_CONTAINER = "container"
ANALYSIS_UNAVAILABLE_SAVED_RESULT = "saved_result"

# An input read found a source document it can't read now, or one that changed while it was read.
ANALYSIS_SOURCE_UNAVAILABLE_CODES = frozenset({
    "analysis_source_manifest_changed",
    "analysis_source_snapshot_changed",
    "analysis_source_unavailable",
    # Loop document re-authorization passes its WorkflowLoopInputError code through.
    "workflow_loop_input_unavailable",
    "workflow_loop_scope_forbidden",
    "workflow_loop_source_changed",
})

# The conversation, message, workflow or run that holds the result is gone or isn't the caller's.
ANALYSIS_CONTAINER_UNAVAILABLE_CODES = frozenset({
    "analysis_conversation_changed",
    "analysis_conversation_deleted",
    "analysis_conversation_unavailable",
    "analysis_conversation_version_missing",
    "analysis_message_masked",
    "analysis_message_unavailable",
    "analysis_retry_changed",
    "analysis_retry_unavailable",
    "analysis_workflow_unavailable",
    "generated_artifact_source_unavailable",
    "native_compute_owner_unavailable",
})

# The stored result, or an earlier result, manifest, receipt, or loop or repeat state it
# depends on, is missing, changed or invalid.
ANALYSIS_SAVED_RESULT_UNAVAILABLE_CODES = frozenset({
    "analysis_artifact_not_valid",
    "analysis_artifact_unbound",
    "analysis_lineage_invalid",
    "analysis_native_identity_invalid",
    "analysis_native_source_mismatch",
    "analysis_producer_unavailable",
    "analysis_result_unavailable",
    "analysis_source_manifest_conflict",
    "analysis_source_manifest_invalid",
    "analysis_source_manifest_missing",
    "generated_artifact_content_changed",
    "generated_artifact_source_conflict",
    "generated_artifact_source_unbound",
    "generated_artifact_source_uncommitted",
    "native_compute_identity_invalid",
    "native_compute_producer_stopped",
    "native_compute_producer_unavailable",
    "native_compute_result_changed",
    "native_compute_result_unavailable",
    "workflow_body_export_invalid",
    "workflow_body_export_scope_invalid",
    "workflow_iteration_outcome_invalid",
    "workflow_iteration_receipt_invalid",
    "workflow_loop_identity_invalid",
    "workflow_loop_item_changed",
    "workflow_loop_item_invalid",
    "workflow_loop_manifest_invalid",
    "workflow_loop_manifest_unavailable",
    "workflow_loop_source_receipt_invalid",
    "workflow_repeat_admission_invalid",
    "workflow_repeat_grant_invalid",
    "workflow_repeat_head_invalid",
    "workflow_repeat_identity_invalid",
    "workflow_repeat_iteration_invalid",
    "workflow_repeat_source_invalid",
    "workflow_repeat_source_uncommitted",
    "workflow_repeat_state_changed",
    "workflow_repeat_state_invalid",
    "workflow_repeat_state_uncommitted",
    "workflow_repeat_transition_invalid",
})

ANALYSIS_UNAVAILABLE_MESSAGES = {
    ANALYSIS_UNAVAILABLE_SOURCE: "A source document for this analysis is no longer available or has changed.",
    ANALYSIS_UNAVAILABLE_CONTAINER: (
        "The conversation, workflow or run that holds this result no longer exists or isn't available to you."
    ),
    ANALYSIS_UNAVAILABLE_SAVED_RESULT: (
        "This saved result can't be used because something it depends on is missing or has changed."
    ),
}


def analysis_unavailable_family(code):
    """Return the message family for ``code``.

    An unclassified code gets the saved-result wording, which blames neither a source
    document nor the caller's access.
    """
    if isinstance(code, str):
        if code in ANALYSIS_SOURCE_UNAVAILABLE_CODES:
            return ANALYSIS_UNAVAILABLE_SOURCE
        if code in ANALYSIS_CONTAINER_UNAVAILABLE_CODES:
            return ANALYSIS_UNAVAILABLE_CONTAINER
    return ANALYSIS_UNAVAILABLE_SAVED_RESULT


class AnalysisResultUnavailable(PermissionError):
    """An analysis input or saved result can't be used.

    ``code`` names the check that failed. ``family`` picks the public wording: a source
    document, the conversation, workflow or run that holds the result, or the saved result
    itself. Pass ``family`` only when the code is shared with a different family.
    """

    def __init__(self, code="analysis_source_unavailable", *, family=None):
        self.code = code
        self.family = family if family in ANALYSIS_UNAVAILABLE_MESSAGES else analysis_unavailable_family(code)
        self.public_message = ANALYSIS_UNAVAILABLE_MESSAGES[self.family]
        super().__init__(self.public_message)


def resolve_analysis_source_manifest(document_ids, user_id, *, resolver=None, **context):
    """Resolve a complete Analyze selection using the existing bounded resolver."""
    if (
        not isinstance(document_ids, (list, tuple))
        or not document_ids
        or any(not isinstance(value, str) or not value.strip() for value in document_ids)
    ):
        raise ValueError("Analysis requires a nonempty list of source identifiers.")
    if resolver is not None and not callable(resolver):
        raise TypeError("The analysis source resolver must be callable.")
    normalized_ids = list(dict.fromkeys(value.strip() for value in document_ids))
    resolve = resolver or resolve_authorized_source_manifest
    manifest = []
    for offset in range(0, len(normalized_ids), SOURCE_MANIFEST_MAX_SOURCES):
        batch = normalized_ids[offset:offset + SOURCE_MANIFEST_MAX_SOURCES]
        resolved = resolve(batch, user_id=user_id, **context)
        if (
            not isinstance(resolved, list)
            or any(not isinstance(source, dict) for source in resolved)
            or [source.get("document_id") for source in resolved] != batch
        ):
            if strict_source_authority_enabled():
                raise_source_authority_error(SourceAuthorityUnverifiedError())
            # The current source lookup itself failed: an input read, not a saved manifest.
            raise AnalysisResultUnavailable("analysis_source_manifest_invalid", family=ANALYSIS_UNAVAILABLE_SOURCE)
        if strict_source_authority_enabled():
            for source in resolved:
                if source.get("authorization_status") not in {"authorized", "unresolved"}:
                    raise_source_authority_error(SourceAuthorityUnverifiedError())
                if source["authorization_status"] == "authorized":
                    try:
                        analysis_source_snapshot([source])
                    except AnalysisResultUnavailable:
                        raise_source_authority_error(SourceAuthorityUnverifiedError())
        manifest.extend(resolved)
    return manifest


def analysis_source_snapshot(sources):
    """Keep source identity/version, never storage locators or cached permissions."""
    if not isinstance(sources, list):
        raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
    snapshots = []
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
        document_id = source.get("document_id")
        scope = source.get("scope")
        scope_id = source.get("scope_id")
        if (
            not isinstance(document_id, str) or not document_id.strip()
            or not isinstance(scope, str) or scope not in SOURCE_SCOPES
            or not isinstance(scope_id, str) or not scope_id.strip()
        ):
            raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
        snapshot = {
            "document_id": document_id.strip(),
            "scope": scope,
            "scope_id": scope_id.strip(),
            "source_version": source.get("source_version"),
            "source_revision": source.get("source_revision"),
        }
        if any(
            value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (str, int, float))
                or (isinstance(value, float) and not math.isfinite(value))
            )
            for value in (snapshot["source_version"], snapshot["source_revision"])
        ):
            raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
        if "content_sha256" in source:
            digest = source["content_sha256"]
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
                raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
            snapshot["content_sha256"] = digest.lower()
        identity = tuple(snapshot.values())
        if identity not in seen:
            snapshots.append(snapshot)
            seen.add(identity)
    return snapshots


def build_analysis_access(sources=(), *, inherited=()):
    """Merge server-resolved contributors; this normalization does not authorize reads."""
    if not isinstance(sources, (list, tuple)) or not isinstance(inherited, (list, tuple)):
        raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
    combined = []
    for source in sources:
        if not isinstance(source, dict):
            raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
        normalized = dict(source)
        if "scope_type" in normalized:
            if "scope" in normalized and normalized["scope"] != normalized["scope_type"]:
                raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
            normalized["scope"] = normalized.pop("scope_type")
        combined.append(normalized)
    for policy in inherited:
        if (
            not isinstance(policy, dict) or policy.get("version") != ANALYSIS_SOURCE_ACCESS_VERSION
            or not isinstance(policy.get("sources"), list) or not policy["sources"]
        ):
            raise AnalysisResultUnavailable("analysis_source_manifest_invalid")
        combined.extend(policy["sources"])
    snapshots = analysis_source_snapshot(combined)
    return {"version": ANALYSIS_SOURCE_ACCESS_VERSION, "sources": snapshots} if snapshots else None


def authorize_analysis_sources(user_id, sources, *, require_snapshot=False, resolver=None):
    """Authorize every contributor; a saved permission is never sufficient."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise AnalysisResultUnavailable("analysis_source_unavailable")
    snapshots = analysis_source_snapshot(sources)
    if not snapshots:
        raise AnalysisResultUnavailable("analysis_source_manifest_missing")

    groups = defaultdict(list)
    for snapshot in snapshots:
        groups[(snapshot["scope"], snapshot["scope_id"])].append(snapshot)

    changed = False
    for (scope, scope_id), original in groups.items():
        fresh = resolve_analysis_source_manifest(
            [source["document_id"] for source in original],
            user_id.strip(),
            resolver=resolver,
            doc_scope="all" if scope == "chat" else scope,
            active_group_ids=[scope_id] if scope == "group" else [],
            active_public_workspace_ids=[scope_id] if scope == "public" else [],
            conversation_id=scope_id if scope == "chat" else None,
        )
        comparison = compare_reauthorized_source_manifests(
            [{**source, "authorization_status": AUTHORIZATION_STATUS_AUTHORIZED} for source in original],
            fresh,
        )
        if comparison["authorization_failure_count"]:
            raise AnalysisResultUnavailable("analysis_source_unavailable")
        fresh_by_id = {source["document_id"]: source for source in fresh}
        for source in original:
            current = fresh_by_id[source["document_id"]]
            version_changed = (
                source["source_version"] != current.get("source_version")
                or source["source_revision"] != current.get("source_revision")
            )
            changed = changed or version_changed
            if require_snapshot and (
                version_changed
                or (source["source_version"] is None and not source["source_revision"])
            ):
                raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
    return {"source_count": len(snapshots), "source_snapshot_changed": changed}
