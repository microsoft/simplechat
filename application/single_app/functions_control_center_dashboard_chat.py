# functions_control_center_dashboard_chat.py
"""Decide whether "Chat with this dashboard" can run, and say what is missing when it cannot.

The dashboard's chat opens an orchestrated conversation that answers through a Control Center
action, so it depends on three administrator settings and on a Control Center action that an
administrator creates. Each requirement is reported on its own, with what to do about it, so a
dashboard viewer sees exactly which part is missing instead of a chat that silently cannot
answer. Settings, roles and storage results are passed in, so this module needs no application
bootstrap and its answers can be tested directly.
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping


# Admin Settings sections the remedies link to, as V2 /admin/settings/<section> paths.
DASHBOARD_CHAT_SETTINGS_LINKS = {
    "agents": "/admin/settings/agents-config",
    "orchestration": "/admin/settings/chat-orchestration-section",
    "action_access": "/admin/settings/chat-orchestration-capabilities-section",
    "governance": "/admin/settings/governance-feature-toggles-section",
    "actions": "/admin/actions",
    "new_action": "/admin/actions/new?type=control_center",
}
DASHBOARD_CHAT_ROLES = frozenset({"User", "Admin"})


def _action_name(action: Mapping[str, Any]) -> str:
    for field in ("display_name", "displayName", "name"):
        value = action.get(field)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:200]
    return "Control Center"


def _requirement(requirement_id, label, met, *, detail="", admin_remedy="", reader_remedy="", link=None, is_admin=False):
    return {
        "id": requirement_id,
        "label": label,
        "met": bool(met),
        "detail": "" if met else detail,
        "remedy": "" if met else (admin_remedy if is_admin else reader_remedy),
        "settings_link": link if (is_admin and not met and link) else None,
    }


def build_dashboard_chat_readiness(
    *,
    settings: Mapping[str, Any],
    user_roles: Iterable[str],
    is_admin: bool,
    stored_actions: Iterable[Mapping[str, Any]],
    available_actions: Iterable[Mapping[str, Any]],
    governance_allows: Callable[[Mapping[str, Any]], bool],
    action_invoke_allowlisted: bool,
) -> Dict[str, Any]:
    """Return each requirement for dashboard chat, whether it is met, and how to meet it.

    ``stored_actions`` are the global Control Center action records; ``available_actions`` are
    the Control Center actions the action catalog offers this caller, which already applies
    scope, enablement, governance and Control Center access. Remedies name the Admin Settings
    location; links are included only for administrators, who can open those pages.
    """
    settings = settings or {}
    roles = {str(role) for role in (user_roles or [])}
    stored = [action for action in (stored_actions or []) if isinstance(action, Mapping)]
    available = [action for action in (available_actions or []) if isinstance(action, Mapping)]
    requirements: List[Dict[str, Any]] = []

    agents_on = bool(settings.get("enable_semantic_kernel"))
    requirements.append(_requirement(
        "agents",
        "Agents and actions are turned on",
        agents_on,
        detail="Dashboard chat answers through a Control Center action, and actions run on the agent runtime.",
        admin_remedy="Turn on Enable Agents in Admin Settings › Agents & Actions.",
        reader_remedy="Ask a SimpleChat administrator to turn on Enable Agents in Admin Settings › Agents & Actions.",
        link=DASHBOARD_CHAT_SETTINGS_LINKS["agents"],
        is_admin=is_admin,
    ))

    orchestration_on = bool(settings.get("enable_chat_orchestration"))
    requirements.append(_requirement(
        "orchestration",
        "Chat Orchestration is turned on",
        orchestration_on,
        detail="Chat Orchestration plans the questions and decides when to use the Control Center action.",
        admin_remedy="Turn on Enable Chat Orchestration in Admin Settings › Orchestration.",
        reader_remedy="Ask a SimpleChat administrator to turn on Enable Chat Orchestration in Admin Settings › Orchestration.",
        link=DASHBOARD_CHAT_SETTINGS_LINKS["orchestration"],
        is_admin=is_admin,
    ))

    action_access_switch = bool(settings.get("enable_chat_orchestration_actions"))
    action_access_on = action_access_switch and bool(action_invoke_allowlisted)
    if not action_access_switch:
        action_detail = "Enable Action Access is off, so orchestration cannot use any action."
        admin_remedy = "Turn on Enable Action Access in Admin Settings › Orchestration › Capabilities."
        reader_remedy = (
            "Ask a SimpleChat administrator to turn on Enable Action Access in "
            "Admin Settings › Orchestration › Capabilities."
        )
    else:
        action_detail = "The orchestration capability list leaves out Use an action."
        admin_remedy = "Add Use an action to the capability list in Admin Settings › Orchestration › Capabilities."
        reader_remedy = (
            "Ask a SimpleChat administrator to add Use an action to the capability list in "
            "Admin Settings › Orchestration › Capabilities."
        )
    requirements.append(_requirement(
        "action_access",
        "Orchestration can use actions",
        action_access_on,
        detail=action_detail,
        admin_remedy=admin_remedy,
        reader_remedy=reader_remedy,
        link=DASHBOARD_CHAT_SETTINGS_LINKS["action_access"],
        is_admin=is_admin,
    ))

    action_ready = bool(available)
    enabled_actions = [action for action in stored if action.get("is_enabled", True) is True]
    if action_ready:
        action_detail, admin_remedy, reader_remedy, link = "", "", "", None
    elif not stored:
        action_detail = "No Control Center action exists yet."
        admin_remedy = (
            "Create one in Admin Settings › Agents & Actions › Global Actions: choose New action, then Control Center. "
            "It needs no connection settings."
        )
        reader_remedy = "Ask a SimpleChat administrator to create a Control Center action in Admin Settings › Agents & Actions › Global Actions."
        link = DASHBOARD_CHAT_SETTINGS_LINKS["new_action"]
    elif not enabled_actions:
        action_detail = "The Control Center action is turned off."
        admin_remedy = "Turn the Control Center action on in Admin Settings › Agents & Actions › Global Actions."
        reader_remedy = "Ask a SimpleChat administrator to turn on the Control Center action in Admin Settings › Agents & Actions › Global Actions."
        link = DASHBOARD_CHAT_SETTINGS_LINKS["actions"]
    elif not agents_on:
        action_detail = "A Control Center action exists, and becomes available once agents and actions are on."
        admin_remedy = "Turn on Enable Agents in Admin Settings › Agents & Actions."
        reader_remedy = "Ask a SimpleChat administrator to turn on Enable Agents in Admin Settings › Agents & Actions."
        link = DASHBOARD_CHAT_SETTINGS_LINKS["agents"]
    elif settings.get("per_user_semantic_kernel") and not settings.get("merge_global_semantic_kernel_with_workspace"):
        action_detail = "Workspace Mode is on, which hides global actions such as the Control Center action."
        admin_remedy = "Turn on Add Global Agents and Actions to Workspaces in Admin Settings › Agents & Actions."
        reader_remedy = (
            "Ask a SimpleChat administrator to turn on Add Global Agents and Actions to Workspaces in "
            "Admin Settings › Agents & Actions."
        )
        link = DASHBOARD_CHAT_SETTINGS_LINKS["agents"]
    elif not any(governance_allows(action) for action in enabled_actions):
        action_detail = "Governance does not let you use the Control Center action."
        admin_remedy = "Allow it for you under Govern Global Actions in Admin Settings › Governance."
        reader_remedy = "Ask a SimpleChat administrator to allow the Control Center action for you in Admin Settings › Governance."
        link = DASHBOARD_CHAT_SETTINGS_LINKS["governance"]
    else:
        action_detail = "The Control Center action is not available to your account right now."
        admin_remedy = "Check that the Control Center action is a global action and that your app roles include Control Center access."
        reader_remedy = "Ask a SimpleChat administrator to check the Control Center action and your Control Center access."
        link = DASHBOARD_CHAT_SETTINGS_LINKS["actions"]
    requirements.append(_requirement(
        "control_center_action",
        "A Control Center action is set up for you",
        action_ready,
        detail=action_detail,
        admin_remedy=admin_remedy,
        reader_remedy=reader_remedy,
        link=link,
        is_admin=is_admin,
    ))

    can_chat = bool(roles & DASHBOARD_CHAT_ROLES)
    if not can_chat:
        requirements.append(_requirement(
            "chat_access",
            "Your account can use chat",
            False,
            detail="Chat is available to accounts with the User or Admin app role.",
            admin_remedy="Assign your account the User app role in Microsoft Entra ID.",
            reader_remedy="Ask your identity administrator to assign your account the User app role.",
            is_admin=is_admin,
        ))

    action = None
    if available:
        chosen = sorted(available, key=lambda item: (_action_name(item).lower(), str(item.get("action_ref") or "")))[0]
        action = {"name": _action_name(chosen)}
    return {
        "ready": all(requirement["met"] for requirement in requirements),
        "action": action,
        "requirements": requirements,
    }


def control_center_action_records(records: Iterable[Any], action_type: str) -> List[Dict[str, Any]]:
    """Keep the stored global actions of one type, reduced to the fields readiness reads."""
    kept = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        record_type = record.get("type")
        if not isinstance(record_type, str) or record_type.strip().lower() != action_type:
            continue
        kept.append({
            "id": record.get("id"),
            "name": record.get("name"),
            "display_name": record.get("display_name") or record.get("displayName"),
            "type": record_type,
            "is_enabled": record.get("is_enabled", True),
        })
    return kept
