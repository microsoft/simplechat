# test_chat_upload_cosmos_response_contract.py
"""Real chat upload context owners with the installed SDK's point responses.

Version: 0.261.328
Implemented in: 0.261.328

Fresh normal/optimized processes import the real web application offline and
exercise existing SDK-default storage doubles, without replacing the owners.
"""

import pytest

from test_orchestration_result_imports import run_probe


PROBE = r'''
import sys

sys.path[:0] = sys.argv[1:3]
from azure.cosmos._cosmos_responses import CosmosDict
from test_support.offline_bootstrap import offline_app_imports


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with offline_app_imports() as environment:
    import app as web
    import route_frontend_chats as route

    container = route.cosmos_conversations_container
    saved = container.upsert_item({
        "id": "upload-owned", "user_id": "upload-user",
        "context": [], "tags": ["retained"], "strict": False,
    })
    check(type(saved) is CosmosDict, "Point writes must return the installed SDK wrapper.")
    context = route._resolve_chat_upload_context(
        " upload-owned ", "upload-user", {"userId": "upload-user"},
    )
    document = context["conversation_item"]
    check(type(document) is CosmosDict, "The real owner should retain its compatible SDK mapping.")
    check(document["_etag"] == saved["_etag"], "Point read lost its ETag.")
    check(document["tags"] == ["retained"], "Point read lost domain fields.")
    check(type(document["context"]) is list, "Nested JSON should remain plain.")
    check(context["conversation_id"] == "upload-owned", "Partition-routed identity changed.")
    check(context["response_conversation_id"] == "upload-owned", "Personal response identity changed.")
    check(context["collaboration_conversation"] is None, "Personal read invented collaboration.")

    before = dict(container.items)
    try:
        route._resolve_chat_upload_context(
            "upload-owned", "other-user", {"userId": "other-user"},
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("SDK mapping bypassed personal conversation ownership.")
    check(container.items == before, "Forbidden upload context changed storage.")

    with web.app.test_request_context():
        for requested_id in ("", "missing-upload"):
            created = route._resolve_chat_upload_context(
                requested_id, "upload-user", {"userId": "upload-user"},
            )
            document = created["conversation_item"]
            check(type(document) is dict, "New conversation must return the constructed domain document.")
            check(document["user_id"] == "upload-user", "New conversation lost its owner.")
            check(created["conversation_id"] == document["id"], "Created conversation identity changed.")
            check(created["response_conversation_id"] == document["id"], "Created response identity changed.")
            check(created["collaboration_conversation"] is None, "Missing context invented collaboration.")
            stored = container.read_item(item=document["id"], partition_key=document["id"])
            check(type(stored) is CosmosDict, "Persisted new conversation is not SDK-shaped.")
            check(bool(stored["_etag"]), "New conversation write lost its ETag.")
            check(stored["title"] == "New Conversation", "New conversation defaults changed.")
            check("_etag" not in document, "Unused write response leaked into the constructed document.")

    check(not environment.network_attempts, "Upload context attempted external I/O.")
print("PASS: chat upload SDK point response contract")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_chat_upload_context_real_owner_sdk_responses(optimized):
    """Verify mapping compatibility, ownership denial, and new/missing contexts."""
    run_probe(PROBE, (), optimized)
