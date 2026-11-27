# Python Backend Test Revamp Plan

- Status: Scope confirmed on 2026-11-19; implementation not started.
- Planning baseline: SimpleChat **0.261.460**, local merge `3278ba9bd`.
  Reconfirm the baseline when work starts.
- Tracking: This plan and the
  [post-merge checklist](./POST_MERGE_STABILIZATION_AND_UI_PARITY_PLAN.md).

## Scope and coverage target

Review **every existing Python backend test** and bring it up to the agreed
standard. That includes unit, API, functional, and regression cases wherever they
live, including legacy scripts and tests that currently fail to collect. A
test's behavior determines scope, not its folder: a Flask API contract serving
Classic or V2 is in scope; a Python Playwright test is not.

Aim for **as close to 100% parity as practical** across applicable backend
contracts and test layers. Map each backend capability and route to runnable
evidence at the appropriate layers. Verify equivalent server behavior for
Classic and V2 when they share a contract, and document intentional differences.
Do not duplicate a test across layers merely to raise a count. Report separately
the percentage of existing backend cases reviewed, the percentage of applicable
contracts exercised, and Python line/branch coverage. List the remaining gaps
and reasons rather than shrinking the denominator.

**Out of scope:** UI interactions, browsers and Playwright, frontend JavaScript
or TypeScript tests, and visual or interaction parity. Leave those suites
unchanged. This is not a live Cosmos audit, a database migration, or a request
to change cloud resources.

## First slice: Cosmos response contracts

The merge baseline had **280 storage owner functions and four test doubles**
awaiting matching evidence. The inventory gate emitted 568 diagnostics and
stopped before the contract tests ran. These are review gaps, not a count of
runtime defects. Clear this PR check independently of the rest of the revamp.

- [ ] Reuse the SDK-shaped helpers in
  [orchestration_revisions.py](../../../functional_tests/test_support/orchestration_revisions.py)
  and [offline_bootstrap.py](../../../functional_tests/test_support/offline_bootstrap.py)
  when building the shared pytest fixture. Use the installed SDK's `CosmosDict`
  for point reads and returned create/replace/upsert/patch documents, and plain
  dictionaries for query rows. Test partition isolation, `_etag` preconditions,
  not-found and conflict handling, and rollback of failed batches where used.
  Keep plain point responses to explicit compatibility cases; pure unit tests
  with no storage boundary can use simpler mocks.
- [ ] Review the [Cosmos inventory](../../../functional_tests/cosmos_response_boundaries.json)
  by storage owner and consumer. Reuse an existing review only if its recorded
  fingerprint matches, including the module fingerprint. Link runnable SDK-backed
  evidence for changed owners and doubles where required; one real-owner test can
  support several entries when it exercises each relevant boundary. Fix
  production code only when execution proves a mismatch. Do not copy
  classifications blindly or expand a legacy exemption to make CI pass.
- [ ] Follow the [Cosmos boundary rules](../../../.github/instructions/cosmos-response-boundaries.instructions.md)
  and run the [existing gate](../../../scripts/check_cosmos_response_boundaries.py)
  and its `--run-contracts` mode with external network access blocked. Exit
  criteria: zero review gaps and passing contract tests on the same tree.

## Remaining backend overhaul

- [ ] Inventory existing test cases and compare discovery and execution against
  the pinned baseline. Triage root pytest collection, legacy direct-run tests,
  fixture/import leakage, and the stale workflow access-count expectation.
  Separate harness failures from product defects before changing expectations.
- [ ] Review and update cases by backend capability. Record a disposition for
  every test: updated, retained with evidence that it already meets the standard,
  or consolidated with a traceable replacement. Preserve meaningful assertions;
  no silent skips, exclusions, or removal of regression coverage.
- [ ] Use focused unit tests for logic, real Flask test-client requests for API
  and authorization contracts, and real Python services with offline test
  doubles for functional flows. For regressions, assert the specific observable
  outcome that would fail on the old behavior. Cover applicable success, denied
  access, invalid input, storage failures, and retry/cancellation behavior.
- [ ] Run the complete in-scope backend suite with pinned dependencies on the
  supported runtime, without a signed-in browser or live credentials. Publish
  collection and test outcomes, the contract-coverage matrix, and any remaining
  exceptions with reasons. Rerun targeted tests while making changes and the
  full in-scope suite before declaring the revamp complete.
