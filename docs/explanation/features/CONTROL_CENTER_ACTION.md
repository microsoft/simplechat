# Control Center Action

## Overview

The Control Center action lets a Control Center viewer ask questions about SimpleChat usage in chat: sign-ins and active users, conversations, document uploads, processing failures and token use, ranked by user, group or public workspace. It reads the same aggregation as the V2 Control Center Dashboard, so an answer in chat matches the dashboard for the same dates. The dashboard's **Chat with this dashboard** button opens an orchestrated chat that uses it.

**Version implemented:** 0.261.301

**Dependencies:** Semantic Kernel actions (`enable_semantic_kernel`), Chat Orchestration with Action Access for chat use, the V2 Control Center Dashboard, and the existing Control Center role settings.

## Technical specifications

### Architecture

| Part | Location | Role |
|---|---|---|
| Shared aggregation | `functions_control_center_dashboard.py` | Dashboard summary, insights and the action's reports. Standard library only, so the action and tests import it without the application bootstrap. |
| Action plugin | `semantic_kernel_plugins/control_center_plugin.py` | `ControlCenterPlugin`, discovered by type `control_center` |
| Access | `functions_authentication.get_request_control_center_capabilities()` | The signed-in request's Control Center capabilities; no request means no access |
| Discovery gate | `functions_action_catalog.py` | Lists or resolves a Control Center action only in global scope and only for a caller who can view the dashboard |
| Type rule | `functions_governance.ensure_action_type_access()` | Refuses the type in personal and group scope, which removes it from those type lists and saves |
| Readiness | `functions_control_center_dashboard_chat.py` | The requirements for dashboard chat and their remedies |

### Access model

The action answers only for someone whose roles grant `can_view_dashboard`: an Admin, or a ControlCenterAdmin or ControlCenterDashboardReader where the Control Center role settings require them. This is enforced three times:

1. The action catalog hides the action from anyone else, so the orchestration planner never sees it.
2. Resolving the action's manifest for a plan step refuses anyone else.
3. Every function re-reads the capabilities from the signed-in session before reading data.

Orchestration captures the caller's roles with their identity and passes them explicitly to the catalog and manifest resolution, including on its worker threads, where the run re-enters a request context carrying the authenticated session. A scheduled workflow run has no signed-in session, so the action refuses it. Any failure to determine access refuses the call.

The type is global-only. Personal and group workspaces cannot list, create or save it; an administrator creates it in **Admin Settings › Agents & Actions › Global Actions**.

### Functions

| Function | Returns |
|---|---|
| `get_dashboard_summary(start_date, end_date, days)` | One row per headline figure with its value, previous-period value, change and definition |
| `get_daily_activity(..., user, workspace_type, group, public_workspace)` | Daily sign-ins, conversations and uploads by workspace type, with totals |
| `get_token_usage(group_by, ..., user, workspace_type, group, public_workspace, model, token_type, limit)` | Tokens by day, model, token type, user, group or public workspace |
| `get_top_activity(entity, ..., limit)` | Users, groups or public workspaces with the most activity records |
| `get_sign_in_pattern(...)` | Sign-ins by UTC weekday and hour |
| `find_entities(kind, search, limit)` | IDs of users by name or email, or of groups and public workspaces by name |

Every result has `success`, and on success the `period` it covers and `rows` that orchestration can chart. Filters are echoed with names. Errors are `permission`, `validation` (a message the model can act on) or `unexpected` (a generic message; details go only to the `[CONTROL_CENTER_ACTION]` log event).

Arguments are validated before any read. Dates are UTC `YYYY-MM-DD`, either both given or replaced by `days` (1 to 366). Entity filters must be IDs, so names go through `find_entities` first. Ranked results return 1 to 50 rows, searches 1 to 10. All reads are fixed, parameterized queries that the Python Cosmos SDK can run across partitions; the action writes nothing.

### Configuration

| Field | Value |
|---|---|
| Type | `control_center` |
| Endpoint | `control_center://internal`, set by the server |
| Authentication | `user` only (`static/json/schemas/control_center.definition.json`) |
| Description | Optional; a blank description is replaced on save with one naming the questions it answers, because the planner chooses actions by description |

The V2 action editor shows it as an internal type with no connection fields. The classic action modal hides it.

### API

`GET /api/v2/control-center/dashboard/chat-readiness` requires login and Control Center dashboard access. It returns:

```json
{
  "ready": false,
  "action": null,
  "requirements": [
    {
      "id": "agents",
      "label": "Agents and actions are turned on",
      "met": false,
      "detail": "Dashboard chat answers through a Control Center action, and actions run on the agent runtime.",
      "remedy": "Turn on Enable Agents in Admin Settings › Agents & Actions.",
      "settings_link": "/admin/settings/agents-config"
    }
  ]
}
```

Requirements are `agents`, `orchestration`, `action_access` (Enable Action Access and **Use an action** in the capability list), `control_center_action` (exists, enabled, offered under Workspace Mode, allowed by governance) and, only when missing, `chat_access` (User or Admin app role). The response reports setting states and the caller's own access, never setting values. `settings_link` is returned only for Admin callers, and the browser renders only `/admin/settings/<section>` and `/admin/actions` paths. Responses are sent with `Cache-Control: no-store`.

## Usage

### Set up

1. Turn on **Enable Agents** in **Admin Settings › Agents & Actions › Agent Runtime**.
2. Turn on **Enable Chat Orchestration** and, under **Capabilities**, **Enable Action Access**. If the capability list is narrowed, include **Use an action**.
3. In **Global Actions**, choose **New action**, then **Control Center**, and save.
4. With Workspace Mode on, turn on **Add Global Agents and Actions to Workspaces**. With **Govern Global Actions** on, allow the people who should use it.

The Dashboard's checklist links administrators to each of these settings.

### Ask questions

Choose **Chat with this dashboard** on the V2 Control Center Dashboard. A new chat opens with orchestration on and a prompt such as:

> Using the Control Center action, help me understand the SimpleChat Control Center dashboard for 2026-09-08 to 2026-10-07 (UTC). Summarize sign-ins and active users, conversations, document uploads and token usage, compare them with the previous period of the same length, call out anything unusual, and chart the daily trends.

The prompt is passed in router state, never the URL, so a link cannot place text in someone's composer, and a reload does not apply it again. Edit it or ask your own question, then send it. Questions can also be asked in any orchestrated chat, for example "which groups used the most tokens last week?".

## Testing and validation

- `functional_tests/test_v2_control_center_action.py`: refusal without dashboard access and outside a signed-in request, role rules through the real capability function, bounded chartable rows, validation before reads, generic storage errors, no writes, kernel function parameters, schema registration, readiness rules and remedies, admin-only links that match real Admin Settings sections and the browser allowlist, and the readiness route.
- `functional_tests/test_orchestration_action_catalog.py`: the action is offered and resolved only to dashboard viewers, never outside global scope, and the type is refused for personal and group governance.
- `functional_tests/test_v2_control_center_dashboard.py`: the shared aggregation and reports.
- `ui_tests/test_v2_control_center_dashboard.py`: the checklist, **Check again**, and the prompt hand-off into a new orchestrated chat.

### Performance

Reports reuse the dashboard's 90-second caches, so a chat and the dashboard asking about the same dates share one read. Each uncached period streams one narrow projection of the activity window and one of the filtered token records. Name lookups are point reads cached per entity.

### Known limitations

- Sign-ins are not recorded against a workspace, so workspace filters narrow conversations and uploads but not sign-ins.
- Rankings include only entities recorded in activity records' `user_id` and workspace-context fields.
- Directory figures (users, groups, workspaces, approvals) are current totals without history, so they have no period comparison.
- A scheduled workflow cannot use the action, because it has no signed-in Control Center viewer.

## Related

- [V2 Control Center](V2_CONTROL_CENTER.md)
- [V2 Control Center Dashboard Usability Fix](../fixes/V2_CONTROL_CENTER_DASHBOARD_USABILITY_FIX.md)
- [Control Center action reference](../../reference/actions/control-center.md)
