# TABULAR DURABLE ARTIFACT LIFECYCLE FIX

Fixed in version: **0.250.199**

## Issue Description

After durable tabular parity was activated for existing deployments, four production scenarios exposed different failures in the same artifact lifecycle:

| Mode and request | Production run | Observed result |
|---|---|---|
| Search with explicit CSV | `f9ba9a10-5807-4b1f-baf4-7b7c1dacb600` | Correct 200-row CSV |
| Analyze with explicit CSV | `24346ece-6351-4653-91c4-a96f4c578052` | One-row Analyze CSV preview, then background failure |
| Search with no explicit format | `858f1f97-e22c-4f5f-b5c3-d642ad1f50f3` | Markdown uploaded, but card remained at 100% without download controls |
| Analyze with no explicit format | `10846d74-6431-4bd1-9c27-7b35c175be1d` | One-row Analyze CSV preview, then `DeploymentNotFound` |

The intended output contract is:

- Search plus explicit CSV: one CSV requested-output artifact.
- Analyze plus explicit CSV: one primary Markdown analysis artifact and one requested CSV artifact.
- Search exhaustive analysis without an explicit format: one primary Markdown analysis artifact.
- Analyze exhaustive analysis without an explicit format: one primary Markdown analysis artifact.

> **Superseded for explicit row-by-row prompts in 0.250.201:** Search now publishes one exhaustive row Markdown artifact, while Analyze publishes a summary Markdown artifact plus an exhaustive row Markdown sibling. Aggregate whole-dataset analysis remains summary-only.

## Root Cause Analysis

The production failures had seven related causes:

1. Pure-tabular Analyze preflight did not pass the selected non-secret model context into the shared durable callback. Background workers therefore resolved the displayed model name against the default Azure OpenAI resource instead of the selected endpoint.
2. Combined execution checkpointed an empty successful-result list before re-raising the captured provider exception, replacing the original failure with `Generated output schema could not be established`.
3. Search hierarchical plans inherited `analysis_required=False` from Search action mode even though the selected durable task was analysis. Their persisted contracts expected zero artifacts.
4. The hierarchical completion path uploaded Markdown without attaching its artifact metadata to the manifest member before validation.
5. Runs were marked `completed` before the required artifact set had validated and committed publication. The UI correctly stopped polling terminal runs, leaving an inconsistent completed run with a `rollback_required` artifact set permanently stuck.
6. Analyze artifact generation treated any exhaustive handoff sentence as CSV-recommended structured content, creating a misleading one-row CSV while the real durable output was pending.
7. The status API stored detailed errors internally but returned only a generic failure statement, so users could not distinguish model deployment, timeout, validation, source-access, or publication failures.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_orchestration.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- Related functional and Playwright regression tests

### Code Changes Summary

- Passed `_build_workflow_model_context(...)` through pure-tabular Analyze preflight using only model and endpoint identifiers, provider, user id, and authorized group context; no credentials are persisted.
- Made hierarchical and combined durable task types explicitly set `analysis_required=True`, independent of whether the initiating action was Search or Analyze.
- Derived required artifacts from durable task semantics for legacy or malformed empty contracts.
- Attached uploaded Markdown metadata to the analysis manifest member before publication validation.
- Required artifact-set lifecycle `completed` before setting run status `completed` for structured, hierarchical, and combined work.
- Reconciled completed legacy runs whose uploaded artifact was hidden solely because its publication commit was missing. The repair is partition-authorized, bounded, and idempotent.
- Re-raised the original generation exception when a combined window produced zero successful batches.
- Suppressed document-analysis companion artifacts when a pure-tabular durable preflight owns the final deliverables.
- Added stable, sanitized failure codes and descriptions while keeping raw SDK/provider error text server-side.
- Projected inconsistent completed runs with incomplete artifact publication as failed instead of displaying a false success state.

## Validation

- New four-scenario matrix drives the real planner, persisted metadata sanitizer, artifact manifest, validation, and public projection against the deterministic 200-row financial-review fixture.
- New lifecycle tests verify Markdown member staging, validation-before-completion, legacy contract repair, original exception preservation, and completed artifact reconciliation.
- Updated Analyze preflight tests verify selected endpoint context reaches the durable callback.
- Updated document-analysis tests verify pending pure-tabular handoffs upload no companion CSV.
- Updated public-status tests verify raw provider endpoints and error payloads are excluded.
- Playwright tests verify hierarchical Markdown completion renders download controls and failed cards show the sanitized reason.
- Full tabular scale coverage, including 100,000-row planning, leases, retries, combined execution, and idempotent publication, passes.

## Impact Analysis

- Exhaustive tabular requests now have the same output semantics in Search and Analyze.
- Analyze uses the selected model endpoint for background work.
- A run cannot report success before its required downloads are available.
- Existing uploaded-but-hidden Markdown artifacts can self-repair when their owner checks status.
- Failed runs provide an actionable category without leaking configuration or provider internals.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.250.199**.
