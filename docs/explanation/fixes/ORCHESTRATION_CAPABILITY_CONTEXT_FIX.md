# Capability-aware orchestration planning

**Version: 0.261.104**

**Fixed in version: 0.261.104**, tracked by `VERSION` in
`application/single_app/config.py`.

## Issue and root cause

Orchestration could describe live retrieval as unauthorized even when the user
expected the deployment's research capabilities to be available. Planner context
combined the real server-resolved capability list with
`user_selected.web_search: false`, conflating an unchecked default with a denial.
Short requests could also bypass the planner entirely.

Agent discovery had a separate shape mismatch: group-ID strings reached catalog
code expecting group records. Its broad fallback then looked like a successfully
resolved empty catalog. Initial model failures likewise looked like successful
answer-only plans.

The existing balanced research-depth guidance had not been removed. These fixes
correct the surrounding context and failure contracts rather than introducing
topic-specific routing.

## Requirements versus availability

The initial planner receives separate, authoritative information:

| Context | Contract |
| --- | --- |
| Available capabilities | Server feature gates, orchestration allowlist, current caller access, and resource prerequisites. Descriptors include arguments, outputs, costs, and per-plan limits. |
| Positive requirements | Selected supported controls, documents, and agents. Initial validation rejects silently dropped selections. |
| Neutral controls | An unchecked control, including legacy false Web values, is not a veto. |
| Authorized resources | Relevant documents, governed actions, current agent records, bounded conversation context, and enabled read-only saved memory. |
| Time and prior activity | Current UTC time and bounded earlier-run summaries; neither grants permissions nor proves evidence was retrieved. |

The planner can use another available capability without a manual opt-in. An
explicit instruction such as "do not browse" remains an instruction. Selected
workspace and document filters continue to bound retrieval; the fix does not
widen authorization.

Selected Deep Research no longer requires selecting Web first. Automatic web
discovery still depends on the server's Web Search setting. Unsupported Image
generation and ineligible URL controls are not silently converted into
orchestration requirements.

An existing Image selection blocks submission until the user chooses regular
Chat with Image or explicitly excludes Image for this orchestration message.
That exclusion does not erase the ordinary-chat Image preference. URL
eligibility uses the resolved message, including attached prompts, rather than
only the draft editor text.

## Planning, editing, and execution

Every Orchestrate request invokes the planner, including short questions.
The model can choose a direct answer when context is sufficient. There is no
keyword router, fixed research quota, compulsory Web step, or mandatory Deep
Research step.

Discovery and provider failures are explicit errors, not empty catalogs or
successful answer-only plans. Missing, empty, or non-list model-authored steps
are rejected before normalization; a missing final answering step is repaired
only when real planned work remains. A failed edit preserves the prior plan. Later
manual/editor narrowing remains possible and reports when original selected
work is removed.

The agent and action catalogs share fresh membership resolution. Client group
IDs or records narrow current, role-checked group records; supplied names and
roles are not trusted. Selected agents are resolved from the authorized catalog.

Before execution, current feature and resource gates are rechecked. Stored plan
usage and positive composer requirements are separate: restoring a model-chosen
Web step does not turn the Web button into an original user selection. Completed
usage reports come from actual executed capabilities, not merely proposed steps.

## Read-only saved memory

With **Fact Memory** enabled (`enable_fact_memory_plugin`), initial planning,
planner edits, and final answers reuse the existing instruction/fact reader.
Recall is limited to eight instructions and four relevant embedded facts, with
each value bounded to 2,000 characters. Saved instructions are preferences
subordinate to the current request; facts are background context, not permissions
or proof of current external conditions.

In a private conversation, personal/public source modes use the caller's memory.
Group/all source modes with a selected group use the first active group's memory,
after fresh membership authorization. Selecting an ID never grants access, and a
denied group does not fall back to personal memory. Public document access does
not create a public-memory scope.

Shared conversations and their hidden source records receive no saved memory.
Owning a source record does not establish a private audience; the owner-only
orchestration API does not establish shared-memory authorization. This limitation
is reported in planner context rather than treating personal memories as shared.

Only audience and scope markers, not recalled prompt text, are saved with a plan
or cached clarification outcome. These markers identify what was used; they do
not grant access. Audience and current membership are checked before publishing
plans, questions, and their replays. Each cached outcome keeps its own scope
even if a later continuation changes sources.

Recall and authorization are repeated before final synthesis so changed
membership or disabled memory cannot reuse a stale payload. The actual recalled
scope is checked again after the model call, before an answer or its memory
citations can be published. Final answers retain the existing `fact_memory`
citation format and provenance.

Planning and orchestration recall do not autosave facts or backfill embeddings.
Missing embeddings are reported as unavailable, while usable instruction
memories can remain. Query embeddings may still require a model request.
Disabled memory performs no memory-store or embedding access. Ordinary chat
keeps its existing backfill behavior.

## Files and regression coverage

The contract is implemented in `functions_orchestration_context.py`,
`functions_orchestration_registry.py`, `functions_orchestration_planner.py`,
`functions_orchestration_schema.py`, the editing/revision modules, and
`route_backend_orchestration.py`. Agent discovery uses
`functions_action_catalog.py` and `functions_agent_catalog.py`. The V2 composer,
request builder, plan normalization, and stores preserve positive selections.

`functional_tests/test_orchestration_capability_context.py` exercises real group
record resolution, authorization narrowing, requirements, and notice projection.
Research-selection, conversation, clarification, revision, and hydration suites
cover their related contracts. Browser tests cover the real composer and the
combined editor/Flask workflow.

`functional_tests/test_orchestration_memory_context.py` exercises the real reader
through planning, editing, and final synthesis, including citations, scope
revocation, audience changes during planning and synthesis, clarification replay,
disabled memory, missing embeddings, and no writes.
`functional_tests/test_fact_memory_read_only_context.py` covers the bounded
reader and unchanged ordinary-chat backfill. Integration lives in
`functions_orchestration_memory.py`, the executor/respond adapter, and the
existing planning/revision routes.

## Evaluation boundaries

The research-planning evaluator captures actual serialized synthetic contexts,
capability projections, guidance, and source fingerprints. Before/after variants
retain their own contexts while keeping scenario permissions and model
parameters paired. Captured source is data and is never executed.

The suite includes an unchanged playlist request, synthetic coastal-planning
paraphrases, a short question, explicit research requirements, neutral false Web
selection, authorized documents and agents, saved preferences, and direct-answer
controls. Controlled completions establish
application behavior, not improved live model judgment. Live paired evaluation
requires an explicitly selected deployment and call budget; it is not performed
by ordinary regression tests.
