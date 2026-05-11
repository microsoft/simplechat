# Assistant Citation Artifact Storage Fix

Fixed/Implemented in version: **0.240.013**

Related config.py update: `VERSION = "0.240.013"`

## Issue Description

Large tool-backed chat responses could exceed Azure Cosmos DB item limits because the assistant message document stored the final answer together with full raw agent citation payloads, including large tabular result sets.

## Root Cause Analysis

- The primary `messages` container stores assistant replies as a single item partitioned by `conversation_id`.
- Assistant documents embedded full `agent_citations` payloads directly on the main message record.
- Tabular tool citations could include large `function_result` payloads with many returned rows, so several successful tabular calls could push a single assistant message over Cosmos DB's 2 MB per-item limit.

## Technical Details

### Files Modified

- `application/single_app/functions_message_artifacts.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/route_frontend_conversations.py`
- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/config.py`
- `functional_tests/test_assistant_citation_artifact_storage.py`

### Code Changes Summary

- Added dedicated helper functions for compacting agent citations, storing full raw citation payloads as linked assistant artifact records, and rehydrating those payloads for exports.
- Updated both the regular chat route and the streaming chat route to persist compact `agent_citations` on the assistant message while moving the full raw citation payloads into child records in the same conversation partition.
- Removed the duplicate `user_message` field from assistant message documents to reduce message size further.
- Excluded assistant artifact records from visible chat history and summary assembly so they do not pollute normal conversation transcripts.
- Updated message deletion to cascade into child records linked through `parent_message_id`, which also prevents orphaned assistant artifact records.
- Updated conversation export hydration so exported assistant messages can still include the preserved raw citation payloads.

### Testing Approach

- Functional regression: `functional_tests/test_assistant_citation_artifact_storage.py`

## Validation

### Before

- Assistant messages embedded full raw agent citation payloads directly in the main chat item.
- Large tabular citation results could make the final assistant message exceed Cosmos DB item limits.
- Export and chat history logic had no dedicated concept of linked assistant-side artifact records.

### After

- Assistant messages store compact citation summaries with linked artifact references.
- Full raw citation payloads are preserved in linked child records rather than on the main assistant message.
- Chat history and summarization exclude the assistant artifact records, while export logic can rehydrate the full raw payloads from those linked records.