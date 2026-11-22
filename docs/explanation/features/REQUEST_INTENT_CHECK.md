# Request Intent Check

## Overview

A chat turn can start work the user did not type a command for: a downloadable file, or a background run over a whole spreadsheet. Until now, keyword matching on the user's message decided whether that work started. A prompt that mentioned a format in order to forbid it ("JSON output is not permitted") or to describe a later step ("Step 5D will generate the JSON") could start an export anyway.

The request intent check separates two jobs:

- **Understanding the request.** Keywords only nominate an action. A short model call decides whether the user wants it in this turn.
- **Controlling execution.** The decision is recorded per action for the turn, and the code that starts a background run or publishes a file checks it again.

**Version implemented:** 0.261.482

**Dependencies:** the conversation's selected chat model (for the check), `functions_appinsights.log_event`.

## Technical Specifications

### Decision

`functions_request_intent.py` builds one decision per user message. Each action has its own permission:

| Action | What it covers |
|---|---|
| `file_export` | Creating a downloadable file in any detected format (JSON, XML, CSV, Markdown, Word, PDF) |
| `background_run` | Submitting a detached tabular run (full export, whole-dataset analysis, one result per row) |

Permissions are independent. "No files" withholds `file_export` only. "No background processing" withholds `background_run` only. Neither affects memory, charts, tables or inline calculations.

Order of authority:

1. **Per-turn override** sent by the client (`suppress_side_effects` on the chat request).
2. **Explicit opt-out** in the message, matched deterministically: direct statements such as "do not create files", "no files", "do not initiate background processing", "in chat only". This applies in every mode and needs no model call.
3. **Model check** for each action the keywords nominated and nothing above decided. The model answers `wanted`, `not_wanted` or `unclear`.
4. **Fail-safe.** A check that errors, times out, returns something unparseable or answers `unclear` withholds the action.

A message that nominates nothing and rules out nothing produces no decision and no model call.

If no model client exists on the path, the check cannot run. That case keeps the existing keyword behavior and is logged as `unchecked`; it is not treated as a failed check.

### Enforcement points

| Where | What it does |
|---|---|
| `get_requested_artifact_formats` (`functions_generated_file_exports.py`) | Drops formats when `file_export` is withheld. Root of every format detector. |
| `question_requests_tabular_generated_output`, `..._hierarchical_analysis`, `..._exhaustive_row_output` (`functions_tabular_orchestration.py`) | Return False when `background_run` is withheld. |
| `queue_tabular_generated_output_run` (`functions_tabular_generated_exports.py`) | Raises `RequestIntentWithheldError` for a chat-published run the turn withheld. This is the single place background runs are created. |
| `maybe_queue_direct_tabular_generated_output`, `maybe_create_tabular_generated_output` (`route_backend_chats.py`) | Return early when `background_run` is withheld. |
| `maybe_create_generated_file_output`, `maybe_create_assistant_file_generated_output` (`route_backend_chats.py`) | Return early when `file_export` is withheld. |

The detectors read the decision from a context variable. The entry points look it up by conversation and message, so they still see it when the work runs on another thread of the same request.

A decision is keyed to the exact message. Workflow prompts, analysis prompts and any other caller of the same detectors see no decision and behave as before.

### What the user sees

- When the app (model check or fail-safe) withholds an action, the reply ends with a note saying what was not started and how to ask for it. If a background run was withheld, the note says the reply covers only what fits in one chat response.
- When the user's own opt-out or override withholds an action, no note is added.
- The answering model receives a system message stating that no file or background work will happen this turn, that it should answer now without asking permission, and that it must not present partial coverage as complete.
- The background handoff message is worded as application status ("The app started a background job to generate the complete JSON for all 826 rows…"). It previously read as the assistant agreeing ("Understood. I am generating…"), which later turns treated as something the model had promised.
- The background export card has an **Answer in chat instead** button. It cancels the run and resends the request with both actions withheld.

### Configuration

`request_intent_check_mode` (backend setting, no admin UI):

| Value | Behavior |
|---|---|
| `active` (default) | The model check decides nominated actions. |
| `shadow` | The model check runs and its verdict is logged; keyword behavior is unchanged. |
| `off` | No model check. |

The explicit opt-out and the per-turn override apply in all three modes.

### Files

- `application/single_app/functions_request_intent.py` (new)
- `application/single_app/functions_generated_file_exports.py`
- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_settings.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `functional_tests/test_request_intent_side_effect_gate.py` (new)

## Coverage Inventory

Keyword checks traced to what they start. "Protected" means the decision is enforced where the action happens.

| Behavior | Triggered by | What happens next | Status |
|---|---|---|---|
| Background tabular export (JSON, XML, CSV) | Format and "all rows"-style keywords | Detached run, file published | Protected |
| Background whole-dataset analysis | "every row" plus an analysis verb | Detached run, result posted to chat | Protected |
| One result per row | "for each row"-style keywords | Detached run | Protected |
| Assistant-generated JSON/XML file | Format keywords | File published from the reply | Protected |
| CSV, Word, PDF, Markdown file from the reply | Format keywords | File published | Protected |
| File owed from an earlier clarification | Previous assistant message | File published | Protected at publication only; not reviewed by the model check |
| Chart guidance | "chart", "graph", "plot", "visualize" | System message encouraging a chart; the model decides | Deferred. Can contradict "don't plot this". |
| Diagram guidance | Diagram keywords | System message with diagram instructions; the model decides | Deferred. Same concern as charts. |
| Memory update | Memory-write keywords | A separate model pass with the memory tool decides whether to write | Not changed. Already a nominate-then-decide design. |
| Workflow runner exports | Workflow and analysis prompts | Detached run or file | Not covered. No decision is recorded for workflow prompts. |
| Chat orchestration (V2 plans) | Planner model | Plan steps, with approval | Not reviewed in this change. |
| V2 interface export card | n/a | n/a | Not changed. The Answer in chat instead button is in the classic interface only. |
| Remaining keyword helpers (document analysis output shape, source review, external retrieval, proactive charts) | Various | Not traced | Unverified |

## Usage

No setup is needed; the check is on by default.

To observe before enforcing, set `request_intent_check_mode` to `shadow` and review `[REQUEST_INTENT]` log events, which record the nominated actions, the permissions, their sources and the model status. Message text is not logged.

To send a turn with actions withheld from a client, add `"suppress_side_effects": true` to the chat request, or a list such as `["file_export"]`.

## Testing and Validation

`functional_tests/test_request_intent_side_effect_gate.py` covers:

- Opt-outs are deterministic, scoped per action, and do not fire on mentions of the topic.
- Ordinary messages produce no decision and no model call.
- The four phrasings that started exports before this change are withheld.
- Genuine export requests still start.
- Errors, timeouts, unparseable and unclear answers withhold the action and produce the visible note.
- A path with no model keeps keyword behavior.
- An endpoint that rejects the request options is retried with its defaults.
- Shadow mode logs without changing behavior.
- The per-turn override, and the prior assistant message being read only when needed.
- A decision does not leak to another message.
- Entry points enforce the decision from another thread.

### Limitations

- The model check uses a stubbed model in tests. Its accuracy on real prompts has not been measured; use `shadow` mode to collect that.
- One extra short model call runs on messages that nominate an action. The call has a 12 second timeout.
- With a background run withheld, a large spreadsheet is answered in the foreground and may be only partly covered. The model is instructed to state its coverage.
- The turn registry is in process memory. It is sufficient because a decision is only consulted while its own request is running; it is not shared across workers.
- **Answer in chat instead** resends the original prompt as a new message, which adds a second copy of it to the conversation. The prompt text is kept in page memory; it is not read back from the rendered message.
