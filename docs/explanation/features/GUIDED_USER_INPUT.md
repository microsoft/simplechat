# Guided user input (v0.261.412)

## Overview

V2 chat presents necessary follow-up questions as a focused interview instead of
emphasizing an empty editor. Users can choose a suggestion, select several
applicable answers, or write a custom answer when the question permits it. The
entire set is reviewed and submitted once; Back and Next do not call a model.

Fixed/Implemented in version: **0.261.411**
(`application/single_app/config.py`).

Orchestration already supported schema-based questions. This enhancement improves
their presentation and adds durable questions to interactive local agents,
including local agents invoked by an orchestration step. Foundry-backed agents,
classic chat, and unattended workflows do not gain this tool.

## Architecture and contracts

`ElicitationForm` is shared by orchestration planning, plan editing, and local-agent
questions. Its existing primitive `requested_schema` and `{action, content}`
response remain compatible. Supplemental text, prompts, and authorized references
remain separate answer-local context.

Closed enums are exhaustive. Open suggestions use a string or string-array
without an enum and a validated `ui_hints.fields` entry:

```json
{
  "input": "choices",
  "allow_custom": true,
  "choices": [
    {"value": "Team", "label": "Project team", "description": "People delivering the work"},
    {"value": "Leadership", "label": "Leadership"}
  ]
}
```

The actual custom text becomes the primitive answer, not an `"other"` sentinel.
Custom input is limited to 4,000 characters. Existing question limits remain
12 fields and 40 choices; two to four necessary questions is a generation
guideline, not a truncation rule. Permission, approval, and resource-identity
questions must not be changed into open-ended choices.

`elicitation_choices.py` owns presentation-hint checks. Initialized runtime
composition supplies existing schema/reference validators to `functions_user_input.py`;
the tool does not import application bootstrap to discover services.

## Local-agent pause and continuation

An interactive, request-owned local-agent kernel receives
`UserInput.request_user_input`. The server binds actor, conversation, execution,
and tool-call identity. A typed `user_input_required` event is emitted only after
the Semantic Kernel continuation has retained the tool history.

Questions use the existing private, expiring interaction-state container and
conditional writes. No new container, administrator switch, or browser dependency
is required. The standalone agent path does not require orchestration, Microsoft
365, or personal action credentials to be enabled.

The response routes are:

| Route | Purpose |
| --- | --- |
| `GET /api/v2/user-input/pending` | List the actor's pending questions for an authorized conversation and obtain the session CSRF token. |
| `POST /api/v2/user-input/<request_id>/answer` | Validate a response against its stored question and retain the submission identity. |
| `POST /api/v2/user-input/<request_id>/continue` | Claim accepted answers and continue the retained local-agent history. |
| `POST /api/v2/user-input/<request_id>/stop` | Stop the actor's accepted standalone continuation without restarting the task. |
| `GET /api/v2/orchestration/questions` | Recover the latest pending planner question without exposing its private planning context. |
| `POST /api/v2/orchestration/questions/cancel` | Persist cancellation of an identified planner question. |

Question-recovery cache handling was fixed in version **0.261.412**, recorded in
`application/single_app/config.py`. All recovery responses, including missing
conversation and storage-failure responses, use `Cache-Control: no-store` so a
retry rechecks the current access and storage state.

Identical answer retries reuse the stored result. A repeated completed continuation
does not execute tools again. A live or uncertain continuation is not automatically
restarted. Orchestration represents a local agent's pause as a `user_input` wait,
retains completed steps, and requires the question's explicit continuation claim
before resuming it. Human wait accounting remains bounded by the existing
one-day interaction allowance.

The composer's Stop action targets the saved standalone input request during
continuation. A reopened continuing request also offers **Stop saved work**.
Cancellation is checked while waiting for a provider, not only after its next
response. Completed external effects are not rolled back; an uncertain operation
is never automatically repeated. Orchestration continuations retain their existing
run-level Stop control.

The public request carries the current actor's ID as a client display-scope stamp,
not an authorization input. Late events and answer responses from an earlier
sign-in cannot populate another actor's question store or continue their work.

## User experience

Choose an answer, use **Write my own** where offered, and move through the
questions with **Next** and **Back**. **Review answers** shows the complete set
with Edit links; **Use these answers** sends it. A question may explicitly group
several existing fields on one page.

**Add context or a file** reveals the existing rich editor. It does not replace a
required closed choice. File questions retain the authorized picker/upload path.
**Continue without answers** declines the set without forwarding draft content.
**Cancel** abandons the request; it does not undo actions already completed.
Minimizing an agent's questions does not answer or cancel them.

Pending questions and already accepted answers can be recovered after reload.
Unsubmitted drafts survive step navigation and temporary conversation switches in
this tab's memory, but are not written to long-lived browser storage. A refresh
can therefore lose unsent draft text. If answers were saved before a connection
failure, **Continue saved work** uses that submission rather than asking the user
to submit a different answer to an already accepted question.

Answers never grant source access or approve external effects. Existing plan
review, current source permissions, Microsoft 365 interactions, and action
credential requirements continue to apply.

## Validation and limitations

`functional_tests/test_guided_user_input.py` exercises open/closed choices and
real SK pause/resume with side-effect counters. The route suite
`test_guided_user_input_routes.py` covers actor isolation, CSRF, revision checks,
idempotent submission, cancellation, and refusal to restart a live continuation.
The existing credential and M365 continuation suites protect neighboring paths.

`ui_tests/test_v2_guided_user_input.py` drives the shipped components and
transports on desktop and narrow mobile viewports. Existing orchestration UI
coverage includes grouped fields, required answers, optional context, review,
and decline behavior.

A lost or changed checkpoint is an explicit recovery failure, not permission to
replay the original task. These controls do not introduce a mandatory interview:
agents and the planner should ask only for facts needed to continue.
