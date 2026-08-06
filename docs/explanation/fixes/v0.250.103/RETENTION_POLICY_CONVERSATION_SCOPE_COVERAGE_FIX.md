# Retention Policy Conversation Scope Coverage Fix

## Header Information

- **Issue:** [#1054](https://github.com/microsoft/simplechat/issues/1054)
- **Fixed in version:** **0.250.103**
- **Area:** Conversation retention for personal, group, and collaborative chats

### Issue Description

Conversation retention previously inferred policy ownership from the Cosmos container. That no longer matched the conversation storage model: current private group conversations live in `conversations`, collaborative conversations live in `collaboration_conversations`, and legacy group conversations remain in `group_conversations`.

### Root Cause

The retention query selected personal records only by `user_id` and group records only by `group_id` in the legacy group container. It did not account for conversation type, collaboration scope, collaboration creator, the `updated_at` activity field, or hidden source records created during conversation conversion.

## Technical Details

### Policy Ownership Matrix

| Conversation type | Storage | Governing policy | Activity field |
|---|---|---|---|
| Personal single-user | `conversations` | Creator's personal policy | `last_updated` |
| Group single-user | `conversations` | Primary group's policy | `last_updated` |
| Personal multi-user | `collaboration_conversations` | Creator's personal policy | `updated_at` |
| Group multi-user | `collaboration_conversations` | `scope.group_id` policy | `updated_at` |
| Legacy group | `group_conversations` | Group policy | `last_updated` |

Converted source records linked through `collaboration_conversation_id` are excluded from independent policy selection. The collaboration cleanup removes the linked source record, preventing duplicate deletion and counting.

### Files Modified

| File | Change |
|---|---|
| `application/single_app/functions_retention_policy.py` | Selects all conversation shapes under the correct personal or group policy, validates activity timestamps, excludes converted sources, and dispatches cleanup by storage type. |
| `application/single_app/functions_collaboration.py` | Adds retention-aware collaboration cleanup for archival, messages, user state, linked sources, thoughts, blob-backed files, activity logs, race handling, and cache invalidation. |
| `application/single_app/functions_group.py` | Persists both new-group retention values as `"default"`. |
| `application/single_app/functions_simplechat_operations.py` | Adds strict blob cleanup mode so retention stops safely when generated files cannot be removed. |
| `application/single_app/functions_thoughts.py` | Adds strict thought cleanup mode so retention can preserve source metadata for retry after a dependency failure. |
| `functional_tests/test_retention_policy_conversation_scope_coverage.py` | Covers the policy matrix and cleanup side effects. |
| `application/single_app/config.py` | Updates the application version to `0.250.103`. |

### Cleanup Behavior

- Destructive retention removes collaboration messages, per-user state, linked personal or legacy group sources, linked source messages, thoughts, and blob-backed generated files.
- Archival retention copies collaboration and linked source conversations/messages into the existing archive containers before deleting active records.
- Personal collaboration deletion revokes automatic chat-upload document sharing.
- Conversation-list caches are invalidated for the collaboration participants and linked source owner.
- Missing or malformed activity timestamps are skipped.
- Already-deleted records are treated as successful race outcomes instead of retention failures.
- Standard and collaboration records are reread immediately before cleanup; records whose activity timestamp or governing scope changed after selection are skipped.
- Dependency cleanup failures leave the live conversation and its record metadata available for a later retention retry.

### Compatibility

Existing groups without a `retention_policy` object continue to resolve missing values through organization defaults. Only newly created groups persist the intended explicit `"default"` state.

## Validation

### Test Coverage

`functional_tests/test_retention_policy_conversation_scope_coverage.py` verifies:

- Every row in the conversation policy matrix.
- Explicit custom values, organization defaults, and `none`.
- Old, new, missing, null, non-string, and malformed timestamps.
- Converted source deduplication.
- Destructive cleanup and archival cleanup.
- Blob-backed file cleanup, user-state removal, linked-source removal, thought cleanup, activity logging, and cache invalidation.
- Already-deleted race handling.
- Concurrent activity revalidation and cleanup-failure preservation.
- Explicit defaults on newly created groups.

### Before and After

| Scenario | Before | After |
|---|---|---|
| Private group conversation | Processed by personal policy | Processed only by primary group policy |
| Personal collaboration | Not processed | Processed by creator's personal policy |
| Group collaboration | Not processed | Processed by scoped group policy |
| Converted source | Could be selected independently | Removed only through collaboration cleanup |
| Invalid activity timestamp | Container query determined behavior | Parsed and skipped safely |
| New group defaults | Missing from stored group document | Both values persisted as `"default"` |

### User Experience

Administrators can rely on configured personal and group retention periods across current and legacy conversation models. Shared conversations no longer remain indefinitely, and private group conversations no longer follow a creator's personal retention setting.
