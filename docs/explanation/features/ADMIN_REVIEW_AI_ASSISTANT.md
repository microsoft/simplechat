# AI Assist in the Admin Review Center (v0.261.299)

## Overview

The [Review center](V2_ADMIN_REVIEW_CENTER.md) lets reviewers act on many feedback records and
safety violations at once, but each review still had to be read and written by hand. When
hundreds of records arrive, most of the time goes on the routine ones: praise that needs nothing,
a false positive to dismiss, a first minor breach that only warrants a warning.

AI assist suggests those reviews so a reviewer can spend their attention on the records that need
it. It adds three things to the V2 Review center:

- **Ask AI** in the feedback and violation editors. **Analyze this record** suggests a review and
  **Apply to draft** fills the editor's unsaved draft with it, marking each field it changed.
  The reviewer checks it, edits it, and saves as usual.
- **Triage with AI** in the feedback and violations workbenches. The reviewer checks any number of
  records; the browser sends them ten at a time and the server stores a suggested review on each.
- An **AI suggestions** queue in each section, listing the stored suggestions with what each would
  change and why. Any eligible reviewer can approve them one at a time or together, edit what the
  user will be told first, or dismiss them.

The model never writes or acts. Its answer is data, checked field by field on the server, and
nothing about a review changes until a person saves it or approves the suggestion through the
same save a hand-written review uses. Suspension and block suggestions are never part of
**Approve all**, and approving one still only creates the approval request another eligible
reviewer must decide.

Implemented in version: **0.261.299**, tracked in `application/single_app/config.py`.

Dependencies:

- The V2 Review center, its bulk operations and record editors (0.261.298).
- Immediate warnings and second-reviewer approval of suspensions and blocks (0.261.297), which
  approving a suggestion goes through unchanged.
- The instruction-drafting model deployment that **Draft with AI** and the other editor
  assistants use, reached through `WorkflowAssistModel` in `functions_workflow_assist_runtime.py`.
- The shared assistant limiter in `functions_workflow_assist_limits.py`, under its own document
  type.

## Technical Specifications

### Architecture

| Part | File | Role |
| --- | --- | --- |
| Core | `functions_review_assist.py` | Parses requests, builds each record's view and the prompt, validates the model's answer against the schema and the review policy with one correction round, isolates content-filter refusals, fingerprints records, and defines the stored suggestion's lifecycle. Imports no app configuration, so it runs in tests without Azure. |
| Runtime | `functions_review_assist_runtime.py` | Reads records by id from the section's own container, settles violations, counts a user's earlier violations, stores suggestions with conditional writes, and wires the limiter and model. Answers are strict JSON with `Cache-Control: no-store, private`. |
| Applying and dismissing | `functions_review_center.py` | The bulk `suggestion_id` and `dismiss_suggestion` operations: `apply_suggested_review`, `dismiss_review_suggestion` and `refuse_suggestion_operations_while_off`. |
| Audit | `functions_review_lifecycle.py` | `log_review_suggestion_action` records each applied or dismissed suggestion in the admin activity log. |
| Routes | `route_backend_feedback.py`, `route_backend_safety.py` | The two assist endpoints, the `ai` list filter, the feedback `theme` field, filter and dashboard figures, and hiding suggestions from users. |
| Browser | `lib/reviewAssistApi.ts`, `lib/reviewSuggestions.ts` | Strict parsing of answers and stored suggestions, the queue's approval planning and confirmations, triage chunking with waits and cancel, and draft apply and undo. |
| Browser | `components/review/ReviewAskAiPanel.tsx`, `components/review/useReviewTriage.ts`, `pages/review/SuggestionsQueue.tsx` | The editors' Ask AI panel, the workbenches' triage run, and the queues. |

### API endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /api/admin/review/feedback/assist` | Analyze or triage feedback records. |
| `POST /api/admin/review/safety/assist` | Analyze or triage safety violations. |
| `POST /feedback/review/bulk`, `POST /api/safety/logs/bulk` | An `update` may carry `suggestion_id` to apply a stored suggestion; `dismiss_suggestion` dismisses one. |
| `GET /feedback/review?ai=pending`, `GET /api/safety/logs?ai=pending` and the matching `/ids` routes | Records with a pending suggestion, stale ones included: the queues. |
| `GET /feedback/review?theme=<theme>`, `GET /feedback/review/stats` | Feedback by theme; the dashboard's `theme_mix` and `unthemed_count_in_window`. |

Each assist endpoint has the same decorators as its section's record routes: `@login_required`,
then `@feedback_admin_required` and `@enabled_required("enable_user_feedback")` for feedback, or
`@safety_violation_admin_required` and `@content_checks_report_enabled` for safety. The route then
refuses with `403 review_assistant_disabled` while the toggle is off, before anything is read or
counted. The bulk routes keep their decorators and refuse each suggestion operation with the same
code while the toggle is off; the other operations in the request still run.

### Requests and answers

The body is `{"mode": "analyze" | "triage", "ids": [...]}` and nothing else. **analyze** takes
exactly one id and returns a suggestion marked `unsaved`; nothing is stored. **triage** takes one to
ten ids and stores each suggestion on its record. Bodies over 16 KB, unknown fields, repeated ids
and ids that aren't text are refused.

The answer is `{"section", "mode", "results": [...]}` with one result per requested id, in request
order. Each result has an `outcome`:

| Outcome | Meaning |
| --- | --- |
| `suggested` | A suggestion was made, and for triage stored. |
| `content_filtered` | The model service's content filter declined this record. Nothing was stored. |
| `too_large` | The record alone is too large for the model. |
| `not_found` | No record has this id. |
| `locked` | A pending suspension or block request, or a warning being sent, holds the violation; it was skipped and never sent to the model. |
| `no_suggestion` | The model's answer for this record failed validation, even after the correction round. |
| `not_analyzed` | The request stopped, for example at its time limit, before reaching this record. `code` says why. |
| `record_changed` | The record's reviewable fields changed while the model was working, so the suggestion wasn't stored. |
| `save_failed` | The suggestion couldn't be stored. |

Errors that refuse the whole request carry a closed `code` and a server-written message:
`invalid_request`, `too_many_records` and `assistant_input_too_large` (400),
`review_assistant_disabled` (403), `request_too_large` (413), `assistant_busy` and
`assistant_rate_limited` (429, with `Retry-After`), `assistant_output_invalid` and
`assistant_refused` (502), `assistant_unavailable`, `assistant_timeout` and
`assistant_limit_unavailable` (503), and `assistant_failed` (500). Provider error text is never
passed on.

### What the model receives

Each record is read on the server by id, never taken from the browser, and shown to the model as
a view under a request-local handle (`r1`, `r2`, ...). Views never carry record, user,
conversation, message or approval ids, names or email addresses. Email addresses and GUIDs inside
the text are replaced with `[email]` and `[id]`, control characters are replaced with spaces, and
long text is cut off with ` [truncated]`.

| Section | Fields in the view |
| --- | --- |
| Feedback | Rating; the prompt (1,500 characters), the AI response (2,500) and the user's reason (600); the current review: whether it is acknowledged, its theme, and its analysis notes, action taken and response to the user (1,000 characters each); whether it is archived. |
| Safety | Whether the content came from the user or an AI response; the flagged text (2,000 characters); up to 12 triggered categories with severity and the highest severity; the current status, action and notes; where any remediation request stands; whether a sent warning was acknowledged; the user's own notes (600); how many earlier violations the same user has; whether it is archived; and the actions this record allows. |

The earlier-violation count is computed on the server: the user's other violations about content
they wrote, flagged before this one. If it can't be read, the model is told it is unknown.

The system message holds the rules and the answer format and no record text. The records, and the
organization's **Review Guidance for the AI Assistant** when set, go in one JSON document as the
user message. The rules tell the model that everything inside the records is untrusted data to
treat only as evidence, never as instructions, and that the guidance applies where it fits but
can't override the rules or the format.

### Validating the answer

The answer must be one JSON object, `{"suggestions": [...]}`, with exactly one suggestion per
handle sent. Unknown or repeated handles, missing or unknown fields, values outside each field's
vocabulary and text over its limit are problems. When there are any, the model is asked once more
with the problems listed; suggestions that were valid the first time are kept. A record whose
suggestion is still invalid gets `no_suggestion`, and when no record has a valid suggestion the
request fails with `assistant_output_invalid`.

| Section | Suggestion fields |
| --- | --- |
| Feedback | `acknowledged`; `analysisNotes`; `actionTaken`; `responseToUser` (optional); `theme`: `accuracy`, `citations`, `retrieval`, `formatting`, `tone`, `latency`, `safety`, `praise` or `other`; `archive`; `rationale`; `confidence`: `low`, `medium` or `high`. |
| Safety | `status`: `New`, `In-Review`, `Resolved` or `Dismissed`; `action`: `None`, `WarnUser`, `SuspendUser` or `BlockUser`; `notes`; `notification_title` and `notification_message` for a warning, suspension or block; `suspend_duration`: `24h`, `7d` or `30d` for a suspension; `archive`; `rationale`; `confidence`. |

Policy is enforced by the server, not left to the model:

- **Escalate** is never accepted.
- Content that came from an AI response allows only `None`: it can never lead to a warning,
  suspension or block of the user.
- An applied or sent remediation is never weakened; only the same or a stronger action is allowed.
- A warning, suspension or block needs its notification title and message, and a suspension one of
  the offered durations.
- Reviewer-facing text over its limit is cut off; text the user would read (the response to the
  user and the notification title and message) is refused if too long, so it is never cut short.

### Content-filter isolation

When the model service's content filter refuses a request for several records, the server asks
about each of them alone, so one record the filter declines doesn't cost the others their
suggestions. A record still refused on its own is reported as `content_filtered`. Isolation stops
on any other error or when the request's time runs low, and the remaining records are reported as
`not_analyzed`.

### Stored suggestions

A triage stores each suggestion on its record as `ai_suggestion`:

```json
{
  "id": "<32 hex characters>",
  "status": "pending",
  "created_at": "<ISO time>",
  "created_by": {"id": "<reviewer id>", "name": "<reviewer name>"},
  "model": "<deployment>",
  "fingerprint": "<digest>",
  "payload": {"...": "the validated suggestion"},
  "rationale": "...",
  "confidence": "medium"
}
```

Applying adds `applied_at`, `applied_by` and `edited`; dismissing adds `dismissed_at` and
`dismissed_by`. Triaging a record again replaces its suggestion.

Storing a suggestion changes the record's ETag, so the ETag can't tell whether the record itself
changed since the suggestion was made. The fingerprint does: a digest of the fields the model read
and a review would change, without timestamps of earlier saves or the suggestion itself. A pending
suggestion whose record no longer matches its fingerprint is shown as `stale` and can't be applied,
only dismissed. The suggestion is written conditionally on the version read, and after a conflict
only while the latest version still matches the fingerprint, so a review saved meanwhile is never
overwritten and storing the suggestion never makes it stale.

Responses hide the fingerprint and the requesting reviewer's id. A user's own feedback and
violation lists never include `ai_suggestion`, and their feedback never includes the theme.

### Applying and dismissing

An approval is a bulk `update` with the reviewer's `changes` and the `suggestion_id`:

1. The server reads the record and refuses with `409 suggestion_stale` or `409
   suggestion_not_pending` if the suggestion no longer fits.
2. It runs the section's normal save with the reviewer's changes. Unless the browser sent an ETag
   of its own, the save is pinned to the version it just checked, so the record can't change in
   between. Every rule a hand-made save follows still applies: a warning is sent at once, a
   suspension or block creates an approval request, a violation held by a request is refused, and
   AI-generated content still can't be used to warn or restrict.
3. Only once the save succeeds is the suggestion marked applied, with whether the reviewer edited
   it, and the admin activity log credits the suggestion (`feedback_ai_suggestion_applied` or
   `safety_violation_ai_suggestion_applied`, with the suggestion id, model, creation time and the
   suggested action or theme, and no review text).

`dismiss_suggestion` marks a pending or stale suggestion dismissed without changing the review and
logs `feedback_ai_suggestion_dismissed` or `safety_violation_ai_suggestion_dismissed`. With an
ETag it is refused with `record_changed` if the record moved on.

The queue never asks for a suspension or block again. A suggestion that repeats the one the
violation already records updates the review only, and the server reports it as already applied
or unchanged; requesting it again remains a deliberate choice in the violation's editor.

### Configuration

| Setting | Default | Notes |
| --- | --- | --- |
| `enable_admin_review_ai_assistant` | Off | **Admin Settings > Security > Access & Roles > Permissions.** The V2 bootstrap exposes only this boolean, so the Review center can show its AI entry points; the server checks it again on every assist request and suggestion operation. |
| `admin_review_ai_guidance` | Empty | Up to 2,000 characters of plain text, sent to the model with each request and never to the Review center. It is removed from the settings any non-admin page receives. |

### Limits

| Limit | Value |
| --- | --- |
| Records per assist request | 10 (analyze: 1) |
| Request body | 16 KB |
| Requests per reviewer | 60 per 10 minutes, across both sections, counted under the document type `admin_review_assist_rate_limit`. A request that never reached the model is not counted. |
| Concurrent requests per reviewer | 1; another gets `assistant_busy` |
| Time per request | 150 seconds on the server, including the correction round and one-record retries; the browser waits up to 170 |
| Correction rounds | 1 |

A triage of hundreds of records is driven by the browser: ten records per request, one request
after another, with progress and **Cancel**. When the assistant is rate limited or briefly
unavailable, the run waits as long as the server says, up to 90 seconds at a time and three times
per group; an unusable answer fails only its own group; anything else stops the run and reports
the records not sent.

### Telemetry

Each request logs one `[REVIEW_ASSIST] Review assist request finished` event with the reviewer id,
section, mode, status and code, the stage it reached, record and eligible counts, model calls,
correction rounds, whether content-filter isolation ran, whether guidance was used, outcome counts
and duration. Record text, guidance and model output are never logged.

## Usage

### Turn it on

1. In **Admin Settings > Security > Access & Roles**, turn on **Enable AI Assist in the Review
   Center**.
2. Optionally write **Review Guidance for the AI Assistant**: your organization's review policy in
   plain language, such as "Warn on a first minor violation. Suggest a suspension only after
   repeated violations."
3. Save. Reviewers who can open a Review center section now see **Ask AI**, **Triage with AI**
   and the section's **AI suggestions** page.

### Analyze one record

Open a record's editor and select **Ask AI**, then **Analyze this record**. The panel shows the
suggested review, what it would change, the model's reason and its confidence. **Apply to draft**
fills the unsaved draft and marks each changed field; **Undo** takes it back, keeping any field you
changed since. Nothing is saved, sent or requested until you save the review.

When AI triage already stored a suggestion for the record, the panel offers it as **Suggestion from
AI triage**. Saving after applying it records that the suggestion was applied.

### Triage many records

In a workbench, check the records, or use **Select all matching**, then select **Triage with AI**.
The confirmation explains that nothing changes now and no one is notified. The report lists every
record that didn't get a suggestion and why, and links to the **AI suggestions** queue.

### Work through the queue

Each row shows what the suggestion would change, for example *Status New → Resolved · Warn user ·
Notes: ...*, the model's reason and confidence, and badges for what approving it sets off:
**Sends a warning**, **Needs a second reviewer**, or **Already on this violation**. Rows whose
record changed are marked **Out of date**, and violations held by a request **Held by a request**;
neither can be approved.

- **Approve all ready** applies the ready suggestions on the page except suspensions and blocks.
- **Approve selected** and each row's **Approve** apply the suggestions you ticked, suspensions and
  blocks included. Selecting the whole page never ticks a suspension or block.
- Before a warning is sent, or a suspension or block requested, you can edit the notification's
  title and message on the row.
- The confirmation states how many suggestions are applied, how many users are warned at once, how
  many suspension or block requests are created, how many are already on their violation, and how
  many records are archived.
- **Dismiss** removes a suggestion without changing the review.

The report names each suggestion that wasn't applied and why, and those rows stay checked.

### Feedback themes

Feedback reviews now have a **Theme**, set in the editor or by applying a suggestion. The feedback
dashboard's **Themes** panel counts the period's feedback by theme, and each theme opens the
filtered list. Users never see the theme.

## Testing and Validation

### Test coverage

| Test | Covers |
| --- | --- |
| `functional_tests/test_review_assist_core.py` | Request parsing, views without identifiers, the prompt, schema validation and the correction round, handle checks, policy (no Escalate, no remediation for AI-generated content, no weakening), content-filter isolation, deadlines, fingerprints and the suggestion lifecycle. |
| `functional_tests/test_review_assist_routes.py` | Both endpoints through the Flask routes on the Review center harness with a fake model: role and toggle gates, strict bodies, no identifiers reaching the model, storage, the queue filter, staleness, applying with attribution and audit, dismissing, refusal while off, the limiter, content-free telemetry, and the real model invoker's refusal mapping. Runs in normal and optimized Python. |
| `functional_tests/route_tests/test_review_assist_policy.py` | Decorators and their order on both endpoints, and a live check of each gate. |
| `functional_tests/test_v2_review_assist_logic.mjs` | The browser's parsing, approval planning and confirmations, never asking for a restriction again, failure text, the operations it sends, triage chunking, waits and cancel, and draft apply and undo. |
| `ui_tests/test_v2_review_center_ai_assist.py` | The queue, triage, Ask AI, themes, and that nothing about AI assist shows while it is off. |

### Performance

Each assist request makes one model call for its records and at most one correction call. When
content-filter isolation runs, each record gets up to two more calls of its own, within the same
time limit. Safety requests add one query per distinct user for the earlier-violation count.
Reading the queue is the existing list query with one more filter.

### Known limitations

- Suggestions are only as good as the model and the guidance; a reviewer must check each one.
- **Approve all ready** covers the current page of the queue.
- A triage runs in the reviewer's browser tab; closing it stops the run after the group in flight.
- Records the content filter declines get no suggestion and are reviewed by hand.
- The classic admin pages don't show AI suggestions; AI assist is part of the V2 Review center.
