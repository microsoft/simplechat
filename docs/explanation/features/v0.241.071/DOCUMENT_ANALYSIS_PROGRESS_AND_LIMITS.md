# Analyze Progress And Limits

## Overview

Version: 0.241.023

Fixed/Implemented in version: **0.241.071**

Updated in version: **0.241.023**

This enhancement adds live analysis progress feedback in chat and formalizes per-surface document limits. Chat now shows an overall progress bar plus per-document progress cards while analysis is running, and the product now caps interactive chat analysis at 3 documents while workflows can analyze up to 10 documents per run.

Dependencies: `functions_document_analysis.py`, `route_backend_chats.py`, `chat-thoughts.js`, `chat-messages.js`, `workspace_workflows.js`, and the existing shared workflow executor.

## Technical Specifications

Architecture overview:
The shared analysis service now pre-resolves targeted documents, tracks chunk and window completion state, and emits structured progress snapshots through its activity callback. The chat streaming endpoint forwards those progress events through the existing background SSE bridge, and the chat thought renderer converts them into Bootstrap progress cards.

Document limits:
Interactive chat analysis is limited to 3 selected documents for responsiveness. Personal workflows allow up to 10 documents so users can run larger deterministic analyses asynchronously.

Progress model:
Progress snapshots report overall and per-document counts for completed windows, chunks, failed windows, retries, and current status text. This keeps users informed during long-running analyses without waiting for the final response.

## Usage Instructions

Interactive chat:
Select up to 3 documents in chat, enable `Analyze`, and send your prompt. The streaming thought area will update with an overall bar and one row per selected file while the analysis is running.

Workflows:
Use workflows when you need to analyze more than 3 documents. Workflow configuration continues to allow fixed document targeting and now rejects configurations above 10 documents.

User guidance:
If a user selects more than 3 documents in chat, the UI and backend both return a message directing them to workflows for larger analysis sets.

## Testing And Validation

Functional coverage:
`functional_tests/test_document_analysis_progress_and_limits.py` verifies shared progress snapshots, streamed chat progress wiring, and chat/workflow document limit enforcement.

UI coverage:
`ui_tests/test_chat_document_analysis_thought_progress.py` validates that the streaming thought placeholder renders overall and per-document progress bars from a structured analysis progress event.

Performance considerations:
Progress updates are lightweight structured thought events and reuse the existing streaming bridge. The chat limit keeps the live experience responsive while workflows absorb larger analysis workloads.