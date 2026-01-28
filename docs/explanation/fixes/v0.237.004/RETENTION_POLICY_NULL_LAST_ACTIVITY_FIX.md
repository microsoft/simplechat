# Retention Policy Null Last Activity Fix

## Version: 0.237.004

## Problem Statement

The retention policy execution was incorrectly deleting brand new conversations that had null or undefined `last_activity_at` fields. Users reported that conversations created just minutes or hours ago were being deleted when the retention policy ran, even with a 730-day (2 year) retention period configured.

### Symptoms
- New conversations deleted unexpectedly after retention policy execution
- Deleted conversations had `last_activity_at: None` in the archived records
- Error logs showed: `name 'cosmos_public_conversations_container' is not defined` for public workspaces

### Example
A conversation created at `2026-01-26T20:16:50` was deleted despite a 730-day retention period because it had `last_activity_at: None`:

```json
{
    "id": "3e137eed-cfe0-4ce4-a011-cf285e20fbc7",
    "last_updated": "2026-01-26T20:16:50.590604",
    "last_activity_at": null,
    "title": "sumamrize https://academy.faa....",
    "archived_at": "2026-01-26T21:22:47.746434+00:00",
    "archived_by_retention_policy": true
}
```

## Root Cause Analysis

### Issue 1: Flawed Query Logic

The original SQL query in `delete_aged_conversations()` had this logic:

```sql
WHERE c.{partition_field} = @partition_value
AND (NOT IS_DEFINED(c.last_activity_at) 
     OR IS_NULL(c.last_activity_at)
     OR (IS_DEFINED(c.last_activity_at) AND NOT IS_NULL(c.last_activity_at) AND c.last_activity_at < @cutoff_date))
```

This query translated to: **Delete if `last_activity_at` is undefined OR null OR older than cutoff.**

The problem: Conversations with null/undefined `last_activity_at` were being deleted **regardless of their actual age**. The intent was likely to handle edge cases, but it had the opposite effect—treating "no activity date" as "infinitely old."

### Issue 2: Missing Public Conversations Container

The code referenced `cosmos_public_conversations_container` for public workspace retention, but this container doesn't exist. Public workspaces only have:
- `cosmos_public_documents_container`
- `cosmos_public_prompts_container`
- `cosmos_public_workspaces_container`

There is no separate conversations container for public workspaces.

## Solution Implementation

### Fix 1: Corrected Query Logic

**File Modified**: `functions_retention_policy.py`

Changed the query to only delete conversations that have a **valid, non-null** `last_activity_at` that is older than the cutoff:

```python
# Query for aged conversations
# ONLY delete conversations that have a valid last_activity_at that is older than the cutoff
# Conversations with null/undefined last_activity_at should be SKIPPED (not deleted)
# This prevents accidentally deleting new conversations that haven't had activity tracked yet
query = f"""
    SELECT c.id, c.title, c.last_activity_at, c.{partition_field}
    FROM c
    WHERE c.{partition_field} = @partition_value
    AND IS_DEFINED(c.last_activity_at) 
    AND NOT IS_NULL(c.last_activity_at)
    AND c.last_activity_at < @cutoff_date
"""
```

**Logic Change**:
- Before: Delete if null/undefined OR older than cutoff
- After: Delete ONLY if valid date AND older than cutoff

### Fix 2: Removed Public Workspace Conversation Processing

**File Modified**: `functions_retention_policy.py`

Replaced the conversation processing block for public workspaces with a comment explaining why it's skipped:

```python
# Note: Public workspaces do not have a separate conversations container.
# Conversations are only stored in personal (cosmos_conversations_container) or 
# group (cosmos_group_conversations_container) workspaces.
# Therefore, we skip conversation processing for public workspaces.
# Only documents are processed for public workspace retention.
```

## Files Modified

| File | Changes |
|------|---------|
| `config.py` | Version updated to `0.237.004` |
| `functions_retention_policy.py` | Fixed query logic (line ~528), removed public workspace conversation processing (line ~453) |

## Testing & Validation

After the fix, retention policy execution should:

1. ✅ Skip conversations with null/undefined `last_activity_at` instead of deleting them
2. ✅ Only delete conversations with valid `last_activity_at` dates older than the retention period
3. ✅ Not show `cosmos_public_conversations_container` errors for public workspaces
4. ✅ Successfully process document retention for public workspaces

### Test Scenarios

| Scenario | Before Fix | After Fix |
|----------|------------|-----------|
| Conversation with `last_activity_at: null` | ❌ Deleted | ✅ Skipped |
| Conversation with `last_activity_at: undefined` | ❌ Deleted | ✅ Skipped |
| Conversation with valid old date | ✅ Deleted | ✅ Deleted |
| Conversation with valid recent date | ✅ Kept | ✅ Kept |
| Public workspace conversation retention | ❌ Error | ✅ Skipped (documents only) |

## Recommendations

1. **Backfill `last_activity_at`**: Consider running a migration to populate `last_activity_at` for existing conversations that have null values, using `last_updated` as a fallback.

2. **Ensure New Conversations Set `last_activity_at`**: Verify that all conversation creation and update paths properly set the `last_activity_at` field.

3. **Monitor Retention Execution**: After deploying this fix, monitor the next retention policy execution to confirm no unexpected deletions occur.

## Related Documentation

- [Retention Policy Feature Documentation](../../features/RETENTION_POLICY.md)
- [v0.236.012 NotFound Error Fix](../v0.236.012/RETENTION_POLICY_NOTFOUND_FIX.md)
- [v0.235.022 Document Deletion Fix](../v0.235.022/RETENTION_POLICY_DOCUMENT_DELETION_FIX.md)
