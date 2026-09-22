# functions_orchestration_native_results.py
"""Native computation to retained orchestration results, without publication.

Version: 0.261.127

The owner binds the native mode; the default production builder validates
explicit query/schema/transformation arguments. Runtime/schema/native execution
imports are deferred so metadata discovery remains safe before bootstrap.
"""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
import logging
import os
import re

from jsonschema import Draft202012Validator

from content_screening.contracts import ScreeningError
from functions_analysis_access import analysis_source_snapshot
from functions_appinsights import log_event
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
_MESSAGES = {
    "native_binding_required": "The native computation bridge is not configured.",
    "native_runtime_invalid": "The native computation has no valid owning runtime.",
    "native_selection_unsupported": "Native computation requires one authorized replayable tabular source. No work was submitted.",
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
    "native_retention_failed": "The complete native output could not be retained. No preview was substituted.",
    "native_cancelled": "Native computation was canceled.",
}


class NativeOrchestrationBridgeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(_MESSAGES[code])


@dataclass(frozen=True)
class NativeOrchestrationRequest:
    """A server-built native plan and its full original computation question."""

    plan: dict
    user_question: str


def _task_type(native_operation, task_type):
    if native_operation not in ("query", "transform", "analysis"):
        raise NativeOrchestrationBridgeError("native_request_invalid")
    selected = task_type if task_type is not None else (
        "hierarchical_analysis" if native_operation == "analysis" else "structured_export"
    )
    allowed = {
        "query": ("structured_export",),
        "transform": ("structured_export", "combined"),
        "analysis": ("hierarchical_analysis",),
    }
    if selected not in allowed[native_operation]:
        raise NativeOrchestrationBridgeError("native_request_invalid")
    return selected


def native_orchestration_output_specs(native_operation, *, task_type=None):
    """Exact required OutputSpecs; analysis-only never advertises records."""
    selected = _task_type(native_operation, task_type)
    outputs = []
    if selected in ("structured_export", "combined"):
        outputs.append(OutputSpec("records", "records-v1"))
    if selected in ("hierarchical_analysis", "combined"):
        outputs.append(OutputSpec("analysis", "structured-v1"))
    outputs.append(OutputSpec("coverage", "structured-v1"))
    return tuple(outputs)


def native_orchestration_arguments_schema():
    """The production v2 argument shape; expression semantics use native validators."""
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
            "expression": {},
            "allowed_values": {"type": "array", "maxItems": 200},
        },
    }
    return {
        "type": "object", "required": ["question", "native_operation", "document_ids"],
        "additionalProperties": False,
        "properties": {
            "question": {"type": "string", "minLength": 1, "maxLength": 24000, "pattern": r"\S"},
            "document_ids": {
                "type": "array", "minItems": 1, "maxItems": 1, "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 256, "pattern": r"^\S+$"},
            },
            "native_operation": {"enum": ["query", "transform", "analysis"]},
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


def validate_native_orchestration_arguments(arguments):
    """Validate an explicit plan without providers, source reads, or query execution."""
    # Native grammar imports are pure and deferred for registry metadata discovery.
    from functions_tabular_csv_query import validate_tabular_csv_query_expression
    from functions_tabular_transformations import normalize_tabular_transformation_spec

    if type(arguments) is not dict or next(
        Draft202012Validator(native_orchestration_arguments_schema()).iter_errors(arguments), None,
    ) is not None:
        raise NativeOrchestrationBridgeError("native_arguments_invalid")
    try:
        if len(canonical_bytes(arguments)) > 65536:
            raise NativeOrchestrationBridgeError("native_arguments_invalid")
        normalized = deepcopy(arguments)
        normalized["task_type"] = _task_type(normalized["native_operation"], normalized.get("task_type"))
        normalize_tabular_transformation_spec(
            normalized.get("transformation_spec"), public_output_schema=normalized.get("columns"),
        )
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


def _failure(step, exc, stage):
    from functions_orchestration_schema import build_failure

    raise_native_orchestration_infrastructure_failure(exc)
    if isinstance(exc, NativeOrchestrationBridgeError):
        code = exc.code
    elif isinstance(exc, (PermissionError, ScreeningError)):
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
        else "result_invalid"
    )
    log_event(
        "[ORCHESTRATION_ADAPTERS] Native result bridge did not complete.",
        extra={"step_id": (step or {}).get("step_id") if isinstance(step, dict) else None,
               "native_code": code, "stage": stage, "error_type": type(exc).__name__},
        level=logging.WARNING,
    )
    result = _step_result(
        status="cancelled" if code == "native_cancelled" else "failed",
        summary=_MESSAGES[code], error=_MESSAGES[code], failure=build_failure(failure_code),
    )
    result["failure"].update({"native_code": code, "retryable": False})
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
    if step.get("inputs"):
        raise NativeOrchestrationBridgeError("native_inputs_unsupported")
    if binding.request_builder is build_native_orchestration_request:
        arguments = validate_native_orchestration_arguments(step.get("arguments"))
        if arguments["native_operation"] != binding.native_operation or arguments["task_type"] != binding.task_type:
            raise NativeOrchestrationBridgeError("native_outputs_invalid")
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


def _sources(step, context, service, *, require_current, require_replay=False):
    manifest = getattr(context, "source_manifest", None)
    if (
        type(manifest) is not list or len(manifest) != 1 or type(manifest[0]) is not dict
        or manifest[0].get("source_kind") != "tabular"
        or manifest[0].get("authorization_status") != "authorized"
    ):
        raise NativeOrchestrationBridgeError("native_selection_unsupported")
    arguments = step.get("arguments", {})
    if type(arguments) is not dict:
        raise NativeOrchestrationBridgeError("native_runtime_invalid")
    selected = arguments.get("document_ids", [])
    if (
        type(selected) is not list or len(selected) > 1
        or (selected and (type(selected[0]) is not str or selected[0] != manifest[0].get("document_id")))
        or arguments.get("left_document_id") or arguments.get("right_document_ids")
    ):
        raise NativeOrchestrationBridgeError("native_selection_unsupported")
    if require_replay:
        source = manifest[0]
        locator = source.get("storage_locator")
        if (
            type(source.get("file_name")) is not str
            or os.path.splitext(source["file_name"])[1].lower() not in (".csv", ".xlsx", ".xls", ".xlsm")
            or type(locator) is not dict
            or any(type(locator.get(key)) is not str or not locator[key] for key in ("container", "blob_path"))
        ):
            raise NativeOrchestrationBridgeError("native_selection_unsupported")
    snapshots = analysis_source_snapshot(manifest)
    service.access.authorize_sources(snapshots, require_snapshot=require_current)
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
        raise NativeOrchestrationBridgeError("native_execution_failed")
    if status != "completed":
        raise NativeOrchestrationBridgeError("native_result_invalid")
    return _retain(native, context, service, producer, snapshots, binding, cancel_requested, input_fingerprint)


def execute_native_orchestration_step(
    step, context, *, settings, user_id, emit=None, cancel_requested=None, binding=None,
):
    """Execute only through an explicitly server-bound native request factory."""
    del emit
    stage = "admission"
    try:
        _check_cancel(cancel_requested)
        service, producer = _runtime(step, context, user_id, binding)
        manifest, snapshots = _sources(step, context, service, require_current=True, require_replay=True)
        input_fingerprint = _input_fingerprint(step, context, binding)
        _guard(context, service, producer)
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
        return _failure(step, exc, stage)


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
        return _failure(step, exc, stage)
