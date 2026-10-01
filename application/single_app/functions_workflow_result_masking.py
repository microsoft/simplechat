# functions_workflow_result_masking.py
"""Recognize and withhold chat messages that rely on a workflow result.

This module has no application imports, so storage code such as collaboration
conversion can use it without importing the result reader. The read-time lineage
check in functions_saved_analysis and the collaboration copy both build their
withheld form here, so a hidden answer looks the same wherever it is withheld.
"""

from collections.abc import Mapping
from copy import deepcopy


WORKFLOW_RESULT_VERSION = "workflow-result-v1"
WORKFLOW_RESULT_UNAVAILABLE_MESSAGE = (
    "This answer is unavailable because access to the workflow result it used could not be confirmed."
)
WORKFLOW_RESULT_MESSAGE_KEYS = ("workflow_result", "workflow_result_context", "workflow_result_contexts")
# A Follow up question carries the context and its answer the descriptor. A later answer
# that only inherited the lineage (workflow_result_contexts) isn't a Follow up turn.
FOLLOW_UP_MESSAGE_KEYS = ("workflow_result", "workflow_result_context")

# Identity and placement only. The collaboration fields keep a shared copy's sender and
# reply position when it is withheld again on read.
_KEPT_MESSAGE_FIELDS = (
    "id", "conversation_id", "role", "timestamp", "model_deployment_name", "agent_display_name", "agent_name",
    "message_kind", "reply_to_message_id", "sender",
)
_KEPT_METADATA_FIELDS = (
    "thread_info", "user_info", "masked", "masked_ranges", "sender", "source_message_id", "source_role",
)
_CLEARED_FIELDS = ("agent_citations", "hybrid_citations", "web_search_citations", "thoughts")


def message_uses_workflow_result(message):
    """True when a stored message's metadata links it to a workflow result in any form."""
    metadata = message.get("metadata") if isinstance(message, Mapping) else None
    return isinstance(metadata, Mapping) and any(key in metadata for key in WORKFLOW_RESULT_MESSAGE_KEYS)


def message_asks_about_workflow_result(message):
    """True for a Follow up question or its answer, the turns a retry or edit can't replay."""
    metadata = message.get("metadata") if isinstance(message, Mapping) else None
    return isinstance(metadata, Mapping) and any(key in metadata for key in FOLLOW_UP_MESSAGE_KEYS)


def withhold_workflow_result_message(message):
    """Return the withheld form of a message that relies on a workflow result.

    A question keeps the user's own text and loses only its link to the result.
    Any other message keeps its identity and thread placement, and its content,
    citations and thoughts are replaced. The input is never changed.
    """
    message = message if isinstance(message, Mapping) else {}
    metadata = message.get("metadata") if isinstance(message.get("metadata"), Mapping) else {}
    if message.get("role") == "user":
        kept = deepcopy(dict(message))
        kept["metadata"] = {
            key: deepcopy(value) for key, value in metadata.items() if key not in WORKFLOW_RESULT_MESSAGE_KEYS
        }
        return kept
    withheld = {key: deepcopy(message[key]) for key in _KEPT_MESSAGE_FIELDS if key in message}
    withheld["content"] = WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
    withheld["metadata"] = {key: deepcopy(metadata[key]) for key in _KEPT_METADATA_FIELDS if key in metadata}
    withheld["metadata"]["workflow_result"] = {"version": WORKFLOW_RESULT_VERSION, "available": False}
    for field in _CLEARED_FIELDS:
        withheld[field] = []
    return withheld
