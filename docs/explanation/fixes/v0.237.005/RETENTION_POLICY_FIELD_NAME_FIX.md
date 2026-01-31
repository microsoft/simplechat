# Retention Policy Field Name Fix

## Version: 0.237.005

## Problem Statement

The retention policy was not deleting any conversations despite being configured with valid retention periods. After the v0.237.004 fix that required conversations to have a valid timestamp field, the policy found zero conversations to delete because it was querying for a field (`last_activity_at`) that doesn't exist on any conversation document.

### Symptoms
- Retention policy execution shows "0 conversations deleted" even with old conversations present
- Manual execution completes successfully but no conversations are affected
- Conversations older than the retention period remain in the database

### Debug Output Example
```
[DEBUG] [INFO]: Querying aged conversations: workspace_type=personal, retention_days=1
[DEBUG] [INFO]: Found 0 aged conversations for personal workspace
```

## Root Cause Analysis

### The Field Mismatch

The retention policy SQL query was looking for `last_activity_at`:

```sql
SELECT c.id, c.title, c.last_activity_at, c.user_id
FROM c
WHERE c.user_id = @partition_value
AND IS_DEFINED(c.last_activity_at) 
AND NOT IS_NULL(c.last_activity_at)
AND c.last_activity_at < @cutoff_date
```

However, **all conversation schemas use `last_updated`**, not `last_activity_at`:

| Schema Version | Era | Field Used |
|----------------|-----|------------|
| Schema 1 (messages embedded) | Legacy | `last_updated` |
| Schema 2 (messages separate) | Middle | `last_updated` |
| Schema 3 (messages with threading) | Current | `last_updated` |

### Example Conversation Documents

**Schema 1 (Legacy - messages embedded):**
```json
{
    "id": "2ff663f2-f260-4a21-a388-dc8f60caa353",
    "user_id": "441f7b4e-2f43-4a83-abf1-40697309b24d",
    "messages": [...],
    "last_updated": "2025-03-04T21:09:23.945024",
    "title": "how do i know if i'm being sca..."
}
```

**Schema 2 (Middle - messages in separate container):**
```json
{
    "id": "4d45051a-693d-4893-8960-9c4c2dc6b8be",
    "user_id": "07e61033-ea1a-4472-a1e7-6b9ac874984a",
    "last_updated": "2025-08-01T18:58:10.137683",
    "title": "what did paul win"
}
```

**Schema 3 (Current - messages with threading):**
```json
{
    "id": "bba2f03e-aa9a-4cee-a8fb-273e0c89c834",
    "user_id": "07e61033-ea1a-4472-a1e7-6b9ac874984a",
    "last_updated": "2026-01-27T21:00:43.910594",
    "title": "tell me about https://microsof...",
    "context": [...],
    "tags": [...],
    "strict": false,
    "is_pinned": false,
    "is_hidden": false
}
```

### Why `last_activity_at` Never Existed

The field `last_activity_at` was likely a planned feature that was never implemented. All conversation creation and update code paths use `last_updated`:

```python
# From route_backend_conversations.py
conversation_item = {
    'id': conversation_id,
    'user_id': user_id,
    'last_updated': datetime.utcnow().isoformat(),  # ← Only 'last_updated' is set
    'title': 'New Conversation',
    ...
}
```

## Solution Implementation

### File Modified: `functions_retention_policy.py`

Changed all references from `last_activity_at` to `last_updated`:

#### 1. Updated SQL Query

```python
# Before (incorrect field)
query = f"""
    SELECT c.id, c.title, c.last_activity_at, c.{partition_field}
    FROM c
    WHERE c.{partition_field} = @partition_value
    AND IS_DEFINED(c.last_activity_at) 
    AND NOT IS_NULL(c.last_activity_at)
    AND c.last_activity_at < @cutoff_date
"""

# After (correct field)
query = f"""
    SELECT c.id, c.title, c.last_updated, c.{partition_field}
    FROM c
    WHERE c.{partition_field} = @partition_value
    AND IS_DEFINED(c.last_updated) 
    AND NOT IS_NULL(c.last_updated)
    AND c.last_updated < @cutoff_date
"""
```

#### 2. Updated Docstring

```python
# Before
"""Delete conversations that exceed the retention period based on last_activity_at."""

# After
"""Delete conversations that exceed the retention period based on last_updated."""
```

#### 3. Updated Result Dictionaries

```python
# Before
deleted_details.append({
    'id': conversation_id,
    'title': conversation_title,
    'last_activity_at': conv.get('last_activity_at')
})

# After
deleted_details.append({
    'id': conversation_id,
    'title': conversation_title,
    'last_updated': conv.get('last_updated')
})
```

## Files Modified

| File | Changes |
|------|---------|
| `config.py` | Version updated to `0.237.005` |
| `functions_retention_policy.py` | Changed `last_activity_at` → `last_updated` in query, docstring, and result dictionaries |

## Testing & Validation

After the fix, retention policy execution should correctly identify and delete old conversations:

```
[DEBUG] [INFO]: Querying aged conversations: workspace_type=personal, retention_days=1
[DEBUG] [INFO]: Found 3 aged conversations for personal workspace
[DEBUG] [INFO]: Deleted conversation abc123 (Test Conversation) due to retention policy
```

### Test Scenarios

| Scenario | Before Fix | After Fix |
|----------|------------|-----------|
| Conversation with valid `last_updated` older than retention | ❌ Not found (wrong field) | ✅ Deleted |
| Conversation with valid `last_updated` newer than retention | ✅ Kept | ✅ Kept |
| Conversation with null `last_updated` | ✅ Skipped | ✅ Skipped |

## Schema Compatibility

This fix ensures compatibility with all three conversation schemas that exist in production:

| Schema | Messages Location | `last_updated` Field | Retention Works? |
|--------|-------------------|---------------------|------------------|
| 1 (Legacy) | Embedded in conversation | ✅ Present | ✅ Yes |
| 2 (Middle) | Separate container | ✅ Present | ✅ Yes |
| 3 (Current) | Separate container + threading | ✅ Present | ✅ Yes |

## Version History

| Version | Issue | Fix |
|---------|-------|-----|
| 0.237.003 | Initial retention policy implementation | N/A |
| 0.237.004 | Conversations with null `last_activity_at` deleted | Required valid timestamp field |
| 0.237.005 | Query used non-existent field | Changed to `last_updated` field |

## Related Documentation

- [v0.237.004 Null Last Activity Fix](../v0.237.004/RETENTION_POLICY_NULL_LAST_ACTIVITY_FIX.md)
- [v0.236.012 NotFound Error Fix](../v0.236.012/RETENTION_POLICY_NOTFOUND_FIX.md)
- [Retention Policy Feature Documentation](../../features/RETENTION_POLICY.md)
