# Upload-Only Content Screening

## Overview

Content screening checks a document when it enters a workspace, and then trusts what is built from it. Screening covers documents that arrive by user upload or File Sync. It does not check, or check again, anything generated from those documents.

Earlier versions also re-checked every result produced from a screened document against that document, both when the result was saved and each time it was read. These results included saved Analyze results, orchestration and workflow outputs, generated files, chat replies and their citations, history and exports. A single deleted, re-uploaded or re-screened document, an access change, or even a failed lookup could hide a result that had already been produced. This happened even when screening was off. Chat history replaced a whole AI reply with "Source content is unavailable pending document screening and review." Saved Analyze results and orchestration files were withheld.

**Implemented in version: 0.261.232.** This version completes a stack of changes that began in 0.261.229. Application version tracking remains in `application\single_app\config.py`.

**Related issue:** [#1621](https://github.com/microsoft/simplechat/issues/1621). Layer 1 also fixes [#1613](https://github.com/microsoft/simplechat/issues/1613).

**Dependencies:**

- The [content screening framework](CONTENT_SCREENING_FRAMEWORK.md): policies, holds, review and release proof.
- The existing conversation, orchestration-run and workflow records, which now decide who can open a saved result.
- The `content_screening\access.py` read boundary, which still performs the input check.

## The model

### What is screened

- Documents that users upload to personal, group and public workspaces.
- Files attached in chat. They are saved into the user's workspace as `chat_upload` documents, so they count as user uploads.
- Documents that File Sync brings in.

Any other way in is screened by default unless it is explicitly marked as generated. Layer 2 adds that marker.

### What is never checked

The following content is not screened when it is created, and it is not checked again when it is read:

- Model replies, including the citation excerpts stored with them.
- Analyze, orchestration and workflow results.
- Generated and merged files, including exports.
- Files that an agent, workflow or orchestration saves or publishes into a workspace (layer 2).
- Model-generated metadata and user edits to metadata (layer 2).

The source lists recorded with each result are still stored. They are provenance: they tell a reader where the result came from. They are not an access check.

### Where saved results get their access

| Result | Who can open it |
| --- | --- |
| Chat AI replies, their stored citations, tool results and conversation exports | Anyone who can open the conversation: its owner, or a participant in a shared conversation. |
| Saved Analyze results from chat, and the generated files projected from them | Anyone who can open the conversation that holds the result. |
| Orchestration retained results, rendered files and orchestration Analyze results | The conversation owner, while the orchestration run that produced them still exists. |
| Workflow results and saved workflow outputs | Anyone with access to the workflow and its run (layer 3a). |

The container checks are unchanged. If a container check fails, the result is refused. Examples: a reader who is not the conversation owner or a participant; an orchestration run that was deleted; a generated file that is not yet approved or published.

Lineage and integrity checks are unchanged. A result whose identity, hashes or references don't match is refused. So is a stale browser reference to a result that has since changed. A saved Analyze result whose recorded source list is missing fails as a lineage error.

### The one input check

When chat, search or an orchestration reads an uploaded document as an input, two conditions apply: the reader must still be able to open the document, and the document must not be held for screening. This check applies to:

- search retrieval (`filter_available_results`)
- document selection, including chat uploads selected for a document action (`_resolve_conversation_task_documents`)
- file bytes and previews (`read_available_document_bytes`)
- opening a cited document (`get_document` in `route_enhanced_citations.py`)
- workspace attachments shown in chat history (`refresh_workspace_attachment`)
- orchestration and Analyze steps that read documents themselves (`resolve_orchestration_source_manifest`, `read_orchestration_source_metadata`, `verify_orchestration_input_sources`, `OrchestrationResultAccess.authorize_input_sources`)
- the input guards in document analysis and comparison

Version checks still protect a read that is in progress. These include resuming an Analyze checkpoint partway through a document, a later step of the same orchestration run reading sources an earlier step named, and finalizing a run whose selected documents changed while it ran.

A follow-up can read documents that an earlier orchestration run's result named. That read is a normal input check against the current document. A newer version is not an error: the step reads the current version.

### The model fence

The model fence is unchanged. It consists of `strict_source_authority`, `guard_model_callable`, `assert_current_request_sources_available` and `_remember_screening_failure`. When an input read in a request or orchestration step finds a held or inaccessible document, the fence blocks every later model call in that operation, even if the caller caught the error.

Only input reads can trip the fence now. Replaying stored replies and citations into model history, reading retained orchestration results, and reading saved Analyze results never record a failure.

The same rule applies when a chat request or an orchestration run publishes its answer. Before the answer is saved, the documents that request or run read are confirmed again. If one of them was held or became inaccessible while the work was still running, the answer is not published. A newer version of a document that the run already read does not block publication.

## Technical specifications

### Changes in 0.261.232 (layer 3b)

| Area | File | Change |
| --- | --- | --- |
| History | `content_screening\access.py` | `public_history_messages` never replaces assistant or tool content or stored citations. It refreshes only workspace-backed file and image messages, which are input reads. Generated-file messages keep their container checks through `sanitize_generated_artifact_history`. |
| Chat | `route_backend_chats.py` | Model history no longer re-checks stored replies, prior tool results or citations. Agent citations produced in the current turn are still checked. Saved-analysis follow-up and save errors name the conversation, not source access. |
| Saved Analyze | `functions_saved_analysis.py` | Save and read paths for chat and orchestration results check the container and lineage only. The recorded sources become provenance (`source_snapshot_changed` is always false). |
| Orchestration | `functions_orchestration_results.py`, `functions_orchestration_source_access.py` | Retained results check the producer, conversation and run, lineage, and external sources. They never read workspace sources. `authorize_orchestration_sources` becomes `verify_orchestration_input_sources`, and `authorize_sources` becomes `authorize_input_sources`. Both are used only when a step reads documents. |
| Orchestration | `functions_orchestration_executor.py` | Sources named by an earlier run or attempt are read at their current version after the input check. Sources named earlier in the same attempt must still match. |
| Generated files | `route_enhanced_citations.py`, `functions_generated_artifact_sources.py`, `functions_orchestration_output_store.py` | Downloads, history and promotion check the conversation, approval, publication and destination. A workspace-linked chat file still reads its workspace document as an input. |
| Exports | `functions_tabular_generated_exports.py`, `route_backend_conversation_export.py` | Tabular exports no longer check `screening_sources`. Conversation exports inherit the history split through `public_history_messages`. |
| V2 | `OrchestrationOutputs.tsx` | The unavailable-file note no longer blames the file's sources. |

### Public messages

| Situation | Message |
| --- | --- |
| A saved Analyze follow-up cannot confirm the conversation or saved result | "This analysis is unavailable because access to its conversation or saved result could not be confirmed." |
| An Analyze result cannot be saved | "The analysis could not be saved because this conversation or a selected document is no longer available." |
| A generated orchestration file cannot be opened | "This file is unavailable because access to its conversation could not be confirmed." |
| A chat artifact download is refused | "You no longer have access to this artifact." |

### Configuration

There are no new settings. `enable_content_screening` and `enable_content_screening_workspace_uploads` keep their meaning. The chat input and output checks (`enable_content_screening_chat_input` and `enable_content_screening_chat_output`) are unchanged and stay off by default.

## Usage

Administrators have nothing to configure. The change applies when the stack is deployed.

What users see:

- A document that is held, deleted or re-uploaded after it was used no longer hides anything built from it. Replies, citation excerpts, saved Analyze results, explanations, orchestration files and exports stay available to everyone who can open their conversation, run or workflow.
- The held document itself is still refused as an input. Search skips it, and selecting it for a document action is refused. Opening the cited document or downloading its bytes returns the screening hold. A workspace attachment in history shows "Source content is unavailable pending document screening and review." until review completes.
- **Ask about this analysis** explains the saved result without reading the original documents. To review the current version of a document, run a new Analyze on it.

Example: a user analyzes a contract, and a reviewer later holds the contract after a policy change. The saved findings, their evidence and the generated CSV stay available in the conversation. A new search in the same conversation no longer returns the contract. Selecting it for a new Analyze is refused until review completes.

## Accepted trade-offs

- **Results are visible to anyone who can see their container**, even without access to the source documents. In a shared conversation, every participant sees the AI replies and their stored citation excerpts. Opening the full cited document still requires access. Group workflows can only read group documents, so group results stay within the group.
- **Nothing is withdrawn after the fact.** Deleting, rejecting or re-screening a document does not remove results already generated from it. There is no data migration. Results that earlier versions withheld when they were read become visible again.
- **Model-written content and metadata are not screened.** This includes web or M365 text that an agent, workflow or orchestration saves as a workspace file, model-generated metadata, and user edits to metadata.

## Delivery

Layer 1 merges first. Layers 2, 3a and 3b each target layer 1 and can merge in any order after it; whichever merges later resolves the `VERSION` and release-notes conflict.

| Layer | Version | Scope | Pull request |
| --- | --- | --- | --- |
| 1 | 0.261.229 | Run history and task output stop re-checking workflow run sources (fixes #1613). | [#1628](https://github.com/microsoft/simplechat/pull/1628) |
| 2 | 0.261.230 | Intake and metadata: generated documents skip screening, and metadata edits no longer put a cleared document back on hold. | [#1629](https://github.com/microsoft/simplechat/pull/1629) |
| 3a | 0.261.231 | Workflow saved results take their access from the workflow and run. | Targets layer 1 |
| 3b | 0.261.232 | Chat, Analyze, orchestration, generated files, history and exports (this document). | Targets layer 1 |

Shared source-check helpers that layer 1's workflow code still calls, such as `authorize_analysis_sources`, stay in place in 3b. Removing the leftovers is a small follow-up after 3a and 3b both merge.

## Testing and validation

`functional_tests\test_saved_results_container_access_chat_orchestration.py` proves:

- Deleting, re-uploading or holding a source document, before or after the result was saved, does not hide saved Analyze results, their pages, evidence, explanations, history or generated projections. The source resolver is never called.
- Retained orchestration outputs read every record after a restart with no source reads.
- Chat AI replies and their stored document and tool citations stay in history and in conversation exports.
- Generated chat files take their conversation's access.
- A held uploaded document is still refused by search retrieval, chat-upload document selection, opening a cited document, file bytes, a workspace-linked chat file, a workspace attachment in history, and an orchestration input read.
- Replaying stored replies leaves the model fence open. A held input read closes it, both in a request and in a headless strict scope.
- Container failures (a lost conversation, a deleted run) and integrity failures (stale digests, mismatched identities, missing source lists, uncommitted or corrupted manifests) are still refused.

Running the new test with the application changes stashed produces 25 failures, which shows that the test detects the old behavior.

`test_orchestration_internal_analysis.py` covers follow-ups that read sources named by an earlier run at their current version, and still refuses held or revoked inputs. The rewritten tests keep their container, integrity and input cases. They include `test_saved_analysis_*.py`, `test_analysis_saved_source_access.py`, `test_analysis_artifact_publication.py`, `test_analyze_backend_saved_integration.py`, `test_content_screening_history.py`, `test_content_screening_read_boundaries.py`, `test_chat_artifact_download_bytes.py` and `test_orchestration_*`.

**Performance:** reading a saved result no longer resolves every source document's metadata, permissions and release proof. History no longer reads documents for every stored reply. Each read therefore makes fewer Cosmos calls.

**Known limitations:** bytes that were already downloaded and requests already sent to a model cannot be recalled. A screening hold applies only to later input reads of the held document.
