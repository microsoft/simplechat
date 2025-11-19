# Group Agent Conversation Metadata Fix (v0.233.161)

## Summary
- **Issue:** Group agent conversations were not flagged as group chats when no documents were retrieved, leaving the UI without the expected group badges.
- **Root Cause:** Conversation metadata never promoted agent-provided group information into the primary context, so `chat_type` stayed unset.
- **Fixed/Implemented in version:** **0.233.161**
- **Related configuration:** `config.py` (`VERSION`)

## Technical Details
- **Files modified:**
  - `application/single_app/functions_conversation_metadata.py`
  - `application/single_app/route_backend_chats.py`
  - `application/single_app/config.py`
- **Key changes:**
  - Accept detailed agent metadata when collecting conversation metadata.
  - Promote group agent context to the primary context (and `chat_type`) when no documents are in play.
  - Ensure the metadata call site forwards agent selection details and bump the global version.
- **Tests added:**
  - `functional_tests/test_group_agent_conversation_metadata_fix.py`

## Validation
- **Automated tests:** `functional_tests/test_group_agent_conversation_metadata_fix.py`
- **Manual verification:** Select a group agent, send a prompt without attaching documents, and confirm the chat header shows `group - <GroupName>` alongside the single-user badge.
