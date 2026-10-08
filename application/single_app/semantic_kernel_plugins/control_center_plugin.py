# control_center_plugin.py
"""Read-only Control Center insights for chat, answered for the signed-in Control Center viewer.

Every function re-checks that the person the action runs for may view the Control Center
dashboard: an Admin, or a ControlCenterAdmin or ControlCenterDashboardReader where the
deployment requires those roles. Agent and orchestration runs carry the authenticated user's
session into the tool call; a scheduled run has none, so it is refused.

The figures come from the same aggregation as the V2 dashboard, so an answer in chat matches
the dashboard for the same dates. Nothing here writes data or accepts query text: each function
runs fixed, parameterized queries and returns bounded rows that orchestration can chart.
"""

import logging
import re
from typing import Annotated, Any, Callable, Dict, List, Optional

from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_control_center_dashboard import (
    CONTROL_CENTER_ACTION_DEFAULT_DESCRIPTION,
    CONTROL_CENTER_ACTION_TYPE,
    CONTROL_CENTER_DASHBOARD_RANKING_LIMIT,
    DASHBOARD_ENTITY_KINDS,
    DASHBOARD_REPORT_MAX_ROWS,
    DASHBOARD_TOKEN_GROUPINGS,
    DASHBOARD_TOKEN_TYPES,
    DASHBOARD_WORKSPACE_TYPES,
    DashboardStores,
    daily_activity_report,
    extract_token_filters,
    find_entities as search_dashboard_entities,
    get_dashboard_summary as load_dashboard_summary,
    resolve_entity_names,
    resolve_requested_period,
    sign_in_pattern_report,
    summary_report_rows,
    token_usage_report,
    top_activity_report,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


CONTROL_CENTER_PLUGIN_TYPE = CONTROL_CENTER_ACTION_TYPE
CONTROL_CENTER_ACCESS_DENIED = (
    "Only Control Center administrators and dashboard readers can use the Control Center action."
)
CONTROL_CENTER_READ_FAILED = "Control Center data could not be read. Try again in a moment."
_ENTITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_MODEL_MAX_LENGTH = 200
_DATE_PARAMETER = "Start date, YYYY-MM-DD (UTC). Leave empty and use days for a range ending today."
_END_PARAMETER = "End date, YYYY-MM-DD (UTC). Required when start_date is given."
_DAYS_PARAMETER = "Number of whole days ending today (UTC), 1 to 366. Ignored when dates are given."
_FUNCTION_DEFINITIONS = (
    (
        "get_dashboard_summary",
        "Headline Control Center figures for a UTC date range compared with the previous equal "
        "range: users, sign-ins, daily/weekly/monthly active users, conversations, document "
        "uploads, processing failures, tokens, groups, public workspaces and pending approvals.",
    ),
    (
        "get_daily_activity",
        "Daily sign-ins, conversations created and document uploads by workspace type, optionally "
        "for one user or workspace.",
    ),
    (
        "get_token_usage",
        "Model token usage totalled by day, model, usage type, user, group or public workspace, "
        "optionally filtered.",
    ),
    (
        "get_top_activity",
        "The users, groups or public workspaces with the most recorded actions in a date range.",
    ),
    (
        "get_sign_in_pattern",
        "Sign-ins totalled by UTC weekday and hour, showing recurring busy times.",
    ),
    (
        "find_entities",
        "Look up the ID of a user by name or email, or of a group or public workspace by name.",
    ),
)


def _default_stores() -> DashboardStores:
    # The storage handles belong to the configured application; they are bound when a tool runs
    # so plugin type discovery can import this module without initializing Azure clients.
    import config

    return DashboardStores(
        activity_logs=config.cosmos_activity_logs_container,
        user_settings=config.cosmos_user_settings_container,
        groups=config.cosmos_groups_container,
        public_workspaces=config.cosmos_public_workspaces_container,
        user_documents=config.cosmos_user_documents_container,
        group_documents=config.cosmos_group_documents_container,
        public_documents=config.cosmos_public_documents_container,
        approvals=config.cosmos_approvals_container,
    )


def _default_capabilities() -> Dict[str, bool]:
    # Imported at the call for the same reason: the authentication module loads the bootstrap.
    from functions_authentication import get_request_control_center_capabilities

    return get_request_control_center_capabilities()


def _entity_id(value: Any, label: str) -> str:
    """Accept an empty filter or an ID; names must be looked up with find_entities first."""
    text = str(value or "").strip()
    if not text or text.lower() == "all":
        return ""
    if not _ENTITY_ID_PATTERN.fullmatch(text):
        raise ValueError(
            f"{label} must be an ID. Use find_entities to look up the ID for {text[:60]!r} first."
        )
    return text


def _choice(value: Any, allowed, label: str) -> str:
    text = str(value or "").strip().lower()
    if not text or text == "all":
        return ""
    if text not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}.")
    return text


def _limit(value: Any, default: int = CONTROL_CENTER_DASHBOARD_RANKING_LIMIT) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise ValueError(f"limit must be a whole number from 1 to {DASHBOARD_REPORT_MAX_ROWS}.")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as ex:
        raise ValueError(f"limit must be a whole number from 1 to {DASHBOARD_REPORT_MAX_ROWS}.") from ex
    if not 1 <= number <= DASHBOARD_REPORT_MAX_ROWS:
        raise ValueError(f"limit must be a whole number from 1 to {DASHBOARD_REPORT_MAX_ROWS}.")
    return number


class ControlCenterPlugin(BasePlugin):
    """Answer questions about SimpleChat usage from the Control Center dashboard's data."""

    def __init__(
        self,
        manifest: Optional[Dict[str, Any]] = None,
        *,
        stores_factory: Optional[Callable[[], DashboardStores]] = None,
        capabilities: Optional[Callable[[], Dict[str, bool]]] = None,
    ):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._stores_factory = stores_factory or _default_stores
        self._capabilities = capabilities or _default_capabilities

    @property
    def display_name(self) -> str:
        return "Control Center"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.get("name", CONTROL_CENTER_PLUGIN_TYPE),
            "type": CONTROL_CENTER_PLUGIN_TYPE,
            "description": CONTROL_CENTER_ACTION_DEFAULT_DESCRIPTION,
            "methods": [
                {
                    "name": name,
                    "description": description,
                    "parameters": [],
                    "returns": {"type": "dict", "description": description},
                }
                for name, description in _FUNCTION_DEFINITIONS
            ],
        }

    def get_functions(self) -> List[str]:
        return [name for name, _ in _FUNCTION_DEFINITIONS]

    def _run(self, operation: str, callback: Callable[[DashboardStores], Dict[str, Any]]) -> Dict[str, Any]:
        try:
            capabilities = self._capabilities() or {}
        except Exception as ex:
            log_event(
                "[CONTROL_CENTER_ACTION] Control Center access could not be checked.",
                extra={"operation": operation, "error_type": type(ex).__name__},
                level=logging.WARNING,
            )
            capabilities = {}
        if not capabilities.get("can_view_dashboard"):
            log_event(
                "[CONTROL_CENTER_ACTION] Refused a Control Center tool call without dashboard access.",
                extra={"operation": operation},
                level=logging.WARNING,
            )
            return {"success": False, "error": CONTROL_CENTER_ACCESS_DENIED, "error_type": "permission"}
        try:
            payload = callback(self._stores_factory())
            return {"success": True, **payload}
        except ValueError as ex:
            return {"success": False, "error": str(ex), "error_type": "validation"}
        except Exception as ex:
            log_event(
                "[CONTROL_CENTER_ACTION] A Control Center tool call failed.",
                extra={"operation": operation, "error_type": type(ex).__name__},
                level=logging.ERROR,
            )
            return {"success": False, "error": CONTROL_CENTER_READ_FAILED, "error_type": "unexpected"}

    @staticmethod
    def _describe_filters(stores: DashboardStores, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Echo the applied filters with names, so an answer can say whose data it describes."""
        lookups = {
            "users": [filters["user_id"]] if filters.get("user_id") else [],
            "groups": [filters["group_id"]] if filters.get("group_id") else [],
            "public_workspaces": [filters["public_workspace_id"]] if filters.get("public_workspace_id") else [],
        }
        names = resolve_entity_names(stores, lookups, log=log_event)
        described = {}
        for key, kind, field in (
            ("user", "users", "user_id"),
            ("group", "groups", "group_id"),
            ("public_workspace", "public_workspaces", "public_workspace_id"),
        ):
            entity_id = filters.get(field)
            if entity_id:
                described[key] = {"id": entity_id, "name": names[kind].get(entity_id, {}).get("name", "")}
        for key in ("workspace_type", "model", "token_type"):
            if filters.get(key):
                described[key] = filters[key]
        return described

    @plugin_function_logger("ControlCenterPlugin")
    @kernel_function(description=_FUNCTION_DEFINITIONS[0][1])
    def get_dashboard_summary(
        self,
        start_date: Annotated[str, _DATE_PARAMETER] = "",
        end_date: Annotated[str, _END_PARAMETER] = "",
        days: Annotated[int, _DAYS_PARAMETER] = 30,
    ) -> dict:
        def run(stores):
            period = resolve_requested_period(start_date, end_date, days)
            summary, _ = load_dashboard_summary(stores, period, {}, log=log_event)
            return {
                "period": period.describe(),
                "previous_period": period.describe_previous(),
                "rows": summary_report_rows(summary),
                "notes": [
                    "Changes compare the period with the equally long period just before it.",
                    "Directory figures (users, groups, public workspaces, approvals) are current totals.",
                ],
            }

        return self._run("get_dashboard_summary", run)

    @plugin_function_logger("ControlCenterPlugin")
    @kernel_function(description=_FUNCTION_DEFINITIONS[1][1])
    def get_daily_activity(
        self,
        start_date: Annotated[str, _DATE_PARAMETER] = "",
        end_date: Annotated[str, _END_PARAMETER] = "",
        days: Annotated[int, _DAYS_PARAMETER] = 30,
        user: Annotated[str, "Optional user ID from find_entities, to show one person's activity."] = "",
        workspace_type: Annotated[str, "Optional workspace type: personal, group or public."] = "",
        group: Annotated[str, "Optional group ID from find_entities."] = "",
        public_workspace: Annotated[str, "Optional public workspace ID from find_entities."] = "",
    ) -> dict:
        def run(stores):
            period = resolve_requested_period(start_date, end_date, days)
            filters = {
                "user_id": _entity_id(user, "user"),
                "workspace_type": _choice(workspace_type, DASHBOARD_WORKSPACE_TYPES, "workspace_type"),
                "group_id": _entity_id(group, "group"),
                "public_workspace_id": _entity_id(public_workspace, "public_workspace"),
            }
            rows = daily_activity_report(stores, period, filters, log=log_event)
            notes = ["Each day counts events recorded on that UTC date."]
            if filters["workspace_type"] or filters["group_id"] or filters["public_workspace_id"]:
                notes.append(
                    "Sign-ins are not recorded against a workspace, so the workspace filters narrow "
                    "conversations and uploads only; sign_ins honor the user filter alone."
                )
            totals = {
                field: sum(int(row.get(field) or 0) for row in rows)
                for field in ("sign_ins", "conversations_created", "uploads_personal", "uploads_group", "uploads_public")
            }
            return {
                "period": period.describe(),
                "filters": self._describe_filters(stores, filters),
                "totals": totals,
                "rows": rows,
                "notes": notes,
            }

        return self._run("get_daily_activity", run)

    @plugin_function_logger("ControlCenterPlugin")
    @kernel_function(description=_FUNCTION_DEFINITIONS[2][1])
    def get_token_usage(
        self,
        group_by: Annotated[str, "How to total tokens: day, model, token_type, user, group or public_workspace."] = "day",
        start_date: Annotated[str, _DATE_PARAMETER] = "",
        end_date: Annotated[str, _END_PARAMETER] = "",
        days: Annotated[int, _DAYS_PARAMETER] = 30,
        user: Annotated[str, "Optional user ID from find_entities."] = "",
        workspace_type: Annotated[str, "Optional workspace type: personal, group or public."] = "",
        group: Annotated[str, "Optional group ID from find_entities."] = "",
        public_workspace: Annotated[str, "Optional public workspace ID from find_entities."] = "",
        model: Annotated[str, "Optional model deployment name, exactly as recorded."] = "",
        token_type: Annotated[str, "Optional usage type: chat, embedding or web_search."] = "",
        limit: Annotated[int, "Rows to return for model, user, group or public_workspace totals, 1 to 50."] = 10,
    ) -> dict:
        def run(stores):
            grouping = _choice(group_by, DASHBOARD_TOKEN_GROUPINGS, "group_by") or "day"
            period = resolve_requested_period(start_date, end_date, days)
            model_name = " ".join(str(model or "").split())
            if len(model_name) > _MODEL_MAX_LENGTH:
                raise ValueError(f"model may not exceed {_MODEL_MAX_LENGTH} characters.")
            filters = extract_token_filters({
                "user_id": _entity_id(user, "user"),
                "workspace_type": _choice(workspace_type, DASHBOARD_WORKSPACE_TYPES, "workspace_type"),
                "group_id": _entity_id(group, "group"),
                "public_workspace_id": _entity_id(public_workspace, "public_workspace"),
                "model": model_name,
                "token_type": _choice(token_type, DASHBOARD_TOKEN_TYPES, "token_type"),
            })
            report = token_usage_report(
                stores, period, filters, group_by=grouping, limit=_limit(limit), log=log_event,
            )
            return {
                "period": period.describe(),
                "group_by": grouping,
                "filters": self._describe_filters(stores, filters),
                "total_tokens": report["total_tokens"],
                "rows": report["rows"],
            }

        return self._run("get_token_usage", run)

    @plugin_function_logger("ControlCenterPlugin")
    @kernel_function(description=_FUNCTION_DEFINITIONS[3][1])
    def get_top_activity(
        self,
        entity: Annotated[str, "Which ranking: users, groups or public_workspaces."] = "users",
        start_date: Annotated[str, _DATE_PARAMETER] = "",
        end_date: Annotated[str, _END_PARAMETER] = "",
        days: Annotated[int, _DAYS_PARAMETER] = 30,
        limit: Annotated[int, "Rows to return, 1 to 50."] = 10,
    ) -> dict:
        def run(stores):
            kind = _choice(entity, DASHBOARD_ENTITY_KINDS, "entity") or "users"
            period = resolve_requested_period(start_date, end_date, days)
            return {
                "period": period.describe(),
                "entity": kind,
                "rows": top_activity_report(stores, period, entity=kind, limit=_limit(limit), log=log_event),
                "notes": [
                    "activity_count counts every recorded action: sign-ins, conversations, uploads, "
                    "token records and administrative changes.",
                ],
            }

        return self._run("get_top_activity", run)

    @plugin_function_logger("ControlCenterPlugin")
    @kernel_function(description=_FUNCTION_DEFINITIONS[4][1])
    def get_sign_in_pattern(
        self,
        start_date: Annotated[str, _DATE_PARAMETER] = "",
        end_date: Annotated[str, _END_PARAMETER] = "",
        days: Annotated[int, _DAYS_PARAMETER] = 30,
    ) -> dict:
        def run(stores):
            period = resolve_requested_period(start_date, end_date, days)
            return {
                "period": period.describe(),
                "rows": sign_in_pattern_report(stores, period, log=log_event),
                "notes": ["Each row totals every sign-in in the period for one UTC weekday and hour."],
            }

        return self._run("get_sign_in_pattern", run)

    @plugin_function_logger("ControlCenterPlugin")
    @kernel_function(description=_FUNCTION_DEFINITIONS[5][1])
    def find_entities(
        self,
        kind: Annotated[str, "What to look up: users, groups or public_workspaces."] = "users",
        search: Annotated[str, "Part of a name or email, at least 2 characters."] = "",
        limit: Annotated[int, "Matches to return, 1 to 10."] = 10,
    ) -> dict:
        def run(stores):
            entity_kind = _choice(kind, DASHBOARD_ENTITY_KINDS, "kind") or "users"
            matches = search_dashboard_entities(stores, entity_kind, search, limit=min(_limit(limit), 10))
            return {"kind": entity_kind, "rows": matches}

        return self._run("find_entities", run)
