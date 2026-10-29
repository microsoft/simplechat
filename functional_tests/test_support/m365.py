# m365.py
"""Scoped cloud fakes for Microsoft 365 behavior tests (version 0.261.031)."""

import copy
import threading
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.cosmos import exceptions


WORKFLOW_REVIEW = {
    "instructions": "Summarize recent mail without sending messages.",
    "capabilities": "Email: read messages only.",
    "runtime_inputs": "No free-form instructions or destination overrides.",
    "triggers": "Manual runs and the saved schedule.",
    "destinations": "The approved conversation and its recorded audience.",
}


class Clock:
    def __init__(self, value=None):
        self.value = value or datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


class Pages:
    def __init__(self, rows, page_size, continuation_token):
        self.rows = rows
        self.page_size = page_size
        self.offset = int(continuation_token or 0)
        self.continuation_token = continuation_token

    def __iter__(self):
        return self

    def __next__(self):
        if self.offset >= len(self.rows):
            self.continuation_token = None
            raise StopIteration
        page = self.rows[self.offset:self.offset + self.page_size]
        self.offset += len(page)
        self.continuation_token = str(self.offset) if self.offset < len(self.rows) else None
        return iter(copy.deepcopy(page))


class Query:
    def __init__(self, rows, page_size):
        self.rows = rows
        self.page_size = page_size

    def __iter__(self):
        return iter(copy.deepcopy(self.rows))

    def by_page(self, continuation_token=None):
        return Pages(self.rows, self.page_size, continuation_token)


class CosmosContainer:
    """Implements conditional replace/batches, partitions, and native paging."""

    def __init__(self, partition_field="group_id"):
        self.partition_field = partition_field
        self.items = {}
        self.lock = threading.RLock()
        self.revision = 0
        self.before_batch = None

    def _key(self, body):
        return body[self.partition_field], body["id"]

    def _saved(self, body):
        self.revision += 1
        return {**copy.deepcopy(body), "_etag": str(self.revision)}

    def create_item(self, body=None, **kwargs):
        with self.lock:
            key = self._key(body)
            if key in self.items:
                raise exceptions.CosmosResourceExistsError(status_code=409, message="Already exists.")
            self.items[key] = self._saved(body)
            return copy.deepcopy(self.items[key])

    def read_item(self, item, partition_key):
        with self.lock:
            key = partition_key, item
            if key not in self.items:
                raise exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found.")
            return copy.deepcopy(self.items[key])

    def replace_item(self, item, body, *, etag, match_condition):
        """Match Cosmos replace semantics: partition routing comes from the body."""
        with self.lock:
            partition_key = body[self.partition_field]
            current = self.read_item(item, partition_key)
            if match_condition != MatchConditions.IfNotModified or current["_etag"] != etag:
                raise exceptions.CosmosHttpResponseError(status_code=412, message="ETag conflict.")
            if self._key(body) != (partition_key, item):
                raise ValueError("Partition or id changed.")
            self.items[(partition_key, item)] = self._saved(body)
            return copy.deepcopy(self.items[(partition_key, item)])

    def upsert_item(self, body):
        with self.lock:
            self.items[self._key(body)] = self._saved(body)
            return copy.deepcopy(self.items[self._key(body)])

    def delete_item(self, item, partition_key):
        with self.lock:
            self.read_item(item, partition_key)
            del self.items[(partition_key, item)]

    def execute_item_batch(self, batch_operations, partition_key):
        if self.before_batch is not None:
            self.before_batch()
        with self.lock:
            staged = copy.deepcopy(self.items)
            for operation in batch_operations:
                name, args = operation[:2]
                options = operation[2] if len(operation) > 2 else {}
                if name == "replace":
                    item_id, body = args
                    key = (partition_key, item_id)
                    if staged.get(key, {}).get("_etag") != options.get("if_match_etag"):
                        raise exceptions.CosmosHttpResponseError(status_code=412, message="ETag conflict.")
                elif name == "create":
                    body = args[0]
                    key = self._key(body)
                    if key in staged:
                        raise exceptions.CosmosResourceExistsError(status_code=409, message="Already exists.")
                else:
                    raise AssertionError(f"Unsupported operation: {name}")
                if self._key(body)[0] != partition_key:
                    raise AssertionError("Cross-partition transaction.")
                staged[key] = self._saved(body)
            self.items = staged
            return []

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False, max_item_count=100):
        with self.lock:
            values = {item["name"]: item["value"] for item in parameters or []}
            rows = copy.deepcopy(list(self.items.values()))
        if partition_key is not None:
            rows = [row for row in rows if row[self.partition_field] == partition_key]
        elif not enable_cross_partition_query:
            raise AssertionError("Unscoped query.")
        for field in ("request_type", "tenant_id", "request_scope", "logical_request", "status"):
            if f"@{field}" in values:
                rows = [row for row in rows if row.get(field) == values[f"@{field}"]]
        if "@kind" in values:
            rows = [row for row in rows if row.get("record_kind") == values["@kind"]]
        for kind in ("m365_approval", "m365_audit"):
            if f"c.record_kind = '{kind}'" in query:
                rows = [row for row in rows if row.get("record_kind") == kind]
        if "c.status = 'pending'" in query:
            rows = [row for row in rows if row.get("status") == "pending"]
        if "c.continuation_status = 'pending'" in query:
            rows = [
                row for row in rows
                if row.get("continuation_status") == "pending" or (
                    row.get("continuation_status") == "claimed"
                    and (row.get("continuation_lease") or {}).get("expires_at", "") <= values["@now"]
                )
            ]
        elif "@now" in values:
            rows = [row for row in rows if row.get("expires_at", "") <= values["@now"]]
        if "@conversation_id" in values:
            rows = [
                row for row in rows
                if row.get("context", {}).get("conversation_id") == values["@conversation_id"]
            ]
        rows.sort(key=lambda row: (row.get("created_at", ""), row["id"]), reverse=True)
        return Query(rows, max_item_count)


class Notifications:
    def __init__(self):
        self.calls = []

    def __call__(self, approval):
        self.calls.append(copy.deepcopy(approval))
        return {"id": f"{approval['id']}:{approval['status']}"}
