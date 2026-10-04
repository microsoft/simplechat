# cosmos_store.py
"""Cosmos DB storage: one partition per map, written with transactional batches, plus a scope and conversation index."""

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient

from .settings import Settings
from .store import MAX_BATCH_OPERATIONS, ConflictError, StoreError

LOGGER = logging.getLogger("mapserver.store")

SYSTEM_PROPERTIES = ("_rid", "_self", "_attachments", "_ts", "_etag", "_lsn")
CONFLICT_STATUS_CODES = (409, 412)


def _clean(item: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in item.items() if key not in SYSTEM_PROPERTIES}


class CosmosMapStore:
    def __init__(self, client: CosmosClient, database_name: str, maps_container_name: str, links_container_name: str):
        database = client.get_database_client(database_name)
        self._client = client
        self._maps = database.get_container_client(maps_container_name)
        self._links = database.get_container_client(links_container_name)

    @classmethod
    def from_settings(cls, settings: Settings, credential: Optional[Any] = None) -> "CosmosMapStore":
        client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key or credential)
        return cls(client, settings.cosmos_database, settings.maps_container, settings.links_container)

    async def _query(self, container: Any, query: str, parameters: List[Dict[str, Any]], partition_key: str) -> List[Dict[str, Any]]:
        try:
            return [
                _clean(item)
                async for item in container.query_items(query=query, parameters=parameters, partition_key=partition_key)
            ]
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            raise StoreError(f"Query failed with status {exc.status_code}.") from exc

    async def read_map(self, map_id: str) -> Optional[Tuple[Dict[str, Any], str]]:
        item = await self.read_item(map_id, map_id, keep_etag=True)
        if item is None or item.get("type") != "map":
            return None
        etag = str(item.get("_etag") or "")
        return _clean(item), etag

    async def read_item(self, map_id: str, item_id: str, keep_etag: bool = False) -> Optional[Dict[str, Any]]:
        try:
            item = await self._maps.read_item(item=item_id, partition_key=map_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            raise StoreError(f"Read failed with status {exc.status_code}.") from exc
        return item if keep_etag else _clean(item)

    async def query_features(self, map_id: str, *, dup_keys: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        if dup_keys is None:
            return await self._query(self._maps, "SELECT * FROM c WHERE c.type = 'feature'", [], map_id)
        if not dup_keys:
            return []
        return await self._query(
            self._maps,
            "SELECT * FROM c WHERE c.type = 'feature' AND c.status = 'active' AND ARRAY_CONTAINS(@keys, c.dup_key)",
            [{"name": "@keys", "value": list(dup_keys)}],
            map_id,
        )

    async def query_feature_revisions(
        self, map_id: str, feature_ids: Sequence[str], as_of_version: int
    ) -> List[Dict[str, Any]]:
        if not feature_ids:
            return []
        return await self._query(
            self._maps,
            "SELECT * FROM c WHERE c.type = 'feature_rev' AND ARRAY_CONTAINS(@ids, c.feature_id) "
            "AND c.valid_from_version <= @version AND c.valid_to_version >= @version",
            [{"name": "@ids", "value": list(feature_ids)}, {"name": "@version", "value": int(as_of_version)}],
            map_id,
        )

    async def query_changes(self, map_id: str, since_version: int, limit: int) -> List[Dict[str, Any]]:
        # Cosmos needs TOP as a literal; limit is an int the engine already bounded.
        top = max(1, min(1000, int(limit)))
        return await self._query(
            self._maps,
            f"SELECT TOP {top} * FROM c WHERE c.type = 'change' AND c.version > @since ORDER BY c.version ASC",
            [{"name": "@since", "value": int(since_version)}],
            map_id,
        )

    async def commit(
        self,
        map_id: str,
        map_doc: Dict[str, Any],
        expected_etag: Optional[str],
        creates: Sequence[Dict[str, Any]],
        replaces: Sequence[Dict[str, Any]],
    ) -> str:
        operations: List[Tuple[Any, ...]] = []
        if expected_etag is None:
            operations.append(("create", (map_doc,)))
        else:
            operations.append(("replace", (map_id, map_doc), {"if_match_etag": expected_etag}))
        operations.extend(("create", (item,)) for item in creates)
        operations.extend(("replace", (item["id"], item)) for item in replaces)
        if len(operations) > MAX_BATCH_OPERATIONS:
            raise StoreError("Too many operations for one batch.")
        try:
            results = await self._maps.execute_item_batch(batch_operations=operations, partition_key=map_id)
        except cosmos_exceptions.CosmosBatchOperationError as exc:
            if exc.status_code in CONFLICT_STATUS_CODES:
                raise ConflictError() from exc
            raise StoreError(f"Batch failed with status {exc.status_code}.") from exc
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            if exc.status_code in CONFLICT_STATUS_CODES:
                raise ConflictError() from exc
            raise StoreError(f"Batch failed with status {exc.status_code}.") from exc
        first = results[0] if results else {}
        return str(first.get("eTag") or (first.get("resourceBody") or {}).get("_etag") or "")

    async def upsert_link(self, row: Dict[str, Any]) -> None:
        try:
            await self._links.upsert_item(body=row)
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            raise StoreError(f"Index write failed with status {exc.status_code}.") from exc

    async def delete_link(self, scope_key: str, map_id: str) -> None:
        try:
            await self._links.delete_item(item=map_id, partition_key=scope_key)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            raise StoreError(f"Index delete failed with status {exc.status_code}.") from exc

    async def list_links(self, scope_key: str) -> List[Dict[str, Any]]:
        return await self._query(self._links, "SELECT * FROM c", [], scope_key)

    async def close(self) -> None:
        await self._client.close()
