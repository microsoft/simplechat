# functions_workflow_configuration.py
"""Bootstrap-free authored workflow execution and result-delivery contracts."""

from copy import deepcopy
from uuid import UUID


WORKFLOW_CONFIGURATION_VERSION = 1
WORKFLOW_CHAT_EXECUTION_MODES = ("orchestration", "selected", "off")
# Execution-only registry literals keep validation below application bootstrap.
# Workflow-control capabilities are not ordinary workflow task tools.
WORKFLOW_CAPABILITY_IDS = (
    "document_search", "document_analyze", "document_compare", "tabular_analyze",
    "tabular_inspect", "tabular_merge", "document_merge", "document_inspect",
    "document_create_from_reference", "document_refresh", "web_search", "url_fetch",
    "deep_research", "agent_invoke", "action_invoke", "compose", "generate_image",
    "render_file",
)
WORKFLOW_VISUAL_REQUIREMENTS = ("chart", "diagram", "image_proposal")
WORKFLOW_RESULTS_DELIVERY_MODES = ("history", "conversation", "task")
WORKFLOW_CONFIGURATION_FIELDS = ("chat_execution", "results_delivery")


class WorkflowConfigurationError(ValueError):
    """A data-free configuration validation error safe to show in an editor."""

    code = "invalid_workflow_configuration"

    def __init__(self, public_message):
        self.public_message = public_message
        super().__init__(public_message)


def _object(value, fields, label):
    if type(value) is not dict or value.keys() - set(fields):
        raise WorkflowConfigurationError(f"{label} must be an object with supported fields.")
    if type(value.get("version")) is not int or value["version"] != WORKFLOW_CONFIGURATION_VERSION:
        raise WorkflowConfigurationError(f"{label} requires version 1.")
    return value


def _selections(value, allowed, label):
    if type(value) is not list or len(value) > len(allowed):
        raise WorkflowConfigurationError(f"{label} must be a list of supported selections.")
    if any(type(item) is not str or item not in allowed for item in value):
        raise WorkflowConfigurationError(f"{label} contains an unsupported selection.")
    return list(dict.fromkeys(value))


def normalize_chat_execution(value):
    """Validate one explicit workflow default or task override; omission means inherit."""
    value = _object(
        value, ("version", "mode", "required_capabilities", "visual_requirements"), "Chat execution",
    )
    mode = value.get("mode")
    if type(mode) is not str or mode not in WORKFLOW_CHAT_EXECUTION_MODES:
        raise WorkflowConfigurationError("Chat execution mode must be orchestration, selected, or off.")
    capabilities = _selections(value.get("required_capabilities", []), WORKFLOW_CAPABILITY_IDS, "Required capabilities")
    visuals = _selections(value.get("visual_requirements", []), WORKFLOW_VISUAL_REQUIREMENTS, "Visual requirements")
    if mode != "selected" and (capabilities or visuals):
        raise WorkflowConfigurationError("Only selected mode accepts capability or visual requirements.")
    if mode == "selected" and not (capabilities or visuals):
        raise WorkflowConfigurationError("Selected mode requires at least one capability or visual requirement.")
    return {"version": 1, "mode": mode, "required_capabilities": capabilities, "visual_requirements": visuals}


def resolve_workflow_chat_execution(workflow, task=None):
    """Resolve a replacing task override, or return None for unchanged legacy dispatch."""
    if task is not None and "chat_execution" in task:
        return normalize_chat_execution(task["chat_execution"])
    if "chat_execution" in workflow:
        return normalize_chat_execution(workflow["chat_execution"])
    return None


def normalize_results_delivery(value, *, workflow_scope="personal"):
    """Validate a destination within its workflow scope, never a caller routing id."""
    value = _object(
        value, ("version", "mode", "conversation_type", "recipient_ids", "all_group_members"), "Results delivery",
    )
    if workflow_scope not in ("personal", "group"):
        raise WorkflowConfigurationError("Results delivery requires a personal or group workflow scope.")
    mode = value.get("mode")
    if type(mode) is not str or mode not in WORKFLOW_RESULTS_DELIVERY_MODES:
        raise WorkflowConfigurationError("Results delivery mode must be history, conversation, or task.")
    allowed_types = ("group", "group_shared") if workflow_scope == "group" else ("personal", "shared")
    conversation_type = value.get("conversation_type", allowed_types[0])
    if type(conversation_type) is not str or conversation_type not in allowed_types:
        raise WorkflowConfigurationError("Results conversations must stay in the workflow's own scope.")
    raw_recipients = value.get("recipient_ids", [])
    if type(raw_recipients) is not list or len(raw_recipients) > 100:
        raise WorkflowConfigurationError("Results recipients must be a list of at most 100 canonical user ids.")
    recipients = []
    for recipient in raw_recipients:
        try:
            if type(recipient) is not str:
                raise ValueError
            normalized = str(UUID(recipient))
            if recipient.lower() != normalized:
                raise ValueError
        except (ValueError, AttributeError) as exc:
            raise WorkflowConfigurationError("Results recipients must be canonical user ids, not names or email addresses.") from exc
        if normalized not in recipients:
            recipients.append(normalized)
    all_members = value.get("all_group_members", False)
    if type(all_members) is not bool:
        raise WorkflowConfigurationError("All group members must be a boolean.")
    shared = conversation_type in ("shared", "group_shared")
    if all_members and (conversation_type != "group_shared" or mode != "conversation"):
        raise WorkflowConfigurationError("All group members is supported only for shared group results.")
    if (recipients or all_members) and (mode != "conversation" or not shared):
        raise WorkflowConfigurationError("Only shared results conversations accept recipients.")
    if all_members and recipients:
        raise WorkflowConfigurationError("Choose named recipients or all current group members, not both.")
    if mode == "conversation" and shared and not (recipients or all_members):
        raise WorkflowConfigurationError("Shared results require named recipients or all current group members.")
    return {
        "version": 1, "mode": mode, "conversation_type": conversation_type,
        "recipient_ids": recipients, "all_group_members": all_members,
    }


def new_workflow_configuration(*, settings=None, workflow_scope="personal"):
    """Defaults for ordinary new drafts, not saved legacy records or chat/replay producers."""
    result = {
        "chat_capabilities_enabled": True,
        "results_delivery": normalize_results_delivery(
            {"version": 1, "mode": "conversation"}, workflow_scope=workflow_scope,
        ),
    }
    if (settings or {}).get("enable_chat_orchestration") is True:
        result["chat_execution"] = normalize_chat_execution({"version": 1, "mode": "orchestration"})
    return result


def workflow_configuration_for_save(payload, existing=None, *, settings=None, workflow_scope="personal", new_defaults=True):
    """Preserve omission on legacy saves; install defaults only on ordinary new records."""
    defaults = new_workflow_configuration(settings=settings, workflow_scope=workflow_scope) if existing is None and new_defaults else {}
    result = {}
    for field in WORKFLOW_CONFIGURATION_FIELDS:
        if field in payload:
            value = payload[field]
        elif existing is not None and field in existing:
            value = existing[field]
        elif field in defaults:
            value = defaults[field]
        else:
            continue
        result[field] = (
            normalize_chat_execution(value) if field == "chat_execution"
            else normalize_results_delivery(value, workflow_scope=workflow_scope)
        )
    return deepcopy(result)
