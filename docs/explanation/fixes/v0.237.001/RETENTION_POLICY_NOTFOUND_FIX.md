# Retention Policy NotFound Error Fix

## Issue Description

The retention policy deletion process was logging errors when attempting to delete conversations or documents that had already been deleted (e.g., by another process or user action between the query and delete operations).

### Error Observed
```
DEBUG: [Log] delete_aged_conversations_deletion_error -- {'error': '(NotFound) Entity with the specified id does not exist in the system.
```

### Root Cause

This is a **race condition** scenario where:
1. The retention policy queries for aged conversations/documents
2. Between the query and the delete operation, the item is deleted by another process (user action, concurrent retention execution, etc.)
3. The delete operation fails with `CosmosResourceNotFoundError` (404 NotFound)

## Fix Applied

**Version:v0.237.001**

The fix adds specific handling for `CosmosResourceNotFoundError` in both conversation and document deletion loops:

### Conversations
- When reading a conversation before archiving: If not found, log debug message and count as already deleted
- When deleting messages: Catch NotFound and continue (message already gone)
- When deleting conversation: Catch NotFound and continue (conversation already gone)

### Documents
- When deleting document chunks: Catch NotFound and continue
- When deleting document: Catch NotFound and continue
- Outer try/catch also handles NotFound to count as successful deletion

## Files Modified

- [functions_retention_policy.py](../../../application/single_app/functions_retention_policy.py)
  - `delete_aged_conversations()` - Added CosmosResourceNotFoundError handling
  - `delete_aged_documents()` - Added CosmosResourceNotFoundError handling

## Technical Details

### Before Fix
```python
# Read would throw exception if item was deleted between query and read
conversation_item = container.read_item(
    item=conversation_id,
    partition_key=conversation_id
)
# Delete would throw exception if item was deleted
container.delete_item(
    item=conversation_id,
    partition_key=conversation_id
)
```

### After Fix
```python
try:
    conversation_item = container.read_item(
        item=conversation_id,
        partition_key=conversation_id
    )
except CosmosResourceNotFoundError:
    # Already deleted - this is fine, count as success
    debug_print(f"Conversation {conversation_id} already deleted (not found during read), skipping")
    deleted_details.append({...})
    continue

# ... archiving and message deletion ...

try:
    container.delete_item(
        item=conversation_id,
        partition_key=conversation_id
    )
except CosmosResourceNotFoundError:
    # Already deleted between read and delete - this is fine
    debug_print(f"Conversation {conversation_id} already deleted (not found during delete)")
```

## Benefits

1. **No false error logs**: Items that are already deleted no longer generate error entries
2. **Accurate counts**: Already-deleted items are properly counted as successful deletions
3. **Graceful handling**: Race conditions are handled without disrupting the overall retention process
4. **Better debugging**: Debug messages clearly indicate when items were already deleted

## Testing

Test by:
1. Enabling retention policy with a short retention period
2. Running the retention policy execution
3. Verify no NotFound errors are logged
4. Verify deletion counts accurately reflect processed items
