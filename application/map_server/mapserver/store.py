# store.py
"""Storage for maps: the interface the engine relies on, and an in-memory store for tests and local runs."""

import copy
import itertools
import threading
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

MAX_BATCH_OPERATIONS = 100


class ConflictError(Exception):
    """The map changed after it was read, so the write must be retried."""


class StoreError(Exception):
    """The store failed for a reason other than a conflict."""


class MapStore(Protocol):
    """Every item of a map lives in one partition keyed by its map_id; links live in a separate index."""

    async def read_map(self, map_id: str) -> Optional[Tuple[Dict[str, Any], str]]:
        """The map document and its ETag, or None."""

    async def read_item(self, map_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Any item in the map's partition, or None."""

    async def query_features(self, map_id: str, *, dup_keys: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Every feature, or only active features whose dup_key is in dup_keys."""

    async def query_feature_revisions(
        self, map_id: str, feature_ids: Sequence[str], as_of_version: int
    ) -> List[Dict[str, Any]]:
        """Earlier states of the given features that were current at as_of_version."""

    async def query_changes(self, map_id: str, since_version: int, limit: int) -> List[Dict[str, Any]]:
        """Changes after since_version, oldest first."""

    async def commit(
        self,
        map_id: str,
        map_doc: Dict[str, Any],
        expected_etag: Optional[str],
        creates: Sequence[Dict[str, Any]],
        replaces: Sequence[Dict[str, Any]],
    ) -> str:
        """Atomically write the map document and items. A None ETag creates the map. Returns the new ETag."""

    async def upsert_link(self, row: Dict[str, Any]) -> None:
        """Add or refresh an index row (scope_key, map_id)."""

    async def delete_link(self, scope_key: str, map_id: str) -> None:
        """Remove an index row if it exists."""

    async def list_links(self, scope_key: str) -> List[Dict[str, Any]]:
        """Index rows for a scope or conversation."""

    async def close(self) -> None:
        """Release connections."""


class InMemoryMapStore:
    """A store that keeps everything in memory, with the same all-or-nothing commit as a Cosmos batch."""

    def __init__(self):
        self._partitions: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._etags: Dict[str, str] = {}
        self._links: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._etag_counter = itertools.count(1)

    async def read_map(self, map_id: str) -> Optional[Tuple[Dict[str, Any], str]]:
        with self._lock:
            doc = self._partitions.get(map_id, {}).get(map_id)
            if doc is None:
                return None
            return copy.deepcopy(doc), self._etags[map_id]

    async def read_item(self, map_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            doc = self._partitions.get(map_id, {}).get(item_id)
            return copy.deepcopy(doc) if doc is not None else None

    async def query_features(self, map_id: str, *, dup_keys: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        wanted = set(dup_keys) if dup_keys is not None else None
        with self._lock:
            items = list(self._partitions.get(map_id, {}).values())
        features = [item for item in items if item.get("type") == "feature"]
        if wanted is not None:
            features = [item for item in features if item.get("status") == "active" and item.get("dup_key") in wanted]
        return copy.deepcopy(features)

    async def query_feature_revisions(
        self, map_id: str, feature_ids: Sequence[str], as_of_version: int
    ) -> List[Dict[str, Any]]:
        wanted = set(feature_ids)
        with self._lock:
            items = list(self._partitions.get(map_id, {}).values())
        return copy.deepcopy([
            item for item in items
            if item.get("type") == "feature_rev"
            and item.get("feature_id") in wanted
            and item.get("valid_from_version", 0) <= as_of_version <= item.get("valid_to_version", -1)
        ])

    async def query_changes(self, map_id: str, since_version: int, limit: int) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._partitions.get(map_id, {}).values())
        changes = sorted(
            (item for item in items if item.get("type") == "change" and item.get("version", 0) > since_version),
            key=lambda item: item["version"],
        )
        return copy.deepcopy(changes[:limit])

    async def commit(
        self,
        map_id: str,
        map_doc: Dict[str, Any],
        expected_etag: Optional[str],
        creates: Sequence[Dict[str, Any]],
        replaces: Sequence[Dict[str, Any]],
    ) -> str:
        if 1 + len(creates) + len(replaces) > MAX_BATCH_OPERATIONS:
            raise StoreError("Too many operations for one batch.")
        with self._lock:
            partition = self._partitions.get(map_id, {})
            if expected_etag is None:
                if map_id in partition:
                    raise ConflictError()
            elif self._etags.get(map_id) != expected_etag:
                raise ConflictError()
            create_ids = [doc["id"] for doc in creates]
            if len(set(create_ids)) != len(create_ids) or any(item_id in partition for item_id in create_ids):
                raise ConflictError()
            if any(doc["id"] not in partition for doc in replaces):
                raise StoreError("A replaced item doesn't exist.")

            updated = dict(partition)
            updated[map_id] = copy.deepcopy(map_doc)
            for doc in list(creates) + list(replaces):
                updated[doc["id"]] = copy.deepcopy(doc)
            self._partitions[map_id] = updated
            etag = f'"{next(self._etag_counter)}"'
            self._etags[map_id] = etag
            return etag

    async def upsert_link(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self._links.setdefault(row["scope_key"], {})[row["id"]] = copy.deepcopy(row)

    async def delete_link(self, scope_key: str, map_id: str) -> None:
        with self._lock:
            self._links.get(scope_key, {}).pop(map_id, None)

    async def list_links(self, scope_key: str) -> List[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(list(self._links.get(scope_key, {}).values()))

    async def close(self) -> None:
        return None
