# Schema-v2 Workflow and Runtime Repairs (0.261.046)

Fixed/Implemented in versions: **0.261.045** and **0.261.046**.
Related configuration update: `application/single_app/config.py` moves from
`0.261.044` through `0.261.046`. Refs #1518. Phase 3 remains uncommitted; beta acceptance is pending.

## Problem

The paused workflow implementation lacked pre-read endpoint governance checks,
and deferred tabular paths still created legacy contexts. Four workflow tests
failed because fixtures lagged the runtime API and asserted a historical version.
Additional boundary tests exposed a chat wrapper rejecting its caller's TLS
arguments, wrong policy-key lookups, and missing actor identity in vision tests.

## Changes

- Workflow scope and item policy checks run before endpoint-store reads or secret
  hydration; current group membership is rechecked.
- Deferred workflow contexts reload saved scope and allowlist stable IDs, omitting
  URLs and credentials. Context-only resolution does not allocate a sync client.
- The chat wrapper forwards the explicit TLS settings accepted by the shared
  factory. Model tests, summaries, and workflows use the canonical
  `allow_insecure_custom_model_endpoints` setting; private-host checks still apply.
- Vision tests bind the current actor to the saved global selection. Explicit
  schema-v2 agent selections remain rejected; agent defaults retain legacy fallback.
- Existing workflow and tabular fixtures match the current helper signatures.

## Validation

Tests were extended in the existing workflow, streaming, scope, and summary files.
Observed failing-first cases covered policy denial, context allowlisting, real
wrapper arguments, actor propagation, and the actual agent-default request shape.
The 20-file offline selection passed 149 tests; the seven directly changed suites
passed 46 tests after final changes. No deployment or provider inference occurred.

## Runtime Hardening in 0.261.046

Model tests preserve the saved credential scope on global fallback. Shared
sync/async clients enforce schema-v2 identity and capabilities before inference,
including body-extension overrides, with per-client policy isolation. Queued
export contexts bind to verified run/conversation ownership; tabular budgets use
the authorized protocol and saved limits. Metadata helpers forward CA/plaintext
policy. Agents remain excluded.

Messages stream ownership now closes responses and HTTP clients before first
iteration, after early exit or parser failure, and after cancellation during
creation or reading. In-flight synchronous reads finish under existing timeouts
before cleanup; cancellation does not force-kill Python threads.

Explicit enable/disable is available in all three endpoint editors, while new
records still start disabled. The complete browser suite passed 53 cases, plus
both changed JavaScript syntax checks. Final consolidated validation passed
235 tests across 22 explicitly selected files with dotenv and external-network
guards enabled. Documentation checks passed 13/13 and route-policy checks 12/12.

Full repository collection remains blocked by app-bootstrap/import-fixture
conflicts. Signed-in beta/APIM validation remains outstanding. Existing publisher
code is untouched. Its read-only beta preflight stopped before build; direct Azure
reads of the target registry and app returned AuthorizationFailed. No deployment
ran. Restore target access and re-run validation before publishing; do not change
credentials or choose another environment to bypass this blocker.