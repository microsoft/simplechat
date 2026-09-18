# functions_workflow_definitions.py
"""Versioned, server-owned workflow data-flow definitions."""

import hashlib
import json
import re
from collections.abc import Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


WORKFLOW_DEFINITION_VERSION = 2
WORKFLOW_BINDABLE_OUTPUTS = frozenset({"authoritative", "text", "records", "json", "documents"})
WORKFLOW_OUTPUT_KINDS = frozenset({"any", "text", "records", "json", "document_results"})
WORKFLOW_INPUT_PROCESSING_MODES = frozenset({"full", "saved_record_report"})
WORKFLOW_PUBLICATION_COMPLETION_POLICIES = ("submitted", "approved", "indexed_ready")
WORKFLOW_FLOW_TASK_FIELDS = frozenset({"inputs", "reference_ids", "output_contract", "approval", "input_processing"})
WORKFLOW_DEFINITION_FIELDS = (
    "name", "description", "task_prompt", "tasks", "runner_type", "chat_capabilities_enabled",
    "trigger_type", "is_enabled", "schedule", "error_handling", "document_action", "analyze",
    "file_sync", "selected_agent", "model_endpoint_id", "model_id", "model_provider",
    "url_access_enabled", "alert_priority", "alert_mode", "alert_rules", "alert_evaluation",
    "definition_version", "reference_inputs", "durable_execution", "flow", "limits",
)
SCHEMA_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties", "items",
    "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum",
    "enum", "title", "description",
})
MAX_SCHEMA_BYTES = 32768
MAX_DEFINITION_REFERENCES = 100
MAX_TASK_BINDINGS = 100
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")


class WorkflowDefinitionError(ValueError):
    """A safe, actionable definition error which can be shown in the editor."""

    def __init__(self, public_message):
        self.public_message = public_message
        super().__init__(public_message)


class WorkflowDefinitionConflict(WorkflowDefinitionError):
    """The editor is stale or cannot preserve the stored definition."""


def normalize_publication_completion_policy(value):
    if not isinstance(value, str) or value not in WORKFLOW_PUBLICATION_COMPLETION_POLICIES:
        raise WorkflowDefinitionError("Publication completion must be submitted, approved, or indexed_ready.")
    return value


def validate_workflow_publication_completion(workflow):
    for task in workflow.get("tasks") or []:
        if not isinstance(task, dict):
            raise WorkflowDefinitionError("A workflow task must be an object.")
        publication = task.get("publication")
        if isinstance(publication, dict) and "completion_policy" in publication:
            normalize_publication_completion_policy(publication["completion_policy"])
            if workflow.get("definition_version") != 3 or workflow.get("durable_execution") is not True:
                raise WorkflowDefinitionError("Publication completion policies require a version-3 durable workflow.")


def workflow_output_kind_matches(actual, expected):
    return expected == "any" or actual == expected or (
        expected == "json" and actual in {"records", "document_results"}
    )


def workflow_definition_revision(workflow):
    """An authored-content revision unaffected by runtime progress updates."""
    document = {field: workflow[field] for field in WORKFLOW_DEFINITION_FIELDS if field in workflow}
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def workflow_definition_for_editor(workflow):
    if not isinstance(workflow, Mapping):
        return workflow
    return {**workflow, "definition_revision": workflow_definition_revision(workflow)}


def _text(value, label, max_length=128):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise WorkflowDefinitionError(f"{label} must be nonempty text of at most {max_length} characters.")
    return value.strip()


def _name(value, label):
    name = _text(value, label, 64)
    if not _NAME.fullmatch(name):
        raise WorkflowDefinitionError(f"{label} must start with a letter and use letters, numbers, underscores or hyphens.")
    return name


def _boolean(value, label):
    if not isinstance(value, bool):
        raise WorkflowDefinitionError(f"{label} must be true or false.")
    return value


def _object(value, allowed_fields, label):
    if not isinstance(value, dict):
        raise WorkflowDefinitionError(f"{label} must be an object.")
    if value.keys() - allowed_fields:
        raise WorkflowDefinitionError(f"{label} contains unsupported fields.")
    return value


def _unique_identifiers(values, label):
    if not isinstance(values, list):
        raise WorkflowDefinitionError(f"{label} must be a list.")
    identifiers = [_text(value, label) for value in values]
    if len(set(identifiers)) != len(identifiers):
        raise WorkflowDefinitionError(f"{label} must not contain duplicates.")
    return identifiers


def normalize_workflow_input_processing(value):
    """Validate an explicit task policy without supplying an authored default."""
    if not isinstance(value, str) or value not in WORKFLOW_INPUT_PROCESSING_MODES:
        raise WorkflowDefinitionError("Task input_processing must be full or saved_record_report.")
    return value


def normalize_workflow_output_schema(schema):
    """A bounded JSON Schema subset without references, code, or regex evaluation."""
    if not isinstance(schema, dict):
        raise WorkflowDefinitionError("Output schema must be a JSON object.")
    try:
        serialized = json.dumps(schema, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise WorkflowDefinitionError("Output schema must contain finite JSON values.") from exc
    if len(serialized.encode("ascii")) > MAX_SCHEMA_BYTES:
        raise WorkflowDefinitionError(f"Output schema must be at most {MAX_SCHEMA_BYTES} bytes.")

    def validate(node, depth=0):
        if depth > 12 or not isinstance(node, (dict, bool)):
            raise WorkflowDefinitionError("Output schema nesting is invalid or exceeds 12 levels.")
        if isinstance(node, bool):
            return
        if node.keys() - SCHEMA_KEYWORDS:
            raise WorkflowDefinitionError(
                "Output schema supports types, properties, required fields, items, bounds and enums; "
                "references, regular expressions and composition keywords are not supported."
            )
        properties = node.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 200:
            raise WorkflowDefinitionError("Output schema properties must be an object with at most 200 fields.")
        for child in properties.values():
            validate(child, depth + 1)
        for field in ("items", "additionalProperties"):
            if field in node:
                validate(node[field], depth + 1)

    validate(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise WorkflowDefinitionError("Output schema is not a valid supported JSON Schema.") from exc
    return json.loads(serialized)


def normalize_workflow_output_contract(value):
    contract = _object(value, {
        "kind", "schema", "expected_count", "identity_field", "require_complete_coverage", "allow_partial",
    }, "Output contract")
    kind = contract.get("kind", "any")
    if not isinstance(kind, str) or kind not in WORKFLOW_OUTPUT_KINDS:
        raise WorkflowDefinitionError("Choose a supported output kind.")
    normalized = {
        "kind": kind,
        "require_complete_coverage": _boolean(contract.get("require_complete_coverage", False), "Complete coverage"),
        "allow_partial": _boolean(contract.get("allow_partial", False), "Partial output policy"),
    }
    if "expected_count" in contract:
        count = contract["expected_count"]
        if type(count) is not int or count < 0 or kind not in {"records", "document_results", "json"}:
            raise WorkflowDefinitionError("Expected count must be a nonnegative integer for a collection output.")
        normalized["expected_count"] = count
    if "identity_field" in contract:
        if kind != "records":
            raise WorkflowDefinitionError("An identity field applies only to a record collection.")
        normalized["identity_field"] = _text(contract["identity_field"], "Identity field")
    if "schema" in contract:
        normalized["schema"] = normalize_workflow_output_schema(contract["schema"])
    return normalized


def normalize_workflow_references(values, *, user_id, group_id=""):
    if not isinstance(values, list) or len(values) > MAX_DEFINITION_REFERENCES:
        raise WorkflowDefinitionError(f"Shared references must be a list of at most {MAX_DEFINITION_REFERENCES} documents.")
    result = []
    seen_ids = set()
    seen_names = set()
    for value in values:
        reference = _object(value, {"id", "name", "document_id", "scope_type", "scope_id"}, "Shared reference")
        reference_id = _text(reference.get("id"), "Reference id")
        name = _name(reference.get("name"), "Reference name")
        document_id = _text(reference.get("document_id"), "Reference document id", 256)
        scope_type = reference.get("scope_type")
        if scope_type not in {"personal", "group", "public"}:
            raise WorkflowDefinitionError("Shared references require a personal, group, or public source scope.")
        if scope_type == "personal":
            scope_id = str(user_id)
            if reference.get("scope_id") not in (None, "", scope_id):
                raise WorkflowDefinitionError("Personal shared references must belong to the workflow owner.")
        else:
            scope_id = _text(reference.get("scope_id"), "Reference scope id")
        if group_id and (scope_type != "group" or scope_id != str(group_id)):
            raise WorkflowDefinitionError("Group workflow references must belong to the workflow's group.")
        if reference_id in seen_ids or name in seen_names:
            raise WorkflowDefinitionError("Shared reference ids and names must be unique.")
        seen_ids.add(reference_id)
        seen_names.add(name)
        result.append({
            "id": reference_id, "name": name, "document_id": document_id,
            "scope_type": scope_type, "scope_id": scope_id,
        })
    return result


def _normalize_bindings(values, earlier_tasks):
    if not isinstance(values, list) or len(values) > MAX_TASK_BINDINGS:
        raise WorkflowDefinitionError(f"Task inputs must be a list of at most {MAX_TASK_BINDINGS} bindings.")
    bindings = []
    names = set()
    for value in values:
        binding = _object(value, {"name", "task_id", "output", "required", "expected_kind"}, "Task input")
        name = _name(binding.get("name"), "Input name")
        task_id = _text(binding.get("task_id"), "Input task id")
        output = binding.get("output", "authoritative")
        expected_kind = binding.get("expected_kind", "any")
        if output not in WORKFLOW_BINDABLE_OUTPUTS or expected_kind not in WORKFLOW_OUTPUT_KINDS:
            raise WorkflowDefinitionError("Task inputs must select a supported final output, not presentation or diagnostics.")
        selector_kind = {"text": "text", "records": "records", "json": "json", "documents": "document_results"}.get(output)
        if selector_kind and not workflow_output_kind_matches(selector_kind, expected_kind):
            raise WorkflowDefinitionError("The expected input kind does not match the selected output representation.")
        if name in names:
            raise WorkflowDefinitionError("Input names must be unique within a task.")
        if task_id not in earlier_tasks:
            raise WorkflowDefinitionError("Task inputs can reference only earlier tasks in the saved order.")
        producer_kind = (earlier_tasks[task_id].get("output_contract") or {}).get("kind", "any")
        if output == "authoritative" and producer_kind != "any" and not workflow_output_kind_matches(producer_kind, expected_kind):
            raise WorkflowDefinitionError("The input kind does not match its producer's declared output kind.")
        if output == "records" and producer_kind not in {"any", "records"}:
            raise WorkflowDefinitionError("A records input requires a producer that can return records.")
        names.add(name)
        bindings.append({
            "name": name, "task_id": task_id, "output": output,
            "required": _boolean(binding.get("required", True), "Required input"),
            "expected_kind": expected_kind,
        })
    return bindings


def normalize_workflow_definition(payload, existing, tasks, *, user_id, group_id=""):
    """Normalize new flow fields after existing task/runner authorization."""
    existing = existing or {}
    version = payload.get("definition_version", 1)
    stored_version = existing.get("definition_version", 1)
    if type(version) is not int or version not in {1, 2, 3}:
        raise WorkflowDefinitionConflict("This workflow definition version is not supported by this editor.")
    if type(stored_version) is not int or stored_version not in {1, 2, 3}:
        raise WorkflowDefinitionConflict("This saved workflow requires a newer editor. Its definition was not changed.")
    if version == 3:
        managed_fields = {
            "id", "definition_revision", "conversation_id", "user_id", "group_id",
            "url_access_authorized", "url_access_authorized_by", "url_access_authorized_at",
            "model_binding_summary", "created_at", "created_by", "modified_at", "modified_by",
            "updated_at", "status", "last_run_started_at", "last_run_at", "last_run_status",
            "last_run_error", "last_run_response_preview", "last_run_trigger_source", "run_count",
            "active_run_id", "active_runtime_version", "last_run_id", "next_run_at",
            "cancellation_requested_at", "cancellation_requested_by", "result_access",
        }
        extras = payload.keys() - set(WORKFLOW_DEFINITION_FIELDS) - managed_fields
        if any(key not in existing or payload[key] != existing[key] for key in extras):
            raise WorkflowDefinitionError("The structured workflow contains unsupported fields.")
    if stored_version >= 2 and version < stored_version:
        raise WorkflowDefinitionConflict("This workflow uses advanced data flow. Open it in V2 to edit without losing its configuration.")
    if version >= 2 and existing:
        if payload.get("definition_revision") != workflow_definition_revision(existing):
            raise WorkflowDefinitionConflict("This workflow changed since it was opened. Reload it before saving.")
        if existing.get("active_run_id"):
            raise WorkflowDefinitionConflict("Wait for the active run to finish or cancel it before editing this workflow.")
    raw_tasks = payload.get("tasks", existing.get("tasks", []))
    validate_workflow_publication_completion({
        **payload, "tasks": raw_tasks,
        "durable_execution": payload.get("durable_execution", existing.get("durable_execution", False)),
    })
    if len(raw_tasks) != len(tasks):
        raise WorkflowDefinitionError("Task data does not match the normalized task list.")
    if version != 3 and any("input_processing" in task for task in raw_tasks):
        raise WorkflowDefinitionError("Task input_processing requires workflow definition version 3.")
    actions = [payload.get("document_action"), *(task.get("document_action") for task in raw_tasks)]
    if version != 3 and any(isinstance(action, dict) and action.get("target_mode") == "current_item" for action in actions):
        raise WorkflowDefinitionError("Current-item Analyze requires workflow definition version 3.")
    has_flow = "reference_inputs" in payload or "flow" in payload or payload.get("durable_execution") is True or any(
        WORKFLOW_FLOW_TASK_FIELDS.intersection(task) for task in raw_tasks
    )
    if version == 1:
        if has_flow:
            raise WorkflowDefinitionError("Advanced inputs and output contracts require workflow definition version 2.")
        return {"definition_version": 1, "tasks": tasks}

    references = normalize_workflow_references(
        payload.get("reference_inputs", existing.get("reference_inputs", [])), user_id=user_id, group_id=group_id,
    )
    reference_ids = {reference["id"] for reference in references}
    durable = _boolean(payload.get("durable_execution", existing.get("durable_execution", False)), "Durable execution")
    normalized_tasks = []
    earlier = {}
    for task, raw in zip(tasks, raw_tasks):
        prepared = dict(task)
        if "input_processing" in raw:
            prepared["input_processing"] = normalize_workflow_input_processing(raw["input_processing"])
        else:
            prepared.pop("input_processing", None)
        if "output_contract" in raw and raw["output_contract"] is not None:
            prepared["output_contract"] = normalize_workflow_output_contract(raw["output_contract"])
        if version == 3:
            # The structured compiler owns node bindings; legacy predecessor rules do not apply.
            prepared["inputs"] = raw.get("inputs", [])
        elif "inputs" in raw and raw["inputs"] is not None:
            prepared["inputs"] = _normalize_bindings(raw["inputs"], earlier)
        if "reference_ids" in raw and raw["reference_ids"] is not None:
            selected_ids = _unique_identifiers(raw["reference_ids"], "Task reference ids")
            if set(selected_ids) - reference_ids:
                raise WorkflowDefinitionError("A task references a shared document which is not in this workflow.")
            prepared["reference_ids"] = selected_ids
        if raw.get("approval") is not None:
            approval = _object(raw["approval"], {"required", "message"}, "Task approval")
            required = _boolean(approval.get("required", False), "Task approval requirement")
            if required and not durable:
                raise WorkflowDefinitionError("Task approval requires durable execution.")
            message = approval.get("message", "")
            if not isinstance(message, str) or len(message) > 1000:
                raise WorkflowDefinitionError("Task approval message must be text of at most 1000 characters.")
            prepared["approval"] = {"required": required, "message": message.strip()}
        normalized_tasks.append(prepared)
        earlier[prepared["id"]] = prepared
    result = {
        "definition_version": version,
        "reference_inputs": references,
        "durable_execution": durable,
        "tasks": normalized_tasks,
    }
    if version == 3:
        # The compiler shares definition helpers, so import at the normalization boundary.
        from functions_workflow_flow import compile_workflow_flow

        compiled = compile_workflow_flow({**payload, **result, "user_id": str(user_id), "group_id": str(group_id or "")})
        result.update({key: compiled[key] for key in ("flow", "tasks", "limits")})
    elif any(key in payload for key in ("flow", "limits", "max_executions", "deadline_seconds")):
        raise WorkflowDefinitionError("Structured flow and run limits require definition version 3.")
    return result
