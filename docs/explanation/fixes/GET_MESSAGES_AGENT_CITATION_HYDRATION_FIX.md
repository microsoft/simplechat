# GET MESSAGES AGENT CITATION HYDRATION FIX

Fixed/Implemented in version: **0.241.116**

Related config.py update: `VERSION = "0.241.116"`

## Header Information

- Issue description: Historical chat loads could fall back to compact agent citation payloads, leaving large JSON-style tool results truncated to the preview data stored on the assistant message.
- Root cause analysis: The active `/api/get_messages` route filtered assistant artifact child records out of the message query before rebuilding the artifact payload map, so it never rehydrated externalized agent citations for the legacy chat loader.
- Version implemented: 0.241.116

## Technical Details

- Files modified: `application/single_app/route_backend_conversations.py`, `application/single_app/config.py`, `functional_tests/test_get_messages_agent_citation_hydration.py`
- Code changes summary: Updated `/api/get_messages` to build the assistant artifact payload map before filtering assistant artifact records and then rehydrate visible agent citations from that map before image hydration runs.
- Testing approach: Added a focused functional regression test that checks the legacy route imports the artifact helpers and applies them in the correct order.

## Validation

- Test results: Focused source-level regression coverage verifies the artifact map is built before filtering and that the visible messages are hydrated afterwards.
- Before/after comparison: Before the fix, the active chat history loader returned compact citation payloads that could stop at the five-item preview stored on the assistant message. After the fix, the loader restores the full externalized citation payload for frontend rendering.
- User experience improvements: Large agent citation results remain inspectable after reloading or reopening conversations instead of collapsing back to compact preview JSON.