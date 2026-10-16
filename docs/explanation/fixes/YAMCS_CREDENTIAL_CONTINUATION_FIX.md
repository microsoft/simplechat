# YAMCS credential continuation fix

Fixed/Implemented in version: **0.261.343**, recorded in
`application/single_app/config.py`.

## Issue and root cause

The React V2 personal-credential card could successfully save a YAMCS identity
and then report that saving or continuing failed. The detached orchestration
worker reauthorized a saved credential wait before entering the existing
execution-identity bridge. The real action catalog resolver reads Flask session
identity, which is unavailable on that worker without the bridge.

There were two related state problems. The card's asynchronous submission
handler inspected React state captured before the save, misclassifying a
continuation failure as an unconfirmed save. The backend credential wrapper
marked an interaction completed whenever execution returned normally, although
the executor can persist a failed outcome and return failure frames normally.

The production investigation confirmed a successful credential submission,
an accepted SSE continuation, and a subsequent worker RuntimeError with a saved
failed execution. The missing Flask request context was reproduced locally
through the real resolver; production telemetry did not retain the exact stack.
Successful credential storage does not establish that YAMCS accepted those
credentials.

## Technical changes

`functions_orchestration_executor.py` validates the captured user and conversation,
then enters `agent_execution_identity.bridge({})` only for saved-wait
reauthorization. Direct actions and agent-owned waits share this branch. Current
conversation ownership, action governance, credential fingerprint, continuation
descriptor, and execution guards remain enforced. The entire worker does not
inherit a mutable browser request.

`functions_orchestration_execution.py` exposes the selected credential step's
outcome from its acknowledged durable finalization. The wrapper in
`route_backend_action_credentials.py` uses that outcome rather than SSE content,
HTTP status, or normal return:

| Selected work | Credential interaction |
| --- | --- |
| Completed or partial, even with a sibling waiting or a later unrelated failure | Completed |
| Failed or cancelled before completion | Failed |
| Waiting on a new credential request | Superseded |
| No confirmed durable outcome | Remains continuing; not automatically retryable |

Conditional writes still require the exact continuation claim and current ETag.
A stale worker cannot close a newer claim or overwrite a renewed pending request.

`CredentialRequestCard.tsx` tracks confirmed saves within the active submission.
After an uncertain save or continuation failure it disables repeat submission
until **Refresh saved request** reads authoritative state.
`actionCredentials.ts` validates that refresh responses belong to the same
request, conversation, run, and turn. Orchestration requests also require a
waiting saved run before continuation is offered. Terminal, superseded, active,
and unconfirmed work does not gain an automatic retry.

Secret inputs and submission buffers are cleared, duplicate submissions are
guarded synchronously, and navigation aborts stale card work. No credentials are
added to chat stores or browser storage. Diagnostics record static stages
`credential_resume_authorization` and `credential_continuation_finalization`,
exception types, and hashed correlation identifiers, never provider error text,
credential values, or request bodies.

## Validation

The regression coverage uses real application modules, detached workers, isolated
Flask identity bridges, catalog authorization, leases, checkpoints, and SDK-shaped
storage doubles. External storage, model, and provider I/O is local test data.

- `functional_tests/test_action_credentials_orchestration_continuation.py`
  covers submit-to-worker resume, concurrent identity isolation, missing and
  mismatched identities, revoked or changed actions, selected-step outcomes,
  renewed challenges, stale claims, unknown outcomes, private-error sentinels,
  preserved deadlines, and no replay of completed siblings.
- `functional_tests/test_action_credentials_bootstrap.py`,
  `test_action_credentials_sk_continuation.py`, and
  `test_action_personal_credentials.py` cover initialization, retained SK tools,
  ordinary chat continuation, and the real YAMCS SDK's local transport boundary.
- `functional_tests/test_v2_action_personal_credentials.mjs` covers safe
  projection, authoritative refresh, CSRF, revision fences, and stream contracts.
- `ui_tests/test_v2_action_credentials.py` exercises actual React cards through
  HTTP conflicts, failing SSE, transport loss, uncertain saves, failed refresh,
  terminal or unconfirmed runs, latest-revision continuation, duplicate submits,
  unmount, private-input cleanup, and desktop/mobile layout.

All 79 tests across the four focused credential Python suites pass, as do the
22 credential browser tests, frontend transport checks, TypeScript/build,
route-policy checks, documentation coverage/quality checks, and 28 orchestration
Cosmos response-contract tests. Desktop light and mobile dark recovery states
were inspected using the production styles.

The broader orchestration continuation run produced 120 passes and one failure:
`test_native_wait_reopens_original_handle_once_and_preserves_child_and_fingerprint`
in `functional_tests/test_orchestration_continuation.py`. That native-compute
fixture reports `result_producer_unavailable` before creating its expected
`compute` wait. The same test fails identically when both changed execution
modules are loaded from unmodified HEAD source in memory. It is a pre-existing
baseline failure, not repaired by this credential-boundary change.

Validation used session-local Python dependency overrides and restored frontend
dependencies; global packages were not changed. These offline results are not
proof of live YAMCS credential acceptance or a full pinned-environment CI run.

## PR #1774 Cosmos contract review

The initial `cosmos-contracts` check failed during inventory validation, before
running its runtime contracts. The credential-continuation change left five
storage-owner reviews stale and introduced three unreviewed test-local
`read_item` overrides. This was a PR-caused review-inventory omission, not an SDK
response failure or transient CI infrastructure problem.

All five storage function fingerprints still match the parent commit and its
reviewed inventory. Adding `credential_continuation_status` changed their shared
module fingerprint, which correctly requires renewed consumer review.
`functional_tests/cosmos_response_boundaries.json` was regenerated with
`scripts/check_cosmos_response_boundaries.py --refresh`, then reviewed against
the actual mapping consumers and SDK-backed runtime regressions. Saved delivery
metadata and regeneration-thread reviews also name their specific existing
runtime tests.

The three new overrides are explicitly classified as `fault-injection`, with
their real runtime evidence attached. Two inject authorization read failures;
the third forces overlapping worker reads but returns the original SDK
`CosmosDict` unchanged. The shared containers still default to SDK responses,
and partition routing, ETags, conditional writes, authorization, and private-error
checks remain intact. No legacy exemption, CI change, weakened assertion, or
production storage change is involved.

Review validation used the session-local Python environment and blocked external
network access before test collection:

- `python scripts\check_cosmos_response_boundaries.py --run-contracts`:
  **1,003 passed, 244 subtests passed**, with **1,059 owners, 407 doubles, and
  zero review gaps**.
- The credential-continuation and orchestration Cosmos-response suites:
  **60 passed**.
- The existing delivery-refresh, regeneration-thread, and conversation-source
  runtime evidence: **27 passed**.
- `python functional_tests\test_docs_site_quality.py`: **6/6 checks passed**.

The first complete local run passed 1,002 tests but failed the SDK-pin assertion
because that environment inherited Cosmos SDK 4.16.3. Restoring the application's
`azure-cosmos==4.9.0` pin in the session-local environment resolved that validation
setup failure; global dependencies and the assertion were not changed.

This follow-up changes only the reviewed inventory and this documentation;
the application version remains **0.261.343**.

## Impact and recovery limitations

The fix applies to the shared credential-continuation boundary, not only YAMCS.
It does not redesign authentication, credential storage, or unrelated telemetry.
It adds no route, setting, browser dependency, or provider.

Deploying the code does not repair a previously terminal attempt. Keep its
identity and saved run intact, refresh their state, and use only recovery
actions the server authorizes. Do not reset live credential or run records,
automatically resend the question, or replay an uncertain external operation.
No deployment, live retry, or production data repair is part of this change.
