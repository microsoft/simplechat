# functions_chat_message_metadata.py
"""Conditional message metadata writes with caller-owned conflict handling.

This storage primitive does not import content checks, settings, or bootstrap
owners. Callers supply their domain exception factory for exhausted conflicts.
"""

from copy import deepcopy

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosAccessConditionFailedError


def patch_message_metadata(container, message, fields=("thread_info",), *, conflict_error):
    incoming = message.get("metadata") or {}
    for _attempt in range(3):
        current = container.read_item(item=message["id"], partition_key=message["conversation_id"])
        updated = deepcopy(current)
        metadata = updated.setdefault("metadata", {})
        for key in fields:
            if key not in incoming:
                continue
            if key == "thread_info":
                metadata.setdefault("thread_info", {}).update(deepcopy(incoming[key]))
            else:
                metadata[key] = deepcopy(incoming[key])
        try:
            return container.replace_item(
                item=current["id"], body=updated, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except CosmosAccessConditionFailedError:
            continue
    raise conflict_error()
