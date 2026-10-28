# test_export_evidence_cosmos_contract.py
"""Functional tests for export owners with real SDK point-response types.

Version: 0.261.389
Implemented in: 0.261.388

Real owners run with external storage/model I/O blocked. Point responses keep
SDK mapping types and ETags; query rows remain ordinary JSON dictionaries.
"""

from copy import deepcopy
import base64
import importlib
import io
from pathlib import Path
import sys
from unittest.mock import Mock

from azure.cosmos._cosmos_responses import CosmosDict
from PIL import Image
import pytest

from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_revisions import AtomicMemoryContainer


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"


@pytest.fixture(scope="module")
def exports():
    previous = set(sys.modules)
    added_path = str(APP) not in sys.path
    with offline_app_imports():
        if added_path:
            sys.path.insert(0, str(APP))
        try:
            module = importlib.import_module("route_backend_conversation_export")
            yield module
        finally:
            for name in set(sys.modules) - previous:
                if str(APP) in (getattr(sys.modules[name], "__file__", "") or ""):
                    sys.modules.pop(name, None)
            if added_path:
                sys.path.remove(str(APP))


@pytest.fixture
def containers(exports, monkeypatch):
    conversations = AtomicMemoryContainer("id")
    messages = AtomicMemoryContainer("conversation_id")
    conversation = conversations.upsert_item({"id": "export-conversation", "user_id": "owner"})
    message = messages.upsert_item({
        "id": "export-answer", "conversation_id": "export-conversation", "role": "assistant",
        "content": "The supported answer.", "metadata": {
            "evidence_status": {
                "version": 1, "scope": "returned_evidence", "state": "partial",
                "sources": [{"name": "Retained source", "document_id": "document-1", "state": "partial",
                             "evidence_count": 1}],
                "source_count": 1, "suggestions": ["Check the source details for the unanswered part."],
            },
        },
    })
    monkeypatch.setattr(exports, "cosmos_conversations_container", conversations)
    monkeypatch.setattr(exports, "cosmos_messages_container", messages)
    return conversations, messages, conversation, message


def test_conversation_export_owner_accepts_sdk_points_and_keeps_query_rows_plain(exports, containers, monkeypatch):
    conversations, messages, conversation, message = containers
    query = Mock(return_value=[deepcopy(dict(message))])
    monkeypatch.setattr(messages, "query_items", query)
    loaded, rows = exports._load_exportable_conversation_for_user("owner", "export-conversation")
    assert type(conversation) is CosmosDict and type(loaded) is CosmosDict
    assert loaded["_etag"] == conversation["_etag"]
    assert type(rows[0]) is dict
    assert query.call_args.kwargs["partition_key"] == "export-conversation"
    denied = exports._load_exportable_conversation_for_user("another-user", "export-conversation")
    assert denied is None


def test_single_message_export_owner_keeps_sdk_mapping_lineage_and_notice(exports, containers):
    _, _, _, original = containers
    loaded = exports._load_export_message_for_user("owner", "export-conversation", "export-answer")
    assert loaded["id"] == original["id"]
    assert loaded["_etag"] == original["_etag"]
    rendered = exports._render_message_export_content(loaded)
    assert "Evidence: Partial document evidence." in rendered
    with pytest.raises(PermissionError):
        exports._load_export_message_for_user("another-user", "export-conversation", "export-answer")


def test_generated_image_export_owner_reopens_sdk_point_after_plain_query_rows(exports, containers, monkeypatch):
    _, messages, _, _ = containers
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="PNG")
    image = messages.upsert_item({
        "id": "export-image", "conversation_id": "export-conversation", "role": "image",
        "content": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        "metadata": {"image_proposal": {"source_assistant_message_id": "export-answer", "visualId": "figure-1"}},
    })
    query_row = {**deepcopy(dict(image)), "content": ""}
    # Only the SDK point document has image bytes, so a failed point read cannot pass via fallback.
    monkeypatch.setattr(messages, "query_items", Mock(return_value=[query_row]))
    assets = exports._load_generated_image_proposal_assets("export-conversation", "export-answer")
    assert len(assets) == 1
    assert assets[0]["message_id"] == "export-image"
    assert assets[0]["data_uri"].startswith("data:image/png;base64,")


def test_changed_tabular_test_containers_now_return_sdk_points_by_default():
    # The peer harness establishes standalone application paths and must not run at collection.
    from test_tabular_row_orchestration_scale import _load_authorization_helper, _load_idempotent_artifact_helper

    authorize = _load_authorization_helper("owner")
    conversation_container = authorize.__globals__["cosmos_conversations_container"]
    point = conversation_container.read_item("conversation", "conversation")
    assert type(point) is CosmosDict
    upload, messages = _load_idempotent_artifact_helper()
    other_conversations = upload.__globals__["cosmos_conversations_container"]
    other_point = other_conversations.read_item("conversation", "conversation")
    assert type(other_point) is CosmosDict
    written = messages.upsert_item({"id": "artifact", "_etag": "kept"})
    read = messages.read_item("artifact", "conversation")
    assert type(written) is CosmosDict and type(read) is CosmosDict
    assert written["_etag"] == read["_etag"] == "kept"
