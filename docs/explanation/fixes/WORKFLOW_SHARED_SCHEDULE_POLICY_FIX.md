# Shared workflow schedule policy and visible save errors

Fixed in version: **0.261.317**.

Application version tracking: `application\single_app\config.py`.

## Issue and root cause

Editing a chat-proposed hourly workflow with Ask AI to run every minute could
pass editor validation but fail on **Confirm and save**. The editor used
`workflow_min_schedule_interval_seconds`, while proposal acceptance also applied
a stricter chat-only minimum. The administrator's general one-second minimum
therefore did not permit the same schedule on both paths.

The reported request returned HTTP 400 on 9 October 2026 at 17:50:11 UTC.
App Service console logs recorded `create_from_payload rejected` and
`cadence_below_minimum`, after ordinary personal-workflow dry runs had passed.
This confirms the mismatched policy rejection, not the numeric value of the
stored chat-only setting. No production settings were changed.

On wide screens the error could remain above the scrolled editor content.
Repeating an identical validation error did not reliably reveal it again.

## Technical changes

`functions_workflow_limits.py` now supplies the general minimum to chat planning
and blueprint validation. `functions_personal_workflows.py` uses that same policy
for editor saves, proposal acceptance, and saved-plan replay. The general default
is one second; supported values are 1 through 86,400 seconds.

`functions_settings.py` discards the retired chat-only key on load and save.
Both Classic and V2 admin forms remove its field. Its old value is not copied to
the general setting. The chat-created workflow count quota is unchanged.

New or changed interval schedules must meet the general minimum. Existing
unchanged shorter schedules remain editable after a policy increase, including
switching between interval and File Sync with the same schedule. Manual and
calendar schedules retain their existing behavior.

`functions_orchestration_planner.py` guides the model to preserve explicit allowed
timing, ask how often when recurring timing is missing, and explain below-policy
requests rather than silently substituting an interval. This is prompt guidance,
not a guarantee of live model obedience.

`WorkflowEditorDialog.tsx` focuses and scrolls save errors into view on desktop
and mobile. Narrow screens reveal the editor rather than leave its error behind
Ask AI or Changes. Repeated identical failures are revealed again. Failed saves
retain the draft and change history, and AI edits still require review.

## Validation and impact

`functional_tests/test_orchestration_workflow_proposal_editor_round_trip.py`
uses real editor serialization and production acceptance routes. It covers an
hourly-to-minute edit with general minimums of 1 and 60 seconds, ignored legacy
floors, a refusal at 61 seconds, claim release, corrected retry, and idempotency.
The persisted accepted schedule is exactly `{"unit": "minutes", "value": 1}`.

`test_workflow_orchestration_limits_settings.py`,
`test_workflow_draft_service.py`, and the workflow planning/capability tests cover
shared policy, retired settings, defaults, quota, and repairable blueprint errors.
Calendar and editor/server parity tests protect existing schedule behavior.

`ui_tests/test_v2_workflow_ask_ai_proposal.py` uses production React components
and the real Ask AI pipeline with scripted replies. Chromium checks cover
minute-based AI edits through review and save, repeated server and validation
errors, viewport visibility and focus at desktop/mobile widths, retained drafts,
and successful retry. Scripted replies prove the contract path, not model quality.

The focused proposal/planner/replay/settings suite passed 383 checks, and the
proposal/editor/admin browser suite passed 65 checks. Frontend typechecking and
build, calendar/editor-server parity, route-policy checks, and documentation
coverage/quality checks passed. Test dependencies were isolated from the shared
Python installation, and real-route tests used authentication-first offline
bootstrap to preserve the application's import order.

Three broader group-editor browser cases remain blocked before the workflow
editor opens: their existing fixture does not handle `GET /api/v2/scope`.
That unrelated fixture was not changed.

Before the fix, the editor could approve an interval that proposal creation
rejected. After the fix, both use one administrator policy and an unsuccessful
save visibly explains the requirement without discarding the user's work.

These are local implementation checks. The change does not deploy the application
or repair an already denied or expired proposal; those may require a new proposal.
