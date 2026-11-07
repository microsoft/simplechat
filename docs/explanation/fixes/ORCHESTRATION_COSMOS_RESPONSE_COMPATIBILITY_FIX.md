# Orchestration Cosmos response compatibility and failure diagnostics

Fixed/Implemented in version: **0.261.140**, recorded in
`application/single_app/config.py`.

The Cosmos response fix shipped in the React V2 branch as 0.261.140. On the V2 shared workspaces branch, which had already assigned 0.261.140 to its group model endpoint APIs, it arrives with the React V2 base merge in version **0.261.181**.

## Issue

A CSV request could produce a plan but never execute a step. Execution admission
returned HTTP 503 with `context_unavailable`; reading the same saved run returned
HTTP 404, and the browser remained in **Checking execution status**. The durable
run was still marked running after its lease expired. Scheduler attempts to
recover it failed with `scheduler_invalid_state`.

Separate writing and document-comparison requests failed with
`deliverables_invalid`, including their one planner correction attempt. Existing
telemetry identified the validation stage but not the rule that rejected either
proposal.

## Root cause

The pinned `azure-cosmos==4.9.0` returns `CosmosDict` objects from document point
reads and writes. These are dictionary subclasses, not exact built-in `dict`
instances.

Several storage owners passed those SDK responses directly to strict
orchestration contracts:

- A conditional execution claim returned `CosmosDict`. The runner rejected its
  type after the claim had already marked the attempt running, before any model
  or step executed.
- Current conversation reads reached result/output authorization as `CosmosDict`.
  The output store interpreted the type mismatch as unavailable conversation
  access. Run detail therefore returned 404 despite matching ownership.
- Revision reads supplied SDK responses to leases and scheduler recovery. The
  scheduler rejected an otherwise valid authoritative run.
- Output point reads and the external-identity and deletion-only callbacks had
  the same representation mismatch at subsequent boundaries.

Plain-dictionary storage doubles did not expose these failures.

The planner's diagnostic gap had a separate cause: every deliverable violation
shared one public code, its specific internal exception message was not logged,
and the logging allowlist retained only the lengths of validation-code and
workflow-ID strings. An HTTP 200 planning stream could therefore contain an
error without identifying the rejected rule in queryable telemetry.

## Changes

### Normalize SDK documents at their owning boundary

`functions_orchestration_plan_revisions.py`,
`functions_orchestration_recovery.py`,
`functions_orchestration_bootstrap.py`, and
`functions_orchestration_output_store.py` convert SDK mapping responses to plain
dictionaries before passing them to domain contracts.

ETags remain available for conditional writes. Ownership, source authorization,
attempt identity, lease fencing, deletion guards, cancellation, and deadlines are
unchanged. Non-mapping output responses are explicitly rejected, not converted
from arbitrary iterable data. Model-generated plans and retained-result
contracts keep their strict shape checks.

No SDK downgrade, database migration, additional capability, or new setting is
required. An expired attempt retains its original execution budget; recovery does
not silently reset its deadline or create another execution.

### Preserve specific, privacy-safe failure facts

Deliverable violations now carry a static internal rule identifier through
`functions_orchestration_schema.py` to the planner's correction and terminal
failure events. Examples include `non_file_format`, `invalid_quantity`,
`answer_producer_mismatch`, `missing_final_response`, and `file_format_mismatch`.

The public `deliverables_invalid` behavior and single correction attempt are
unchanged. Neither a generic failure nor a guessed rule is converted into an
answer-only plan.

Execution preparation records its stage, response type, and safe failure code.
HTTP admission records whether a durable outcome was confirmed. Run-status and
scheduler diagnostics retain their stage and exception class without publishing
raw SDK exception bodies.

`functions_appinsights.py` preserves these narrowly scoped fields and SHA-256
hashes of workflow IDs. These events omit raw prompts, document text, complete
provider responses, user identity, credentials, and arbitrary deliverable
descriptions. Essential failures do not require verbose debug logging.

See [Orchestration failure diagnostics](../../reference/logging-tags.md#orchestration-failure-diagnostics)
for fields and bounded Application Insights/Log Analytics queries.

## Validation

`functional_tests/test_orchestration_cosmos_response_contract.py` uses real
authenticated routes, claims, leases, result/output stores, publication, and
scheduler code with only external I/O doubled. Both plain dictionaries and the
installed SDK's actual `CosmosDict` responses are exercised.

Before the fix, the SDK-shaped cases reproduced HTTP 503 admission, HTTP 500 run
listing, HTTP 404 run detail, and the unnormalized claim/lease records. After the
fix, the same boundaries support execution and readable saved status. Coverage
includes:

- Conditional ETags, foreign owners, malformed responses, and storage outages.
- Source-free answer publication and status reads without additional model calls.
- A downloadable CSV checked against all 50 unique state/capital pairs, including
  its headers and final row, rather than just a file card or preview.
- An expired initial claim reaching a durable timeout without content generation.
- A confirmed preparation failure saving its terminal outcome and releasing its
  lease.
- Current external identity/settings reads and deletion-only tombstone cleanup
  with SDK-shaped responses.

`test_orchestration_failure_telemetry.py` checks each declared rejection rule,
correction versus final-attempt diagnostics, logger allowlists, hashed correlation,
and private-data canaries with debug logging both enabled and disabled. Critical
regressions also run under optimized Python.

The existing browser-to-Flask recovery suite,
`ui_tests/test_v2_orchestration_recovery_backend.py`, exercises both storage
response shapes, including stream loss and explicit checkpoint retry.

## Planner declaration follow-up

The historical logs did not retain the rejected proposals. Subsequent authorized
planner-only calls to the configured model reproduced the writing and comparison
failure: answer deliverables carried both a file-format field and an item count,
and the single correction removed only the first invalid field.

The same patch now includes explicit kind-specific planning guidance and handling
for an optional null answer binding in file-only plans. See the
[planner deliverable fields fix](ORCHESTRATION_PLANNER_DELIVERABLE_FIELDS_FIX.md)
for the reproduced sequence, scope of the model probes, and regression coverage.
Validation still rejects missing required answers and unsupported deliverables.

## Repository-wide boundary follow-up (0.261.324)

Fixed/Implemented in version: **0.261.324**, recorded by the version update in
`application/single_app/config.py`.

The earlier fixes were not reverted. A subsequently introduced operation journal
copied a point-read `CosmosDict` before passing it to `canonical_bytes`. The
subclass survived `deepcopy`, so strict JSON validation failed after an external
operation had already produced its durable action. That journal's boundary is
repaired separately as part of the
[email review flow fix](ORCHESTRATION_EMAIL_REVIEW_FLOW_FIX.md). No historical
conversation, outgoing action, or operation is rewritten or replayed.

### Shared document boundary

`application/single_app/cosmos_document_utils.py` provides
`normalize_cosmos_document(value)`. It accepts a `collections.abc.Mapping`,
returns a new plain top-level dictionary, and retains every document field,
including `_etag`. Nested values are deliberately unchanged. Non-mappings,
including lists of key/value pairs, raise `TypeError`; they never become an
empty document or a success-shaped fallback.

The utility imports neither configuration nor the SDK, settings, logging, or
Azure clients. Storage owners retain their own authorization, metadata stripping,
absence/outage handling, conditional writes, and error translation. Equivalent
existing conversions in bootstrap, revisions, recovery, and output storage now
use this utility without weakening their original validation. Settings' private
metadata-stripping helpers remain with settings rather than changing their
different semantics to fit a universal helper.

`validate_json` remains strict. This is an outer document representation boundary,
not recursive domain repair or a global SDK monkeypatch.

### Classified audit, not a count of purported bugs

`functional_tests/cosmos_response_boundaries.json` inventories application storage
functions, repository scripts, and deployer point boundaries. It includes returned
responses, method references passed to helpers, `getattr`-mediated methods,
module-level reads, conditional batch paths, and separate query/batch entries.
Each record has an implementation fingerprint, a consumer classification, an
explicit evidence scope, and applicable test references.

The reviewed snapshot contains 1,045 storage scopes in 169 files: 7 normalized
strict boundaries, 810 SDK-compatible consumers, and 228 unused responses.
Evidence is deliberately separated: 99 scopes cite owner-runtime regressions,
718 retain source review plus real SDK API evidence, and 228 discard responses.
These are inventory/assurance categories, not counts of production defects.
Owner-runtime references exercise representative real-owner SDK regressions;
they do not establish exhaustive branch coverage of every listed function.
The per-consumer classification records the reviewed contract, not a static
proof that every downstream call is safe.

The principal findings are:

| Owner or consumer | Classification and evidence |
| --- | --- |
| Operation journal | Confirmed strict JSON mismatch, reproduced with the real SDK. The owner normalizes before copying; uncertain-effect recovery remains explicit. |
| Bootstrap, revisions, leases/recovery, outputs | Previously repaired strict boundaries. Real authenticated route, ETag, ownership, scheduler, publication, and download contracts still pass in both storage modes. |
| Checkpoints, continuation guards, artifact messages | SDK-compatible field access, nested plain JSON, or metadata-stripping projections. Raw point messages are not themselves the strict descriptor/result envelopes. |
| Workflow control, journal, result manifests/chunks | Control verification accepts dictionary subclasses, replacements are plain metadata-stripped projections, and result field verification accepts `Mapping`. SDK-default runtime/result tests pass without broad production rewrites. |
| M365 requests, approvals, delivery/resume, files/history | Mapping-compatible storage consumers. Public/domain projections and the independently normalized operation receipt must not be conflated with raw point responses. SDK-default regressions preserve current access and ETag behavior. |
| Existing settings, document/admin, prompt/catalog, notification, script/deployer consumers | Classified field/JSON/projection consumers or unused responses. Their inventory distinguishes source review plus real SDK API evidence from owner-runtime SDK coverage; it does not claim every legacy owner has a new end-to-end test. |

No additional production mismatch was proven by these migrated runtime suites and
the strict-sink review. An exposed SDK mapping, an exact-dictionary check on a
domain payload, or a grep hit is not sufficient evidence of a defect. The
deployer's configuration point read is a mapping field consumer, so no deployer
implementation or deployer version change is required.

Unchanged legacy source-reviewed owners have a closed fingerprint baseline.
Changed or new owners cannot inherit that limited evidence: they need a reviewed
consumer contract and owner-runtime SDK coverage. The checker is a maintained
change/review guard, not an interprocedural type proof. This distinction is
intentional, so representative SDK evidence cannot silently become a claim of
universal runtime verification.

### Realistic shared and inline test boundaries

The shared M365 and atomic orchestration containers now return the **actual
application-pinned SDK `CosmosDict`** from point reads and returned writes by
default. Workflow runtime/result doubles, offline bootstrap/result-route storage,
workflow chat delivery containers, and the inherited orchestration result/message
containers use the same default. `sdk_responses=False` is an explicit compatibility
probe, not the normal easy test path.

Query rows/pages remain plain dictionaries. Real SDK transport tests also verify
that nested JSON is plain and returned create/upsert/replace/patch documents have
the point-response wrapper. Both modes preserve fields, ETags, partition routing,
conditional conflicts, and failed-batch atomicity.

The inventory separately records inherited Cosmos containers, write-only and
embedded subprocess containers, test-local fault/compatibility seams, and
domain-level runtime/result mocks. Its 389 entries comprise 11 SDK-default
containers, 4 domain doubles, 227 staged legacy containers, 141 existing
explicit compatibility seams, and 6 runtime-tested fault-injection seams.
Domain mocks deliberately keep plain domain projections; they are not made to
impersonate a Cosmos client. Unchanged inline fakes outside the migrated owners
remain an explicit staged-migration baseline. Removed or changed exemptions fail
the guard, and a new Cosmos container cannot declare itself an unchanged legacy
fake.
Existing compatibility seams have their own closed baseline. A new or changed
point override must supply runtime `fault-injection` evidence instead of
silently preserving an old plain-response override.

### Dedicated deterministic gate and contributor rule

`.github/workflows/cosmos-response-contract-check.yml` runs the inventory,
normalizer/shared-double contracts, real SDK transport contracts, orchestration
response/operation/import/telemetry suites, and affected M365/workflow regressions.
The email-review-flow suite also runs in this gate, covering real owner
publication with SDK-default storage alongside operation-journal receipt tests.
It uses existing application/test requirement pins, no cloud credentials, and
`test_support.cosmos_network_guard` to block socket/DNS network access before
collection. Windows' standard-library loopback socket pair for asyncio is the
only narrowly scoped connection exception, not permission for application HTTP.

Pinned tokenizer data is prepared as a dependency asset in a workspace-local
cache during setup, before network is blocked. This avoids an encoding download
inside a test while keeping the real context-budget calculation. Offline route
fixtures enter through the real orchestration bootstrap and mock the current
model endpoint's external client factory as well as the legacy planner factory.
Legacy approval coverage supplies current external safety dependencies and fails
if that unrelated remediation is unexpectedly invoked.

The generated-output lifecycle fixture originally injected raw Cosmos reads as
domain-level conversation/run access callbacks. SDK-shaped defaults exposed that
fixture mismatch through both normal and optimized scheduler transport probes.
Its storage-owning callbacks now normalize before strict `OrchestrationResultAccess`
authorization, matching production bootstrap behavior. No domain validator or
authorization rule was weakened, and no container was forced into plain mode.
Production service wiring uses `read_owned_conversation`, which normalizes its
point document, and `get_orchestration_run`, which returns a plain
metadata-stripped projection after its ownership checks. External-source access
uses those same callbacks through `_read_metadata`. The fixture failure is not
evidence of another production `OrchestrationResultAccess` representation bug.
Both transport probes now belong to the core gate; lifecycle fault overrides
have explicit runtime evidence rather than an unchanged compatibility exemption.

The workflow is triggered by relevant application, script/deployer, test/shared
double, requirement, inventory, contributor-rule, and workflow changes. A new
storage module or differently named test fake cannot avoid the gate.
The runner derives additional test selectors from reviewed owner-runtime,
SDK-default, domain-double, and fault-injection evidence. A newly reviewed
owner's regression therefore executes in CI without requiring a second,
independently maintained workflow test list.

Contributor instructions are in
`.github/instructions/cosmos-response-boundaries.instructions.md`. Run:

```powershell
python scripts\check_cosmos_response_boundaries.py
python scripts\check_cosmos_response_boundaries.py --refresh
python scripts\check_cosmos_response_boundaries.py --run-contracts
```

`--refresh` only stages changed implementations as `review-required`; it does
not automatically approve a classification or expand a legacy baseline.

### Follow-up validation

The normalizer suite covers field/ETag preservation, mapping versus invalid
response shapes, strict nested-domain rejection, and fresh-process normal and
optimized Python imports without configuration or SDK dependencies. Guard tests
cover unused versus returned/helper responses, module-level and dynamic method
references, point/query/batch distinctions, inherited and domain doubles,
similarly named non-Cosmos APIs, new/changed owners, and stale evidence/exemptions.

Verified with the application's actual `azure-cosmos==4.9.0`; the SDK version
assertion reads its expected value from the application requirements rather than
introducing a second pin:

- Final normalizer/shared-default, inventory guard, and real SDK transport
  contracts: **58 passed**:
  `python -m pytest -p test_support.cosmos_network_guard functional_tests\test_cosmos_document_boundaries.py functional_tests\test_m365_cosmos_sdk_contract.py -q --disable-warnings --tb=short`.
- Final dedicated runtime gate in the independently pinned environment:
  **567 passed**, including **231 subtests**:
  `.venv\pinned\Scripts\python.exe scripts\check_cosmos_response_boundaries.py --run-contracts`.
  This verifies Cosmos 4.9.0, Semantic Kernel 1.39.4, and the application-pinned
  Flask/Werkzeug versions, with external network blocked during tests.
- Final inventory checker: **1,045 owners, 389 doubles, zero review gaps**:
  `python scripts/check_cosmos_response_boundaries.py`.
- Lifecycle fixture follow-up: **275 passed**:
  `.venv\pinned\Scripts\python.exe -m pytest -p test_support.cosmos_network_guard functional_tests\test_orchestration_output_lifecycle.py functional_tests\test_cosmos_document_boundaries.py -q --disable-warnings --tb=short`.
  Both normal/optimized scheduler transport probes and the underlying file-tick
  no-replay regression also pass together (**3 passed**).
- Broader eight-file integration suite after the fixture boundary correction:
  **560 passed and 112 subtests passed**:
  `.venv\pinned\Scripts\python.exe -m pytest -p test_support.cosmos_network_guard functional_tests\test_orchestration_harness_routes.py functional_tests\test_orchestration_harness_chat_checks.py functional_tests\test_orchestration_action_runtime.py functional_tests\test_orchestration_executor.py functional_tests\test_orchestration_results.py functional_tests\test_orchestration_output_lifecycle.py functional_tests\test_workflow_runtime_integration.py functional_tests\test_workflow_result_store.py -q --disable-warnings --tb=short`.
  The earlier 220 lifecycle failures no longer reproduce; SDK-default point
  responses remain enabled and strict domain authorization remains unchanged.
- Complete retained-results/output lifecycle plus real SDK production boundary
  regressions: **310 passed**:
  `.venv\pinned\Scripts\python.exe -m pytest -p test_support.cosmos_network_guard functional_tests\test_orchestration_results.py functional_tests\test_orchestration_output_lifecycle.py functional_tests\test_orchestration_cosmos_response_contract.py -q --disable-warnings --tb=short`.
- Orchestration Cosmos, revision, and telemetry contracts: **90 passed**,
  including **36 subtests**, with external network blocked.
- M365 runtime/authorization/approval/file/history and workflow runtime/result
  contracts: **153 passed**, including **131 subtests**, with external network
  blocked.

An additional exploratory run of all workflow chat-delivery suites and M365
continuation/pending-delivery/execution-preflight suites passed **426 tests and
31 subtests**, but reported seven unrelated existing failures: six route-first
public-workspace import-cycle probes (using their own unchanged plain-dictionary
container), and one stale stranger-edit refusal expectation. Broader workflow
result-route/review probes also retain stale retry expectations: an absent
message is rejected before workflow-result retry checks, and an unfinished
attempt prevents an ordinary edit. The refusal and result-route/review outcomes
were reproduced with explicit plain point responses. These are not additional
Cosmos representation mismatches and were not changed or placed in this bounded
contract gate.

These checks do not send real mail, contact deployed Azure resources, change
production configuration, or relax authorization/result contracts.
