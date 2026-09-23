# Orchestration harness integration with chat checks and model routing

**Version: 0.261.131**

Fixed/Implemented in version: **0.261.131**, recorded in
`application/single_app/config.py`. Refs #1509.

## Issue and root cause

The target branch added two features while the Gather / Reason / Render harness
was in review: per-step Auto model routing and configurable chat content checks.
Both were wired into the standard orchestration route and step executor. The
harness uses a separate headless runner and dependency executor, so merging the
branches textually would have left two gaps.

- **Unenforced model bindings.** Auto routing assigns and revalidates a model per
  standard-executor step. The dependency executor has no equivalent per-step
  scope. A harness plan could have displayed model choices it never applied.
- **Unchecked harness replies.** The chat output checkpoint ran in the standard
  route's final publication. Harness replies are published by the headless
  runner, including scheduler continuations and model-free file-status updates,
  so they would have bypassed the administrator's output checks.

## Changes

| Area | Behavior |
| --- | --- |
| Contract admission | A new request that selects **Auto - choose per step** uses contract v1 even when the harness preview is admitted. Manual model selections continue to use the preview when admitted. |
| Dependency planning | `plan_request` rejects Auto for contract v2 before loading routing candidates or calling a model. Routing instructions are added only to standard-contract planner prompts. |
| Harness execution | A dependency plan carrying `model_routing: auto` fails closed with `model_routing_changed` before model setup, rather than silently ignoring bindings. |
| Reply publication | The headless publisher checks the complete reply with the shared `chat_output` checkpoint. A removed reply publishes only the safety notice, without citations or file cards. Checked metadata stays private in frames. |
| Retraction | Publication preserves an administrator's earlier retraction through the existing publication guard; later republication cannot restore removed text. |
| Check before display | Active execution marks the run pending when that mode and an output scanner are enabled. Run history hides the run's files until the checked reply is saved. |
| Run history | Removed or pending replies hide v2 file listings, cards and counts in run summaries and details, in addition to the target's step-summary masking. |
| Streams | Harness streams use the shared content-check event filter. Terminal frames include `role`, `replace_content`, and `blocked`, matching standard orchestration. |
| Retries | A prepared retry does not inherit its parent's publication check state. |
| Publication failure | The target's retraction probe after a failed publication batch now treats a missing reply as "not retracted" and re-raises the original error. Previously a `CosmosResourceNotFoundError` replaced typed authority uncertainty, turning a retryable no-outcome failure into a durable failed publication. |

The merge also combines both branches' plan-revision fields, step records,
event fields and checkpoint fingerprints. `model_binding` participates in the
plan fingerprint only when present, so existing v1 and v2 fingerprints are
unchanged. Screened history keeps the harness branch's operational-error
separation while stripping private chat-check metadata. The V2 client keeps
harness output handling and the target's replacement and safety rendering; a
blocked terminal event is never treated as a user cancellation.

Rendered files remain governed by their own current-source authorization. When
a reply is removed, links and listings are hidden, but private file records are
not deleted, matching the standard orchestration behavior for generated files.

## Validation

`functional_tests/test_orchestration_harness_chat_checks.py` uses the real
headless runner, lease, publication guard, retained results and renderer with a
deterministic in-memory screening rule. It covers a removed reply with a rendered
file, a passing reply, check-before-display pending state, preserved
administrator retraction, fail-closed Auto bindings, and planner rejection
without candidate or model access.

`functional_tests/test_orchestration_harness_routes.py` covers Auto admission and
removed-reply file visibility through the real authenticated run, detail, and
list routes.

The target branch's changed suites were rerun on the merged tree. The same seven
failures and four setup errors reproduce on the unmodified target: Flask
`test_client()` requires `werkzeug.__version__` in this environment, and one
offline probe reaches the release checker. They are not caused by this merge.

## Limitations

Per-step Auto routing is not yet available for dependency plans. Supporting it
requires per-step model scopes in the dependency executor, recovery bindings for
retained results, and planner guidance for Gather / Reason tasks.
