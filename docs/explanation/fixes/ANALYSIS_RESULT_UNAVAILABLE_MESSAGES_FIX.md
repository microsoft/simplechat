# Saved-Result Error Messages Fix

Fixed in version: **0.261.234**

Related issue: [#1621](https://github.com/microsoft/simplechat/issues/1621) (follow-up).

## Issue

From 0.261.230 through 0.261.232, saved and generated results stopped re-checking the documents they came from. The error those checks raised, `AnalysisResultUnavailable`, kept its old wording, so people were told about source access when the actual problem was different:

- The exception had one message for every case: "This analysis is unavailable because its source access could not be confirmed." Routes that return a `PermissionError` message passed it straight to the user.
- The workflow runner reported every `AnalysisResultUnavailable` as "A required source is no longer available for this workflow run.", including a missing or changed earlier result, a broken loop or Repeat record, and a deleted conversation or run.
- When a task's result couldn't be saved, the runner always said that "a document it read changed or became unavailable while it ran". The same message appeared when the result's own source list was malformed.
- A loop paused with "The current loop item's original source is no longer available." even when the saved collection behind the item had changed.
- The workflow progress view said "Workflow progress is unavailable because current access could not be confirmed." when a saved record behind a publication gate failed its check.
- Explaining a saved analysis, saving an Analyze result and the final publication check each used one fixed text for every case. For example, a saved result with a broken source list was reported as "this conversation or a selected document is no longer available".
- History placeholders said a saved analysis or saved workflow output was unavailable "because its access could not be confirmed".

## Root Cause

`AnalysisResultUnavailable` is raised at about 200 places with 53 distinct codes. Most describe a saved result whose lineage, manifest, receipt or loop and Repeat state is missing, changed or invalid. Others describe the conversation, message, workflow or run that holds the result. Only a few mean that a source document can't be read right now, and those come from input reads. The exception and every mapping that turned it into text assumed the last case. Five raises passed no code at all, so they got the source default even when they checked a message or workflow binding.

## Technical Details

Files modified:

- `application/single_app/functions_analysis_access.py`
- `application/single_app/functions_document_analysis_checkpoints.py`
- `application/single_app/functions_document_analysis_results.py`
- `application/single_app/functions_saved_analysis.py`
- `application/single_app/functions_workflow_artifacts.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_workflow_flow_runner.py`
- `application/single_app/functions_generated_artifact_sources.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_workflows.py`
- `application/single_app/config.py`
- `functional_tests/test_analysis_unavailable_message_families.py` (new)
- `functional_tests/test_workflow_durable_routes.py`
- `functional_tests/test_analyze_backend_saved_integration.py`

### Message families

`functions_analysis_access.py` classifies every code into one of three families, held in explicit frozensets. Each code is classified by what its raise sites check, not by its name.

| Family | Meaning | Frozenset | Message |
| --- | --- | --- | --- |
| Source | An input read found a source document it can't read now, or one that changed while it was read. | `ANALYSIS_SOURCE_UNAVAILABLE_CODES` | "A source document for this analysis is no longer available or has changed." |
| Container | The conversation, message, workflow or run that holds the result is gone or isn't the caller's. | `ANALYSIS_CONTAINER_UNAVAILABLE_CODES` | "The conversation, workflow or run that holds this result no longer exists or isn't available to you." |
| Saved result | The stored result, or an earlier result, manifest, receipt, or loop or Repeat state it depends on, is missing, changed or invalid. | `ANALYSIS_SAVED_RESULT_UNAVAILABLE_CODES` | "This saved result can't be used because something it depends on is missing or has changed." |

`AnalysisResultUnavailable(code, *, family=None)` sets `code`, `family` and `public_message`, and uses `public_message` as its own text. `analysis_unavailable_family(code)` returns the family for a code. An unclassified code falls back to the saved-result wording, which blames neither a source document nor the caller's access. The functional test keeps every application raise classified.

Three raise sites share a code with another family, so they pass `family=` explicitly:

- `resolve_analysis_source_manifest` raises `analysis_source_manifest_invalid` as a source failure, because the current source lookup itself failed during an input read.
- `index_analysis_source_manifest` raises `analysis_source_manifest_invalid` as a source failure when an assigned document was not authorized by the current lookup.
- `load_workflow_artifact_binding` raises `generated_artifact_source_unavailable` as a saved-result failure, because a saved output's run records could not be loaded. The workflow and run scope checks raise the same code as a container failure.

The five raises that passed no code now pass one. `authorize_analysis_sources` (an invalid reader or an authorization failure) and `AnalysisWorkUnitCheckpoints.validate_sources` keep `analysis_source_unavailable`. `_load_authorized_message` now raises `analysis_message_unavailable`, and `_load_authorized_workflow` raises `analysis_workflow_unavailable`. Both are container failures. No route, V2 code or test branched on their old default code, and they map to the same response codes as before: `workflow_result_access_denied` for chat follow-ups, `output_access_denied` for generated files and `workflow_result_invalid` for the workflow result reader.

Loop document re-authorization (`_authorize_frozen_document`) passes the `WorkflowLoopInputError` code through. Those codes (`workflow_loop_input_unavailable`, `workflow_loop_source_changed` and `workflow_loop_scope_forbidden`) are source codes.

### Where the family now picks the text

| Place | Source | Container | Saved result |
| --- | --- | --- | --- |
| Workflow task error | "A required source is no longer available for this workflow run." (unchanged) | "A conversation, workflow or run that this task needs is no longer available." | "A saved result this task needs can't be used because something it depends on is missing or has changed." |
| Task result not saved | "The analysis result was not saved because a document it read changed or became unavailable while it ran. Dependent tasks were not run." (unchanged) | "The analysis result was not saved because the conversation, workflow or run that holds it is no longer available. Dependent tasks were not run." | "The analysis result was not saved because something it depends on is missing or has changed. Dependent tasks were not run." |
| Loop item pause | "The current loop item's original source is no longer available." (unchanged) | "The conversation, workflow or run that holds the current loop item's input is no longer available." | "The current loop item's saved input can't be used because something it depends on is missing or has changed." |
| Saved analysis explanation | The family message | The family message | The family message |
| Analyze save | Unchanged combined message | Unchanged combined message | "The analysis could not be saved because something it depends on is missing or has changed." |
| Analyze publication check | "The analysis could not be saved because a selected document is no longer available or has changed." | "This analysis conversation is unavailable." (unchanged) | "The analysis could not be saved because something it depends on is missing or has changed." |
| Workflow progress | "Workflow progress is unavailable." followed by the family message | Same | Same |

The runner keys its text by the family's string value with a source default, so the 70 functional test files that compile the runner from source keep working without new names. Other `PermissionError` refusals keep their existing text: an explanation still says "This analysis is unavailable because access to its conversation or saved result could not be confirmed.", and workflow progress still says "Workflow progress is unavailable because current access could not be confirmed."

History placeholders no longer blame access confirmation:

- A saved analysis that can't be shown: "This saved analysis is unavailable because it or something it depends on is missing, has changed or can't be read right now."
- A saved workflow output that can't be shown: "Saved workflow output is unavailable because it or the workflow run it came from is missing, has changed or can't be read right now."

### Not changed

- The exception class, every code (except the two former bare raises above), every raise and catch site, HTTP statuses and response `code` values.
- Genuine source-authority messages: `content_screening/contracts.py`, and the orchestration plan input check in `route_backend_orchestration.py`.
- Code-based mappings that already used neutral text or closed codes: task result pages (409), execution history (409), activity streams, chat follow-up refusal codes, generated file output codes and orchestration failure codes. Their codes are shared with genuine access refusals, so their text can't vary by family without changing the code.
- Loop input and Repeat pauses whose text already said "no longer available or could not be verified".

## Validation

`functional_tests/test_analysis_unavailable_message_families.py`:

- Scans every `AnalysisResultUnavailable(...)` call in `application/single_app` and fails for a bare raise, an unclassified code, an unknown `family=` value, or a computed code without a reviewed resolution. It resolves the one computed code by walking the `WorkflowLoopInputError` codes that `reauthorize_workflow_loop_document` can raise.
- Pins the three `family=` overrides, keeps the frozensets disjoint, and checks each family's message and that no message mentions source access or promises a retry.
- Raises real input reads and binding checks to prove their codes and families, and that the renamed container codes keep every response code.
- Runs the real task sequence, through the shared inventory harness, for each family: a task that can't read its input and a result that can't be saved. Each records the family's message on the failed task.
- Posts to the chat routes through the shared Analyze harness: explanation, save and publication check return 403 with the family's message, and other refusals keep their old text.
- Checks the loop pause reasons and the history placeholders, and that no application file still says "source access could not be confirmed".

`functional_tests/test_workflow_durable_routes.py` checks that workflow progress names a failed saved record with the family message, and that a group membership refusal keeps its access message.

Against the unchanged 0.261.232 code, the new test file fails at import, because the family constants don't exist there. The old single message would fail every message check, and the five bare raises fail the scan.
