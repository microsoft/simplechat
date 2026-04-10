# AGENT TOOL CITATION FULL RESULTS FIX

Fixed/Implemented in version: **0.240.048**

Related config.py update: `VERSION = "0.240.048"`

## Header Information

- Issue description: Agent tool citations in chat showed a compact tabular summary with sample rows and truncated cell values, which made it difficult for users to verify whether the tool actually returned the correct rows.
- Root cause analysis: The chat message stored a compact agent citation payload for performance, but the normal citation modal only rendered that compact payload and never hydrated the full raw artifact that was already persisted alongside the assistant message.
- Version implemented: 0.240.048

## Technical Details

- Files modified: `application/single_app/route_frontend_conversations.py`, `application/single_app/static/js/chat/chat-messages.js`, `application/single_app/static/js/chat/chat-citations.js`, `application/single_app/config.py`, `functional_tests/test_agent_citation_full_results_modal.py`, `ui_tests/test_agent_citation_modal_full_results.py`
- Code changes summary: Added a lazy conversation-scoped endpoint that returns the raw stored agent citation artifact on demand. Updated the chat citation buttons to carry artifact metadata, and changed the agent citation modal to fetch the raw payload when opened.
- User-facing behavior: Tabular tool results now open with a short preview, can expand to 25 rows, and can then show all returned rows when more than 25 were returned by the tool call.
- Testing approach: Added source-level regression coverage for the lazy artifact endpoint and row controls, plus a UI test that validates preview, 25-row, and full-row expansion in the browser.

## Validation

- Test results: Focused functional and UI coverage validate the new full-result hydration flow and the row expansion controls.
- Before/after comparison: Before the fix, the citation modal only exposed the compact sample payload. After the fix, opening the citation loads the raw stored payload and lets the user inspect the entire returned row set.
- User experience improvements: Users can verify tabular tool outputs directly from the citation modal without losing important rows to sample-only truncation.