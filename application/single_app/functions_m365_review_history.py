# functions_m365_review_history.py
"""Bounded owner-partitioned review history, separate from delivery receipts."""

from copy import deepcopy
import json

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from cosmos_document_utils import normalize_cosmos_document


MAX_REVIEW_HISTORY_ITEMS = 40
MAX_REVIEW_HISTORY_BYTES = 1600000


def history_id(action_id):
    return f"pending-review:{action_id}"


def read_review_history(container, action):
    try:
        record = normalize_cosmos_document(container.read_item(
            history_id(action["id"]), partition_key=action["user_id"],
        ))
    except CosmosResourceNotFoundError:
        return None
    if record.get("user_id") != action["user_id"] or record.get("action_id") != action["id"]:
        raise PermissionError("Review history belongs to another action.")
    return record


def commit_review_history(container, action, updated, entry):
    """Commit one action revision and its history in one owner-partition transaction."""
    existing = read_review_history(container, action)
    record = deepcopy(existing) if existing else {
        "id": history_id(action["id"]), "user_id": action["user_id"],
        "action_id": action["id"], "conversation_id": action.get("conversation_id", ""),
        "type": "msgraph_pending_review_history", "items": [],
    }
    items = record["items"]
    if entry.get("assist_turn_id"):
        for item in items:
            if item["id"] == entry["assist_turn_id"] and item["kind"] == "assist":
                item.update(saved=True, applied=True)
    items.append(deepcopy(entry))
    while len(items) > MAX_REVIEW_HISTORY_ITEMS or len(json.dumps(items, ensure_ascii=True).encode()) > MAX_REVIEW_HISTORY_BYTES:
        items.pop(0)
    record["items"] = items
    record["updated_at"] = entry["created_at"]
    operations = [
        ("replace", (action["id"], updated), {"if_match_etag": action["_etag"]}),
        ("replace", (record["id"], record), {"if_match_etag": existing["_etag"]})
        if existing else ("create", (record,)),
    ]
    container.execute_item_batch(batch_operations=operations, partition_key=action["user_id"])
    return normalize_cosmos_document(container.read_item(action["id"], partition_key=action["user_id"]))


def clear_review_history(container, action):
    """Remove editable material on terminal delivery without removing its receipt."""
    existing = read_review_history(container, action)
    if existing is None:
        return
    # The terminal action is authoritative even if a concurrent history request lost its race.
    container.delete_item(existing["id"], partition_key=action["user_id"])
