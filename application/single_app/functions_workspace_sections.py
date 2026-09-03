# functions_workspace_sections.py

"""Decide which sections of the personal workspace a given user may see.

The personal workspace is assembled from eight independent capabilities, and whether any
one of them is available depends on three different kinds of check:

- plain application settings, such as ``allow_user_agents``
- per-user role checks, such as file sync and workflows, which read app roles
- governance policy, which can deny an individual user a capability the tenant enabled

Those checks were previously spread between ``route_frontend_workspace`` and the Jinja
conditions in ``workspace.html``. The V2 interface cannot read either, so rather than
restate the rules a third time they are collected here and both interfaces call this. A
capability added or retired in one place then reaches both surfaces at once, which is the
same reasoning that keeps the chat catalog builders shared in ``route_backend_v2``.

Each section reports *why* it is unavailable, not merely that it is. The V2 overview shows
disabled sections with their reason, because a section that silently disappears is the main
reason people cannot tell whether a capability is missing, broken, or simply not switched on
for them.
"""

import logging

from functions_appinsights import log_event
from functions_file_sync import is_file_sync_enabled_for_user
from functions_governance import (
    is_action_scope_access_allowed,
    is_governance_access_allowed,
)
from functions_settings import is_user_workflows_enabled_for_user

# Order matters: it is the order the sections are presented in, within their groups.
WORKSPACE_SECTION_IDS = (
    "documents",
    "sync",
    "prompts",
    "agents",
    "actions",
    "workflows",
    "identities",
    "endpoints",
)

# Grouping is reported with the availability so the two interfaces agree on where a
# section belongs. "knowledge" is what the assistant can draw on, "automation" is what it
# can do, and "connections" is the shared plumbing the other two reuse.
WORKSPACE_SECTION_GROUPS = {
    "documents": "knowledge",
    "sync": "knowledge",
    "prompts": "knowledge",
    "agents": "automation",
    "actions": "automation",
    "workflows": "automation",
    "identities": "connections",
    "endpoints": "connections",
}

_DISABLED_BY_ADMIN = "Your administrator has not enabled this for your account."
_DENIED_BY_GOVERNANCE = "Your administrator has restricted your access to this capability."


def _governance_allows(feature_key, user_id, *, scope=None):
    """Report whether governance permits a capability, without letting an error hide it.

    Governance failures are treated as permissive here on purpose. This function only
    decides whether to *show* a section; every underlying route re-checks governance and
    answers 403 on its own. Failing closed would therefore hide a section the user is
    entitled to without protecting anything, whereas failing open shows a section whose
    endpoints still refuse the request.
    """
    try:
        if scope is not None:
            return bool(is_action_scope_access_allowed(feature_key, user_id, scope))
        return bool(is_governance_access_allowed(feature_key, user_id))
    except Exception as exc:
        log_event(
            f"[WORKSPACE_SECTIONS] Governance check failed for {feature_key}: {exc}",
            extra={"user_id": user_id, "feature_key": feature_key},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return True


def _section(enabled, reason=None):
    return {"enabled": bool(enabled), "reason": None if enabled else reason}


def build_workspace_section_availability(
    settings,
    user_id,
    *,
    user_info=None,
    user_roles=None,
    file_sync_enabled=None,
):
    """Describe every personal workspace section for one user.

    ``file_sync_enabled`` may be supplied by a caller that has already computed it, since
    the check reads app roles and there is no reason to repeat it.

    Returns a dict carrying the section map plus the two intermediate values callers need
    in their own right: ``file_sync_enabled`` and the resolved ``governance`` flags.
    """
    source_settings = settings or {}
    resolved_user_id = str(user_id or "")

    if file_sync_enabled is None:
        file_sync_enabled = False
        if resolved_user_id:
            try:
                file_sync_enabled = bool(
                    is_file_sync_enabled_for_user(
                        source_settings,
                        resolved_user_id,
                        (user_info or {}).get("email"),
                        user_info=user_info,
                    )
                )
            except Exception as exc:
                log_event(
                    f"[WORKSPACE_SECTIONS] File sync availability check failed: {exc}",
                    extra={"user_id": resolved_user_id},
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )
    file_sync_enabled = bool(file_sync_enabled)

    governance = {
        "user_agents": _governance_allows("governance_user_agents", resolved_user_id),
        "user_actions": _governance_allows(
            "governance_user_actions", resolved_user_id, scope="personal"
        ),
        "user_endpoints": _governance_allows("governance_user_endpoints", resolved_user_id),
        "global_endpoints": _governance_allows("governance_global_endpoints", resolved_user_id),
    }

    semantic_kernel_enabled = bool(source_settings.get("enable_semantic_kernel", False))
    # Personal agents and actions additionally require the per-user Semantic Kernel switch;
    # without it the tenant runs a shared kernel and personal definitions have nowhere to load.
    personal_kernel = bool(source_settings.get("per_user_semantic_kernel", False)) and (
        semantic_kernel_enabled
    )
    allow_agents = bool(source_settings.get("allow_user_agents", False))
    allow_plugins = bool(source_settings.get("allow_user_plugins", False))
    allow_endpoints = bool(source_settings.get("allow_user_custom_endpoints", False)) and bool(
        source_settings.get("enable_multi_model_endpoints", False)
    )

    try:
        workflows_enabled = bool(
            is_user_workflows_enabled_for_user(source_settings, user_roles=user_roles)
        )
    except Exception as exc:
        log_event(
            f"[WORKSPACE_SECTIONS] Workflow availability check failed: {exc}",
            extra={"user_id": resolved_user_id},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        workflows_enabled = False

    agents_enabled = personal_kernel and allow_agents
    actions_enabled = agents_enabled and allow_plugins

    sections = {
        # Documents and prompts have no capability of their own: reaching the workspace at
        # all already required enable_user_workspace.
        "documents": _section(True),
        "prompts": _section(True),
        "sync": _section(
            file_sync_enabled,
            "File sync is not enabled for your account, so external file sources cannot "
            "be configured here.",
        ),
        # Identities serve file sync and actions, so either one being available is enough
        # to justify managing stored credentials.
        "identities": _section(
            file_sync_enabled or semantic_kernel_enabled,
            "Identities appear once file sync or agents are enabled, since they exist to "
            "supply credentials to those.",
        ),
        "agents": _section(
            agents_enabled and governance["user_agents"],
            _DENIED_BY_GOVERNANCE
            if agents_enabled and not governance["user_agents"]
            else "Personal agents are not enabled for your account.",
        ),
        "actions": _section(
            actions_enabled and governance["user_actions"],
            _DENIED_BY_GOVERNANCE
            if actions_enabled and not governance["user_actions"]
            else "Personal actions are not enabled for your account.",
        ),
        "workflows": _section(
            workflows_enabled,
            "Personal workflows are not enabled for your account.",
        ),
        "endpoints": _section(
            allow_endpoints and governance["user_endpoints"],
            _DENIED_BY_GOVERNANCE
            if allow_endpoints and not governance["user_endpoints"]
            else "Personal model endpoints are not enabled for your account.",
        ),
    }

    for section_id, section in sections.items():
        section["group"] = WORKSPACE_SECTION_GROUPS[section_id]

    return {
        "enabled": bool(source_settings.get("enable_user_workspace", False)),
        "file_sync_enabled": file_sync_enabled,
        "governance": governance,
        "sections": sections,
    }


def build_workspace_governance(settings, user_id, *, user_info=None, user_roles=None):
    """Return only the governance flags, in the shape the classic workspace template uses."""
    availability = build_workspace_section_availability(
        settings,
        user_id,
        user_info=user_info,
        user_roles=user_roles,
    )
    return availability["governance"]


__all__ = [
    "WORKSPACE_SECTION_GROUPS",
    "WORKSPACE_SECTION_IDS",
    "build_workspace_governance",
    "build_workspace_section_availability",
]
