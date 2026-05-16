# Document Analysis

## Overview

Version: 0.241.023

Fixed/Implemented in version: **0.241.069**

Updated in version: **0.241.023**

Document Analysis adds a deterministic Analyze mode for workflows and chat. Instead of relying on bounded hybrid-search results, the feature targets fixed documents, walks every ordered page or chunk window, and returns a final answer with explicit coverage details.

Dependencies: personal workflows, chat streaming, ordered document retrieval in `functions_search_service.py`, and the shared executor in `functions_document_analysis.py`.

## Technical Specifications

Architecture overview:
The shared executor resolves structured document targets, builds ordered windows from stored chunks, runs the selected model or agent on every window, retries failed windows when configured, and reduces the window outputs into one final answer.

Workflow support:
Personal workflows now persist an `analyze` configuration with `document_ids`, `doc_scope`, scope hints for group or public workspaces, and optional windowing controls.

Chat support:
Chat exposes a dedicated Analyze entry point and routes those requests through `/api/chat/analyze/stream`, which reuses the same backend execution path as workflows.

Coverage output:
Final responses append a deterministic coverage section with total windows, processed windows, failed windows, retries, and per-document range information.

## Usage Instructions

How to enable/configure:
In the workspace workflow modal, enable `Document analysis selected documents`, provide fixed document ids or use the current workspace selection, and optionally tune window size, window percent, or retries.

User workflows:
Manual and scheduled workflows can now analyze the full contents of targeted documents without depending on the top search hits.

Interactive chat:
Open the workspace selector in chat, choose one or more documents, enable `Analyze`, and send the prompt you want applied across every page or chunk window.

Integration points:
The shared executor is implemented in `application/single_app/functions_document_analysis.py`, the workflow runner calls it through `functions_workflow_runner.py`, and chat reuses the same path from `route_backend_chats.py`.

## Testing And Validation

Test coverage:
`functional_tests/test_document_analysis_feature.py` verifies the shared executor, workflow storage and runner wiring, chat endpoints, and the workspace/chat entry points.

Performance considerations:
Document analysis is intentionally more expensive than bounded search because it processes every window for the targeted documents. It is opt-in and leaves the default chat and workflow behavior unchanged.

Known limitations:
Chat currently uses the default page-based windowing configuration for the interactive analysis entry point. Workflow configuration exposes the more advanced window controls.