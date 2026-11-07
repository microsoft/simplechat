# Orchestration clarification continuation fix (0.261.367)

Fixed/Implemented in version: **0.261.367**

Application version: `application/single_app/config.py`.

## Issue and root cause

A self-contained orchestration request could ask for a required fact, receive an
answer, and then ask an unnecessary question about additional scope instead of
returning to planning. The observed UI failure happened before plan review,
execution, editing, or download acceptance.

The conversation resolver already skipped its model call when there was no
history and no source reference to resolve. However, the presence of clarification
answers disabled that shortcut. Answering a question therefore introduced a
history-resolution call even when the resolver had no history to interpret.
If that model returned another clarification, the route saved it and returned
before invoking the capability planner.

The answer was not lost: the server preserved it with the original request.
The unnecessary routing step prevented that complete context from returning to
the planner that decides the work.

## Changes

`application/single_app/functions_orchestration_planner.py` now keeps the existing
empty-history shortcut when clarification answers are present. It does not bypass
resolution when history was truncated or the request needs a source target
resolved. The shortcut preserves the original message and the existing retrieval
policy rather than manufacturing a plan or assuming no retrieval is necessary.

Resolver instructions distinguish resolving references from collecting new task
requirements. Planner instructions reinforce using sensible defaults for optional
presentation choices while honoring explicit requests to ask for missing facts.
Existing required capability choices, such as ambiguous spreadsheet-merge layout,
remain in effect.

The existing context builder supplies the unchanged request and all accepted
answers to the capability planner and execution. Public question schemas, SSE
events, frontend state, authorization, model selection, manual review, and
idempotency contracts are unchanged. No dependencies, settings, or capabilities
were added.

## Before and after

Before, an empty-history turn's accepted answer forced conversation resolution.
A resolver-generated optional question could prevent any plan from being created.

After, that turn returns directly to the capability planner with its original
requirements and accepted answers. Genuine missing task facts may still produce a
second question. Historical follow-ups, missing source targets, and incomplete
history continue to use resolution. The fix neither caps question rounds nor
automatically answers, declines, or runs anything.

## Validation

Regression coverage includes:

- `functional_tests/test_orchestration_conversation_context.py`: no resolver call
  for complete empty-history continuations, preservation of accepted/declined/
  cancelled answers, and retained resolution for missing sources and truncated
  history.
- `functional_tests/test_orchestration_elicitation_routes.py`: real planning and
  run routes with persisted answers, replay, multiple necessary questions, and
  TXT rendering. Parameterized numeric and string answers retain distinct original
  identifiers, supplemental instructions, and requested filenames.
- `ui_tests/test_v2_orchestration_elicitation_backend.py`: real browser components
  and controller connected to the real offline Flask routes. Both a single-answer
  path and an essential two-question path reach a saved manual-review plan without
  starting execution.

The resolver/context/editor-planner group passed **48 tests and 37 subtests**.
The real-route, selected-source, merge-choice, and download group passed **66 tests**.
Both new local Chromium browser cases passed. The V2 TypeScript/production asset
build also completed. External model, source-discovery, and storage I/O was
replaced at existing test boundaries; these are not live model-quality results.

The local Python environment initially had incompatible OpenSSL dependencies.
Validation used a session-local environment with a compatible cryptography
override without modifying the shared installation or application requirements.
The older `test_orchestration_plan_revision_routes.py` suite could not initialize
because its configuration stub lacks `cosmos_settings_container`. That unrelated
fixture problem is not repaired or counted as passing here. The focused editor
planner contract and current file-download suites passed separately.

The deployed UI case was not rerun and the application was not deployed or changed
in Azure. Incident telemetry did not expose the exact first question or answer,
nor an immutable deployed application revision. The original live scenario's
later plan-editing and download acceptance stages remain unverified. Separate
external-harness findings are retained as session artifacts, not product changes.
