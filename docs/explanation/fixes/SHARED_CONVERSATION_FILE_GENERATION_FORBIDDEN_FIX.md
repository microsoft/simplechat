# Shared Conversation File Generation "Forbidden" Fix

## Issue

In a shared (collaborative) conversation, a user who was invited into the conversation received:

```
Stream interrupted before any content was received.
Stream interrupted: Forbidden
```

The reported case was a participant asking `@Telemetry generate a csv of the 900 samples` in a
conversation shared from a personal chat. No content was returned at all.

- **Fixed in version:** **0.260.006**
- **Related feature:** `docs/explanation/features/SHARED_CONVERSATION_FILE_APPROVALS.md`

## Root Cause Analysis

A collaborative conversation is backed by a hidden **source conversation**
(`conversation_kind: 'collaboration_source'`, created in
`functions_collaboration.ensure_collaboration_source_conversation`) whose `user_id` is always the
shared conversation creator.

`/api/collaboration/conversations/<id>/stream` bridges into the internal `chat_stream_api` view
using that source conversation id, but keeps the **requesting participant's** session. Every
downstream owner-equality comparison therefore failed for participants.

Four separate gates were involved:

| # | Location | Check | Effect |
|---|----------|-------|--------|
| 1 | `route_backend_chats._authorize_personal_conversation_access`, called by `chat_stream_api` | `conversation_item.get('user_id') != user_id` | Returned `{'error': 'Forbidden'}, 403`. The collaboration bridge converts any `>= 400` response into a stream error, producing the reported banner. This blocked **all** AI invocation by participants, not just file generation. |
| 2 | `functions_simplechat_operations._upload_generated_chat_artifact_for_current_user` | `conversation.user_id != current_user_id` | Raised `PermissionError("Forbidden")` when persisting the artifact. `maybe_create_generated_file_output` swallowed it, so the file silently disappeared. |
| 3 | `functions_simplechat_operations._resolve_group_upload_target_for_current_user` | `assert_group_role(Owner/Admin/DocumentManager)` | Plain group `User` members could not save generated documents into a group workspace. |
| 4 | `route_enhanced_citations._get_authorized_chat_artifact_message` | `conversation.user_id != user_id` | Participants could not **download** a generated artifact even once it existed. |

Gate 1 explains why the failure looked file-specific: collaborative conversations default to
`ai_invocation_mode: 'explicit_only'`, so ordinary participant messages never reach the stream
bridge. The first explicit AI invocation was the first time the gate was hit.

Two secondary defects were found while fixing this:

- `assert_generated_chat_artifact_is_published_for_user` read the export run using the
  **caller's** id as the partition key. Background exports are queued by the participant while
  the owner may be the one downloading, so an approved large CSV would have been unreadable.
- `commit_generated_chat_artifact_publication_for_user` and
  `delete_generated_chat_artifact_for_user` carried the same owner-only comparison, which would
  have broken publication and rollback for participant-queued background exports. 900 rows
  exceeds the 500-row inline threshold, so the reported case used exactly this path.

Three further defects were caught in review of the approval gate itself and fixed before
merge:

- **Requester self-approval.** `resolve_generated_file_approver_role` resolved group-scope
  approvers purely by group role, so a group `Admin` or `DocumentManager` who was only a
  participant could stage a file and immediately approve it themselves. The requester check now
  runs before the scope branch.
- **Bypass via `/api/enhanced_citations/tabular`.** That route streams any blob-backed file
  message after a single conversation-ownership check and never consulted the approval gate. A
  plain group `User` who created a group shared conversation — explicitly not an approver — could
  fetch a staged CSV or XLSX directly. The gate now runs there before the blob is read, and the
  route returns `403` rather than `500` for a withheld file.
- **Truncation before authorization.** `list_pending_generated_file_approvals_for_user` applied
  `TOP @limit` across the whole messages container and filtered by approver afterwards in
  Python, so a tenant with more than 50 pending files could return an empty list to an approver
  who genuinely had items waiting. Candidates are now narrowed to the caller's own approval
  scopes inside the query.

## Technical Details

### Files modified

| File | Change |
|------|--------|
| `collaboration_models.py` | Added `COLLABORATION_SOURCE_KIND` and replaced the string literals |
| `functions_collaboration.py` | Added `is_collaboration_source_conversation`, `get_collaboration_conversation_for_source`, and `build_conversation_participation_context` |
| `route_backend_chats.py` | `_authorize_personal_conversation_access` now delegates to the collaboration-aware `_resolve_authorized_conversation_context` |
| `functions_simplechat_operations.py` | Artifact upload, publication commit, and rollback authorize through the participation context; artifact writes by participants are staged; run owner recorded for publication checks |
| `route_enhanced_citations.py` | Download authorizes participants and enforces the approval gate before the export manifest check |
| `functions_generated_file_approvals.py` | New module holding approval state and gating logic |
| `functions_notifications.py` | Added the three generated-file approval notification types |
| `functions_settings.py` | Added `require_shared_conversation_file_approval`, default `True` |
| `background_tasks.py` | Auto-deny sweep for expired staged files |
| `static/js/chat/chat-file-approvals.js` | New inline approval card |
| `static/js/chat/chat-messages.js` | Renders the approval card and suppresses downloads while staged |

### Key change

All five call sites of `_authorize_personal_conversation_access` now resolve access through a
single shared helper, which mirrors the pattern already used by chat file uploads in
`route_frontend_chats._resolve_chat_upload_context`:

```python
def build_conversation_participation_context(user_id, conversation_item):
    # Owners keep their existing behavior.
    if normalized_user_id and owner_user_id == normalized_user_id:
        return {..., 'is_owner': True}

    # Participants are authorized against the linked shared conversation instead.
    collaboration_conversation = get_collaboration_conversation_for_source(normalized_item)
    if not collaboration_conversation:
        raise PermissionError('You can only access your own conversations')

    collaboration_access = assert_user_can_participate_in_collaboration_conversation(
        normalized_user_id,
        collaboration_conversation,
    )
    return {..., 'is_owner': False}
```

Ordinary personal conversations with no collaboration link remain strictly owner-only.

### Testing approach

`functional_tests/test_shared_conversation_file_approval_fix.py` loads the approval module
against dependency stubs, because `config.py` connects to Cosmos DB at import time. The
authorization wiring for each gate is asserted against the real source using AST extraction, the
same technique used by `test_broken_access_control_findings_fix.py`.

Two existing tests that extract these functions via AST were updated to supply the new
dependency: `test_generated_artifact_lifecycle_authorization.py` and
`test_tabular_row_orchestration_scale.py`.

### Impact analysis

- Participants can now invoke the AI in shared conversations at all — the primary regression.
- Owners see no behavior change: `is_owner` short-circuits before any approval logic.
- Non-shared personal conversations are unchanged and remain owner-only.
- Downloads gain one extra check that runs before the existing publication assertion, so a
  staged file can never be retrieved.

## Validation

| Test | Result |
|------|--------|
| `functional_tests/test_shared_conversation_file_approval_fix.py` | 16/16 passed |
| `functional_tests/test_generated_artifact_lifecycle_authorization.py` | 6/6 passed |
| `functional_tests/test_tabular_row_orchestration_scale.py` | passed |
| `functional_tests/test_assistant_table_csv_artifact.py` | 35/35 passed |
| `functional_tests/test_generated_json_xml_exports.py` | 7/7 passed |
| `functional_tests/route_tests/` | 12/12 passed across three suites |

Pre-existing failures unrelated to this change and confirmed against a clean baseline:
`test_mixed_source_hardening.py` (one assertion), `test_tabular_generated_output_exports.py`
(stale exact-version assertions pinned to `0.241.144`), and any test requiring live Azure
credentials.

### Before and after

| Scenario | Before | After |
|----------|--------|-------|
| Participant asks the AI anything in a shared conversation | `Stream interrupted: Forbidden`, no content | Normal response |
| Participant asks for a CSV | Forbidden, or artifact silently dropped | File created, held for approval, approver notified |
| Owner approves | Not possible | File becomes downloadable for the conversation |
| Owner denies | Not possible | Stored file deleted, decision recorded in the card |
| Nobody responds | Not possible | Auto-denied after 3 days, blob deleted |
| Owner generates their own file | Worked | Unchanged |
