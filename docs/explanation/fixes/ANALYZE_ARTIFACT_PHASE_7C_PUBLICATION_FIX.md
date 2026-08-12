# Analyze Artifact Phase 7C Publication Fix

Fixed in version: **0.250.180**

Related issue: **#1233**

## Issue Description

Combined durable Analyze runs could stage a requested structured artifact before
the Markdown analysis member was validated. Public status hid the staged member,
but direct generated-artifact download and workspace-promotion routes authorized
only conversation ownership and generated-artifact metadata. A user with the
staged artifact message id could therefore access a sibling before the required
artifact set completed.

Multi-format durable requests were also rejected even though the artifact-set
contract could represent multiple requested siblings.

## Root Cause Analysis

Generated artifact messages did not carry server-owned artifact-set lifecycle
metadata, and direct artifact routes had no way to distinguish legacy published
artifacts from new staged artifact-set members. Publication validation updated
the run manifest but did not commit the backing generated message metadata.

The durable publisher also serialized only one structured requested format from
the canonical checkpoint set.

## Technical Details

Files modified:

- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/route_enhanced_citations.py`
- `functional_tests/test_generated_artifact_lifecycle_authorization.py`
- `functional_tests/test_tabular_phase5_artifact_set_lifecycle.py`
- `functional_tests/test_analyze_deliverable_contract.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/features/ANALYZE_DELIVERABLE_CONTRACT.md`
- `application/single_app/config.py`

New generated tabular artifact messages include run id, artifact-set id,
member id, lifecycle state, validation state, and publication generation.
Legacy generated artifacts without those fields retain existing visibility.

Direct generated-artifact download and promotion now reauthorize new
artifact-set members against the owning run's completed and validated manifest.
The route rejects staged, rolled-back, stale-generation, incomplete, or
cross-object members before serving or promoting blob content.

The durable structured publisher now serializes each requested CSV, JSON, or XML
sibling from the same validated ordered checkpoints. The manifest publishes all
required members in one generation and preserves Markdown as the primary Analyze
artifact.

Failed post-staging publication states can pass the resume/cancel guard when
their artifact-set manifest is still validating, publishing, failed, or
rollback-required, preventing runs from being stranded behind
`publishing_started_at`.

## Validation

- Staged generated artifacts are rejected by direct artifact authorization.
- Legacy generated artifacts without artifact-set metadata remain accessible.
- Committed artifacts require a completed, validated run manifest with matching
  set id, member id, message id, and publication generation.
- Valid combined artifact sets commit every member in one publication generation.
- Invalid required sets fail closed without committing backing messages.
- Analyze plus multiple requested structured formats selects durable combined
  execution and publishes Markdown plus each requested sibling in order.
- The cumulative scale suite passes through 30,000-row bounded finalization,
  100,000-row planning and hardening, publication idempotency, cancellation,
  restart, authorization, and route suppression checks.

## Impact Analysis

New artifact-set members are no longer directly accessible before the set is
valid and completed. Users can request multiple durable structured siblings for
supported formats without rerunning generation. Existing generated artifacts and
old run readers are preserved.
