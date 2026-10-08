# V2 Control Center Dashboard Usability Fix

**Fixed in version:** 0.261.300

## Issue

An administrator reviewing the V2 Control Center Dashboard reported several problems:

- **Top token consumers** and **Top activity** listed users, groups and public workspaces by GUID, so nobody could tell who or what they were.
- **DAU**, **WAU** and **MAU** were labeled only as "unique users", without saying what was counted or over which days.
- The token filters sat at the top of the page, so they looked like page-wide filters. Picking a user changed the token totals but not the sign-in, conversation or upload charts, which read as the filters not working. The filters were also far from the charts they did change.
- **Chat with these trends** failed for every administrator with HTTP 401 "User not authenticated", and nothing in the Control Center granted the missing access.

## Root cause

| Problem | Cause |
|---|---|
| GUIDs in rankings | `GET /api/v2/control-center/dashboard/insights` returned only the recorded `user_id`, `group_id` and `public_workspace_id` values. Nothing resolved them to names. |
| Unclear active-user figures | The tiles had no definitions. DAU, WAU and MAU are measured through the range's end date, not across the range, and nothing said so. |
| Filters that seemed broken | The token filters were always token-only by design; the classic page showed them inside its token card. V2 moved them above everything else. |
| 401 from the trends chat | `POST /api/admin/control-center/activity-trends/chat` read `session['user_id']`, which the application never sets; the signed-in user is `session['user']`. Past that check, it wrote a malformed conversation (messages embedded in the conversation document and a hard-coded `gpt-4o` model), and V2 then linked to `/chat/<id>`, which is not a V2 route. The classic page's chat modal had no button that opened it, so the path had never worked. |

Testing also found three drill-through defects:

- The combined "Conversations and logins" chart opened conversation logs even when a login point was selected.
- The stacked charts hover by date, so a click on any segment opened the first series at that date (personal uploads, or chat tokens) instead of the segment selected.
- Drill-throughs dropped the active token filters, and dashboard readers were shown links to Users, Groups and Activity Logs, sections they cannot open.

## Resolution

### Dashboard

The dashboard aggregation moved from `route_backend_control_center.py` to `functions_control_center_dashboard.py`, which the new Control Center action also uses. The summary and insights routes are now thin wrappers with unchanged authorization and the same 90-second cache, split into an activity half keyed by date range and a token half keyed by date range and token filters.

- Rankings carry each entity's `name`, `detail` (a user's email) and `found`. Names are read by ID and cached; an entity that no longer exists is shown as **Unknown user**, **Deleted group** or **Deleted public workspace**.
- Insights carry `daily_activity` (sign-ins, conversations created and uploads by workspace type) and `token_usage_by_type`, so the dashboard no longer calls the classic `activity-trends` API.
- The page is organized into **Directory**, **Sign-ins**, **Conversations and documents**, **Token usage** and **Most active**. Each figure states what it counts; DAU, WAU and MAU name the end date and window, and the section says each person counts once.
- The token filters sit inside **Token usage**, state that they change only that section, and have **Clear filters**.
- Sign-ins and conversations have separate charts. A chart click opens the series under the pointer, or the whole day when the click is beside a stack. Token drill-throughs keep the filters, and links appear only for sections the viewer's capabilities include.

### Chat with this dashboard

**Chat with these trends** was replaced by **Chat with this dashboard**. It calls `GET /api/v2/control-center/dashboard/chat-readiness`. When every requirement is met, it opens a new chat with orchestration on and a prompt describing the dashboard's dates and token filters, passed in router state so a link cannot prefill anyone's composer. Otherwise it shows each requirement as **Ready** or **Needs set-up** with what to do, linking administrators to the setting. Answers come from the new read-only [Control Center action](../features/CONTROL_CENTER_ACTION.md).

The broken endpoint and the classic page's unreachable chat modal and script were removed.

## Files modified

| File | Change |
|---|---|
| `application/single_app/functions_control_center_dashboard.py` | New shared dashboard aggregation, names, daily series and action reports |
| `application/single_app/functions_control_center_dashboard_chat.py` | New readiness rules for dashboard chat |
| `application/single_app/route_backend_control_center.py` | Thin dashboard routes, new chat-readiness route, legacy trends chat route removed |
| `application/v2_ui/src/components/controlCenter/DashboardSection.tsx` | Reorganized dashboard, drawn with the shared dashboard parts |
| `application/v2_ui/src/components/dashboard/DashboardParts.tsx` | Optional `headingLevel` on the shared `ChartPanel`, so the dashboard's chart panels nest under their section headings |
| `application/v2_ui/src/components/controlCenter/DashboardChat.tsx` | New button and requirements checklist |
| `application/v2_ui/src/lib/composerDraftHandoff.ts`, `components/chat/Composer.tsx` | One-shot prompt hand-off into a new chat |
| `application/v2_ui/src/App.tsx` | `/admin/settings/<section>` deep links |
| `application/single_app/templates/control_center.html`, `static/js/control-center.js` | Unreachable classic chat modal and script removed |

## Validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_control_center_dashboard.py` | Aggregation, names and caching, daily series, split cache halves, Cosmos query shapes, route wrappers |
| `functional_tests/test_v2_control_center_action.py` | Action access, validation, bounded rows, readiness rules and route |
| `functional_tests/test_orchestration_action_catalog.py` | Control Center action offered and resolved only for dashboard viewers, global only |
| `ui_tests/test_v2_control_center_dashboard.py` | Sections, definitions, names, filter scope, capability-aware links, segment drill-through, checklist and prompt hand-off |
| `functional_tests/route_tests/` | Route inventory and security policy for the readiness route |

### Before and after

| Before | After |
|---|---|
| `1. 3f2a…` in Top token consumers | **Jane Doe** with her email, ID on hover |
| "DAU · WAU · MAU (unique users, measured through the selected end date)" | Separate tiles, each saying who it counts and over which days |
| Filters above the page that changed some charts | Filters inside Token usage that say they change only that section |
| 401 "User not authenticated" | A new orchestrated chat with the prompt ready, or a checklist of what to set up |
