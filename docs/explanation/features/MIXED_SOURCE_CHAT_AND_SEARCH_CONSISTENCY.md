# Mixed-Source Chat and Search Consistency

Implemented in version: **0.250.064**

GitHub issue: [#1057](https://github.com/microsoft/simplechat/issues/1057)

Parent initiative: [#1055](https://github.com/microsoft/simplechat/issues/1055)

Phase 1 dependency: [#1056](https://github.com/microsoft/simplechat/issues/1056)

## Overview

SimpleChat Chat and workflow Search now treat explicit document selections as authoritative context even when the Search Documents panel is closed. Narrative documents continue through bounded hybrid retrieval, while selected or relevance-chosen CSV and Excel sources use the existing tabular planner and tool runner. Both branches normalize their results into the bounded evidence-envelope contract introduced in Phase 1 and provide one coverage-aware synthesis handoff to the selected model or agent.

This is Phase 2 of the mixed-source orchestration initiative. Explicit-selection behavior changes only when the independent `enable_mixed_source_chat_search` flag is enabled. Relevance-derived table candidates use a second default-off rollout stage.

## Purpose

Previously, the browser could send valid `selected_document_ids` with `hybrid_search: false` after the Search Documents panel closed. Standard Chat, streaming Chat, and tabular execution then treated the panel-derived toggle as the authority and ignored the explicit selection. Workflow Search retrieved narrative chunks but did not run selected tables through tabular tools.

Phase 2 separates source intent from retrieval preference and gives every explicit selected source a terminal coverage state without turning Chat or Search into exhaustive catalog analysis.

## Dependencies

- The Phase 1 authorized source manifest, capability partition, selection mode, and bounded evidence envelope from `functions_mixed_source_orchestration.py`
- Existing authorization-aware document resolution in `functions_search_service.py`
- Existing hybrid search, tabular planning, tool invocation, citation, generated-output, model, agent, and workflow runners
- Existing conversation history sufficiency and authorized grounding revalidation helpers
- Structured telemetry through `functions_appinsights.log_event(...)`

No new authorization model, tabular runner, synthesis contract, route, storage container, or persisted source-reuse mechanism is introduced.

## Technical Specifications

### Request Contract

The shared Chat payload now sends:

- `selection_mode`: `selected` for one or more explicit IDs; otherwise `relevance`
- `selected_document_ids`: the ordered explicit selection
- `document_context_requested`: true whenever explicit IDs exist, even if the panel is closed
- `hybrid_search`: the existing panel-derived compatibility and retrieval preference

The backend validates contradictory values and fails closed. Explicit IDs force selected mode and document context. With the rollout flag disabled, the legacy toggle-gated behavior remains active.

Collaboration streaming and retry/edit replay preserve the same fields. Replayed IDs remain untrusted hints and are reauthorized before use.

### Effective Context Order

Chat resolves evidence in this order:

1. A fresh authorized manifest for the current explicit selection
2. Freshly reauthorized conversation grounding only when there is no current selection and the history assessor requires new evidence
3. Relevance-bounded catalog candidates

Current explicit selections suppress stale conversation source guidance, automatic source expansion, and duplicate chat-upload table execution. History-sufficient turns still answer from existing conversation context without rerunning retrieval or tabular tools. Phase 2 does not persist a new follow-up source-selection record.

### Native Engine Dispatch

The manifest is partitioned once by source capability:

- Narrative sources are sent to bounded hybrid retrieval using only their authorized IDs.
- Explicit tabular sources are sent one at a time through the existing tabular planner and runner so each table reaches a completed, failed, or intentionally skipped terminal state.
- A tabular source is completed only after the existing runner records at least one successful native tabular tool call. Nonempty model text without tool coverage fails closed.
- Clearly narrative-only prompts may skip row-level processing for a selected table; collective summaries, schema questions, calculations, and table-oriented prompts invoke the tabular path.
- Unauthorized, unresolved, and unsupported sources never reach an engine and contribute only scrubbed failure coverage.

The manifest carries an internal request-scoped storage locator for authorized tabular records. The existing tabular plugin accepts that exact location only when it appears in the current request authorization context, preserving archived revision identity and approved shared-document access without authorizing arbitrary blob prefixes. The locator is not logged or included in synthesis evidence.

Tabular tool citations, inline chart citations, and generated outputs continue through their existing channels. Narrative excerpts continue through hybrid citations.

### Bounded Relevance Candidates

All Documents Chat and Search remain relevance-bounded. When `enable_mixed_source_relevance_candidates` is also enabled, a second authorized search over indexed schema-rich chunks considers spreadsheet, workbook, worksheet, CSV, column, and table terms. It requests at most 36 results and admits at most six unique tabular document candidates.

Candidate IDs are resolved again through the Phase 1 manifest before tabular execution. Assigned-knowledge searches remain constrained to their trusted document allowlist. No code enumerates or processes the entire authorized catalog.

### Evidence and Synthesis

Narrative and tabular results are normalized into the Phase 1 evidence envelope. The final bounded handoff records:

- Selection origin: selected, history, or relevance
- Native engine and terminal status for each source
- Bounded narrative excerpts and citation identifiers
- Bounded computed tabular summaries and tool citations
- Missing, unauthorized, unsupported, skipped, or failed coverage
- Whether the final answer must state partial coverage

The same handoff reaches standard Chat, streaming Chat, local model runners, local agent runners, Foundry-backed runners, and model or agent workflow Search.

### Diagnostics

Phase 2 emits aggregate structured diagnostics for:

- Explicit-selection activations
- Narrative result counts
- Tabular candidate, completed, failed, and skipped counts
- Mixed synthesis count
- Selected, history, and relevance decisions
- Partial coverage and authorization/failure omissions

Diagnostics do not include document IDs, filenames, content, blob paths, prompts, evidence, credentials, or raw configuration.

### API Endpoints

No routes are added or moved. Existing Chat, streaming Chat, collaboration, retry/edit, and workflow execution paths consume the new internal request fields.

### Configuration

- `enable_mixed_source_chat_search`: default off; enables Phase 2 Chat and Search behavior.
- `enable_mixed_source_relevance_candidates`: default off and effective only when the Phase 2 flag is enabled; activates relevance-derived table candidates after explicit-selection telemetry is stable.
- `enable_mixed_source_manifest`: remains the independent Phase 1 shadow flag and is not a prerequisite for Phase 2.

Disabling the Phase 2 flag restores legacy toggle-gated Chat and narrative-only workflow Search behavior without a data migration.

## Security

- Personal sources are reauthorized through current ownership or approved sharing checks.
- Group sources are reauthorized against current group membership.
- Public sources are reauthorized against currently visible public workspaces.
- Chat-upload sources require ownership of the active conversation.
- Caller-supplied scope, workspace IDs, ownership fields, CSS state, and persisted metadata are never accepted as authorization decisions.
- Missing and unauthorized sources retain the same scrubbed unresolved shape, preventing a metadata enumeration oracle.
- Workflow tabular tool context is derived from the freshly authorized manifest, not from workflow payload scope values.
- Browser rendering and payload changes introduce no HTML sinks, external runtime assets, or raw settings exposure.

## Usage

Enable `enable_mixed_source_chat_search` in application settings. Users may select narrative and tabular documents, close the Search Documents panel, and send a standard Chat prompt. The explicit selection remains active. Workflow Search uses the same mixed-source behavior for selected or bounded recent targets. After explicit-selection telemetry is stable, enable `enable_mixed_source_relevance_candidates` to allow bounded relevance-derived tables to compete outside the initial chunk hits.

Disable the flag to roll back to the legacy `hybrid_search` gate while retaining the Phase 1 contracts.

## Testing and Validation

- Functional coverage: `functional_tests/test_mixed_source_chat_search_consistency.py`
- Shared contract coverage: `functional_tests/test_mixed_source_manifest_contracts.py`
- Browser payload coverage: `ui_tests/test_chat_mixed_source_selection_payload.py`
- Existing workflow, history-grounding, selected-document authorization, route-policy, broken-access-control, and XSS guardrails remain part of the validation gate.

Coverage includes panel-open/panel-closed equivalence, standard/streaming shared execution, PDF plus XLSX, DOCX plus CSV in both orders, calculations, narrative-only prompts, per-table terminal coverage, partial failure, personal/group/public/chat-upload scopes, workflow model and agent runners, relevant tables outside initial hits, collaboration/replay/Foundry propagation, diagnostics privacy, and flag-off rollback.

## Performance

- Initial narrative retrieval remains bounded by existing Chat and Search limits.
- The metadata/schema candidate stage is capped at 36 search results and six tabular candidates.
- Only planner-selected relevance candidates receive tabular analytical calls.
- Explicit tables run independently to guarantee terminal coverage; evidence is bounded before final synthesis.
- Exhaustive rows remain in existing generated artifacts and checkpoints rather than model context.

## Known Limitations and Scope Guardrails

Phase 2 does not implement:

- Exhaustive Analyze All Documents semantics from Phase 3 (#1058)
- Cross-format Compare from Phase 4 (#1059)
- New persisted follow-up source reuse from Phase 5 (#1060)
- Full route-to-service extraction, broader hardening, or rollout completion from Phase 6 (#1061)
- Per-document workflow-mode changes

Chat and Search remain relevance-bounded. Analyze and Compare behavior is otherwise unchanged by this phase.

## Related Version Update

`application/single_app/config.py` was updated from **0.250.062** to **0.250.064** after preserving a concurrent application version increment while completing the Phase 2 delivery associated with #1057.