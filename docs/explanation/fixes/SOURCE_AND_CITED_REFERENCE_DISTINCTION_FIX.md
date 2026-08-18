# Retrieved Sources and Cited References Distinction Fix

## Header information

**Issue:** Retrieved document and web search results were presented as citations even when the final assistant response did not reference them.

**Root cause:** SimpleChat stored complete retrieval result arrays in `hybrid_citations` and `web_search_citations`, then reused those arrays for the per-message Sources disclosure, the Used documents drawer, conversation details, and export reference sections. The data model did not preserve a separate exact-citation subset.

Fixed/Implemented in version: **0.250.215**

Related config.py update: `VERSION = "0.250.215"`

Associated issue: `microsoft/simplechat#1249`

## Technical details

### Persisted contract

New assistant responses preserve both source and reference data:

| Field | Meaning |
|---|---|
| `hybrid_citations` | Every returned workspace document source |
| `web_search_citations` | Every returned web source |
| `agent_citations` | Tool and agent executions that occurred |
| `citation_tracking_version` | Indicates exact citation subsets are authoritative |
| `cited_hybrid_citations` | Returned document records matched by exact citation IDs, with strict filename/location matching for explicit legacy-style source references |
| `cited_web_search_citations` | Returned web records whose normalized URLs appear in the final response |

Conversation records persist `used_documents` for exact active-response usage and `legacy_used_documents` for pre-tracking compatibility. Normal metadata reads use these compact fields and do not reparse message history.

### Files modified

- `application/single_app/functions_citation_tracking.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/collaboration_models.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-citations.js`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/static/js/chat/chat-conversation-contents.js`
- `application/single_app/static/js/chat/chat-streaming.js`

### Code changes

- Exact `[#citation-id]` tokens are matched to returned document records after final response content is settled. Explicit `(Source: filename, Page/Sheet/Location: value)` references provide a strict fallback for response paths that omit the hidden ID.
- Final-response HTTP(S) URLs are normalized and matched to returned web records.
- Full source arrays remain unchanged for the per-message **Sources** disclosure and JSON audit output.
- The **Used documents** drawer reads exact active-response usage plus an explicit historical fallback.
- Conversation details continue to show all source documents and add a **Cited** badge only to exact tracked documents.
- Retry, edit, attempt switching, deletion, collaboration mirroring, workflow messages, and conversation forks maintain the exact used-document aggregate.
- Canceled/interrupted persisted responses update source metadata and notify active clients; collaboration stream bridges mirror persisted partial responses before returning the terminal error.
- Conversation Markdown/PDF and per-message Word/PowerPoint/email reference sections use cited document/web subsets plus executed tools. Foundry web-source proxy entries are represented once as web references rather than duplicated as tool references.
- Historical messages without a tracking version retain their previous broad export behavior.

### Testing approach

- `functional_tests/test_chat_cited_source_tracking.py` validates exact document IDs, normalized web URLs, immutable source arrays, aggregation, lifecycle rebuilds, collaboration propagation, UI contracts, and export selection.
- `functional_tests/test_conversation_export.py` validates that tracked reference appendices exclude retrieved-only document and web sources while JSON retains them.
- `functional_tests/test_per_message_export.py` and `functional_tests/test_per_message_powerpoint_export.py` validate the shared Word, email, and PowerPoint reference path.
- `ui_tests/test_chat_conversation_contents_drawer.py` validates strict Used documents selection and historical fallback.
- `ui_tests/test_chat_scope_lock_and_conversation_details_escaping.py` validates the full source inventory, exact Cited badge, and safe rendering.

### Impact analysis

- No Cosmos migration is required.
- Existing source links and enhanced citation behavior remain unchanged.
- New responses gain exact reference semantics.
- Historical conversations remain readable and keep their previous drawer/export behavior when exact data is unavailable.
- Ordinary metadata reads remain constant-time with respect to message history; message scans occur only after uncommon lifecycle mutations.

## Validation

### Before

- Every retrieved document could appear in **Used documents**.
- Conversation details could not distinguish cited documents from retrieved-only documents.
- Export reference sections could list every returned document and web result.

### After

- **Sources** remains the complete retrieval/execution disclosure.
- **Used documents** reflects cited documents in active responses, with an explicit legacy fallback.
- Conversation details list all source documents and mark exact citations.
- Reference-producing exports contain exact cited document/web records and executed tools.
- JSON exports preserve both complete source arrays and exact cited subsets.

### User experience improvement

Users can now tell what the model reviewed from what it actually cited, and exported references accurately represent the evidence visible in the generated response.
