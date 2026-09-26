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
