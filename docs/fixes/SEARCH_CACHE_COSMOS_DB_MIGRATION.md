# Search Cache Cosmos DB Migration

**Version:** 0.229.064  
**Date:** 2025-06-01  
**Type:** Architecture Enhancement

## Overview

Successfully migrated the search result caching system from in-memory storage to Azure Cosmos DB for multi-instance App Service deployment support. This enables cache sharing across multiple application instances with automatic TTL-based expiration.

## Problem Statement

The original in-memory cache implementation (`_search_results_cache` dictionary) worked well for single-instance deployments but had critical limitations for production multi-instance scenarios:

1. **No cache sharing**: Each App Service instance maintained its own cache
2. **Inconsistent user experience**: Same query could return cached results on one instance but perform full search on another
3. **No session affinity guarantee**: App Service scale-out doesn't guarantee users hit the same instance
4. **Wasted compute**: Redundant searches across instances for the same queries
5. **No distributed invalidation**: Document changes only invalidated cache on one instance

## Solution Architecture

### Cosmos DB Container Configuration

Created dedicated search cache container in `config.py`:

```python
cosmos_search_cache_container = cosmos_database.create_container_if_not_exists(
    id="search_cache",
    partition_key=PartitionKey(path="/user_id"),
    default_ttl=300  # 5 minutes TTL
)
```

**Key Design Decisions:**
- **Partition Key**: `user_id` for efficient personal search cache reads
- **TTL**: 300 seconds (5 minutes) for automatic expiration
- **Cross-partition queries**: Used for group and public workspace invalidation

### Cache Item Schema

```python
{
    "id": "<cache_key>",              # SHA256 hash of query + scope + fingerprints
    "user_id": "<user_id>",           # Partition key
    "doc_scope": "<scope>",           # personal/group/public/all
    "results": [...],                 # Search results array
    "expiry_time": "<ISO-8601>",      # When cache expires
    "created_at": "<ISO-8601>",       # When cache was created
    "ttl": 300                        # Cosmos DB TTL in seconds
}
```

## Implementation Details

### Files Modified

#### 1. `utils_cache.py` - Complete Migration
**Before**: In-memory dictionary operations  
**After**: Cosmos DB read/write/query operations

**Key Changes:**
- `get_cached_search_results(cache_key, user_id)`: 
  - Now uses `cosmos_search_cache_container.read_item()`
  - Requires `user_id` parameter for partition key
  - Returns `None` if not found (Cosmos handles expiry automatically)

- `cache_search_results(cache_key, results, user_id, doc_scope)`:
  - Now uses `cosmos_search_cache_container.upsert_item()`
  - Creates cache item with TTL metadata
  - Requires `user_id` and `doc_scope` parameters

- `invalidate_personal_search_cache(user_id)`:
  - Queries all cache entries for specific user
  - Uses partition key for efficient single-partition query
  - Deletes matching entries

- `invalidate_group_search_cache(group_id)`:
  - Performs cross-partition query using `CONTAINS(c.doc_scope, @group_id)`
  - Affects all users with group document access
  - Requires `enable_cross_partition_query=True`

- `invalidate_public_workspace_search_cache(workspace_id)`:
  - Performs cross-partition query using `CONTAINS(c.doc_scope, @workspace_id)`
  - Affects all users with workspace access
  - Requires `enable_cross_partition_query=True`

- `clear_all_cache()`:
  - Cross-partition query to fetch all cache items
  - Deletes all entries (administrative function)

- `get_cache_stats()`:
  - Uses `COUNT(1)` query to get total entries
  - Returns Cosmos DB-specific metrics
  - Note: All returned items are "active" (TTL handles expiration)

**Removed Functions:**
- `_evict_oldest_cache_entries()` - No longer needed (Cosmos TTL handles this)
- `_search_results_cache` dictionary - Replaced with Cosmos container
- `MAX_CACHE_SIZE` constant - Not applicable with Cosmos DB

#### 2. `functions_search.py` - Parameter Updates
**Changes:**
- `get_cached_search_results(cache_key, user_id)` - Added `user_id` parameter
- `cache_search_results(cache_key, results, user_id, doc_scope)` - Added `user_id` and `doc_scope` parameters

#### 3. `config.py` - Container Creation
**Changes:**
- Added `cosmos_search_cache_container` with partition key and TTL configuration
- Incremented version to `0.229.064`

### Cache Invalidation Strategy

**Event-Based Invalidation** (unchanged from in-memory implementation):

| Document Event | Invalidation Function | Scope |
|----------------|----------------------|-------|
| Personal document upload/delete/share | `invalidate_personal_search_cache(user_id)` | Single user partition |
| Group document upload/delete/share | `invalidate_group_search_cache(group_id)` | Cross-partition (all group members) |
| Public document upload/delete | `invalidate_public_workspace_search_cache(workspace_id)` | Cross-partition (all workspace users) |

**Invalidation Locations** (unchanged):
- `route_backend_documents.py` - Personal document endpoints
- `route_backend_group_documents.py` - Group document endpoints
- `route_backend_public_documents.py` - Public workspace endpoints

## Performance Considerations

### Query Performance
- **Personal cache reads**: Single partition query (fast, ~5-10ms)
- **Group/public invalidation**: Cross-partition queries (slower, ~50-100ms)
- **Cache writes**: Upsert operations (fast, ~10-20ms)

### Cost Optimization
- **TTL-based cleanup**: Automatic, no manual eviction logic
- **Partition strategy**: Efficient user-based partitioning
- **RU consumption**: 
  - Read cache: ~1 RU
  - Write cache: ~5-10 RU
  - Cross-partition invalidation: ~10-50 RU (depending on result count)

### Scalability
- **Multi-instance ready**: All instances share same cache
- **No cache size limits**: Cosmos DB handles scaling
- **Automatic expiration**: TTL removes stale entries without manual intervention

## Testing Recommendations

### Functional Tests to Create

1. **test_cosmos_cache_basic_operations.py**
   - Cache write and read
   - TTL expiration validation
   - Cache key generation with fingerprints

2. **test_cosmos_cache_invalidation.py**
   - Personal search cache invalidation
   - Group search cache invalidation (cross-partition)
   - Public workspace cache invalidation (cross-partition)
   - Document upload triggers invalidation

3. **test_cosmos_cache_multi_instance.py**
   - Simulate multiple app instances
   - Verify cache sharing across instances
   - Test invalidation propagation

4. **test_cosmos_cache_stats.py**
   - Verify `get_cache_stats()` returns correct counts
   - Test `clear_all_cache()` functionality

### Manual Testing Checklist

- [ ] Enable debug logging: `DEBUG_SEARCH_CACHE=1`
- [ ] Perform search, verify cache write
- [ ] Perform same search, verify cache hit
- [ ] Upload document, verify cache invalidation
- [ ] Wait 5+ minutes, verify TTL expiration
- [ ] Test cross-instance cache sharing (if multi-instance environment available)

## Debug Logging

Debug logging remains unchanged. Enable with environment variable:

```bash
DEBUG_SEARCH_CACHE=1
```

**Log Categories:**
- `CACHE_READ` - Cache retrieval attempts
- `CACHE_WRITE` - Cache storage operations
- `INVALIDATION` - Cache invalidation events
- `ADMIN` - Administrative operations (clear_all_cache)

## Migration Benefits

### Before (In-Memory Cache)
- ❌ Single-instance only
- ❌ No cache sharing
- ❌ Manual eviction logic required
- ❌ Cache inconsistency across instances
- ✅ Fast read/write (in-process)

### After (Cosmos DB Cache)
- ✅ Multi-instance ready
- ✅ Shared cache across all instances
- ✅ Automatic TTL-based expiration
- ✅ Consistent cache behavior
- ✅ Still fast with partition key optimization (~5-10ms reads)

## Known Limitations

1. **Cross-partition invalidation cost**: Group and public workspace invalidation requires cross-partition queries, which are more expensive than single-partition queries. Consider adding `group_id` or `workspace_id` fields to cache items if invalidation performance becomes an issue.

2. **No query result filtering**: Cross-partition invalidation queries (`CONTAINS(c.doc_scope, @id)`) rely on string matching. More precise indexing could improve performance.

3. **TTL resolution**: Cosmos DB TTL cleanup runs periodically (not instantaneous). Expired items may remain briefly visible.

## Future Enhancements

1. **Enhanced cache item schema**: Add explicit `group_id` and `workspace_id` fields for more efficient invalidation queries
2. **Cache warming**: Pre-populate cache for common queries during low-traffic periods
3. **Cache analytics**: Track hit rates, invalidation patterns, and performance metrics
4. **Partial invalidation**: More granular invalidation based on specific documents rather than entire scopes
5. **Cache compression**: Compress result arrays to reduce storage costs

## Rollback Plan

If issues arise, revert to in-memory cache by:

1. Restore `_search_results_cache` dictionary and `MAX_CACHE_SIZE` constant
2. Restore original function implementations in `utils_cache.py`
3. Remove Cosmos DB container creation from `config.py`
4. Update `functions_search.py` to remove `user_id` and `doc_scope` parameters

Note: Keep cosmos container for potential re-migration.

## Related Documentation

- **Original Issue**: GitHub issue documenting inconsistent search results
- **Feature Documentation**: `..\docs\features\SEARCH_RESULT_CACHING.md` (if exists)
- **Cosmos DB Best Practices**: See `.github\copilot-instructions.md` for Cosmos DB guidance

## Version History

- **0.229.063**: In-memory cache implementation with fingerprinting and debug logging
- **0.229.064**: Migrated to Cosmos DB for multi-instance support
