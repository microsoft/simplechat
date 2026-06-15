# Chat Upload Personal Workspace Isolation Fix (v0.241.208)

Version: 0.241.208

Fixed/Implemented in version: **0.241.208**

Related config.py version update: `application/single_app/config.py` now sets `VERSION = "0.241.208"`.

## Issue Description

The assigned-knowledge task context split introduced a risky route-level search shape for upload-first agent chats. When a public/global agent had public assigned knowledge and the user uploaded a personal task document, the route could merge assigned public document IDs with the uploaded task document IDs and activate a broad user-context search.

## Root Cause Analysis

- Assigned knowledge document IDs and user task document IDs were temporarily combined before normal Search built its search arguments.
- Auto-linked uploads could produce an `all`-scope user-context search instead of a narrow current-user personal task-document search.
- The assigned/user-context merge accepted personal-looking results without requiring the result `user_id` to match the current user.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_upload_personal_workspace_handoff.py`

### Code Changes Summary

- Kept assigned knowledge document IDs out of the auto-linked upload task-document merge.
- Preserved assigned knowledge as a separate top-12 reference search.
- Disabled shared personal document expansion for auto-linked upload Search paths.
- Required appended personal user-context search results to have `user_id` matching the current user.
- Applied the same isolation in normal and streaming chat Search.

### Testing Approach

- Extended the chat upload handoff functional source-contract test with assertions for task/assigned ID separation, current-user personal-result filtering, and shared personal search disabling.

## Impact Analysis

- Public/global agents can still use public assigned knowledge as reference context.
- Uploaded personal task documents remain usable for Search and Analyze.
- Auto-linked upload Search can no longer broaden into other users' personal workspace documents.

## Validation

Expected validation commands:

```powershell
python -m py_compile application/single_app/route_backend_chats.py functional_tests/test_chat_upload_personal_workspace_handoff.py
python functional_tests/test_chat_upload_personal_workspace_handoff.py
```