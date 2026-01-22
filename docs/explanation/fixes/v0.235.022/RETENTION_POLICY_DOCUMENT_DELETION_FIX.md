# Retention Policy Document Deletion Fix

**Version Implemented:** 0.235.022

## Problem Statement

The retention policy execution was failing when attempting to delete aged documents, while conversation deletion worked correctly. The error manifested as:

```
[DEBUG] [INFO]: Error querying aged documents for personal (partition_value=1d6312bd-3eaa-4586-8b74-e90eee126f78): (BadRequest) One of the input values is invalid.
```

This prevented the automated cleanup of old documents based on user-configured retention policies.

## Root Cause Analysis

Investigation revealed **four distinct issues** causing the document deletion to fail:

### Issue 1: Wrong Field Name
Documents use `last_updated` as the timestamp field, but the retention policy was querying for `last_activity_at` (which is used by conversations).

**Document schema:**
```json
{
  "upload_date": "2025-11-20T15:17:57Z",
  "last_updated": "2025-11-20T15:54:22Z"
}
```

**Incorrect query:**
```sql
WHERE c.last_activity_at < @cutoff_date
```

### Issue 2: Date Format Mismatch
Documents store timestamps in `YYYY-MM-DDTHH:MM:SSZ` format, but the query was using Python's `.isoformat()` which produces `+00:00` suffix with microseconds.

- **Document format:** `2026-01-08T21:49:15Z`
- **Query format:** `2026-01-15T15:49:09.828460+00:00`

Cosmos DB string comparison failed due to format differences.

### Issue 3: Duplicate Column in SELECT
The query included both `c.{partition_field}` and `c.user_id` in the SELECT clause. When `partition_field='user_id'`, this created a duplicate column causing query errors.

**Problematic query:**
```sql
SELECT c.id, c.file_name, c.title, c.last_updated, c.user_id, c.user_id
```

### Issue 4: Incorrect Activity Logging Parameter
The `log_conversation_deletion()` function was called with `deletion_reason='retention_policy'`, but this parameter doesn't exist in the function signature. It should use `additional_context` instead.

## Solution Implementation

### File Modified: `functions_retention_policy.py`

#### Fix 1: Correct Field Name
Changed document queries to use `last_updated` instead of `last_activity_at`:

```python
# Query for aged documents
# Documents use 'last_updated' field (not 'last_activity_at' like conversations)
query = f"""
    SELECT c.id, c.file_name, c.title, c.last_updated, c.user_id
    FROM c
    WHERE c.{partition_field} = @partition_value
    AND c.last_updated < @cutoff_date
"""
```

#### Fix 2: Correct Date Format
Changed from `.isoformat()` to `.strftime()` to match document timestamp format:

```python
# Documents use format like '2026-01-08T21:49:15Z' so we match that format
cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
cutoff_iso = cutoff_date.strftime('%Y-%m-%dT%H:%M:%SZ')
```

#### Fix 3: Remove Duplicate Column
Simplified SELECT to avoid duplicate columns:

```python
SELECT c.id, c.file_name, c.title, c.last_updated, c.user_id
```

#### Fix 4: Correct Activity Logging Parameter
Changed from invalid parameter to proper `additional_context`:

```python
# Before (incorrect)
log_conversation_deletion(
    ...
    deletion_reason='retention_policy'
)

# After (correct)
log_conversation_deletion(
    ...
    additional_context={'deletion_reason': 'retention_policy'}
)
```

### Additional Improvements

#### Enhanced Debug Logging
Added comprehensive debug logging to aid future troubleshooting:

```python
debug_print(f"Processing retention for user {user_id}: conversations={conversation_retention_days} days, documents={document_retention_days} days")
debug_print(f"Querying aged documents: workspace_type={workspace_type}, partition_field={partition_field}, partition_value={partition_value}, cutoff_date={cutoff_iso}, retention_days={retention_days}")
debug_print(f"Found {len(aged_documents)} aged documents for {workspace_type} workspace")
```

## Testing & Validation

After the fix, retention policy execution completed successfully:

```
[DEBUG] [INFO]: Querying aged documents: workspace_type=personal, partition_field=user_id, partition_value=1d6312bd-3eaa-4586-8b74-e90eee126f78, cutoff_date=2026-01-15T15:58:09Z, retention_days=1
[DEBUG] [INFO]: Found 1 aged documents for personal workspace
[DEBUG] [INFO]: [DELETE DOCUMENT] Starting deletion for document: 36a030b2-57b2-426b-8aa9-6f49eed5f8a6
[DEBUG] [INFO]: Logged document deletion transaction: 36a030b2-57b2-426b-8aa9-6f49eed5f8a6
Successfully deleted blob at 1d6312bd-3eaa-4586-8b74-e90eee126f78/test.pdf
[DEBUG] [INFO]: Deleted document 36a030b2-57b2-426b-8aa9-6f49eed5f8a6 (test.pdf) due to retention policy
[DEBUG] [INFO]: Notification created: 5a92235d-d408-4449-9c72-0951ed198688 [personal] [system_announcement]
[DEBUG] [INFO]: Retention policy execution completed: {'success': True, ... 'documents': 1, 'users_affected': 1 ...}
```

## Files Changed

| File | Changes |
|------|---------|
| `functions_retention_policy.py` | Fixed field name, date format, duplicate columns, activity logging |
| `config.py` | Version bump to 0.235.022 |

## Impact

- **Retention Policy:** Now correctly deletes aged documents based on user settings
- **Activity Logging:** Document deletions are properly logged with deletion reason
- **User Notifications:** Users receive notifications when documents are deleted by retention policy
- **Blob Storage:** Associated blob files are correctly removed

## Related Components

- Conversation retention (uses `last_activity_at` - unchanged)
- Group workspace retention (shares same document deletion logic)
- Public workspace retention (shares same document deletion logic)
