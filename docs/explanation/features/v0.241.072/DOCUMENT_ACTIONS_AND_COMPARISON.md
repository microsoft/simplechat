# Document Actions And Comparison

Version: 0.241.072

Fixed/Implemented in version: **0.241.072**

Dependencies: `functions_document_actions.py`, `functions_document_comparison.py`, `functions_workflow_runner.py`, `route_backend_chats.py`, `static/js/chat/chat-messages.js`, `static/js/workspace/workspace_workflows.js`

## Overview

This feature turns analysis into a generic backend document action model and adds deterministic document comparison on top of the same ordered retrieval path.

Chat and workflows now use the same action shape:

- `none` for standard prompt runs
- `analyze` for full ordered review across fixed documents
- `comparison` for one-left-to-many-right comparison runs

## Technical Specifications

The backend now normalizes shared document action payloads in `functions_document_actions.py`, including scope hints, ordered window settings, retries, and target documents.

Comparison is implemented in `functions_document_comparison.py` as a backend action, not as a plugin. The service:

- builds full analysis summaries for the left document and each right-side document
- compares each right document against the left baseline
- reduces multiple pairwise comparisons into one final response when needed
- preserves coverage and progress reporting through the existing thought stream model

Workflow execution and chat execution both dispatch through the shared document action runner in `functions_workflow_runner.py` and `route_backend_chats.py`.

## Usage Instructions

In chat, choose an action from the `Action` selector beside document selection.

- `Search Documents` keeps the normal prompt flow while searching the selected documents for relevant context.
- `Analyze` reviews every ordered page or chunk from the selected documents.
- `Compare Documents` treats one selected document as the left baseline and compares every other selected document against it.

In workflows, choose `Action Type` in the workflow modal.

- `Analyze` accepts a fixed list of document ids.
- `Compare Documents` accepts one left document id and one or more right document ids.
- Chat currently caps document actions at 3 documents and workflows cap them at 10 documents.

## Testing And Validation

Coverage for this feature includes:

- functional wiring tests for the shared document action model and comparison service
- updated analysis regression tests for the new shared action routes and selectors
- a UI workflow modal test that verifies comparison payload submission

Known limitation:

- comparison currently supports one-left-to-many-right only; many-to-many comparison is not part of this version.