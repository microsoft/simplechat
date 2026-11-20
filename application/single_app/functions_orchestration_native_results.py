# functions_orchestration_native_results.py
"""Native computation to retained orchestration results, without publication.

Version: 0.261.446
Implemented in: 0.261.127
Typed, bounded cross-file computation added in: 0.261.437
Complete preparation and bounded prepared lowering added in: 0.261.446

The owner binds the native mode; the default production builder validates
explicit query/schema/transformation arguments. Runtime/schema/native execution
imports are deferred so metadata discovery remains safe before bootstrap.
"""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import os
import re
import sys
import hashlib

from jsonschema import Draft202012Validator

from blob_container_readiness import STORAGE_FAILURE_CODE, STORAGE_FAILURE_MESSAGE
from content_screening.contracts import ScreeningError
from functions_analysis_access import analysis_source_snapshot
from functions_appinsights import log_event, workflow_log_context
from functions_orchestration_execution_policy import orchestration_file_policy
from functions_orchestration_result_contracts import (
    Completeness,
    Coverage,
    OutputSpec,
    ProducerIdentity,
    RecordColumn,
    ResultContractError,
    TaskResult,
    canonical_bytes,
)
from functions_orchestration_results import MAX_VALUE_BYTES, NamedOutput, OrchestrationResults


NATIVE_WAIT_KIND = "native_tabular_compute"
# One authoring call and up to two corrections of an authoring fault, counted durably.
LOWERING_MAX_CALLS = 3
_MESSAGES = {
    "native_binding_required": "The native computation bridge is not configured.",
    "native_runtime_invalid": "The native computation has no valid owning runtime.",
    "native_selection_unsupported": "Native computation requires one authorized replayable tabular source. No work was submitted.",
    "native_source_changed": "A selected source changed after planning. Create and review a fresh plan before running it.",
    "native_inputs_unsupported": "Native computation accepts an original tabular document, not named result inputs. No work was submitted.",
    "native_outputs_invalid": "The declared outputs do not match the requested native computation mode.",
    "native_request_invalid": "The native computation requires a trusted executable request, not a preview or prose-only plan.",
    "native_arguments_invalid": "Native computation requires an explicit operation and its validated query/schema/transformation arguments.",
    "native_query_unsupported": "Native query expressions support row-local filtering, not global reductions. Complete matching-row counts are retained in coverage; model-supported analysis requires analysis mode.",
    "native_model_unavailable": "The selected native computation model is unavailable.",
    "native_wait_invalid": "The pending native computation could not be matched to this step and attempt.",
    "native_access_unavailable": "The native computation is unavailable because its ownership or source access changed.",
    "native_guard_unavailable": "The owning attempt cannot authorize native result retention.",
    "native_result_invalid": "The native computation did not provide all complete declared outputs.",
    "native_execution_failed": "Native computation did not complete successfully.",
    "native_storage_unavailable": STORAGE_FAILURE_MESSAGE,
    "native_retention_failed": "The complete native output could not be retained. No preview was substituted.",
    "native_cancelled": "Native computation was canceled.",
    "native_relational_limit": "The complete cross-file calculation exceeds its processing limits. No shortened result was used.",
    "native_relational_ambiguous": "The selected relationship has duplicate or overlapping matches. Specify the intended relationship before calculating.",
    "native_relational_invalid": "The cross-file calculation could not use the specified columns, values, or relationship rules. No result was published.",
    "native_source_schema_mismatch": (
        "The calculation's column assertion does not match the complete source header. "
        "Review the source schema and calculation plan; no result was published."
    ),
    "native_formula_value_unavailable": (
        "A selected formula has no saved result. Save recalculated values in Excel before calculating; "
        "no empty value or zero was substituted."
    ),
}
# Service codes meaning the approved source no longer matches what would be read.
_SOURCE_CHANGED_CODES = frozenset({"native_compute_source_identity_mismatch"})


class _NoHarnessExecutionError(Exception):
    """Stands in for the harness error class while its module is not loaded; never raised."""


class NativeOrchestrationBridgeError(ValueError):
    def __init__(self, code, *, rule=None, detail=None):
        self.code = code
        self.rule = rule or code
        # Content-free location tokens; they are re-sanitized wherever they are logged or described.
        self.detail = dict(detail or {})
        super().__init__(_MESSAGES[code])


@dataclass(frozen=True)
class NativeOrchestrationRequest:
    """A server-built native plan and its full original computation question."""

    plan: dict
    user_question: str


def _task_type(native_operation, task_type):
    if native_operation not in ("query", "transform", "analysis", "prepare", "relate"):
        raise NativeOrchestrationBridgeError("native_request_invalid")
    selected = task_type if task_type is not None else (
        "hierarchical_analysis" if native_operation == "analysis" else "structured_export"
    )
    allowed = {
        "query": ("structured_export",),
        "transform": ("structured_export", "combined"),
        "analysis": ("hierarchical_analysis",),
        "prepare": ("structured_export",),
        "relate": ("structured_export",),
    }
    if selected not in allowed[native_operation]:
        raise NativeOrchestrationBridgeError("native_request_invalid")
    return selected


def native_orchestration_output_specs(native_operation, *, task_type=None):
    """Exact required OutputSpecs; analysis-only never advertises records."""
    selected = _task_type(native_operation, task_type)
    outputs = []
    if native_operation == "prepare":
        outputs.append(OutputSpec("context", "structured-v1"))
    elif selected in ("structured_export", "combined"):
        outputs.append(OutputSpec("records", "records-v1"))
    if native_operation == "relate":
        outputs.append(OutputSpec("lineage", "records-v1"))
    if selected in ("hierarchical_analysis", "combined"):
        outputs.append(OutputSpec("analysis", "structured-v1"))
    outputs.append(OutputSpec("coverage", "structured-v1"))
    return tuple(outputs)


def native_orchestration_arguments_schema():
    """The production v2 argument shape; expression semantics use native validators."""
    # The relational grammar is pure and must not bootstrap source/storage clients.
    from functions_tabular_relational import (
        MAX_RELATIONAL_SOURCES, RELATIONAL_EXPRESSION_POINTER, relational_spec_schema,
    )

    column = {
        "type": "string", "minLength": 1, "maxLength": 128,
        "pattern": r"^(?!__simplechat)(?!source_row_number$)(?!source_row_identity$)\S(?:[\s\S]*\S)?$",
    }
    transformation_field = {
        "type": "object", "required": ["name"], "additionalProperties": False,
        "properties": {
            "name": deepcopy(column),
            "mode": {"enum": ["deterministic", "semantic", "hybrid"]},
            "type": {"enum": ["string", "number", "integer", "date", "boolean", "object", "array"]},
            "nullable": {"type": "boolean"},
            "expression": {"description": RELATIONAL_EXPRESSION_POINTER},
            "allowed_values": {"type": "array", "maxItems": 200},
        },
    }
    context_dataset = {
        "type": "object", "additionalProperties": False,
        "required": ["alias", "document_id", "context_columns", "key_profiles"],
        "properties": {
            "alias": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_]{0,47}$"},
            "document_id": {"type": "string", "minLength": 1, "maxLength": 256},
            "sheet": {"type": "string", "minLength": 1, "maxLength": 128},
            "header_row": {"type": "integer", "minimum": 1, "maximum": 1000},
            "cell_range": {
                "type": "string",
                "pattern": r"^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$",
            },
            "table_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "context_columns": {
                "type": "array", "maxItems": 256, "uniqueItems": True, "items": deepcopy(column),
            },
            "key_profiles": {
                "type": "array", "maxItems": 8, "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["name", "columns"],
                    "properties": {
                        "name": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_]{0,47}$"},
                        "columns": {
                            "type": "array", "minItems": 1, "maxItems": 8,
                            "uniqueItems": True, "items": deepcopy(column),
                        },
                    },
                },
            },
        },
    }

    schema = {
        "type": "object", "required": ["question", "native_operation", "document_ids"],
        "additionalProperties": False,
        "properties": {
            "question": {"type": "string", "minLength": 1, "maxLength": 24000, "pattern": r"\S"},
            "document_ids": {
                "type": "array", "minItems": 1, "maxItems": MAX_RELATIONAL_SOURCES, "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"^\S+$"},
            },
            "native_operation": {"enum": ["query", "transform", "analysis", "prepare", "relate"]},
            "relational_spec": relational_spec_schema(),
            "calculation_mode": {"const": "prepared-v1"},
            "preparation_request": {
                "type": "object", "additionalProperties": False,
                "required": ["version", "datasets"],
                "properties": {
                    "version": {"const": "tabular-context-request-v1"},
                    "datasets": {
                        "type": "array", "minItems": 1, "maxItems": MAX_RELATIONAL_SOURCES,
                        "items": context_dataset,
                    },
                },
            },
            "task_type": {"enum": ["structured_export", "hierarchical_analysis", "combined"]},
            "query_expression": {"type": "string", "minLength": 1, "maxLength": 4096, "pattern": r"\S"},
            "columns": {"type": "array", "minItems": 1, "maxItems": 50, "uniqueItems": True, "items": column},
            "selected_sheet": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"^\S(?:[\s\S]*\S)?$"},
            "transformation_spec": {
                "type": "object", "required": ["version", "fields"], "additionalProperties": False,
                "properties": {
                    "version": {"enum": ["tabular-transform-v1", "tabular-transform-v2"]},
                    "fields": {"type": "array", "minItems": 1, "maxItems": 50, "items": transformation_field},
                },
            },
        },
        "oneOf": [
            {
                "properties": {"native_operation": {"const": "query"}, "task_type": {"const": "structured_export"}},
                "required": ["query_expression", "columns"], "not": {"required": ["transformation_spec"]},
            },
            {
                "properties": {
                    "native_operation": {"const": "transform"}, "task_type": {"enum": ["structured_export", "combined"]},
                },
                "required": ["columns"],
            },
            {
                "properties": {
                    "native_operation": {"const": "analysis"}, "task_type": {"const": "hierarchical_analysis"},
                },
                "not": {"anyOf": [{"required": ["columns"]}, {"required": ["transformation_spec"]}]},
            },
        ],
    }
    for variant in schema["oneOf"]:
        variant["properties"]["document_ids"] = {"maxItems": 1}
        variant["allOf"] = [{"not": {"required": ["relational_spec"]}}]
    schema["oneOf"].append({
        "properties": {"native_operation": {"const": "prepare"}, "task_type": {"const": "structured_export"}},
        "required": ["preparation_request"],
        "not": {"anyOf": [
            {"required": [name]}
            for name in (
                "columns", "query_expression", "selected_sheet", "transformation_spec",
                "relational_spec", "calculation_mode",
            )
        ]},
    })
    schema["oneOf"].append({
        "properties": {
            "native_operation": {"const": "relate"}, "task_type": {"const": "structured_export"},
        },
        "required": ["relational_spec"],
        "not": {"anyOf": [
            {"required": [name]}
            for name in (
                "columns", "query_expression", "selected_sheet", "transformation_spec",
                "preparation_request", "calculation_mode",
            )
        ]},
    })
    schema["oneOf"].append({
        "properties": {
            "native_operation": {"const": "relate"}, "task_type": {"const": "structured_export"},
            "calculation_mode": {"const": "prepared-v1"},
        },
        "required": ["calculation_mode"],
        "not": {"anyOf": [
            {"required": [name]}
            for name in (
                "columns", "query_expression", "selected_sheet", "transformation_spec",
                "preparation_request", "relational_spec",
            )
        ]},
    })
    return schema


def validate_native_orchestration_arguments(arguments):
    """Validate an explicit plan without providers, source reads, or query execution."""
    # Native grammar imports are pure and deferred for registry metadata discovery.
    from functions_tabular_csv_query import validate_tabular_csv_query_expression
    from functions_tabular_relational import TabularRelationalError, normalize_relational_spec
    from functions_tabular_transformations import (
        TabularTransformationSpecError, normalize_tabular_transformation_spec,
    )

    if type(arguments) is not dict or next(
        Draft202012Validator(native_orchestration_arguments_schema()).iter_errors(arguments), None,
    ) is not None:
        raise NativeOrchestrationBridgeError("native_arguments_invalid")
    try:
        if len(canonical_bytes(arguments)) > 65536:
            raise NativeOrchestrationBridgeError("native_arguments_invalid")
        normalized = deepcopy(arguments)
        normalized["task_type"] = _task_type(normalized["native_operation"], normalized.get("task_type"))
        if normalized["native_operation"] == "prepare":
            datasets = normalized["preparation_request"]["datasets"]
            identifiers = [item["document_id"] for item in datasets]
            if (
                identifiers != normalized["document_ids"]
                or len({item["alias"] for item in datasets}) != len(datasets)
                or any(
                    len([profile["name"] for profile in item["key_profiles"]])
                    != len({profile["name"] for profile in item["key_profiles"]})
                    for item in datasets
                )
            ):
                raise NativeOrchestrationBridgeError("native_arguments_invalid")
            return normalized
        if normalized["native_operation"] == "relate" and "relational_spec" in normalized:
            normalized["relational_spec"] = normalize_relational_spec(
                normalized["relational_spec"], normalized["document_ids"],
            )
            return normalized
        if normalized["native_operation"] == "relate":
            return normalized
        normalize_tabular_transformation_spec(
            normalized.get("transformation_spec"), public_output_schema=normalized.get("columns"),
        )
    except TabularRelationalError as exc:
        raise NativeOrchestrationBridgeError("native_arguments_invalid", rule=exc.code, detail=exc.detail) from exc
    except NativeOrchestrationBridgeError:
        raise
    except TabularTransformationSpecError as exc:
        raise NativeOrchestrationBridgeError(
            "native_arguments_invalid", detail={"check": "transformation_spec", "transform_code": exc.code},
        ) from exc
    except (ValueError, TypeError, RecursionError) as exc:
        raise NativeOrchestrationBridgeError("native_arguments_invalid") from exc
    try:
        normalized["query_expression"] = validate_tabular_csv_query_expression(
            normalized.get("query_expression", "index == index"),
        )
    except ValueError as exc:
        raise NativeOrchestrationBridgeError("native_query_unsupported") from exc
    return normalized


def build_native_orchestration_request(
    step, context, *, settings, user_id, source_manifest, native_operation, task_type, cancel_requested=None,
):
    """Build an executable native plan from validated v2 arguments, not prose inference."""
    del context, user_id
    _check_cancel(cancel_requested)
    arguments = validate_native_orchestration_arguments(step.get("arguments"))
    if arguments["native_operation"] != native_operation or arguments["task_type"] != task_type:
        raise NativeOrchestrationBridgeError("native_outputs_invalid")
    if (
        type(source_manifest) is not list or len(source_manifest) != 1 or type(source_manifest[0]) is not dict
        or source_manifest[0].get("source_kind") != "tabular"
        or source_manifest[0].get("authorization_status") != "authorized"
        or arguments["document_ids"] != [source_manifest[0].get("document_id")]
    ):
        raise NativeOrchestrationBridgeError("native_selection_unsupported")
    source_format = os.path.splitext(source_manifest[0].get("file_name", ""))[1].lower()
    if "selected_sheet" in arguments and source_format == ".csv":
        raise NativeOrchestrationBridgeError("native_selection_unsupported")
    # Existing planner/contract services are route-free; no native client is created here.
    from functions_analysis_deliverables import build_analysis_deliverable_contract
    from functions_tabular_orchestration import (
        _build_execution_group_id, _build_request_fingerprint, _build_tabular_execution_units,
        plan_tabular_request,
    )
    from functions_tabular_transformations import (
        get_tabular_transformation_model_fields, normalize_tabular_transformation_spec,
    )

    question = arguments["question"]
    columns = arguments.get("columns", [])
    spec = normalize_tabular_transformation_spec(arguments.get("transformation_spec"), public_output_schema=columns)
    analysis = task_type in {"combined", "hierarchical_analysis"}
    action_mode = "analyze" if analysis else None
    hints = {
        "native_operation": native_operation, "query_expression": arguments["query_expression"],
        "public_output_schema": columns, "transformation_spec": spec,
    }
    if "selected_sheet" in arguments:
        hints["selected_sheet"] = arguments["selected_sheet"]
    plan = plan_tabular_request(
        question, source_manifest, action_mode=action_mode, settings=settings,
        caller="orchestration", requested_output_hints=hints,
    )
    execution_contract = (
        "foreground_aggregate" if plan["execution_contract"] == "foreground_aggregate" else task_type
    )
    request_fingerprint = _build_request_fingerprint(
        question, action_mode, execution_contract, None, plan["source_coverage"],
    )
    model_fields = get_tabular_transformation_model_fields(spec, columns)
    transformation_mode = (
        "deterministic" if native_operation == "query" or (spec and not model_fields)
        else "hybrid" if spec.get("deterministic_field_order")
        else "semantic"
    )
    row_output = task_type != "hierarchical_analysis"
    contract = build_analysis_deliverable_contract(
        action_mode=action_mode, analysis_required=analysis, requested_artifacts=[],
        public_output_schema=columns,
        row_cardinality="one_per_source_row" if row_output else "not_applicable",
        ordering="source_order" if row_output else "not_applicable",
        transformation_mode=transformation_mode, transformation_spec=spec,
        validation_profile=(
            "exact_rows_schema_and_rules" if row_output and spec
            else "exact_rows_schema" if row_output else "artifact_set"
        ),
        source_fingerprint=plan["deliverable_contract"]["source_fingerprint"],
        request_fingerprint=request_fingerprint,
    ).to_dict()
    if contract["public_output_schema"] != columns:
        raise NativeOrchestrationBridgeError("native_arguments_invalid")
    plan.update({
        "deliverable_contract": contract, "execution_contract": execution_contract,
        "durable_task_type": task_type, "requested_output_formats": [], "output_format": None,
        "generated_output_requested": False, "hierarchical_analysis_requested": analysis,
        "exhaustive_row_output_requested": False, "row_analysis_mode": "summary", "row_analysis_questions": [],
        "execution_state": "foreground" if execution_contract == "foreground_aggregate" else "declined",
        "reason_code": "bounded_foreground" if execution_contract == "foreground_aggregate" else "durable_intent",
        "safe_failure_details": None, "request_fingerprint": request_fingerprint,
        "execution_group_id": _build_execution_group_id(
            question, action_mode, execution_contract, None, plan["source_coverage"],
        ),
        "execution_units": _build_tabular_execution_units(
            question, source_manifest, action_mode, execution_contract, task_type, None,
            plan["source_coverage"], settings,
        ),
    })
    _check_cancel(cancel_requested)
    return NativeOrchestrationRequest(plan, question)


@dataclass(frozen=True)
class NativeOrchestrationBridge:
    native_operation: str
    task_type: str
    request_builder: Callable
    model_resolver: Callable | None = None
    source_policy: str = "current"
    max_analysis_bytes: int = MAX_VALUE_BYTES
    input_fingerprint_for_step: Callable | None = None

    @property
    def output_specs(self):
        return native_orchestration_output_specs(self.native_operation, task_type=self.task_type)

    def execute(self, step, context, *, settings, user_id, emit=None, cancel_requested=None):
        return execute_native_orchestration_step(
            step, context, settings=settings, user_id=user_id, emit=emit,
            cancel_requested=cancel_requested, binding=self,
        )

    def resume(self, step, context, pending_result, *, settings, user_id, emit=None, cancel_requested=None):
        return resume_native_orchestration_step(
            step, context, pending_result, settings=settings, user_id=user_id,
            emit=emit, cancel_requested=cancel_requested, binding=self,
        )


def build_native_orchestration_bridge(
    *, native_operation, request_builder=None, task_type=None, model_resolver=None,
    source_policy="current", max_analysis_bytes=MAX_VALUE_BYTES, input_fingerprint_for_step=None,
):
    """Bind trusted callbacks, never a browser/model-selected execution function.

    request_builder(step, context, *, settings, user_id, source_manifest,
                    native_operation, task_type, cancel_requested)
        -> NativeOrchestrationRequest
    model_resolver(step, context, *, settings, user_id)
        -> {"gpt_model": str, "model_context": dict | None} (optional)
    input_fingerprint_for_step(step, context) -> the owning checkpoint fingerprint

    Without request_builder the production v2 argument builder is used.
    Without model_resolver the initialized context's gpt_model/model_context are
    used. No route, settings owner, client factory, or model-selection fallback
    is discovered here. Bind .execute/.resume to the parent's dispatch/resolver.
    """
    selected = _task_type(native_operation, task_type)
    if request_builder is None:
        request_builder = build_native_orchestration_request
    if (
        not callable(request_builder)
        or any(value is not None and not callable(value) for value in (model_resolver, input_fingerprint_for_step))
        or source_policy not in ("current", "snapshot")
        or type(max_analysis_bytes) is not int or not 0 < max_analysis_bytes <= MAX_VALUE_BYTES
    ):
        raise NativeOrchestrationBridgeError("native_binding_required")
    return NativeOrchestrationBridge(
        native_operation, selected, request_builder, model_resolver, source_policy,
        max_analysis_bytes, input_fingerprint_for_step,
    )


def _step_result(**values):
    # Schema imports registry metadata; metadata discovery must not import it back.
    from functions_orchestration_schema import build_step_result

    return build_step_result(**values)


def _check_cancel(cancel_requested):
    if cancel_requested is not None:
        if not callable(cancel_requested):
            raise NativeOrchestrationBridgeError("native_runtime_invalid")
        if cancel_requested():
            raise NativeOrchestrationBridgeError("native_cancelled")


def raise_native_orchestration_infrastructure_failure(error):
    """Preserve typed service failures without promoting native validation errors."""
    # Read-side classification is needed only on failure, not during native discovery.
    from functions_orchestration_artifacts import external_authority_failure
    from functions_orchestration_output_store import OutputError, OutputStorageError
    from functions_orchestration_rendering import raise_output_read_infrastructure_failure
    from functions_workflow_result_store import WorkflowResultStorageUnavailableError

    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, WorkflowResultStorageUnavailableError):
            raise OutputStorageError() from error
        try:
            raise_output_read_infrastructure_failure(current)
        except (ScreeningError, OutputStorageError, OutputError, PermissionError):
            raise
        except Exception as failure:
            if external_authority_failure(failure) is not None:
                raise
            # The read helper also raises unknown nested causes. Native validation
            # remains a safe failure, but a deeper recognized outage must not vanish.
        current = current.__cause__


def _failure(step, exc, stage, context=None):
    from functions_orchestration_schema import build_failure
    from functions_tabular_relational import native_error_diagnostics

    raise_native_orchestration_infrastructure_failure(exc)
    service_code = getattr(exc, "code", None)
    service_code = service_code if isinstance(service_code, str) else None
    if isinstance(exc, NativeOrchestrationBridgeError):
        code = exc.code
    elif service_code == "relational_cancelled":
        code = "native_cancelled"
    elif service_code == "relational_match_ambiguous":
        code = "native_relational_ambiguous"
    elif service_code == "relational_schema_changed":
        code = "native_source_schema_mismatch"
    elif service_code and service_code.startswith("relational_"):
        code = "native_relational_limit" if service_code.endswith("_limit") else "native_relational_invalid"
    elif service_code in {
        "too_many_sources", "row_limit_exceeded", "cell_too_large", "source_too_large",
        "workbook_too_large", "too_many_sheets", "calculation_context_too_large",
        "calculation_context_work_limit",
    }:
        code = "native_relational_limit"
    elif service_code == "sheet_required":
        code = "native_relational_invalid"
    elif service_code == "formula_cache_missing":
        code = "native_formula_value_unavailable"
    elif isinstance(exc, (PermissionError, ScreeningError)) or service_code in _SOURCE_CHANGED_CODES:
        code = "native_access_unavailable"
    elif isinstance(exc, ResultContractError) and "guard" in exc.code:
        code = "native_guard_unavailable"
    else:
        code = "native_retention_failed" if stage == "retention" else "native_execution_failed"
    failure_code = (
        "user_cancelled" if code == "native_cancelled"
        else "context_unavailable" if code == "native_access_unavailable"
        else "ownership_lost" if code == "native_guard_unavailable"
        else "analysis_result_not_saved" if code == "native_retention_failed"
        else "source_schema_mismatch" if code == "native_source_schema_mismatch"
        else STORAGE_FAILURE_CODE if code == "native_storage_unavailable"
        else "result_invalid"
    )
    step_id = step.get("step_id") if isinstance(step, dict) else None
    log_event(
        "[ORCHESTRATION_ADAPTERS] Native result bridge did not complete.",
        extra={
            **workflow_log_context(
                run_id=getattr(context, "run_id", None),
                conversation_id=getattr(context, "conversation_id", None),
                turn_id=getattr(context, "turn_id", None),
                step_id=step_id,
            ),
            "native_code": code, "stage": stage,
            "error_type": type(exc).__name__, "failure_code": failure_code,
            "execution_code": service_code or code,
            **native_error_diagnostics(exc),
        },
        level=logging.WARNING,
    )
    result = _step_result(
        status="cancelled" if code == "native_cancelled" else "failed",
        summary=_MESSAGES[code], error=_MESSAGES[code], failure=build_failure(failure_code),
    )
    result["failure"].update({"native_code": code, "retryable": code == "native_storage_unavailable"})
    calculation_cause = None
    if getattr(exc, "rule", None) in {"generation_incomplete", "lowering_call_limit",
                                       "lowering_call_uncertain"}:
        calculation_cause = "generation_incomplete"
    elif service_code == "relational_match_ambiguous":
        calculation_cause = "relationship_grain_invalid"
    elif service_code == "relational_schema_changed":
        calculation_cause = None
    elif service_code and service_code.startswith("relational_"):
        calculation_cause = "calculation_program_invalid"
    if calculation_cause is not None:
        result["failure"]["calculation_cause"] = calculation_cause
        result["summary"] = build_failure(calculation_cause)["message"]
        result["error"] = result["summary"]
    return result


def _runtime(step, context, user_id, binding):
    if type(binding) is not NativeOrchestrationBridge:
        raise NativeOrchestrationBridgeError("native_binding_required")
    if (
        type(step) is not dict or step.get("role") != "reason"
        or step.get("enabled", True) is not True or getattr(context, "plan_contract_version", None) != 2
        or not callable(getattr(context, "result_producer", None))
        or not callable(getattr(context, "result_guard_token_for_step", None))
        or type(step.get("inputs", {})) is not dict
    ):
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    prepared = (
        binding.native_operation == "relate"
        and step.get("arguments", {}).get("calculation_mode") == "prepared-v1"
    )
    if step.get("inputs") and not (prepared and set(step["inputs"]) == {"preparation"}):
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    if binding.request_builder is build_native_orchestration_request:
        arguments = validate_native_orchestration_arguments(step.get("arguments"))
        if arguments["native_operation"] != binding.native_operation or arguments["task_type"] != binding.task_type:
            raise NativeOrchestrationBridgeError("native_outputs_invalid")
    elif binding.native_operation == "relate":
        raise NativeOrchestrationBridgeError("native_binding_required")
    service = getattr(context, "result_service", None)
    if not isinstance(service, OrchestrationResults):
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    producer = context.result_producer(step)
    if type(producer) is not ProducerIdentity or (
        producer.user_id != user_id or producer.user_id != getattr(context, "user_id", None)
        or producer.conversation_id != getattr(context, "conversation_id", None)
        or producer.run_id != getattr(context, "run_id", None)
        or producer.attempt_index != getattr(context, "attempt_index", None)
        or producer.step_id != step.get("step_id") or producer.capability_id != step.get("capability_id")
        or producer.capability_id not in ("tabular_analyze", "document_analyze")
    ):
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    expected = {spec.name: spec.kind for spec in binding.output_specs}
    declared = step.get("outputs")
    if (
        type(declared) is not list or len(declared) != len(expected)
        or any(type(value) is not dict or set(value) != {"name", "kind"} for value in declared)
        or {value["name"]: value["kind"] for value in declared} != expected
    ):
        raise NativeOrchestrationBridgeError("native_outputs_invalid")
    service.access.authorize_producer(producer)
    return service, producer


def _sources(step, context, service, *, require_current, require_replay=False, multiple=False):
    manifest = getattr(context, "source_manifest", None)
    if (
        type(manifest) is not list or not manifest or (not multiple and len(manifest) != 1)
        or any(type(source) is not dict or source.get("source_kind") != "tabular"
               or source.get("authorization_status") != "authorized" for source in manifest)
    ):
        raise NativeOrchestrationBridgeError("native_selection_unsupported")
    # A schema discovered during planning belongs to that source revision, not to
    # whatever later occupies the same document ID. Older plans have no such fence.
    from functions_orchestration_source_context import source_planning_revision

    revisions = getattr(context, "planning_source_revisions", None) or {}
    for source in manifest:
        expected = revisions.get(source.get("document_id"))
        if expected is not None and expected != source_planning_revision(source):
            raise NativeOrchestrationBridgeError("native_source_changed")
    arguments = step.get("arguments", {})
    if type(arguments) is not dict:
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    selected = arguments.get("document_ids", [])
    if (
        type(selected) is not list or (not multiple and len(selected) > 1)
        or (multiple and selected != [source.get("document_id") for source in manifest])
        or (selected and any(type(value) is not str for value in selected))
        or (not multiple and selected and selected[0] != manifest[0].get("document_id"))
        or arguments.get("left_document_id") or arguments.get("right_document_ids")
    ):
        raise NativeOrchestrationBridgeError("native_selection_unsupported")
    if require_replay:
        for source in manifest:
            locator = source.get("storage_locator")
            if (
                type(source.get("file_name")) is not str
                or os.path.splitext(source["file_name"])[1].lower() not in (".csv", ".xlsx", ".xls", ".xlsm")
                or type(locator) is not dict
                or any(type(locator.get(key)) is not str or not locator[key] for key in ("container", "blob_path"))
            ):
                raise NativeOrchestrationBridgeError("native_selection_unsupported")
    snapshots = analysis_source_snapshot(manifest)
    # The native engine reads the uploaded tabular file itself, so this is an input read.
    service.access.authorize_input_sources(snapshots, require_snapshot=require_current)
    return deepcopy(manifest), snapshots


def _input_fingerprint(step, context, binding):
    if binding.input_fingerprint_for_step is None:
        return None
    value = binding.input_fingerprint_for_step(step, context)
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    return value


def _guard(context, service, producer):
    token = context.result_guard_token_for_step(producer.step_id)
    if type(token) is not str or not token.strip() or token != token.strip():
        raise NativeOrchestrationBridgeError("native_guard_unavailable")
    service.access.authorize_producer(producer, for_write=True)
    service.store.prepare_orchestration_result(
        producer.user_id, producer.conversation_id, producer.run_id, producer.step_id, guard_token=token,
    )
    return token


def _validate_wait(wait, producer):
    from functions_native_tabular_compute import validate_native_compute_handle

    if type(wait) is not dict or set(wait) != {"kind", "handle"} or wait["kind"] != NATIVE_WAIT_KIND:
        raise NativeOrchestrationBridgeError("native_wait_invalid")
    try:
        validate_native_compute_handle(wait["handle"], producer.to_dict())
    except (ValueError, PermissionError) as exc:
        raise NativeOrchestrationBridgeError("native_wait_invalid") from exc
    return deepcopy(wait["handle"])


def _pending(native, producer):
    if native.get("reader") is not None or native.get("readers"):
        raise NativeOrchestrationBridgeError("native_result_invalid")
    wait = {"kind": NATIVE_WAIT_KIND, "handle": native.get("handle")}
    _validate_wait(wait, producer)
    return _step_result(
        status="waiting", summary="Native computation is pending; no result is ready to consume.",
        task_result=TaskResult(producer, "reason", "pending", ()), wait=wait,
    )


def _completeness(reader):
    value = reader.completeness
    fields = {"status", "expected_count", "actual_count", "coverage", "validation", "checks", "limitations", "preview"}
    if (
        type(value) is not dict or set(value) != fields
        or type(value["checks"]) is not list or type(value["limitations"]) is not list
        or value["coverage"] != reader.coverage or value["actual_count"] != reader.item_count
    ):
        raise NativeOrchestrationBridgeError("native_result_invalid")
    result = Completeness(
        value["status"], value["expected_count"], value["actual_count"],
        Coverage.from_dict(value["coverage"]), value["validation"],
        tuple(value["checks"]), tuple(value["limitations"]), value["preview"],
    )
    result.require_readable()
    return result


def _records(reader, cancel_requested):
    for index, row in enumerate(reader.iter_records()):
        if index % 256 == 0:
            _check_cancel(cancel_requested)
        yield row
    _check_cancel(cancel_requested)


def _retained_summary(task):
    records = next((item for item in task.outputs if item.output_name == "records"), None)
    return (
        f"Native computation retained all {records.item_count:,} records."
        if records is not None else "Native analysis retained its complete result."
    )


def _retain(native, context, service, producer, snapshots, binding, cancel_requested, input_fingerprint):
    from functions_native_analysis_results import NativeTabularResultReader

    _validate_wait({"kind": NATIVE_WAIT_KIND, "handle": native.get("handle")}, producer)
    expected = {spec.name: spec.kind for spec in binding.output_specs if spec.name != "coverage"}
    readers = native.get("readers")
    if (
        type(readers) is not dict or set(readers) != set(expected)
        or native.get("reader") is not (readers.get("records") or readers.get("analysis"))
    ):
        raise NativeOrchestrationBridgeError("native_result_invalid")
    outputs = []
    coverage = {"sources": deepcopy(snapshots), "outputs": {}}
    counts = []
    limitations = []
    summary = None
    for name, kind in expected.items():
        reader = readers[name]
        if (
            not isinstance(reader, NativeTabularResultReader) or reader.kind != kind
            or analysis_source_snapshot(reader.sources) != snapshots or reader.sources != snapshots
        ):
            raise NativeOrchestrationBridgeError("native_result_invalid")
        complete = _completeness(reader)
        columns = tuple(RecordColumn.from_dict(column) for column in reader.columns)
        if tuple(column.name for column in columns) != reader.schema:
            raise NativeOrchestrationBridgeError("native_result_invalid")
        if kind == "records-v1":
            value = _records(reader, cancel_requested)
        else:
            _check_cancel(cancel_requested)
            value = reader.read_value(max_bytes=binding.max_analysis_bytes)
            _check_cancel(cancel_requested)
            if type(value) is not dict or not isinstance(value.get("summary"), str):
                raise NativeOrchestrationBridgeError("native_result_invalid")
            summary = value["summary"]
        outputs.append(NamedOutput(name, kind, value, complete, columns))
        coverage["outputs"][name] = complete.to_dict()
        counts.append(complete.coverage)
        limitations.extend(complete.limitations)
    if any(count != counts[0] for count in counts):
        raise NativeOrchestrationBridgeError("native_result_invalid")
    outputs.append(NamedOutput(
        "coverage", "structured-v1", coverage,
        Completeness("complete", 1, 1, counts[0], "valid", ("native_complete_output_coverage",),
                     tuple(dict.fromkeys(limitations))),
    ))
    _check_cancel(cancel_requested)
    guard_token = _guard(context, service, producer)
    options = {"input_fingerprint": input_fingerprint} if input_fingerprint is not None else {}
    task = service.persist_task_result(
        producer=producer, role="reason", status="complete", outputs=outputs, sources=snapshots,
        origin="grounded", source_policy=binding.source_policy, guard_token=guard_token, **options,
    )
    _check_cancel(cancel_requested)
    return _step_result(status="completed", summary=summary or _retained_summary(task), task_result=task)


def _finish(native, context, service, producer, snapshots, binding, cancel_requested, input_fingerprint):
    if type(native) is not dict:
        raise NativeOrchestrationBridgeError("native_result_invalid")
    status = native.get("status")
    if status == "pending":
        return _pending(native, producer)
    if status == "cancelled":
        raise NativeOrchestrationBridgeError("native_cancelled")
    if status == "failed":
        if native.get("failure_code") == STORAGE_FAILURE_CODE:
            raise NativeOrchestrationBridgeError("native_storage_unavailable")
        raise NativeOrchestrationBridgeError("native_execution_failed")
    if status != "completed":
        raise NativeOrchestrationBridgeError("native_result_invalid")
    return _retain(native, context, service, producer, snapshots, binding, cancel_requested, input_fingerprint)


def _execute_relational(step, context, service, producer, manifest, snapshots, binding, settings, cancel_requested):
    """Run the bounded deterministic extension without a provider or native job."""
    from functions_orchestration_merge import build_tabular_merge_sources, tabular_merge_limits
    from functions_tabular_merge import read_tabular_source_records
    from functions_tabular_relational import calculate_relational_sources

    arguments = validate_native_orchestration_arguments(step["arguments"])
    limits = tabular_merge_limits(settings)
    if len(manifest) > limits.max_sources:
        raise NativeOrchestrationBridgeError("native_relational_limit")
    fingerprint = _input_fingerprint(step, context, binding)
    sources = build_tabular_merge_sources(
        manifest, producer.user_id, byte_reader=getattr(context, "merge_source_reader", None),
    )
    with orchestration_file_policy(allow_generated_files=False):
        datasets = {}
        for source, selected in zip(sources, arguments["relational_spec"]["datasets"]):
            def open_table(source=source, selected=selected):
                _check_cancel(cancel_requested)
                return read_tabular_source_records(
                    source, sheet=selected.get("sheet"), header_row=selected.get("header_row"),
                    cell_range=selected.get("cell_range"), table_id=selected.get("table_id"),
                    limits=limits, cancel_requested=cancel_requested,
                )

            datasets[selected["alias"]] = open_table
        calculated = calculate_relational_sources(
            arguments["relational_spec"], datasets, limits=limits, cancel_requested=cancel_requested,
        )
    _check_cancel(cancel_requested)
    service.access.authorize_input_sources(snapshots, require_snapshot=True)
    calculated["coverage"]["source_snapshots"] = deepcopy(snapshots)
    coverage = Coverage(len(snapshots), len(snapshots), "sources")
    checks = ("complete_authorized_tables", "validated_relational_operations", "precise_decimal_values",
              "declared_match_cardinality", "exact_row_lineage")
    count = len(calculated["records"])
    complete = Completeness("complete", count, count, coverage, "valid", checks, ())
    columns = tuple(RecordColumn.from_dict(column) for column in calculated["columns"])
    outputs = [
        NamedOutput("records", "records-v1", calculated["records"], complete, columns),
        NamedOutput("lineage", "records-v1", calculated["lineage"], complete, (
            RecordColumn("result_row", "integer"), RecordColumn("sources", "array"),
        )),
        NamedOutput("coverage", "structured-v1", calculated["coverage"],
                    Completeness("complete", 1, 1, coverage, "valid", checks, ())),
    ]
    token = _guard(context, service, producer)
    options = {"input_fingerprint": fingerprint} if fingerprint is not None else {}
    task = service.persist_task_result(
        producer=producer, role="reason", status="complete", outputs=outputs, sources=snapshots,
        origin="grounded", source_policy=binding.source_policy, guard_token=token, **options,
    )
    _check_cancel(cancel_requested)
    return _step_result(status="completed", summary=f"Calculated and retained {count:,} records from {len(snapshots)} files.",
                        task_result=task)


def _prepared_program_prompt(question, context_value, schema, *, correction=None):
    instructions = (
        "Author one closed deterministic tabular relational program for the approved question. "
        "Use only the exact preparation below and the supplied schema. Return JSON only, with no "
        "prose or additional wrapper. Do not hardcode fixture outcomes, document IDs outside the "
        "selection, new sources, SQL, Python, tools, or an external action. Keep every declared "
        "source, preserve exact identifiers and signed decimal values, and declare complete records, "
        "lineage and coverage through the relational result/output contract. Classify the complete "
        "relevant population before filtering: retain explicit unknown and excluded dispositions "
        "instead of turning an excluded record into a missing one or dropping it."
    )
    if correction is not None:
        instructions += (
            f" Correct the prior authored program. The closed validation category is "
            f"{correction.get('category')}, check {correction.get('check')}, "
            f"step index {correction.get('step_index')}. When a rejection object is supplied, it "
            "states what was wrong; use it. Do not change the approved sources, "
            "question, horizon, output fields, token budget or requested effects."
        )
    payload = {
        "instructions": instructions, "question": question,
        "program_schema": schema, "complete_preparation": context_value,
    }
    if isinstance((correction or {}).get("program"), dict):
        payload["rejected_program"] = deepcopy(correction["program"])
    rejection = {
        key: deepcopy(correction[key]) for key in ("location", "feedback")
        if isinstance((correction or {}).get(key), dict)
    }
    if rejection:
        # What was wrong, in the terms the authoring model already has: its own program and the
        # prepared headers. Never logged; the telemetry path reads the closed detail only.
        payload["rejection"] = rejection
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _prepared_state(store, step_id, binding, fingerprint):
    from functions_orchestration_checkpoints import CheckpointError

    try:
        return store.load_lowering_state(
            step_id, binding=binding, input_fingerprint=fingerprint,
        )
    except CheckpointError as exc:
        if exc.code == "checkpoint_unavailable":
            return {
                "version": "tabular-program-lowering-v1",
                "phase": "context_checked", "calls_used": 0,
                "completion_contract_version": "harness-stop-v1",
            }
        raise


def _evaluation_correction(error):
    """A well-formed program that could not evaluate a row of the real data.

    The finding is the evaluator's own: which step and operand, the kind of value it expected
    and the kind it found. It carries no cell value. The author already holds its program and
    the kinds each column holds, so this is enough to revise the step. A join whose matches
    contradict its declared cardinality is not returned this way: see _safe_program_correction.
    """
    from functions_tabular_relational import safe_native_detail

    detail = safe_native_detail(getattr(error, "detail", None))
    correction = {
        "category": error.code, "check": detail.get("check") or "step_evaluation",
        "step_index": detail.get("step_index", 0), "origin": "evaluation",
    }
    location = {key: value for key, value in detail.items() if key not in ("check", "step_index")}
    if location:
        correction["location"] = location
    return correction


def _saved_correction_admissible(correction):
    """Whether a correction read back from saved state is one this code would have saved."""
    from functions_tabular_relational import TabularRelationalError

    if correction.get("origin") == "evaluation":
        return (
            isinstance(correction.get("category"), str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", correction["category"]) is not None
        )
    return _safe_program_correction(TabularRelationalError(
        correction["category"], detail={
            key: correction[key] for key in ("check", "step_index") if key in correction
        },
    )) is not None


def _safe_program_correction(error):
    from functions_tabular_relational import TabularRelationalError
    from functions_tabular_transformations import TabularTransformationEvaluationError

    if isinstance(error, TabularTransformationEvaluationError):
        return _evaluation_correction(error)
    if not isinstance(error, TabularRelationalError):
        return None
    category = error.code
    if category not in {
        "relational_column_missing", "relational_spec_invalid",
        "relational_expression_invalid", "relational_source_unused",
    }:
        return None
    detail = error.detail or {}
    if (
        detail.get("check") in {"json_parse", "json_object"}
        or category == "relational_column_missing"
        and detail.get("check") != "column_missing"
    ):
        return None
    correction = {
        "category": category,
        "check": detail.get("check") or "closed_validation",
        "step_index": detail.get("step_index", 0),
    }
    location = {key: value for key, value in detail.items() if key not in ("check", "step_index")}
    if location:
        correction["location"] = location
    if isinstance(getattr(error, "feedback", None), dict):
        correction["feedback"] = deepcopy(error.feedback)
    return correction


def _approved_preparation_request_digest(context, request, *, question=None):
    approved_request = getattr(context, "resolved_message", None) or getattr(
        context, "user_message", None,
    ) or question
    if not isinstance(approved_request, str) or not approved_request.strip():
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    return hashlib.sha256(canonical_bytes({
        "question": approved_request, "request": request,
    })).hexdigest()


def _preparation_sources_match(value, snapshots, prepared_sources, manifest):
    if (
        type(value) is not list
        or type(prepared_sources) is not list
        or len(value) != len(prepared_sources)
        or len(value) != len(snapshots)
        or len(value) != len(manifest)
    ):
        return False
    for bound, prepared, snapshot, source in zip(value, prepared_sources, snapshots, manifest):
        if (
            not isinstance(bound, dict) or not isinstance(prepared, dict)
            or bound.get("document_id") != prepared.get("document_id")
            or bound.get("document_id") != snapshot.get("document_id")
            or bound.get("document_id") != source.get("document_id")
            or bound.get("content_sha256") != prepared.get("content_sha256")
            or {key: item for key, item in bound.items() if key != "content_sha256"} != snapshot
        ):
            return False
    return True


def _bound_preparation_step(context, step):
    binding = (step.get("inputs") or {}).get("preparation") or {}
    step_id = (binding.get("binding") or {}).get("step_id")
    plan_steps = getattr(context, "plan_steps", None)
    if not isinstance(step_id, str) or type(plan_steps) is not list:
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    preparation_step = next(
        (candidate for candidate in plan_steps
         if isinstance(candidate, dict) and candidate.get("step_id") == step_id),
        None,
    )
    if (
        not isinstance(preparation_step, dict)
        or preparation_step.get("capability_id") != "tabular_analyze"
    ):
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    preparation_arguments = validate_native_orchestration_arguments(
        preparation_step.get("arguments"),
    )
    if preparation_arguments.get("native_operation") != "prepare":
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    return preparation_step, preparation_arguments


def _source_with_content_fence(source, expected_digest):
    from functions_tabular_merge import TabularMergeSource

    if re.fullmatch(r"[a-f0-9]{64}", expected_digest or "") is None:
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")

    def load():
        content = source.load_bytes()
        if isinstance(content, bytearray):
            content = bytes(content)
        if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != expected_digest:
            raise NativeOrchestrationBridgeError("native_source_changed")
        return content

    return TabularMergeSource(
        source.source_id, source.file_name, load, extension=source.extension,
    )


def _execute_prepared_relational(
    step, context, service, producer, manifest, snapshots, binding, settings, cancel_requested,
):
    """Lower one prepared calculation, with a durable call ceiling and no tools."""
    from functions_orchestration_checkpoints import CheckpointError, CheckpointStore
    from functions_orchestration_merge import build_tabular_merge_sources, tabular_merge_limits
    from functions_orchestration_result_runtime import read_complete_input, resolve_step_inputs
    from functions_tabular_merge import TabularMergeSource, read_tabular_source_records
    from functions_tabular_relational import (
        TabularRelationalError, calculate_relational_sources, check_relational_columns,
        normalize_relational_spec, relational_spec_schema, with_operation_version,
    )
    from functions_tabular_transformations import TabularTransformationEvaluationError

    invoke = getattr(context, "invoke_prompt", None)
    store = getattr(context, "completeness_store", None)
    checkpoint_binding = getattr(context, "completeness_binding", None)
    if (
        not callable(invoke) or getattr(invoke, "enforces_complete_generation", False) is not True
        or not isinstance(store, CheckpointStore) or not isinstance(checkpoint_binding, str)
    ):
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    readers = resolve_step_inputs(step, context)
    if set(readers) != {"preparation"}:
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    reader = readers["preparation"]
    if reader.reference.output_name != "context" or reader.reference.producer.capability_id != "tabular_analyze":
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    context_value = read_complete_input(reader, max_bytes=96 * 1024)
    _preparation_step, preparation_arguments = _bound_preparation_step(context, step)
    arguments = validate_native_orchestration_arguments(step["arguments"])
    if (
        type(context_value) is not dict
        or context_value.get("version") != "tabular-calculation-context-v1"
        or context_value.get("complete") is not True
        or context_value.get("analytical_request_sha256")
        != _approved_preparation_request_digest(
            context, preparation_arguments["preparation_request"],
            question=arguments["question"],
        )
    ):
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    preparation_binding = step["inputs"]["preparation"]["binding"]
    preparation_task = context.task_results.get(preparation_binding["step_id"])
    if (
        preparation_task is None
        or [output.output_name for output in preparation_task.outputs] != ["context", "coverage"]
    ):
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    coverage_reader = service.open_result(
        preparation_task.output("coverage"), require_current_sources=True,
    )
    coverage_reader.recheck()
    preparation_coverage = read_complete_input(coverage_reader)
    if (
        type(preparation_coverage) is not dict
        or preparation_coverage.get("complete") is not True
        or preparation_coverage.get("source_snapshots") != context_value.get("source_snapshots")
        or preparation_coverage.get("profile_sha256") != context_value.get("profile_sha256")
        or preparation_coverage.get("analytical_request_sha256")
        != context_value.get("analytical_request_sha256")
    ):
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    prepared_sources = context_value.get("datasets")
    requested_sources = preparation_arguments["preparation_request"].get("datasets")
    if (
        type(prepared_sources) is not list
        or type(requested_sources) is not list
        or [item.get("document_id") for item in prepared_sources] != [
            item.get("document_id") for item in manifest
        ]
        or [item.get("document_id") for item in requested_sources] != [
            item.get("document_id") for item in manifest
        ]
        or [item.get("document_id") for item in preparation_coverage.get("datasets") or []]
        != [item.get("document_id") for item in manifest]
        or preparation_arguments.get("document_ids") != arguments["document_ids"]
        or any(
            prepared.get("alias") != requested.get("alias")
            or prepared.get("selection") != {
                key: requested[key]
                for key in ("header_row", "cell_range", "table_id") if key in requested
            }
            or [
                item.get("column") for item in prepared.get("context_columns") or []
                if isinstance(item, dict)
            ] != requested.get("context_columns")
            or [
                {"name": item.get("name"), "columns": item.get("columns")}
                for item in prepared.get("key_profiles") or []
                if isinstance(item, dict)
            ] != requested.get("key_profiles")
            or (
                "sheet" in requested
                and prepared.get("sheet") != requested["sheet"]
            )
            for prepared, requested in zip(prepared_sources, requested_sources)
        )
        or not _preparation_sources_match(
            context_value.get("source_snapshots"), snapshots, prepared_sources, manifest,
        )
        or context_value.get("profile_sha256") != hashlib.sha256(canonical_bytes({
            "datasets": prepared_sources,
            "source_snapshots": context_value.get("source_snapshots"),
            "analytical_request_sha256": context_value.get("analytical_request_sha256"),
        })).hexdigest()
    ):
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    fingerprint = _input_fingerprint(step, context, binding)
    state = _prepared_state(store, step["step_id"], checkpoint_binding, fingerprint)
    limits = tabular_merge_limits(settings)
    if fingerprint is None:
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    source_headers = {
        item["alias"]: item["headers"] for item in prepared_sources if isinstance(item, dict)
    }
    if state["phase"] in {"program_saved", "evaluating"}:
        try:
            saved_program = normalize_relational_spec(
                state.get("program"), arguments["document_ids"],
            )
            check_relational_columns(saved_program, source_headers)
            if saved_program != state.get("program"):
                raise TabularRelationalError(
                    "relational_spec_invalid", detail={"check": "saved_program_normalization"},
                )
            prepared_by_id = {
                item["document_id"]: item for item in prepared_sources
                if isinstance(item, dict)
            }
            for dataset in saved_program["datasets"]:
                prepared = prepared_by_id[dataset["document_id"]]
                expected_selectors = {
                    "sheet": prepared.get("sheet"),
                    **prepared.get("selection"),
                }
                if (
                    dataset["alias"] != prepared["alias"]
                    or any(
                        dataset.get(name) != value
                        for name, value in expected_selectors.items()
                        if name in dataset
                    )
                    or "columns" in dataset and dataset["columns"] != prepared["headers"]
                ):
                    raise TabularRelationalError(
                        "relational_selection_invalid",
                        detail={"check": "saved_program_selection"},
                    )
        except (KeyError, TypeError, TabularRelationalError) as exc:
            raise CheckpointError("checkpoint_invalid") from exc
    sources = build_tabular_merge_sources(
        manifest, producer.user_id, byte_reader=getattr(context, "merge_source_reader", None),
    )
    sources = [
        _source_with_content_fence(source, prepared["content_sha256"])
        for source, prepared in zip(sources, prepared_sources)
    ]
    verified_sources = []
    for source in sources:
        content = source.load_bytes()
        verified_sources.append(TabularMergeSource(
            source.source_id, source.file_name, lambda value=content: value,
            extension=source.extension,
        ))
    service.access.authorize_input_sources(snapshots, require_snapshot=True)
    with orchestration_file_policy(allow_generated_files=False):
        datasets = {}
        for source, prepared in zip(verified_sources, prepared_sources):
            def open_table(source=source, prepared=prepared):
                return read_tabular_source_records(
                    source, sheet=prepared.get("sheet") or None,
                    header_row=prepared["selection"].get("header_row"),
                    cell_range=prepared["selection"].get("cell_range"),
                    table_id=prepared["selection"].get("table_id"),
                    limits=limits, cancel_requested=cancel_requested,
                )

            datasets[prepared["alias"]] = open_table

        correction = None
        if state["phase"] == "failure_saved":
            if (
                state.get("completion_confirmed") is not True
                or not isinstance(state.get("last_failure"), dict)
                or not isinstance(state.get("program"), dict)
            ):
                last_failure = state.get("last_failure") or {}
                failure_detail = {
                    key: last_failure[key] for key in (
                        "check", "step_index", "role", "missing_count", "category",
                    ) if key in last_failure
                } if isinstance(last_failure, dict) else {}
                raise TabularRelationalError(
                    last_failure.get("category", "relational_spec_invalid")
                    if isinstance(last_failure.get("category"), str)
                    else "relational_spec_invalid",
                    detail=failure_detail,
                )
            correction = deepcopy(state["last_failure"])
            correction["program"] = deepcopy(state["program"])
            if not _saved_correction_admissible(correction):
                raise TabularRelationalError(
                    correction["category"], detail={
                        key: correction[key] for key in ("check", "step_index")
                        if key in correction
                    },
                )
        while True:
            if state["phase"] == "call_reserved":
                raise NativeOrchestrationBridgeError(
                    "native_execution_failed", rule="lowering_call_uncertain",
                )
            if state["phase"] in ("program_saved", "evaluating") and (
                isinstance(state.get("program"), dict)
                and state.get("completion_confirmed") is True
            ):
                program = deepcopy(state["program"])
            else:
                if state["calls_used"] >= LOWERING_MAX_CALLS:
                    raise NativeOrchestrationBridgeError(
                        "native_execution_failed", rule="lowering_call_limit",
                    )
                reservation = deepcopy(state)
                reservation.pop("program", None)
                reservation.pop("program_sha256", None)
                reservation.pop("last_failure", None)
                reservation.update({
                    "phase": "call_reserved", "calls_used": state["calls_used"] + 1,
                    "completion_confirmed": False,
                })
                state = store.save_lowering_state(
                    step["step_id"], reservation,
                    binding=checkpoint_binding, input_fingerprint=fingerprint,
                )

                def reserve_response_format_retry():
                    nonlocal state
                    if state["calls_used"] >= LOWERING_MAX_CALLS:
                        raise NativeOrchestrationBridgeError(
                            "native_execution_failed", rule="lowering_call_limit",
                        )
                    retry_reservation = deepcopy(state)
                    retry_reservation.pop("program", None)
                    retry_reservation.pop("program_sha256", None)
                    retry_reservation.pop("last_failure", None)
                    retry_reservation.update({
                        "phase": "call_reserved", "calls_used": state["calls_used"] + 1,
                        "completion_confirmed": False,
                    })
                    state = store.save_lowering_state(
                        step["step_id"], retry_reservation,
                        binding=checkpoint_binding, input_fingerprint=fingerprint,
                    )

                try:
                    response = invoke(
                        _prepared_program_prompt(
                            arguments["question"], context_value, relational_spec_schema(),
                            correction=correction,
                        ),
                        stage="tabular_program_lowering",
                        metadata={
                            "json_output": True, "complete_saved_analysis_input": True,
                            "require_complete_generation": True,
                            "before_response_format_retry": reserve_response_format_retry,
                        },
                    )
                    program = json.loads(response)
                    if not isinstance(program, dict):
                        raise TabularRelationalError("relational_spec_invalid", detail={"check": "json_object"})
                    # This path admits both operation sets, so the version follows from the
                    # operations and is stated here, not checked against what was written.
                    program, authored_version = with_operation_version(program)
                    if authored_version != program.get("version"):
                        log_event(
                            "[ORCHESTRATION_NATIVE] Calculation program version set from its operations.",
                            level=logging.DEBUG,
                            extra={
                                **workflow_log_context(
                                    run_id=getattr(context, "run_id", None),
                                    conversation_id=getattr(context, "conversation_id", None),
                                    step_id=step["step_id"],
                                ),
                                "stage": "tabular_program_lowering",
                                "program_version": program.get("version"),
                                "authored_version_valid": authored_version in (
                                    "tabular-relate-v1", "tabular-relate-v2",
                                ),
                            },
                        )
                    program = normalize_relational_spec(program, arguments["document_ids"])
                    check_relational_columns(program, source_headers)
                    state = store.save_lowering_state(
                        step["step_id"], {
                            **state, "phase": "program_saved",
                            "program": deepcopy(program),
                            "program_sha256": hashlib.sha256(canonical_bytes(program)).hexdigest(),
                            "completion_confirmed": True,
                            "token_usage": deepcopy(getattr(context, "prompt_token_usage", {}) or {}),
                        }, binding=checkpoint_binding, input_fingerprint=fingerprint,
                    )
                except Exception as exc:
                    # Read the already-loaded class instead of importing here: an import that
                    # fails inside this handler would replace the authoring fault being handled.
                    # No instance can exist unless that module is loaded.
                    HarnessExecutionError = getattr(
                        sys.modules.get("functions_orchestration_execution"), "HarnessExecutionError", None,
                    ) or _NoHarnessExecutionError

                    if not isinstance(exc, (json.JSONDecodeError, TabularRelationalError, HarnessExecutionError)):
                        raise
                    if isinstance(exc, HarnessExecutionError) and (
                        getattr(exc, "rule", None) != "generation_incomplete"
                    ):
                        raise
                    if isinstance(exc, json.JSONDecodeError):
                        exc = TabularRelationalError(
                            "relational_spec_invalid", detail={"check": "json_parse"},
                        )
                    elif isinstance(exc, HarnessExecutionError):
                        correction = {
                            "category": "generation_incomplete",
                            "check": "complete_generation", "step_index": 0,
                        }
                        failed = deepcopy(state)
                        failed.pop("program", None)
                        failed.pop("program_sha256", None)
                        failed.update({
                            "phase": "failure_saved",
                            "last_failure": correction,
                            "completion_confirmed": False,
                            "token_usage": deepcopy(
                                getattr(context, "prompt_token_usage", {}) or {}
                            ),
                        })
                        state = store.save_lowering_state(
                            step["step_id"], failed,
                            binding=checkpoint_binding, input_fingerprint=fingerprint,
                        )
                        if state["calls_used"] >= LOWERING_MAX_CALLS:
                            raise
                        continue
                    candidate = program if isinstance(locals().get("program"), dict) else None
                    correction = _safe_program_correction(exc) if candidate is not None else None
                    failed = deepcopy(state)
                    if correction is None:
                        failed.pop("program", None)
                        failed.pop("program_sha256", None)
                    else:
                        correction["program"] = deepcopy(candidate)
                        failed["program"] = deepcopy(candidate)
                        failed["program_sha256"] = hashlib.sha256(canonical_bytes(candidate)).hexdigest()
                    failed.update({
                        "phase": "failure_saved",
                        "last_failure": correction or {"category": exc.code},
                        "completion_confirmed": correction is not None,
                        "token_usage": deepcopy(
                            getattr(context, "prompt_token_usage", {}) or {}
                        ),
                    })
                    state = store.save_lowering_state(
                        step["step_id"], failed,
                        binding=checkpoint_binding, input_fingerprint=fingerprint,
                    )
                    if correction is None or state["calls_used"] >= LOWERING_MAX_CALLS:
                        raise
                    continue
            state = store.save_lowering_state(
                step["step_id"], {**state, "phase": "evaluating"},
                binding=checkpoint_binding, input_fingerprint=fingerprint,
            )
            try:
                calculated = calculate_relational_sources(
                    program, datasets, limits=limits, cancel_requested=cancel_requested,
                )
            except (TabularRelationalError, TabularTransformationEvaluationError) as exc:
                correction = _safe_program_correction(exc)
                if correction is not None:
                    correction["program"] = deepcopy(program)
                    log_event(
                        "[ORCHESTRATION_NATIVE] Calculation program returned to its author.",
                        extra={
                            **workflow_log_context(
                                run_id=getattr(context, "run_id", None),
                                conversation_id=getattr(context, "conversation_id", None),
                                step_id=step["step_id"],
                            ),
                            "stage": "tabular_program_lowering",
                            "correction_category": correction["category"],
                            "correction_origin": correction.get("origin") or "validation",
                            "calls_used": state["calls_used"],
                            "calls_limit": LOWERING_MAX_CALLS,
                        },
                    )
                failed = deepcopy(state)
                if correction is None:
                    failed.pop("program", None)
                    failed.pop("program_sha256", None)
                failed.update({
                    "phase": "failure_saved",
                    "last_failure": correction or {"category": exc.code},
                    "completion_confirmed": correction is not None,
                    "token_usage": deepcopy(
                        getattr(context, "prompt_token_usage", {}) or {}
                    ),
                })
                state = store.save_lowering_state(
                    step["step_id"], failed,
                    binding=checkpoint_binding, input_fingerprint=fingerprint,
                )
                if correction is None or state["calls_used"] >= LOWERING_MAX_CALLS:
                    raise
                continue
            break
    service.access.authorize_input_sources(snapshots, require_snapshot=True)
    calculated["coverage"]["source_snapshots"] = deepcopy(context_value["source_snapshots"])
    calculated["coverage"]["preparation_profile_sha256"] = context_value["profile_sha256"]
    coverage = Coverage(len(snapshots), len(snapshots), "sources")
    checks = (
        "complete_authorized_tables", "complete_preparation_context",
        "complete_generation_confirmed", "validated_relational_operations",
        "precise_decimal_values", "declared_match_cardinality", "exact_row_lineage",
    )
    count = len(calculated["records"])
    complete = Completeness("complete", count, count, coverage, "valid", checks, ())
    outputs = [
        NamedOutput(
            "records", "records-v1", calculated["records"], complete,
            tuple(RecordColumn.from_dict(column) for column in calculated["columns"]),
        ),
        NamedOutput("lineage", "records-v1", calculated["lineage"], complete, (
            RecordColumn("result_row", "integer"), RecordColumn("sources", "array"),
        )),
        NamedOutput(
            "coverage", "structured-v1", calculated["coverage"],
            Completeness("complete", 1, 1, coverage, "valid", checks, ()),
        ),
    ]
    token = _guard(context, service, producer)
    task = service.persist_task_result(
        producer=producer, role="reason", status="complete", outputs=outputs, sources=snapshots,
        origin="grounded", source_policy=binding.source_policy, guard_token=token,
        input_fingerprint=fingerprint,
    )
    store.save_lowering_state(
        step["step_id"], {**state, "phase": "retained", "completion_confirmed": True},
        binding=checkpoint_binding, input_fingerprint=fingerprint,
    )
    return _step_result(
        status="completed", summary=f"Calculated and retained {count:,} prepared records.",
        task_result=task,
    )


def _execute_preparation(
    step, context, service, producer, manifest, snapshots, binding, settings, cancel_requested,
):
    """Commit complete, exact analytical context before any model authors a program."""
    from functions_orchestration_merge import build_tabular_merge_sources, tabular_merge_limits
    from functions_tabular_merge import prepare_tabular_source_context

    arguments = validate_native_orchestration_arguments(step["arguments"])
    request = arguments["preparation_request"]
    limits = tabular_merge_limits(settings)
    fingerprint = _input_fingerprint(step, context, binding)
    if len(manifest) > limits.max_sources:
        raise NativeOrchestrationBridgeError("native_relational_limit")
    sources = build_tabular_merge_sources(
        manifest, producer.user_id, byte_reader=getattr(context, "merge_source_reader", None),
    )
    datasets = []
    with orchestration_file_policy(allow_generated_files=False):
        for source, requested in zip(sources, request["datasets"]):
            _check_cancel(cancel_requested)
            datasets.append(prepare_tabular_source_context(
                source, requested, limits=limits, cancel_requested=cancel_requested,
            ))
    service.access.authorize_input_sources(snapshots, require_snapshot=True)
    request_digest = _approved_preparation_request_digest(
        context, request, question=arguments["question"],
    )
    source_snapshots = [
        {**deepcopy(snapshot), "content_sha256": dataset["content_sha256"]}
        for snapshot, dataset in zip(snapshots, datasets)
    ]
    context_value = {
        "version": "tabular-calculation-context-v1",
        "analytical_request_sha256": request_digest,
        "source_snapshots": deepcopy(source_snapshots),
        "datasets": datasets,
        "complete": True, "limitations": [],
    }
    context_value["profile_sha256"] = hashlib.sha256(
        canonical_bytes({
            "datasets": datasets, "source_snapshots": source_snapshots,
            "analytical_request_sha256": request_digest,
        })
    ).hexdigest()
    if len(canonical_bytes(context_value)) > 96 * 1024:
        raise NativeOrchestrationBridgeError("native_relational_limit")
    coverage = {
        "version": "structured-v1",
        "source_snapshots": deepcopy(source_snapshots),
        "analytical_request_sha256": request_digest,
        "profile_sha256": context_value["profile_sha256"],
        "datasets": [
            {
                "alias": item["alias"], "document_id": item["document_id"],
                "headers": deepcopy(item["headers"]), "row_count": item["physical_row_count"],
                "selection": deepcopy(item["selection"]),
                "complete": True,
            }
            for item in datasets
        ],
        "input_rows": sum(item["physical_row_count"] for item in datasets),
        "complete": True,
    }
    result_coverage = Coverage(len(snapshots), len(snapshots), "sources")
    complete = Completeness(
        "complete", 1, 1, result_coverage, "valid",
        ("complete_authorized_tables", "complete_context_columns", "complete_key_profiles"),
        (),
    )
    outputs = [
        NamedOutput("context", "structured-v1", context_value, complete),
        NamedOutput("coverage", "structured-v1", coverage, complete),
    ]
    token = _guard(context, service, producer)
    options = {"input_fingerprint": fingerprint} if fingerprint is not None else {}
    task = service.persist_task_result(
        producer=producer, role="reason", status="complete", outputs=outputs, sources=snapshots,
        origin="grounded", source_policy=binding.source_policy, guard_token=token, **options,
    )
    return _step_result(
        status="completed",
        summary=(
            f"Prepared complete calculation context from {len(snapshots)} files "
            f"and {coverage['input_rows']:,} rows."
        ),
        task_result=task,
    )


def execute_native_orchestration_step(
    step, context, *, settings, user_id, emit=None, cancel_requested=None, binding=None,
):
    """Execute only through an explicitly server-bound native request factory."""
    del emit
    stage = "admission"
    try:
        _check_cancel(cancel_requested)
        service, producer = _runtime(step, context, user_id, binding)
        relational = binding.native_operation == "relate"
        multiple = binding.native_operation in ("prepare", "relate")
        manifest, snapshots = _sources(
            step, context, service, require_current=True, require_replay=True, multiple=multiple,
        )
        input_fingerprint = _input_fingerprint(step, context, binding)
        _guard(context, service, producer)
        if relational:
            stage = "execution"
            if step.get("arguments", {}).get("calculation_mode") == "prepared-v1":
                return _execute_prepared_relational(
                    step, context, service, producer, manifest, snapshots,
                    binding, settings, cancel_requested,
                )
            return _execute_relational(
                step, context, service, producer, manifest, snapshots, binding, settings, cancel_requested,
            )
        if binding.native_operation == "prepare":
            stage = "execution"
            return _execute_preparation(
                step, context, service, producer, manifest, snapshots, binding, settings, cancel_requested,
            )
        with orchestration_file_policy(allow_generated_files=False):
            if binding.model_resolver is None:
                model = {
                    "gpt_model": getattr(context, "gpt_model", None),
                    "model_context": getattr(context, "model_context", None),
                }
            else:
                model = binding.model_resolver(step, context, settings=settings, user_id=user_id)
            if (
                type(model) is not dict or not set(model).issubset({"gpt_model", "model_context"})
                or type(model.get("gpt_model")) is not str or not model["gpt_model"].strip()
                or (model.get("model_context") is not None and type(model["model_context"]) is not dict)
            ):
                raise NativeOrchestrationBridgeError("native_model_unavailable")
            _check_cancel(cancel_requested)
            request = binding.request_builder(
                step, context, settings=settings, user_id=user_id, source_manifest=manifest,
                native_operation=binding.native_operation, task_type=binding.task_type,
                cancel_requested=cancel_requested,
            )
            if (
                type(request) is not NativeOrchestrationRequest or type(request.plan) is not dict
                or type(request.user_question) is not str or not request.user_question.strip()
            ):
                raise NativeOrchestrationBridgeError("native_request_invalid")
            # These services require bootstrap-owned native clients only when invoked.
            from functions_native_tabular_compute import (
                NativeTabularComputeError, _compute_request, build_native_tabular_compute_callback,
            )
            from functions_tabular_orchestration import execute_tabular_plan

            try:
                normalized = _compute_request(request.plan, request.user_question)
            except NativeTabularComputeError as exc:
                raise NativeOrchestrationBridgeError("native_request_invalid") from exc
            if normalized["operation"] != binding.native_operation or normalized["task_type"] != binding.task_type:
                raise NativeOrchestrationBridgeError("native_outputs_invalid")
            _check_cancel(cancel_requested)
            callback = build_native_tabular_compute_callback(
                user_id=producer.user_id, conversation_id=producer.conversation_id,
                producer=producer.to_dict(), source_manifest=manifest,
                gpt_model=model["gpt_model"], model_context=model.get("model_context"),
                settings=settings, cancel_requested=cancel_requested,
            )
            stage = "execution"
            result = execute_tabular_plan(
                request.plan, execution_policy="data_only", durable_execution_callback=callback,
                user_question=request.user_question,
            )
            stage = "retention"
            return _finish(
                result.get("native_compute_result"), context, service, producer,
                snapshots, binding, cancel_requested, input_fingerprint,
            )
    except Exception as exc:
        return _failure(step, exc, stage, context)


def resume_native_orchestration_step(
    step, context, pending_result, *, settings, user_id, emit=None, cancel_requested=None, binding=None,
):
    """Read one original handle once; never plan, select a model, or submit work."""
    del settings, emit
    stage = "resume"
    try:
        _check_cancel(cancel_requested)
        service, producer = _runtime(step, context, user_id, binding)
        _, snapshots = _sources(step, context, service, require_current=binding.source_policy == "current")
        pending = pending_result.get("task_result") if type(pending_result) is dict else None
        if (
            type(pending) is not TaskResult or pending.producer != producer
            or pending.role != "reason" or pending.status != "pending" or pending.outputs
            or pending_result.get("status") != "waiting"
        ):
            raise NativeOrchestrationBridgeError("native_wait_invalid")
        handle = _validate_wait(pending_result.get("wait"), producer)
        input_fingerprint = _input_fingerprint(step, context, binding)
        from functions_native_analysis_results import open_native_tabular_result

        native = open_native_tabular_result(
            user_id=producer.user_id, conversation_id=producer.conversation_id,
            handle=handle, producer=producer.to_dict(), require_current_sources=binding.source_policy == "current",
        )
        _check_cancel(cancel_requested)
        if type(native) is not dict:
            raise NativeOrchestrationBridgeError("native_result_invalid")
        retained = (getattr(context, "task_results", None) or {}).get(producer.step_id)
        if retained is not None and type(retained) is not TaskResult:
            raise NativeOrchestrationBridgeError("native_wait_invalid")
        if native.get("status") == "completed" and input_fingerprint is not None:
            recovered = service.recover_task_result(producer=producer, input_fingerprint=input_fingerprint)
            _check_cancel(cancel_requested)
            if retained is not None and retained.status == "complete" and recovered != retained:
                raise NativeOrchestrationBridgeError("native_wait_invalid")
            if recovered is not None:
                retained = recovered
        if retained is not None and retained.status == "complete":
            expected = {spec.name: spec.kind for spec in binding.output_specs}
            if (
                type(retained) is not TaskResult or retained.producer != producer or retained.role != "reason"
                or native.get("status") != "completed"
                or {item.output_name: item.kind for item in retained.outputs} != expected
            ):
                raise NativeOrchestrationBridgeError("native_wait_invalid")
            for reference in retained.outputs:
                _check_cancel(cancel_requested)
                service.open_result(reference, require_current_sources=binding.source_policy == "current").recheck()
            _check_cancel(cancel_requested)
            return _step_result(status="completed", summary=_retained_summary(retained), task_result=retained)
        if retained is not None and retained.status not in {"pending", "complete"}:
            raise NativeOrchestrationBridgeError("native_wait_invalid")
        stage = "retention"
        with orchestration_file_policy(allow_generated_files=False):
            return _finish(
                native, context, service, producer, snapshots, binding, cancel_requested, input_fingerprint,
            )
    except Exception as exc:
        return _failure(step, exc, stage, context)
