# Agent Actions Ignored When Workspace Evidence Is Present

**Fixed in version: 0.260.023**

**Issue:** [#1332](https://github.com/microsoft/simplechat/issues/1332)

**Related:** [#1021](https://github.com/microsoft/simplechat/issues/1021) — turn-level orchestration across chat capabilities, the strategic solution to this class of problem. This fix addresses the concrete symptom and does not close that initiative.

## Issue

Selecting an agent that has actions, enabling a workspace, and asking a specific
quantitative question produced an answer that:

1. never invoked any of the agent's actions, and
2. reported numbers that were not actually present in the spreadsheet it cited.

The reported case was a telemetry question against a workspace containing an
Excel file. Workspace search retrieved a narrative document plus the spreadsheet,
and the assistant answered from retrieved text alone, fabricating values.

The turn behaved as "retrieval **or** actions" instead of "retrieval **and**
actions". Evidence gathering should be additive: gather everything the turn is
capable of gathering, then reason over the union and decide what is relevant.

## Root Cause

Three independent defects combined to produce the symptom.

### 1. Tabular computation was suppressed by the presence of any narrative source

`should_run_tabular_evidence()` in `functions_mixed_source_orchestration.py` was
a keyword heuristic that ended with a blanket rule:

```python
if has_narrative_sources:
    return False
```

A single PDF landing in the relevance results suppressed computation over an
authorized spreadsheet. The heuristic also treated topic words — `report`,
`policy`, `procedure`, `contract`, `agreement`, `memo`, `letter`, `narrative`,
`prose` — as evidence-type signals. Those words describe subject matter, not
which engine can answer a question, so they misfired frequently.

When the gate returned `False`, `execute_tabular_evidence_sources(...,
execute=False)` emitted a `skipped` evidence envelope and the tabular engine
never ran.

Note that when `enable_mixed_source_chat_search` is disabled, the legacy path in
`route_backend_chats.py` computes workspace tabular sources unconditionally. The
mixed-source path had regressed that behavior; this fix restores parity.

### 2. Only a truncated preview of a spreadsheet is indexed

`_build_tabular_schema_summary()` in `functions_documents.py` indexes a single
schema chunk holding at most `TABULAR_SCHEMA_SUMMARY_MAX_PREVIEW_ROWS` (3) rows
per sheet. This is intentional — the full file lives in blob storage and the
tabular engine reads it directly.

However, when defect 1 skipped computation, that preview was still handed to the
model as ordinary retrieved text. The model then derived counts and averages from
three rows, which is the direct source of the incorrect values.

The indexed chunk even ends with "This file is available for detailed analysis
via the Tabular Processing plugin" — the model read the advertisement for the
tool while being instructed not to use it.

### 3. The retrieval augmentation prompt forbade using actions

`build_search_augmentation_system_prompt()` in `route_backend_chats.py`
instructed:

> Base your answer only on information supported by the retrieved excerpts and
> any computed tool-backed results included elsewhere in this conversation
> context.

The mixed-source evidence handoff built by
`build_mixed_source_evidence_handoff()` was likewise a closed "synthesize one
answer" instruction.

Agent actions were in fact available. Agents are constructed with
`FunctionChoiceBehavior.Auto()` in `semantic_kernel_loader.py`, and the agent is
invoked with the augmented history through `selected_agent.invoke_stream(...)`.
No code disables tools when documents are in scope. The model simply obeyed the
instruction not to look anywhere else, and the retrieved excerpts appeared
sufficient, so it never called an action.

## Files Modified

| File | Change |
|---|---|
| `application/single_app/functions_mixed_source_orchestration.py` | Inverted the tabular gate; narrowed narrative markers; rewrote the skipped-envelope summary; added action permission and a preview-row guard to the evidence handoff |
| `application/single_app/route_backend_chats.py` | Rewrote `build_search_augmentation_system_prompt()` |
| `application/single_app/config.py` | Version `0.260.022` -> `0.260.023` |
| `functional_tests/test_agent_actions_with_workspace_evidence.py` | New regression test |
| `functional_tests/test_mixed_source_chat_search_consistency.py` | Updated the gating contract a generic question now computes rather than skips |

## Code Changes

### Additive tabular gating

`should_run_tabular_evidence()` now defaults to running. Computation is skipped
only when narrative sources are present **and** the question unambiguously names
a narrative artifact:

```python
narrative_artifact_markers = (
    "pdf", "docx", "word document", "presentation", "powerpoint",
    "paragraph", "section",
)
```

Topic words no longer suppress computation. Explicit tabular intent and
collective phrasing still short-circuit to `True`.

### Skipped sources are now self-correcting

A skipped tabular envelope previously read "Tabular processing was not needed for
this narrative-only request", which told the model the source was irrelevant. It
now states that the full table was never read, that any indexed excerpt is a
truncated preview, that numeric conclusions must not be drawn from it, and that
the tabular analysis action should be called if values are required.

### Prompt contract permits and expects action use

The retrieval augmentation prompt now frames excerpts as starting evidence rather
than the only permitted evidence, directs the model to call an available action
when the excerpts lack what the question needs, keeps a hard no-fabrication rule,
and forbids deriving any numeric conclusion from tabular preview rows.

The mixed-source handoff carries the same permission plus a guard against
numeric conclusions drawn from an indexed preview of a source whose evidence
status is not `completed`.

No new setting was introduced. These are correctness fixes and apply
unconditionally.

## Validation

```powershell
python .\functional_tests\test_agent_actions_with_workspace_evidence.py
python -m pytest .\functional_tests\test_mixed_source_manifest_contracts.py .\functional_tests\test_tabular_computed_results_prompt_priority.py -q
```

The new test asserts:

- a quantitative question with narrative sources present now computes the
  tabular source (the reported regression);
- an unambiguous narrative-artifact question still skips computation;
- topic words such as "report" no longer suppress computation;
- the skipped envelope warns against numeric conclusions from preview rows;
- the search prompt permits action invocation and no longer says "only";
- the handoff instruction permits action invocation.

Existing contracts in `test_tabular_computed_results_prompt_priority.py` and
`test_mixed_source_manifest_contracts.py` continue to pass unchanged.

### Known unrelated failures

Three tests in `test_mixed_source_chat_search_consistency.py` fail both before
and after this change, at identical assertions. Their harness builds a synthetic
namespace for `_execute_mixed_source_tabular_evidence` that is missing
`maybe_queue_search_tabular_generated_output`, so the stubbed tabular runner
raises and every source reports `failed`. A third failure originates in
`foundry_agent_runtime.py`. Both are pre-existing harness drift and are out of
scope for this fix.

## Before / After

| | Before | After |
|---|---|---|
| Spreadsheet + PDF in scope, quantitative question | Tabular engine skipped | Tabular engine runs |
| Model's view of a skipped spreadsheet | "not needed for this narrative-only request" | Explicit warning that the table was not read and the action should be called |
| Retrieved excerpts insufficient | Model answers from excerpts or declines | Model calls an available action, then reasons over both |
| Numbers from a 3-row preview | Permitted implicitly | Explicitly forbidden |
