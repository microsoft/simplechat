# functions_tabular_orchestration.py
"""Route-neutral planning helpers for tabular request orchestration."""

import hashlib
import json
import os
from typing import Mapping

from functions_analysis_deliverables import (
    ANALYSIS_DELIVERABLE_EVENT_FINALIZED,
    ANALYSIS_DELIVERABLE_EVENT_PLANNED,
    ANALYSIS_ORDERING_NOT_APPLICABLE,
    ANALYSIS_ORDERING_SOURCE_ORDER,
    ANALYSIS_ROW_CARDINALITY_NOT_APPLICABLE,
    ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW,
    ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC,
    ANALYSIS_TRANSFORMATION_MODE_SEMANTIC,
    ANALYSIS_VALIDATION_PROFILE_ARTIFACT_SET,
    ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA,
    ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES,
    build_analysis_deliverable_contract,
    emit_analysis_deliverable_contract_event,
)
from functions_assistant_table_exports import assistant_table_export_requested
from functions_generated_file_exports import get_requested_artifact_formats
from functions_generated_file_exports import get_requested_structured_artifact_format
from functions_generated_file_exports import get_requested_structured_artifact_formats


TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION = "tabular-orchestration-v1"
TABULAR_SOURCE_EXTENSIONS = {"csv", "xlsx", "xls", "xlsm"}
TABULAR_RUN_TASK_STRUCTURED_EXPORT = "structured_export"
TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS = "hierarchical_analysis"
TABULAR_RUN_TASK_COMBINED = "combined"
TABULAR_EXECUTION_CONTRACT_FOREGROUND_AGGREGATE = "foreground_aggregate"
TABULAR_EXECUTION_CONTRACT_STRUCTURED_EXPORT = TABULAR_RUN_TASK_STRUCTURED_EXPORT
TABULAR_EXECUTION_CONTRACT_HIERARCHICAL_ANALYSIS = TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS
TABULAR_EXECUTION_CONTRACT_COMBINED = TABULAR_RUN_TASK_COMBINED
TABULAR_EXECUTION_STATE_FOREGROUND = "foreground"
TABULAR_EXECUTION_STATE_DECLINED = "declined"
TABULAR_EXECUTION_STATE_QUEUED = "queued"
TABULAR_EXECUTION_STATE_CANCELED = "canceled"
TABULAR_LIFECYCLE_STATE_PLANNED = "planned"
TABULAR_LIFECYCLE_EVIDENCE_PENDING = "pending"
TABULAR_PLANNER_MODE_OFF = "off"
TABULAR_PLANNER_MODE_SHADOW = "shadow"
TABULAR_PLANNER_MODE_ACTIVE = "active"
TABULAR_PLANNER_MODES = {
    TABULAR_PLANNER_MODE_OFF,
    TABULAR_PLANNER_MODE_SHADOW,
    TABULAR_PLANNER_MODE_ACTIVE,
}
TABULAR_PARITY_ROLLOUT_CONTRACT_VERSION = "tabular-parity-rollout-v1"
TABULAR_PARITY_ROLLOUT_STATES = {"active", "paused", "rollback"}
TABULAR_LEGACY_POST_TOOL_FALLBACK_MODES = {"enabled", "observe", "disabled"}
TABULAR_LEGACY_POST_TOOL_FALLBACK_DECISION_VERSION = "tabular-legacy-fallback-retirement-v1"


def settings_flag_enabled(settings, key, default=False):
    """Return whether a settings flag is enabled."""
    value = (settings or {}).get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def normalize_tabular_request_planner_mode(settings=None, mode=None):
    """Return a supported shared tabular planner mode."""
    raw_mode = mode
    if raw_mode is None:
        raw_mode = (settings or {}).get("tabular_request_planner_mode", TABULAR_PLANNER_MODE_OFF)
    normalized_mode = str(raw_mode or "").strip().lower()
    if normalized_mode in TABULAR_PLANNER_MODES:
        return normalized_mode
    return TABULAR_PLANNER_MODE_OFF


def _coerce_rollout_percentage(value, default=100):
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = int(default)
    return max(0, min(100, parsed_value))


def normalize_tabular_parity_rollout_state(settings=None, state=None):
    """Return the supported rollout state for new shared tabular assignments."""
    raw_state = state
    if raw_state is None:
        raw_state = (settings or {}).get("tabular_analyze_parity_rollout_state", "active")
    normalized_state = str(raw_state or "").strip().lower()
    if normalized_state in TABULAR_PARITY_ROLLOUT_STATES:
        return normalized_state
    return "active"


def normalize_tabular_legacy_post_tool_fallback_mode(settings=None, mode=None):
    """Return the supported legacy fallback mode for post-tool recovery."""
    raw_mode = mode
    if raw_mode is None:
        raw_mode = (settings or {}).get("tabular_legacy_post_tool_fallback_mode", "enabled")
    normalized_mode = str(raw_mode or "").strip().lower()
    if normalized_mode in TABULAR_LEGACY_POST_TOOL_FALLBACK_MODES:
        return normalized_mode
    return "enabled"


def build_tabular_legacy_post_tool_fallback_decision(
    settings=None,
    mode=None,
    planner_result=None,
    generated_output=None,
    fallback_source="post_tool_generated_output",
):
    """Return the Phase 9 decision for the legacy post-tool fallback path."""
    normalized_mode = normalize_tabular_legacy_post_tool_fallback_mode(settings, mode=mode)
    normalized_source = str(fallback_source or "post_tool_generated_output").strip().lower()
    if normalized_source not in {"post_tool_generated_output", "shared_preflight", "planner"}:
        normalized_source = "post_tool_generated_output"

    result = planner_result if isinstance(planner_result, Mapping) else {}
    generated_metadata = generated_output if isinstance(generated_output, Mapping) else None
    if generated_metadata is None and isinstance(result.get("generated_output_metadata"), Mapping):
        generated_metadata = result.get("generated_output_metadata")

    if generated_metadata:
        action = "suppress"
        should_invoke = False
        reason_code = "shared_durable_metadata_present"
    elif normalized_mode == "observe":
        action = "observe"
        should_invoke = False
        reason_code = "observe_only"
    elif normalized_mode == "disabled":
        action = "suppress"
        should_invoke = False
        reason_code = "mode_disabled"
    else:
        action = "invoke"
        should_invoke = True
        reason_code = "mode_enabled"

    return {
        "contract_version": TABULAR_LEGACY_POST_TOOL_FALLBACK_DECISION_VERSION,
        "fallback_source": normalized_source,
        "mode": normalized_mode,
        "action": action,
        "should_invoke": should_invoke,
        "reason_code": reason_code,
        "planner_contract_version": str(result.get("planner_contract_version") or "").strip(),
        "execution_contract": str(result.get("execution_contract") or "").strip().lower(),
        "execution_state": str(result.get("execution_state") or "").strip().lower(),
        "generated_metadata_present": bool(generated_metadata),
    }


def build_tabular_parity_rollout_assignment(settings=None, request_key=None, mode=None):
    """Build a stable, frontend-safe Phase 8 rollout assignment summary."""
    settings = settings if isinstance(settings, Mapping) else {}
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"search", "analyze", "multifile", "mixed"}:
        normalized_mode = "tabular"
    rollout_state = normalize_tabular_parity_rollout_state(settings)
    rollout_percent = _coerce_rollout_percentage(
        settings.get(
            "tabular_analyze_parity_rollout_percent",
            settings.get("tabular_generation_rollout_percentage", 100),
        ),
        default=100,
    )
    assignment_key = json.dumps(
        {
            "contract_version": TABULAR_PARITY_ROLLOUT_CONTRACT_VERSION,
            "mode": normalized_mode,
            "request_key": str(request_key or "").strip(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cohort_bucket = int(hashlib.sha256(assignment_key.encode("utf-8")).hexdigest()[:8], 16) % 100
    assigned_by_cohort = cohort_bucket < rollout_percent
    assigned = rollout_state == "active" and assigned_by_cohort
    if rollout_state == "rollback":
        assignment_reason_code = "rollback_active"
    elif rollout_state == "paused":
        assignment_reason_code = "rollout_paused"
    elif assigned_by_cohort:
        assignment_reason_code = "assigned"
    else:
        assignment_reason_code = "outside_rollout_cohort"
    return {
        "contract_version": TABULAR_PARITY_ROLLOUT_CONTRACT_VERSION,
        "mode": normalized_mode,
        "planner_mode": normalize_tabular_request_planner_mode(settings),
        "rollout_state": rollout_state,
        "assigned": assigned,
        "assignment_reason_code": assignment_reason_code,
        "cohort_bucket": cohort_bucket,
        "rollout_percent": rollout_percent,
        "search_shared_preflight_enabled": settings_flag_enabled(
            settings,
            "enable_tabular_search_shared_preflight",
            False,
        ),
        "analyze_durable_preflight_enabled": settings_flag_enabled(
            settings,
            "enable_tabular_analyze_durable_preflight",
            False,
        ),
        "mixed_deferred_composition_planning_enabled": settings_flag_enabled(
            settings,
            "enable_tabular_mixed_deferred_composition_planning",
            False,
        ),
        "multifile_execution_unit_planning_enabled": settings_flag_enabled(
            settings,
            "enable_tabular_multifile_execution_unit_planning",
            False,
        ),
        "legacy_post_tool_fallback_mode": normalize_tabular_legacy_post_tool_fallback_mode(settings),
    }


def get_tabular_generated_output_format(user_question):
    """Return the requested generated-output file format when the user asked for one."""
    requested_formats = get_tabular_generated_output_formats(user_question)
    return requested_formats[0] if requested_formats else None


def get_tabular_generated_output_formats(user_question):
    """Return requested durable tabular artifact formats in user-request order."""
    return get_requested_structured_artifact_formats(user_question)


def question_requests_tabular_generated_output(user_question):
    """Return True when the prompt asks for a downloadable structured tabular export."""
    normalized_question = str(user_question or "").strip().lower()
    requested_format = get_tabular_generated_output_format(user_question)
    if not normalized_question or not requested_format:
        return False

    exhaustive_markers = (
        "all rows",
        "every row",
        "for each row",
        "for every row",
        "all lines",
        "every line",
        "for each line",
        "for every line",
        "line by line",
        "full json",
        "full csv",
        "full xml",
        "entire",
        "complete",
        "convert",
        "download",
        "save",
        "export",
        "create",
        "generate",
        "populate",
        "one object per",
        "one row per",
        "one line per",
        "one output row per",
        "each object",
        "each row",
        "each line",
    )
    if requested_format == "csv" and assistant_table_export_requested(user_question):
        return True

    return any(marker in normalized_question for marker in exhaustive_markers)


def question_requests_tabular_hierarchical_analysis(user_question):
    """Return True when the prompt asks for whole-dataset row-level synthesis."""
    normalized_question = str(user_question or "").strip().lower()
    if not normalized_question:
        return False

    exhaustive_markers = (
        "all rows",
        "every row",
        "each row",
        "for each row",
        "for every row",
        "all lines",
        "every line",
        "each line",
        "for each line",
        "for every line",
        "line by line",
        "entire dataset",
        "entire file",
        "whole dataset",
        "whole file",
    )
    analysis_markers = (
        "analyze",
        "analyse",
        "summarize",
        "summarise",
        "synthesize",
        "synthesise",
        "evaluate",
        "assess",
        "classify",
        "review",
        "find patterns",
        "patterns",
        "themes",
        "risks",
        "risk patterns",
        "answer",
        "answer each question",
        "answer every question",
    )
    return any(marker in normalized_question for marker in exhaustive_markers) and any(
        marker in normalized_question for marker in analysis_markers
    )


def get_tabular_generated_output_task_type(
    generated_output_requested,
    hierarchical_analysis_requested,
    settings,
    action_mode=None,
):
    """Map request intent to the existing durable generated-output task type."""
    hierarchical_analysis_enabled = settings_flag_enabled(
        settings,
        "enable_tabular_hierarchical_analysis",
        False,
    )
    analysis_required = str(action_mode or "").strip().lower() == "analyze"
    if generated_output_requested and analysis_required:
        return TABULAR_RUN_TASK_COMBINED
    if generated_output_requested and hierarchical_analysis_requested and hierarchical_analysis_enabled:
        return TABULAR_RUN_TASK_COMBINED
    if generated_output_requested:
        return TABULAR_RUN_TASK_STRUCTURED_EXPORT
    if hierarchical_analysis_requested and hierarchical_analysis_enabled:
        return TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS
    return None


def _dedupe_tabular_file_contexts(file_contexts=None):
    """Return unique tabular file contexts while preserving first-seen order."""
    unique_contexts = []
    seen_contexts = set()

    for file_context in file_contexts or []:
        if not isinstance(file_context, Mapping):
            continue

        context_key = (
            str(file_context.get("file_name") or "").strip(),
            str(file_context.get("source_hint") or "workspace").strip().lower(),
            str(file_context.get("group_id") or "").strip(),
            str(file_context.get("public_workspace_id") or "").strip(),
            str((file_context.get("storage_locator") or {}).get("container") or "").strip()
            if isinstance(file_context.get("storage_locator"), Mapping)
            else "",
            str((file_context.get("storage_locator") or {}).get("blob_path") or "").strip()
            if isinstance(file_context.get("storage_locator"), Mapping)
            else "",
        )
        if not context_key[0] or context_key in seen_contexts:
            continue

        seen_contexts.add(context_key)
        unique_contexts.append(dict(file_context))

    return unique_contexts


def _is_supported_tabular_context(file_context):
    file_name = str((file_context or {}).get("file_name") or "").strip()
    source_format = os.path.splitext(file_name)[1].lower().lstrip(".")
    return bool(file_name and source_format in TABULAR_SOURCE_EXTENSIONS)


def _build_source_coverage(file_contexts):
    coverage_entries = []
    for file_context in file_contexts:
        file_name = str(file_context.get("file_name") or "").strip()
        source_format = os.path.splitext(file_name)[1].lower().lstrip(".")
        coverage_entries.append({
            "file_name": file_name,
            "source_format": source_format,
            "source_hint": str(file_context.get("source_hint") or "workspace").strip().lower(),
            "document_id": str(file_context.get("document_id") or "").strip(),
            "source_version": str(file_context.get("source_version") or "").strip(),
            "coverage_state": TABULAR_LIFECYCLE_STATE_PLANNED,
            "execution_state": TABULAR_LIFECYCLE_STATE_PLANNED,
            "evidence_status": TABULAR_LIFECYCLE_EVIDENCE_PENDING,
            "terminal": False,
            "required_for_composition": True,
            "safe_reason_code": "planned",
            "generated_reference_present": False,
        })
    return coverage_entries


def _build_execution_group_id(
    user_question,
    action_mode,
    execution_contract,
    output_format,
    source_coverage,
):
    return _build_request_fingerprint(
        user_question,
        action_mode,
        execution_contract,
        output_format,
        source_coverage,
    )


def _build_tabular_execution_unit(
    unit_index,
    user_question,
    action_mode,
    execution_contract,
    durable_task_type,
    output_format,
    relationship,
    source_contexts,
    source_coverage,
    required_completion_policy,
):
    unit_fingerprint = _build_request_fingerprint(
        user_question,
        action_mode,
        execution_contract,
        output_format,
        source_coverage,
    )
    return {
        "unit_id": f"tabular-unit-{int(unit_index)}-{unit_fingerprint[:12]}",
        "request_order": int(unit_index),
        "operation_relationship": relationship,
        "source_ids": [
            str(source.get("document_id") or "").strip()
            for source in source_contexts
            if str(source.get("document_id") or "").strip()
        ],
        "source_versions": [
            str(source.get("source_version") or "").strip()
            for source in source_contexts
        ],
        "source_count": len(source_contexts),
        "source_coverage": list(source_coverage or []),
        "execution_contract": execution_contract,
        "durable_task_type": durable_task_type,
        "output_format": output_format,
        "idempotency_fingerprint": unit_fingerprint,
        "required_completion_policy": required_completion_policy,
        "execution_state": "planned",
    }


def _build_tabular_execution_units(
    user_question,
    normalized_contexts,
    action_mode,
    execution_contract,
    durable_task_type,
    output_format,
    source_coverage,
    settings,
):
    if not normalized_contexts:
        return []

    multifile_enabled = settings_flag_enabled(
        settings,
        "enable_tabular_multifile_execution_unit_planning",
        False,
    )
    if durable_task_type and len(normalized_contexts) > 1 and multifile_enabled:
        execution_units = []
        for unit_index, (source_context, source_entry) in enumerate(
            zip(normalized_contexts, source_coverage),
            start=1,
        ):
            execution_units.append(_build_tabular_execution_unit(
                unit_index,
                user_question,
                action_mode,
                execution_contract,
                durable_task_type,
                output_format,
                "independent",
                [source_context],
                [source_entry],
                "all_units_required",
            ))
        return execution_units

    return [_build_tabular_execution_unit(
        1,
        user_question,
        action_mode,
        execution_contract,
        durable_task_type,
        output_format,
        "independent" if len(normalized_contexts) == 1 else "collective",
        list(normalized_contexts),
        list(source_coverage or []),
        "single_unit_complete",
    )]


def _build_request_fingerprint(
    user_question,
    action_mode,
    execution_contract,
    output_format,
    source_coverage,
):
    fingerprint_payload = {
        "planner_contract_version": TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
        "action_mode": str(action_mode or "").strip().lower(),
        "execution_contract": execution_contract,
        "output_format": output_format,
        "source_coverage": source_coverage,
        "question_hash": hashlib.sha256(
            str(user_question or "").strip().encode("utf-8")
        ).hexdigest(),
    }
    serialized_payload = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def _build_source_coverage_fingerprint(source_coverage):
    fingerprint_payload = {
        "planner_contract_version": TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
        "source_coverage": list(source_coverage or []),
    }
    serialized_payload = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()


def _callback_requested_cancellation(cancel_requested=None):
    if cancel_requested is None:
        return False
    if callable(cancel_requested):
        return bool(cancel_requested())
    return bool(cancel_requested)


def plan_tabular_request(
    user_question,
    file_contexts,
    action_mode=None,
    settings=None,
    caller=None,
    requested_output_hints=None,
):
    """Classify a tabular request without reading rows or creating durable work."""
    normalized_contexts = [
        file_context
        for file_context in _dedupe_tabular_file_contexts(file_contexts)
        if _is_supported_tabular_context(file_context)
    ]
    output_hints = dict(requested_output_hints or {}) if isinstance(requested_output_hints, Mapping) else {}
    normalized_action_mode = str(action_mode or "").strip().lower()
    analysis_required = normalized_action_mode == "analyze"
    requested_output_formats = get_requested_artifact_formats(user_question)
    structured_output_formats = get_tabular_generated_output_formats(user_question)
    generated_output_requested = question_requests_tabular_generated_output(user_question)
    hierarchical_analysis_requested = question_requests_tabular_hierarchical_analysis(user_question)
    durable_task_type = get_tabular_generated_output_task_type(
        generated_output_requested,
        hierarchical_analysis_requested,
        settings,
        action_mode=normalized_action_mode,
    )
    output_format = structured_output_formats[0] if structured_output_formats else None
    execution_contract = durable_task_type or TABULAR_EXECUTION_CONTRACT_FOREGROUND_AGGREGATE
    source_coverage = _build_source_coverage(normalized_contexts)
    execution_group_id = _build_execution_group_id(
        user_question,
        action_mode,
        execution_contract,
        output_format,
        source_coverage,
    )
    request_fingerprint = _build_request_fingerprint(
        user_question,
        action_mode,
        execution_contract,
        output_format,
        source_coverage,
    )
    execution_units = _build_tabular_execution_units(
        user_question,
        normalized_contexts,
        action_mode,
        execution_contract,
        durable_task_type,
        output_format,
        source_coverage,
        settings,
    )
    reason_code = "bounded_foreground"
    execution_state = TABULAR_EXECUTION_STATE_FOREGROUND
    safe_failure_details = None

    if durable_task_type:
        execution_state = TABULAR_EXECUTION_STATE_DECLINED
        reason_code = "durable_intent"
    elif hierarchical_analysis_requested and not durable_task_type:
        reason_code = "hierarchical_analysis_disabled"

    if not normalized_contexts:
        execution_state = TABULAR_EXECUTION_STATE_DECLINED
        reason_code = "no_replayable_tabular_context"
    elif durable_task_type and len(normalized_contexts) != 1:
        execution_state = TABULAR_EXECUTION_STATE_DECLINED
        if settings_flag_enabled(settings, "enable_tabular_multifile_execution_unit_planning", False):
            reason_code = "multi_context_execution_units_unavailable"
            safe_failure_details = (
                "Multi-file execution units were planned, but durable fan-out is unavailable."
            )
        else:
            reason_code = "multi_context_durable_not_enabled"

    rollout_assignment = build_tabular_parity_rollout_assignment(
        settings,
        request_key=request_fingerprint,
        mode=action_mode,
    )
    transformation_spec = output_hints.get("transformation_spec")
    transformation_mode = output_hints.get("transformation_mode") or (
        ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC
        if transformation_spec
        else ANALYSIS_TRANSFORMATION_MODE_SEMANTIC
    )
    validation_profile = (
        ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES
        if generated_output_requested and transformation_spec
        else ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA
        if generated_output_requested
        else ANALYSIS_VALIDATION_PROFILE_ARTIFACT_SET
    )
    deliverable_contract = build_analysis_deliverable_contract(
        action_mode=action_mode,
        requested_output_formats=requested_output_formats,
        public_output_schema=(
            output_hints.get("public_output_schema")
            or output_hints.get("output_schema")
            or []
        ),
        row_cardinality=(
            ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW
            if generated_output_requested
            else ANALYSIS_ROW_CARDINALITY_NOT_APPLICABLE
        ),
        ordering=(
            ANALYSIS_ORDERING_SOURCE_ORDER
            if generated_output_requested
            else ANALYSIS_ORDERING_NOT_APPLICABLE
        ),
        transformation_mode=transformation_mode,
        transformation_spec=transformation_spec,
        validation_profile=validation_profile,
        source_fingerprint=_build_source_coverage_fingerprint(source_coverage),
        request_fingerprint=request_fingerprint,
    )

    result = {
        "planner_contract_version": TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
        "deliverable_contract": deliverable_contract.to_dict(),
        "execution_contract": execution_contract,
        "execution_state": execution_state,
        "durable_task_type": durable_task_type,
        "generated_output_requested": generated_output_requested,
        "hierarchical_analysis_requested": hierarchical_analysis_requested,
        "requested_output_formats": requested_output_formats,
        "output_format": output_format,
        "action_mode": normalized_action_mode,
        "caller": str(caller or "").strip().lower(),
        "source_count": len(normalized_contexts),
        "source_coverage": source_coverage,
        "execution_group_id": execution_group_id,
        "execution_units": execution_units,
        "request_fingerprint": request_fingerprint,
        "rollout_assignment": rollout_assignment,
        "legacy_post_tool_fallback_decision": build_tabular_legacy_post_tool_fallback_decision(
            mode=rollout_assignment.get("legacy_post_tool_fallback_mode"),
            fallback_source="planner",
        ),
        "reason_code": reason_code,
        "requested_output_hints": output_hints,
        "token_usage": None,
        "citations": [],
        "generated_output_metadata": None,
        "bounded_evidence": None,
        "deferred_composition": None,
        "safe_failure_details": safe_failure_details,
    }
    emit_analysis_deliverable_contract_event(
        settings,
        ANALYSIS_DELIVERABLE_EVENT_PLANNED,
        contract=deliverable_contract,
        dimensions={
            "selected_execution_task_type": durable_task_type or execution_contract,
            "passthrough_selected": False,
            "planner_reason_code": reason_code,
        },
    )
    return result


def execute_tabular_plan(
    plan,
    durable_execution_callback=None,
    cancel_requested=None,
    idempotency_cache=None,
    **execution_context,
):
    """Execute a durable tabular plan through the provided side-effect boundary."""
    if _callback_requested_cancellation(cancel_requested):
        return {
            "planner_contract_version": TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
            "execution_contract": (plan or {}).get("execution_contract"),
            "execution_state": TABULAR_EXECUTION_STATE_CANCELED,
            "generated_output_metadata": None,
            "reason_code": "request_canceled",
            "safe_failure_details": "Tabular request was canceled before active execution.",
        }

    if not isinstance(plan, Mapping):
        return {
            "planner_contract_version": TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
            "execution_contract": None,
            "execution_state": TABULAR_EXECUTION_STATE_DECLINED,
            "generated_output_metadata": None,
            "reason_code": "invalid_plan",
            "safe_failure_details": "Tabular planner result was invalid.",
        }

    if plan.get("execution_contract") == TABULAR_EXECUTION_CONTRACT_FOREGROUND_AGGREGATE:
        result = dict(plan)
        result.update({
            "execution_state": TABULAR_EXECUTION_STATE_FOREGROUND,
            "generated_output_metadata": None,
            "reason_code": "foreground_contract",
            "safe_failure_details": None,
        })
        return result

    if plan.get("reason_code") != "durable_intent":
        result = dict(plan)
        result.update({
            "execution_state": TABULAR_EXECUTION_STATE_DECLINED,
            "generated_output_metadata": None,
            "safe_failure_details": (
                plan.get("safe_failure_details")
                or "Tabular durable execution was not eligible."
            ),
        })
        return result

    rollout_assignment = (
        plan.get("rollout_assignment")
        if isinstance(plan.get("rollout_assignment"), Mapping)
        else {}
    )
    if rollout_assignment and rollout_assignment.get("assigned") is False:
        result = dict(plan)
        result.update({
            "execution_state": TABULAR_EXECUTION_STATE_DECLINED,
            "generated_output_metadata": None,
            "reason_code": "rollout_not_assigned",
            "safe_failure_details": "Request is outside the active tabular parity rollout cohort.",
        })
        return result

    fingerprint = str(plan.get("request_fingerprint") or "").strip()
    if isinstance(idempotency_cache, dict) and fingerprint and fingerprint in idempotency_cache:
        result = dict(plan)
        result.update({
            "execution_state": TABULAR_EXECUTION_STATE_QUEUED,
            "generated_output_metadata": idempotency_cache[fingerprint],
            "reason_code": "active_execution_reused",
            "safe_failure_details": None,
        })
        return result

    if not callable(durable_execution_callback):
        result = dict(plan)
        result.update({
            "execution_state": TABULAR_EXECUTION_STATE_DECLINED,
            "generated_output_metadata": None,
            "reason_code": "durable_executor_unavailable",
            "safe_failure_details": "Tabular durable executor was unavailable.",
        })
        return result

    generated_output_metadata = durable_execution_callback(
        plan=plan,
        **execution_context,
    )
    if not generated_output_metadata:
        result = dict(plan)
        result.update({
            "execution_state": TABULAR_EXECUTION_STATE_DECLINED,
            "generated_output_metadata": None,
            "reason_code": "durable_runner_declined",
            "safe_failure_details": "Tabular durable runner did not accept the request.",
        })
        return result

    if isinstance(idempotency_cache, dict) and fingerprint:
        idempotency_cache[fingerprint] = generated_output_metadata

    result = dict(plan)
    result.update({
        "execution_state": TABULAR_EXECUTION_STATE_QUEUED,
        "generated_output_metadata": generated_output_metadata,
        "reason_code": "active_execution_accepted",
        "safe_failure_details": None,
    })
    return result


def orchestrate_tabular_request(
    user_question,
    file_contexts,
    action_mode=None,
    settings=None,
    caller=None,
    requested_output_hints=None,
    planner_mode=None,
    durable_execution_callback=None,
    cancel_requested=None,
    idempotency_cache=None,
    **execution_context,
):
    """Plan and optionally execute a tabular request through the shared facade."""
    normalized_mode = normalize_tabular_request_planner_mode(settings, mode=planner_mode)
    if normalized_mode == TABULAR_PLANNER_MODE_OFF:
        return {
            "planner_contract_version": TABULAR_ORCHESTRATION_PLANNER_CONTRACT_VERSION,
            "planner_mode": TABULAR_PLANNER_MODE_OFF,
            "execution_contract": None,
            "execution_state": TABULAR_EXECUTION_STATE_DECLINED,
            "generated_output_metadata": None,
            "reason_code": "planner_off",
            "shadow_side_effects": False,
            "legacy_post_tool_fallback_decision": build_tabular_legacy_post_tool_fallback_decision(
                settings=settings,
                fallback_source="planner",
            ),
            "safe_failure_details": None,
        }

    plan = plan_tabular_request(
        user_question,
        file_contexts,
        action_mode=action_mode,
        settings=settings,
        caller=caller,
        requested_output_hints=requested_output_hints,
    )
    plan["planner_mode"] = normalized_mode
    plan["shadow_side_effects"] = False
    plan["legacy_post_tool_fallback_decision"] = build_tabular_legacy_post_tool_fallback_decision(
        settings=settings,
        planner_result=plan,
        fallback_source="planner",
    )
    if normalized_mode == TABULAR_PLANNER_MODE_SHADOW:
        return plan

    active_execution_context = dict(execution_context)
    active_execution_context.setdefault("user_question", user_question)
    active_execution_context.setdefault("file_contexts", file_contexts)
    active_execution_context.setdefault("settings", settings)
    result = execute_tabular_plan(
        plan,
        durable_execution_callback=durable_execution_callback,
        cancel_requested=cancel_requested,
        idempotency_cache=idempotency_cache,
        **active_execution_context,
    )
    result.update({
        "planner_mode": normalized_mode,
        "shadow_side_effects": False,
    })
    result["legacy_post_tool_fallback_decision"] = build_tabular_legacy_post_tool_fallback_decision(
        settings=settings,
        planner_result=result,
        fallback_source="shared_preflight",
    )
    emit_analysis_deliverable_contract_event(
        settings,
        ANALYSIS_DELIVERABLE_EVENT_FINALIZED,
        contract=result.get("deliverable_contract"),
        dimensions={
            "selected_execution_task_type": result.get("durable_task_type") or result.get("execution_contract"),
            "execution_state": result.get("execution_state"),
            "planner_reason_code": result.get("reason_code"),
        },
        metrics={
            "required_artifact_completion_count": 1
            if isinstance(result.get("generated_output_metadata"), Mapping)
            else 0,
        },
    )
    return result
