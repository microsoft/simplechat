# Shared Cache Support for Group and Public Workspace Searches

**Version:** 0.229.065  
**Date:** November 9, 2025  
**Type:** Bug Fix - Cache Sharing

## Problem Statement

The initial Cosmos DB cache implementation (v0.229.064) had a **critical bug** that prevented cache sharing for group and public workspace searches.

### The Bug

Even though the cache key generation correctly excluded `user_id` for group/public scopes to enable cache sharing, **the partition key was always set to `user_id`**, causing cache misses:

**Scenario:**
1. User A searches "machine learning" in Group X
2. Cache stored: `{id: "abc123", user_id: "userA", ...}` in partition `userA`
3. User B searches "machine learning" in Group X
4. Same cache key generated: `abc123` ✅
5. But Cosmos DB read fails: Looking for `abc123` in partition `userB` ❌
6. Result: Cache miss, full search executed again

**Impact:**
- Group searches never shared cache across members
- Public workspace searches never shared cache across users
- Search performance gains only applied to personal searches
- Wasted compute and RUs for redundant searches

## Solution

Implemented **scope-based partition keys** that align with the cache sharing intent:

### Partition Key Strategy

| Doc Scope | Partition Key | Sharing Behavior |
|-----------|--------------|------------------|
| `personal` | `user_id` | Private to user |
| `group` | `group:{group_id}` | Shared across all group members |
| `public` | `public:{workspace_id}` | Shared across all workspace users |
| `all` | Priority: group > public > personal | Shared when applicable |

### Implementation

#### 1. Added Helper Function: `get_cache_partition_key()`

```python
def get_cache_partition_key(
    doc_scope: str,
    user_id: str,
    active_group_id: Optional[str] = None,
    active_public_workspace_id: Optional[str] = None
) -> str:
    """
    Determine the partition key to use for cache storage based on scope.
    
    For shared caches (group/public), use a consistent partition key so all users
    can access the same cached results.
    """
    if doc_scope == "personal":
        return user_id
    elif doc_scope == "group":
        return f"group:{active_group_id}" if active_group_id else user_id
    elif doc_scope == "public":
        return f"public:{active_public_workspace_id}" if active_public_workspace_id else user_id
    elif doc_scope == "all":
        # For "all" scope, prioritize group > public > personal
        if active_group_id:
            return f"group:{active_group_id}"
        elif active_public_workspace_id:
            return f"public:{active_public_workspace_id}"
        else:
            return user_id
    else:
        return user_id
```

#### 2. Updated `get_cached_search_results()`

**Before:**
```python
def get_cached_search_results(cache_key: str, user_id: str):
    cache_item = cosmos_search_cache_container.read_item(
        item=cache_key,
        partition_key=user_id  # ❌ Always user_id
    )
```

**After:**
```python
def get_cached_search_results(
    cache_key: str, 
    user_id: str,
    doc_scope: str = "all",
    active_group_id: Optional[str] = None,
    active_public_workspace_id: Optional[str] = None
):
    # Determine correct partition key based on scope
    partition_key = get_cache_partition_key(doc_scope, user_id, active_group_id, active_public_workspace_id)
    
    cache_item = cosmos_search_cache_container.read_item(
        item=cache_key,
        partition_key=partition_key  # ✅ Scope-based
    )
```

#### 3. Updated `cache_search_results()`

**Before:**
```python
def cache_search_results(cache_key: str, results: List[Dict], user_id: str, doc_scope: str):
    cache_item = {
        "id": cache_key,
        "user_id": user_id,  # ❌ Always user_id
        # ...
    }
```

**After:**
```python
def cache_search_results(
    cache_key: str, 
    results: List[Dict], 
    user_id: str, 
    doc_scope: str,
    active_group_id: Optional[str] = None,
    active_public_workspace_id: Optional[str] = None
):
    # Determine correct partition key based on scope
    partition_key = get_cache_partition_key(doc_scope, user_id, active_group_id, active_public_workspace_id)
    
    cache_item = {
        "id": cache_key,
        "user_id": partition_key,  # ✅ Scope-based (stored as user_id for Cosmos DB)
        # ...
    }
```

#### 4. Updated `functions_search.py` Calls

**Before:**
```python
cached_results = get_cached_search_results(cache_key, user_id)
cache_search_results(cache_key, results, user_id, doc_scope)
```

**After:**
```python
cached_results = get_cached_search_results(
    cache_key, user_id, doc_scope, active_group_id, active_public_workspace_id
)
cache_search_results(
    cache_key, results, user_id, doc_scope, active_group_id, active_public_workspace_id
)
```

## How Cache Sharing Works Now

### Group Search Example

**Group ID:** `group-engineering`  
**Members:** Alice, Bob, Carol

1. **Alice searches "python best practices"**
   - Cache key: `sha256("python best practices|group|<fingerprint>")`
   - Partition key: `group:group-engineering`
   - Stored: `{id: "abc123", user_id: "group:group-engineering", results: [...]}`

2. **Bob searches "python best practices" (5 seconds later)**
   - Same cache key: `abc123` ✅
   - Same partition key: `group:group-engineering` ✅
   - **Cache HIT** - Returns Alice's cached results
   - **Performance**: 5-10ms instead of 500-1500ms

3. **Carol searches "python best practices" (30 seconds later)**
   - Same cache key: `abc123` ✅
   - Same partition key: `group:group-engineering` ✅
   - **Cache HIT** - Returns cached results
   - **Performance**: 5-10ms instead of 500-1500ms

### Public Workspace Example

**Workspace ID:** `workspace-company-docs`  
**Users:** Hundreds of employees

1. **First user searches "vacation policy"**
   - Cache key: `sha256("vacation policy|public|<fingerprint>")`
   - Partition key: `public:workspace-company-docs`
   - Stored: `{id: "xyz789", user_id: "public:workspace-company-docs", results: [...]}`

2. **All subsequent users searching "vacation policy"**
   - Same cache key: `xyz789` ✅
   - Same partition key: `public:workspace-company-docs` ✅
   - **Cache HIT** for all users
   - **Impact**: 100 searches = 1 actual search + 99 cache hits

## Benefits

### Performance Improvements

| Scope | Before Fix | After Fix | Improvement |
|-------|-----------|-----------|-------------|
| Personal | Cache works | Cache works | No change |
| Group (10 members) | 10 full searches | 1 search + 9 cache hits | **90% reduction** |
| Public (100 users) | 100 full searches | 1 search + 99 cache hits | **99% reduction** |

### Cost Reduction (RU Consumption)

**Example: 100 users searching "quarterly report" in public workspace**

**Before Fix:**
- 100 full searches × 50 RU each = 5,000 RU
- No cache sharing

**After Fix:**
- 1 full search = 50 RU
- 99 cache reads × 1 RU each = 99 RU
- **Total: 149 RU** (97% reduction)

### User Experience

✅ **Consistent performance**: All users get fast results, not just the first searcher  
✅ **Real-time collaboration**: Group members benefit from each other's searches  
✅ **Scalability**: Public workspaces scale efficiently with more users

## Cache Invalidation Impact

Cache invalidation still works correctly with scope-based partition keys:

### Personal Document Change
```python
invalidate_personal_search_cache(user_id)
# Query: WHERE c.user_id = user_id
# Affects: Only that user's cache entries
```

### Group Document Change
```python
invalidate_group_search_cache(group_id)
# Query: WHERE CONTAINS(c.doc_scope, group_id) - cross-partition
# Affects: All cache entries containing that group
# Includes: group:{group_id} partitions and "all" scope searches
```

### Public Workspace Document Change
```python
invalidate_public_workspace_search_cache(workspace_id)
# Query: WHERE CONTAINS(c.doc_scope, workspace_id) - cross-partition
# Affects: All cache entries containing that workspace
# Includes: public:{workspace_id} partitions and "all" scope searches
```

## Debug Logging Enhancement

Enhanced debug logging to show partition key usage:

```python
debug_print(
    "CACHE HIT - Returning cached results from Cosmos DB",
    "CACHE",
    cache_key=cache_key[:16],
    result_count=len(results),
    scope=doc_scope,
    partition_key=partition_key[:25],  # NEW
    ttl_remaining=f"{seconds_remaining:.1f}s"
)
```

**Example Output:**
```
[CACHE 12:34:56.789] [CACHE] CACHE HIT - Returning cached results from Cosmos DB 
  cache_key=abc123def456... result_count=12 scope=group 
  partition_key=group:group-engineering ttl_remaining=245.3s
```

## Testing Recommendations

### Functional Test: Group Cache Sharing

```python
def test_group_cache_sharing():
    """Test that group members share cache results."""
    
    # Setup
    group_id = "test-group-123"
    user_a = "user-alice"
    user_b = "user-bob"
    query = "test query"
    
    # User A performs search (cache miss)
    results_a = hybrid_search(
        query=query,
        user_id=user_a,
        doc_scope="group",
        active_group_id=group_id,
        # ...
    )
    
    # User B performs same search (should be cache hit)
    results_b = hybrid_search(
        query=query,
        user_id=user_b,
        doc_scope="group",
        active_group_id=group_id,
        # ...
    )
    
    # Verify results are identical
    assert results_a == results_b
    
    # Verify cache was shared (check logs or stats)
    # Should see "CACHE HIT" in debug logs for User B
```

### Functional Test: Public Workspace Cache Sharing

```python
def test_public_workspace_cache_sharing():
    """Test that public workspace users share cache results."""
    
    workspace_id = "workspace-public-123"
    users = ["user1", "user2", "user3"]
    query = "public document search"
    
    all_results = []
    
    for user_id in users:
        results = hybrid_search(
            query=query,
            user_id=user_id,
            doc_scope="public",
            active_public_workspace_id=workspace_id,
            # ...
        )
        all_results.append(results)
    
    # All users should get identical results
    assert all_results[0] == all_results[1] == all_results[2]
    
    # Only first search should execute full search
    # Remaining 2 should be cache hits
```

### Performance Test: Cache Sharing Impact

```python
import time

def test_cache_sharing_performance():
    """Measure performance improvement from cache sharing."""
    
    group_id = "perf-test-group"
    users = [f"user-{i}" for i in range(10)]
    query = "performance test query"
    
    search_times = []
    
    for user_id in users:
        start = time.time()
        results = hybrid_search(
            query=query,
            user_id=user_id,
            doc_scope="group",
            active_group_id=group_id,
            # ...
        )
        elapsed = time.time() - start
        search_times.append(elapsed)
    
    # First search should be slow (cache miss)
    assert search_times[0] > 0.5  # >500ms
    
    # Subsequent searches should be fast (cache hits)
    for i in range(1, 10):
        assert search_times[i] < 0.05  # <50ms
    
    print(f"First search: {search_times[0]*1000:.0f}ms")
    print(f"Avg cached search: {sum(search_times[1:])/9*1000:.0f}ms")
    print(f"Speedup: {search_times[0]/sum(search_times[1:])*9:.1f}x")
```

## Migration Notes

### Backward Compatibility

⚠️ **Breaking Change**: Existing cache entries from v0.229.064 will NOT be accessible after this update.

**Reason**: Partition keys have changed from `user_id` to scope-based keys like `group:{id}` or `public:{id}`.

**Impact**:
- All users will experience cache misses on first search after update
- Cache will rebuild naturally as searches are performed
- No data loss, just temporary performance impact during cache rebuild

**Mitigation**:
- Optional: Clear all cache before deployment: `clear_all_cache()`
- Cache will repopulate within 5-10 minutes of normal usage
- TTL will clean up old entries automatically

## Files Modified

1. **`utils_cache.py`**
   - Added `get_cache_partition_key()` helper function
   - Updated `get_cached_search_results()` signature and implementation
   - Updated `cache_search_results()` signature and implementation
   - Enhanced debug logging with partition key information

2. **`functions_search.py`**
   - Updated `get_cached_search_results()` call with additional parameters
   - Updated `cache_search_results()` call with additional parameters

3. **`config.py`**
   - Version updated to `0.229.065`

## Verification Checklist

- [x] No lint errors
- [x] Helper function `get_cache_partition_key()` added
- [x] Cache read uses scope-based partition key
- [x] Cache write uses scope-based partition key
- [x] `functions_search.py` passes all required parameters
- [x] Debug logging includes partition key information
- [x] Version updated in config.py

## Related Documentation

- **Main Feature**: `docs/features/SEARCH_RESULT_CACHING.md`
- **Migration**: `docs/fixes/SEARCH_CACHE_COSMOS_DB_MIGRATION.md`
- **Cosmos DB Best Practices**: `.github/copilot-instructions.md`

## Version History

- **0.229.064**: Cosmos DB migration (bug: no cache sharing for group/public)
- **0.229.065**: Fixed cache sharing with scope-based partition keys ✅
