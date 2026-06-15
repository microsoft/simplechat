# Assigned Knowledge Task Context Split Fix (v0.241.207)

Version: 0.241.207

Fixed/Implemented in version: **0.241.207**

Related config.py version update: `application/single_app/config.py` now sets `VERSION = "0.241.207"`.

## Issue Description

Assigned knowledge and user-uploaded task documents could be treated too similarly in chat workflows. In public/global agent flows, this could cause the agent to answer from assigned knowledge while a newly uploaded task document was still being indexed, or require the user to manually select Analyze even though the uploaded document was already linked to the conversation.

## Root Cause Analysis

- Assigned knowledge was primarily wired through the normal workspace search path.
- Analyze and Compare executed against selected document IDs, but did not automatically search assigned knowledge as agent reference context.
- Normal Search could continue with assigned knowledge only when a conversation-linked upload existed but was not search-ready yet.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_upload_personal_workspace_handoff.py`

### Code Changes Summary

- Added a top-12 assigned-knowledge reference search helper for agent document actions.
- Enriched Analyze and Compare prompts with assigned-knowledge reference excerpts without adding assigned knowledge documents to the task document IDs.
- Added assigned-knowledge context citations to document-action responses.
- Added a backend pending-upload guard for normal and streaming Search so an agent cannot answer from assigned knowledge alone while uploaded task documents are still processing.
- Preserved user-selected and conversation-linked uploads as the task document corpus.

### Testing Approach

- Updated the chat upload handoff functional source-contract test to validate the assigned-knowledge/task-document split.
- Added assertions for fixed top-12 assigned-knowledge search, prompt enrichment, citation merging, task-document hint usage, and pending-upload Search blocking.

## Impact Analysis

- Public/global agents can use public assigned knowledge as reference context while analyzing or comparing uploaded personal task documents.
- Assigned knowledge remains agent context by default, not an implicit task document selection.
- Users receive a clear processing response when they upload a document and ask the agent to use it before indexing is complete.

## Validation

Expected validation commands:

```powershell
python -m py_compile application/single_app/route_backend_chats.py functional_tests/test_chat_upload_personal_workspace_handoff.py
python functional_tests/test_chat_upload_personal_workspace_handoff.py
```

Before this fix, an agent could fall back to assigned knowledge and say uploaded document text was unavailable. After this fix, assigned knowledge is searched as reference context, uploaded/selected documents remain task documents, and pending uploads produce an explicit processing response.