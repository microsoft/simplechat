"""
Search Result Caching Utility

This module provides document-set-aware caching for search results with event-based invalidation.
It ensures cache consistency by:
1. Including document set fingerprints in cache keys
2. Invalidating cache when documents are added/removed/shared
3. Supporting scope-aware caching (personal, group, public workspaces)
4. Sharing cache across users for group/public workspace searches

Cache Strategy:
- Personal searches: User-specific cache (invalidated on user's document changes)
- Group searches: Shared cache across all group members (invalidated on group document changes)
- Public searches: Shared cache across all workspace users (invalidated on public document changes)
- "All" scope: Combines fingerprints from all applicable scopes
"""

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from config import (
    cosmos_user_documents_container,
    cosmos_group_documents_container,
    cosmos_public_documents_container,
    cosmos_search_cache_container
)
from azure.cosmos.exceptions import CosmosResourceNotFoundError

logger = logging.getLogger(__name__)

# Debug logging control - set environment variable DEBUG_SEARCH_CACHE=1 to enable
DEBUG_ENABLED = os.environ.get('DEBUG_SEARCH_CACHE', '0') == '1'


def get_cache_settings():
    """
    Get cache settings from app settings (admin configurable).
    Falls back to defaults if settings unavailable.
    
    Returns:
        tuple: (cache_enabled, ttl_seconds)
    """
    try:
        from functions_settings import get_settings
        settings = get_settings()
        return (
            settings.get('enable_search_result_caching', True),
            settings.get('search_cache_ttl_seconds', 300)
        )
    except Exception as e:
        logger.warning(f"Failed to load cache settings, using defaults: {e}")
        return (True, 300)  # Default: enabled with 5 minute TTL


def debug_print(message: str, context: str = "CACHE", **kwargs):
    """
    Conditional debug logging with timestamp and context.
    
    Only logs when DEBUG_SEARCH_CACHE environment variable is set to '1'.
    Includes timestamp, context label, and optional key-value pairs.
    
    Args:
        message: Main debug message
        context: Context label (e.g., "CACHE", "SEARCH", "FINGERPRINT")
        **kwargs: Additional key-value pairs to log
    """
    if not DEBUG_ENABLED:
        return
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    
    # Build extra info string from kwargs
    extra_info = ""
    if kwargs:
        extra_parts = [f"{k}={v}" for k, v in kwargs.items()]
        extra_info = " | " + ", ".join(extra_parts)
    
    debug_message = f"[{timestamp}] [{context}] {message}{extra_info}"
    logger.info(debug_message)
    print(debug_message, flush=True)  # Also print to stdout for visibility


def get_personal_document_fingerprint(user_id: str) -> str:
    """
    Generate a fingerprint of user's personal documents (including shared with them).
    
    Args:
        user_id: User ID to get document fingerprint for
        
    Returns:
        SHA256 hash of sorted document IDs
    """
    debug_print("Generating personal document fingerprint", "FINGERPRINT", user_id=user_id[:8])
    
    try:
        query = """
            SELECT c.id, c.version
            FROM c
            WHERE c.user_id = @user_id OR ARRAY_CONTAINS(c.shared_user_ids, @user_id)
            ORDER BY c.id
        """
        parameters = [{"name": "@user_id", "value": user_id}]
        
        documents = list(
            cosmos_user_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        
        # Include both ID and version to detect document updates
        doc_identifiers = [f"{doc['id']}:v{doc['version']}" for doc in documents]
        doc_identifiers.sort()
        
        fingerprint_string = '|'.join(doc_identifiers)
        fingerprint = hashlib.sha256(fingerprint_string.encode()).hexdigest()
        
        debug_print(
            f"Generated personal fingerprint: {fingerprint[:16]}...",
            "FINGERPRINT",
            user_id=user_id[:8],
            doc_count=len(documents)
        )
        
        return fingerprint
        
    except Exception as e:
        logger.error(f"Error generating personal document fingerprint for user {user_id}: {e}")
        debug_print(f"[DEBUG] ERROR generating fingerprint: {e}", "FINGERPRINT", user_id=user_id[:8])
        # Return timestamp-based fingerprint to prevent caching on error
        return hashlib.sha256(str(datetime.now().timestamp()).encode()).hexdigest()


def get_group_document_fingerprint(group_id: str) -> str:
    """
    Generate a fingerprint of group documents (including shared with group).
    
    Args:
        group_id: Group ID to get document fingerprint for
        
    Returns:
        SHA256 hash of sorted document IDs
    """
    debug_print("Generating group document fingerprint", "FINGERPRINT", group_id=group_id[:8])
    
    try:
        query = """
            SELECT c.id, c.version
            FROM c
            WHERE c.group_id = @group_id OR ARRAY_CONTAINS(c.shared_group_ids, @group_id)
            ORDER BY c.id
        """
        parameters = [{"name": "@group_id", "value": group_id}]
        
        documents = list(
            cosmos_group_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        
        doc_identifiers = [f"{doc['id']}:v{doc['version']}" for doc in documents]
        doc_identifiers.sort()
        
        fingerprint_string = '|'.join(doc_identifiers)
        fingerprint = hashlib.sha256(fingerprint_string.encode()).hexdigest()
        
        debug_print(
            f"Generated group fingerprint: {fingerprint[:16]}...",
            "FINGERPRINT",
            group_id=group_id[:8],
            doc_count=len(documents)
        )
        
        return fingerprint
        
    except Exception as e:
        logger.error(f"Error generating group document fingerprint for group {group_id}: {e}")
        debug_print(f"[DEBUG] ERROR generating fingerprint: {e}", "FINGERPRINT", group_id=group_id[:8])
        return hashlib.sha256(str(datetime.now().timestamp()).encode()).hexdigest()


def get_public_workspace_document_fingerprint(public_workspace_id: str) -> str:
    """
    Generate a fingerprint of public workspace documents.
    
    Args:
        public_workspace_id: Public workspace ID to get document fingerprint for
        
    Returns:
        SHA256 hash of sorted document IDs
    """
    debug_print("Generating public workspace document fingerprint", "FINGERPRINT", workspace_id=public_workspace_id[:8])
    
    try:
        query = """
            SELECT c.id, c.version
            FROM c
            WHERE c.public_workspace_id = @public_workspace_id
            ORDER BY c.id
        """
        parameters = [{"name": "@public_workspace_id", "value": public_workspace_id}]
        
        documents = list(
            cosmos_public_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        
        doc_identifiers = [f"{doc['id']}:v{doc['version']}" for doc in documents]
        doc_identifiers.sort()
        
        fingerprint_string = '|'.join(doc_identifiers)
        fingerprint = hashlib.sha256(fingerprint_string.encode()).hexdigest()
        
        debug_print(
            f"Generated public workspace fingerprint: {fingerprint[:16]}...",
            "FINGERPRINT",
            workspace_id=public_workspace_id[:8],
            doc_count=len(documents)
        )
        
        return fingerprint
        
    except Exception as e:
        logger.error(f"Error generating public workspace document fingerprint for workspace {public_workspace_id}: {e}")
        debug_print(f"[DEBUG] ERROR generating fingerprint: {e}", "FINGERPRINT", workspace_id=public_workspace_id[:8])
        return hashlib.sha256(str(datetime.now().timestamp()).encode()).hexdigest()


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
    
    Args:
        doc_scope: Scope of search ("personal", "group", "public", "all")
        user_id: User ID (for personal scope)
        active_group_id: Active group ID (for group scope)
        active_public_workspace_id: Active public workspace ID (for public scope)
        
    Returns:
        Partition key string to use for Cosmos DB operations
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


def generate_search_cache_key(
    query: str,
    user_id: str,
    document_id: Optional[str] = None,
    doc_scope: str = "all",
    active_group_id: Optional[str] = None,
    active_public_workspace_id: Optional[str] = None,
    top_n: int = 12,
    enable_file_sharing: bool = True
) -> str:
    """
    Generate a cache key that includes document set fingerprints.
    
    The cache key ensures that:
    - Same query + same document set = cache hit
    - Same query + different document set = cache miss
    - Personal scope: User-specific cache
    - Group/Public scope: Shared cache across users with access
    
    Args:
        query: Search query text
        user_id: User ID (for personal scope)
        document_id: Specific document filter
        doc_scope: Scope of search ("personal", "group", "public", "all")
        active_group_id: Active group ID (for group scope)
        active_public_workspace_id: Active public workspace ID (for public scope)
        top_n: Number of results
        enable_file_sharing: Whether file sharing is enabled
        
    Returns:
        SHA256 hash string to use as cache key
    """
    # Normalize query (case-insensitive, whitespace-normalized)
    normalized_query = ' '.join(query.lower().strip().split())
    
    # Build fingerprint based on scope
    fingerprints = []
    
    if doc_scope in ["personal", "all"]:
        personal_fp = get_personal_document_fingerprint(user_id)
        fingerprints.append(f"personal:{personal_fp}")
    
    if doc_scope in ["group", "all"] and active_group_id:
        group_fp = get_group_document_fingerprint(active_group_id)
        fingerprints.append(f"group:{group_fp}")
    
    if doc_scope in ["public", "all"] and active_public_workspace_id:
        public_fp = get_public_workspace_document_fingerprint(active_public_workspace_id)
        fingerprints.append(f"public:{public_fp}")
    
    # Combine all components
    # Note: For group/public scopes, we DON'T include user_id in cache key
    # so cache is shared across users with access
    if doc_scope == "personal":
        cache_key_components = [
            normalized_query,
            user_id,  # Include user_id for personal searches
            document_id or '',
            doc_scope,
            str(top_n),
            str(enable_file_sharing),
            '|'.join(fingerprints)
        ]
    else:
        # For group/public/all, exclude user_id to enable cache sharing
        cache_key_components = [
            normalized_query,
            document_id or '',
            doc_scope,
            active_group_id or '',
            active_public_workspace_id or '',
            str(top_n),
            str(enable_file_sharing),
            '|'.join(fingerprints)
        ]
    
    cache_key_string = '|'.join(cache_key_components)
    cache_key = hashlib.sha256(cache_key_string.encode()).hexdigest()
    
    debug_print(
        f"Generated cache key: {cache_key[:16]}...",
        "CACHE_KEY",
        query=query[:40],
        scope=doc_scope,
        fingerprint_count=len(fingerprints)
    )
    
    logger.debug(f"Generated cache key for query '{query[:50]}...': {cache_key}")
    return cache_key


def get_cached_search_results(
    cache_key: str, 
    user_id: str,
    doc_scope: str = "all",
    active_group_id: Optional[str] = None,
    active_public_workspace_id: Optional[str] = None
) -> Optional[List[Dict[str, Any]]]:
    """
    Retrieve cached search results from Cosmos DB if still valid.
    
    Args:
        cache_key: Cache key to lookup
        user_id: User ID (for personal scope partition key)
        doc_scope: Document scope to determine partition key
        active_group_id: Active group ID (for group scope partition key)
        active_public_workspace_id: Active public workspace ID (for public scope partition key)
        
    Returns:
        Cached results if found and not expired, None otherwise
    """
    # Check if caching is enabled
    cache_enabled, ttl_seconds = get_cache_settings()
    if not cache_enabled:
        debug_print("Cache DISABLED - Skipping cache read", "CACHE")
        return None
    
    # Determine correct partition key based on scope for shared cache access
    partition_key = get_cache_partition_key(doc_scope, user_id, active_group_id, active_public_workspace_id)
    
    try:
        # Try to read from Cosmos DB using scope-based partition key
        cache_item = cosmos_search_cache_container.read_item(
            item=cache_key,
            partition_key=partition_key
        )
        
        # Check if still valid (Cosmos TTL handles automatic deletion, but check anyway)
        expiry_time = datetime.fromisoformat(cache_item['expiry_time'].replace('Z', '+00:00'))
        
        if datetime.now(timezone.utc) < expiry_time:
            seconds_remaining = (expiry_time - datetime.now(timezone.utc)).total_seconds()
            results = cache_item['results']
            
            debug_print(
                "CACHE HIT - Returning cached results from Cosmos DB",
                "CACHE",
                cache_key=cache_key[:16],
                result_count=len(results),
                scope=doc_scope,
                partition_key=partition_key[:25],
                ttl_remaining=f"{seconds_remaining:.1f}s"
            )
            logger.info(f"Cache hit for key: {cache_key} (scope: {doc_scope}, partition: {partition_key[:25]})")
            return results
        else:
            # Expired - delete from cache
            debug_print(
                "Cache entry EXPIRED - Removing from Cosmos DB",
                "CACHE",
                cache_key=cache_key[:16]
            )
            logger.debug(f"Cache expired for key: {cache_key}")
            try:
                cosmos_search_cache_container.delete_item(item=cache_key, partition_key=partition_key)
            except:
                pass  # Already deleted by TTL or doesn't exist
            
    except CosmosResourceNotFoundError:
        debug_print(
            "CACHE MISS - Need to execute search",
            "CACHE",
            cache_key=cache_key[:16]
        )
        logger.debug(f"Cache miss for key: {cache_key}")
    except Exception as e:
        logger.error(f"Error reading cache from Cosmos DB: {e}")
        debug_print(f"[DEBUG] Cache read ERROR: {e}", "CACHE", cache_key=cache_key[:16])
    
    return None


def cache_search_results(cache_key: str, results: List[Dict[str, Any]], user_id: str, 
                         doc_scope: str = "all", active_group_id: Optional[str] = None,
                         active_public_workspace_id: Optional[str] = None) -> None:
    """
    Store search results in Cosmos DB cache with expiry time.
    
    Args:
        cache_key: Cache key to store under
        results: Search results to cache
        user_id: User ID (for personal scope partition key)
        doc_scope: Document scope for the search
        active_group_id: Active group ID (for group scope partition key)
        active_public_workspace_id: Active public workspace ID (for public scope partition key)
    """
    # Check if caching is enabled
    cache_enabled, ttl_seconds = get_cache_settings()
    if not cache_enabled:
        debug_print("Cache DISABLED - Skipping cache write", "CACHE")
        return
    
    # Determine correct partition key based on scope for shared cache storage
    partition_key = get_cache_partition_key(doc_scope, user_id, active_group_id, active_public_workspace_id)
    
    expiry_time = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    
    cache_item = {
        "id": cache_key,
        "user_id": partition_key,  # Store partition key as user_id for Cosmos DB
        "doc_scope": doc_scope,
        "results": results,
        "expiry_time": expiry_time.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
        # No ttl field - app logic handles expiry and deletion manually
    }
    
    try:
        cosmos_search_cache_container.upsert_item(cache_item)
        
        debug_print(
            "Cached search results in Cosmos DB",
            "CACHE",
            cache_key=cache_key[:16],
            result_count=len(results),
            expires_in=f"{ttl_seconds}s",
            scope=doc_scope,
            partition_key=partition_key[:25]
        )
        
        logger.debug(f"Cached search results with key: {cache_key}, scope: {doc_scope}, partition: {partition_key[:25]}, ttl: {ttl_seconds}s, expires at: {expiry_time}")
    except Exception as e:
        logger.error(f"Error caching search results to Cosmos DB: {e}")
        debug_print(f"[DEBUG] Cache write ERROR: {e}", "CACHE", cache_key=cache_key[:16])


# Cache Expiration Strategy:
# - App logic checks expiry_time field and deletes expired entries during reads
# - No Cosmos DB TTL (gives admin full control via settings)
# - Expired entries cleaned up on-demand when accessed
# - Event-based invalidation clears cache immediately on document changes


def invalidate_personal_search_cache(user_id: str) -> int:
    """
    Invalidate all cached searches for a specific user's personal documents in Cosmos DB.
    
    Call this when:
    - User uploads a document
    - User deletes a document
    - Document is shared with/unshared from user
    - User's document is updated
    
    Args:
        user_id: User ID whose cache should be invalidated
        
    Returns:
        Number of cache entries invalidated
    """
    debug_print(
        "Invalidating personal search cache in Cosmos DB",
        "INVALIDATION",
        user_id=user_id[:8]
    )
    
    try:
        # Query all cache entries for this user (partition key = user_id)
        query = "SELECT c.id FROM c WHERE c.user_id = @user_id"
        parameters = [{"name": "@user_id", "value": user_id}]
        
        items = list(cosmos_search_cache_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
        count = len(items)
        
        # Delete each cache entry
        for item in items:
            try:
                cosmos_search_cache_container.delete_item(
                    item=item['id'],
                    partition_key=user_id
                )
            except Exception as e:
                logger.warning(f"Failed to delete cache item {item['id']}: {e}")
        
        if count > 0:
            debug_print(
                f"Invalidated {count} cache entries from Cosmos DB",
                "INVALIDATION",
                user_id=user_id[:8]
            )
            logger.info(f"Invalidated {count} cache entries for user {user_id}")
        
        return count
        
    except Exception as e:
        logger.error(f"Error invalidating personal search cache: {e}")
        debug_print(f"[DEBUG] Invalidation ERROR: {e}", "INVALIDATION", user_id=user_id[:8])
        return 0


def invalidate_group_search_cache(group_id: str) -> int:
    """
    Invalidate all cached searches for a specific group's documents in Cosmos DB.
    
    Call this when:
    - Document is uploaded to group
    - Document is deleted from group
    - Document is shared with/unshared from group
    - Group document is updated
    
    Note: This requires a cross-partition query since cache entries are partitioned by user_id.
    
    Args:
        group_id: Group ID whose cache should be invalidated
        
    Returns:
        Number of cache entries invalidated
    """
    debug_print(
        "Invalidating group search cache in Cosmos DB (affects ALL group members)",
        "INVALIDATION",
        group_id=group_id[:8]
    )
    
    try:
        # Cross-partition query to find all cache entries containing this group
        # Looking for doc_scope containing group references
        query = "SELECT c.id, c.user_id FROM c WHERE CONTAINS(c.doc_scope, @group_id)"
        parameters = [{"name": "@group_id", "value": group_id}]
        
        items = list(cosmos_search_cache_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        count = len(items)
        
        # Delete each cache entry using its partition key
        for item in items:
            try:
                cosmos_search_cache_container.delete_item(
                    item=item['id'],
                    partition_key=item['user_id']
                )
            except Exception as e:
                logger.warning(f"Failed to delete cache item {item['id']}: {e}")
        
        if count > 0:
            debug_print(
                f"Invalidated {count} cache entries from Cosmos DB",
                "INVALIDATION",
                group_id=group_id[:8]
            )
            logger.info(f"Invalidated {count} cache entries for group {group_id}")
        
        return count
        
    except Exception as e:
        logger.error(f"Error invalidating group search cache: {e}")
        debug_print(f"[DEBUG] Invalidation ERROR: {e}", "INVALIDATION", group_id=group_id[:8])
        return 0


def invalidate_public_workspace_search_cache(public_workspace_id: str) -> int:
    """
    Invalidate all cached searches for a specific public workspace's documents in Cosmos DB.
    
    Call this when:
    - Document is uploaded to public workspace
    - Document is deleted from public workspace
    - Public workspace document is updated
    
    Note: This requires a cross-partition query since cache entries are partitioned by user_id.
    
    Args:
        public_workspace_id: Public workspace ID whose cache should be invalidated
        
    Returns:
        Number of cache entries invalidated
    """
    debug_print(
        "Invalidating public workspace cache in Cosmos DB (affects ALL workspace users)",
        "INVALIDATION",
        workspace_id=public_workspace_id[:8]
    )
    
    try:
        # Cross-partition query to find all cache entries containing this public workspace
        # Looking for doc_scope containing workspace references
        query = "SELECT c.id, c.user_id FROM c WHERE CONTAINS(c.doc_scope, @workspace_id)"
        parameters = [{"name": "@workspace_id", "value": public_workspace_id}]
        
        items = list(cosmos_search_cache_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        count = len(items)
        
        # Delete each cache entry using its partition key
        for item in items:
            try:
                cosmos_search_cache_container.delete_item(
                    item=item['id'],
                    partition_key=item['user_id']
                )
            except Exception as e:
                logger.warning(f"Failed to delete cache item {item['id']}: {e}")
        
        if count > 0:
            debug_print(
                f"Invalidated {count} cache entries from Cosmos DB",
                "INVALIDATION",
                workspace_id=public_workspace_id[:8]
            )
            logger.info(f"Invalidated {count} cache entries for public workspace {public_workspace_id}")
        
        return count
        
    except Exception as e:
        logger.error(f"Error invalidating public workspace search cache: {e}")
        debug_print(f"[DEBUG] Invalidation ERROR: {e}", "INVALIDATION", workspace_id=public_workspace_id[:8])
        return 0


def invalidate_document_cache(
    document_id: str,
    user_id: Optional[str] = None,
    group_id: Optional[str] = None,
    public_workspace_id: Optional[str] = None
) -> int:
    """
    Invalidate cache for a specific document across all relevant scopes.
    
    This is a convenience function that invalidates cache in all applicable scopes.
    
    Args:
        document_id: Document ID that changed
        user_id: User ID if personal document
        group_id: Group ID if group document
        public_workspace_id: Public workspace ID if public document
        
    Returns:
        Total number of cache entries invalidated
    """
    total_invalidated = 0
    
    if user_id:
        total_invalidated += invalidate_personal_search_cache(user_id)
    
    if group_id:
        total_invalidated += invalidate_group_search_cache(group_id)
    
    if public_workspace_id:
        total_invalidated += invalidate_public_workspace_search_cache(public_workspace_id)
    
    return total_invalidated


def clear_all_cache() -> int:
    """
    Clear entire search results cache from Cosmos DB.
    
    Use for administrative purposes or testing.
    
    Returns:
        Number of cache entries cleared
    """
    debug_print("Clearing ALL cache entries from Cosmos DB", "ADMIN")
    
    try:
        # Query all items (cross-partition query)
        query = "SELECT c.id, c.user_id FROM c"
        
        items = list(cosmos_search_cache_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        count = len(items)
        
        # Delete each cache entry
        for item in items:
            try:
                cosmos_search_cache_container.delete_item(
                    item=item['id'],
                    partition_key=item['user_id']
                )
            except Exception as e:
                logger.warning(f"Failed to delete cache item {item['id']}: {e}")
        
        logger.info(f"Cleared all search cache ({count} entries)")
        debug_print(f"[DEBUG] Cleared {count} cache entries", "ADMIN")
        return count
        
    except Exception as e:
        logger.error(f"Error clearing all cache: {e}")
        debug_print(f"[DEBUG] Clear cache ERROR: {e}", "ADMIN")
        return 0


def get_cache_stats() -> Dict[str, Any]:
    """
    Get current cache statistics for monitoring from Cosmos DB.
    
    Returns:
        Dictionary with cache metrics
    """
    try:
        # Query all items to count (cross-partition query)
        query = "SELECT VALUE COUNT(1) FROM c"
        
        result = list(cosmos_search_cache_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        total_entries = result[0] if result else 0
        
        # Note: Expired items are deleted by app logic on-demand when accessed
        # Count includes both active and expired entries (no Cosmos TTL)
        cache_enabled, ttl_seconds = get_cache_settings()
        
        # Count expired entries by checking expiry_time field
        now = datetime.now(timezone.utc)
        expired_count = 0
        try:
            query_expired = "SELECT VALUE COUNT(1) FROM c WHERE c.expiry_time < @now"
            result_expired = list(cosmos_search_cache_container.query_items(
                query=query_expired,
                parameters=[{"name": "@now", "value": now.isoformat()}],
                enable_cross_partition_query=True
            ))
            expired_count = result_expired[0] if result_expired else 0
        except:
            expired_count = 0  # Ignore errors in counting expired
        
        return {
            "total_entries": total_entries,
            "active_entries": total_entries - expired_count,
            "expired_entries": expired_count,
            "storage_type": "cosmos_db",
            "cache_enabled": cache_enabled,
            "cache_ttl_seconds": ttl_seconds,
            "note": "Expired entries deleted on-demand by app logic (no Cosmos DB TTL)"
        }
        
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        cache_enabled, ttl_seconds = get_cache_settings()
        return {
            "total_entries": 0,
            "active_entries": 0,
            "storage_type": "cosmos_db",
            "cache_enabled": cache_enabled,
            "cache_ttl_seconds": ttl_seconds,
            "error": str(e)
        }
