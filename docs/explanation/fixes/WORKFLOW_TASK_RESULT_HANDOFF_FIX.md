# Workflow Task Result Handoff Fix

Fixed in version: **0.261.106**

The application version is recorded in `application/single_app/config.py`.

## Issue

Analyze could produce a complete result and downloadable artifacts while the next workflow task received only a message such as "I analyzed one source document." Separately, ordinary task handoffs retained only the first and last 6,000 characters of the preceding reply. Findings in the middle could disappear even when the selected model had sufficient context.

## Root cause

The sequence used the presentation field `reply` as its data interface. Analyze retained its final answer separately in `analysis_result`, and Markdown exports could contain both final findings and intermediate notes. Task history retained previews rather than an independently reloadable result.

Increasing the character limit or passing the whole Markdown export would not fix that contract: display text can omit findings, and diagnostic notes can contain competing intermediate versions.

## Resolution

Workflow tasks now persist a `workflow-result-v1` manifest and independently readable named sections before advancing. The producer selects the authoritative final output. Presentation and diagnostics remain available separately but are not automatically supplied to the next task.

The legacy Analyze adapter uses its final `analysis_reply`, recognizing a complete JSON object or array where available. A producer can explicitly provide `authoritative_result` with `kind` and `value`. The raw-note-preferred CSV builder is not treated as a source of finalized records merely because it created an export.

The next task reloads the manifest and selected section, verifies their producer identity, and records the exact references it consumed. No workspace upload, embedding, or re-indexing is required for this handoff.

The fixed task-context character cap is removed. Request budgets use verified catalog/deployment metadata, the effective task model, system instructions, tools, and response capacity. Inputs that cannot fit are rejected explicitly rather than shortened. Model-default response allowances use the available context; an explicitly configured response length remains a reservation.

## Files and interfaces

- `functions_workflow_results.py`: versioned manifest, producer selection, named sections, and consumption receipts.
- `functions_workflow_result_store.py`: immutable Blob/Cosmos storage, integrity checks, bounded readers, and cleanup.
- `functions_workflow_context.py`: direct model and local Semantic Kernel request budgets, including tool-result rounds.
- `functions_workflow_runner.py`: production handoff, per-document final-result retention, and persistence-before-success.
- Personal/group workflow stores, workflow routes, and activity serialization: references, scoped reads, and history metadata.
- Model capability resolver/catalog and the narrowly scoped Semantic Kernel loader integration: actual model identity and verified token ceilings.

See [Workflow Data Flow](../features/WORKFLOW_DATA_FLOW.md) for the result and reader contracts.

## Impact and limitations

Existing workflow definitions, artifact cards, and manual Add to Workspace behavior remain supported. Only runs created with this result contract have durable task sections; old previews are not presented as recovered full results.

This fix preserves the producer's final output. It does not prove semantic completeness, reconstruct findings omitted by Analyze itself, introduce arbitrary earlier-task bindings, or add automatic checkpoint resume. Schema-based deliverable validation and general control flow are separate milestones.

Hosted agents may manage prompts and tools internally; their budget audit covers the submitted input, not an inaccessible internal context. Models without verified limits use a clearly identified compatibility policy. Known models without an available tokenizer use a conservative byte-based bound.

## Regression coverage

The inventory regression executes production Analyze/artifact/dispatch functions, saves real result manifests and sections through the production store using isolated service doubles, recreates the store for reads, and synthesizes an explanation from the reloaded records.

Coverage includes batches of 1, 10, 100, and 500 records, output above the old character cap, contradictory diagnostics, exact consumed references, Blob and Cosmos storage, bounded pages, revoked group access, malformed references, and Semantic Kernel tool-round budgeting. Storage failures do not trigger another model invocation.

Relevant tests are `test_workflow_task_result_handoff.py`, `test_workflow_result_contract.py`, `test_workflow_result_store.py`, `test_workflow_result_routes.py`, `test_workflow_context_budget.py`, and `test_model_token_limit_resolution.py` under `functional_tests/`.
