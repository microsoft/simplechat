# test_chat_artifact_download_bytes.py
"""
Functional regressions for authorized generated artifact download bytes.
Version: 0.261.113
Implemented in: 0.261.113

Production route, message/lifecycle authorization, internal blob reader, saved
analysis/source reader, and response functions execute against isolated storage.
Workspace-document admission is deliberately unavailable: a standalone generated
artifact must not be misidentified as an ID-less workspace source.
"""

import ast
import hashlib
import logging
import mimetypes
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from azure.core.exceptions import AzureError, ResourceNotFoundError
from flask import Flask, Response, jsonify, request
from werkzeug.utils import secure_filename

from test_generated_artifact_lifecycle_authorization import (
    FakeContainer,
    FakeNotFound,
    load_operation_helpers,
)
from test_saved_analysis_service import read_options, saved, saved_chat  # noqa: F401


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
CONVERSATION = "conversation-1"
ARTIFACT = "artifact-1"
DOWNLOAD = f"/api/chat_artifacts/download?conversation_id={CONVERSATION}&message_id={ARTIFACT}"
CSV = b"finding,source\nSole supplier,Supplier\n"
MARKDOWN = b"# Findings\n\nSole supplier -- Supplier.\n"


def load_definitions(filename, names, namespace):
    tree = ast.parse((APP / filename).read_text(encoding="utf-8"))
    definitions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            definitions.append(node)
    assert {node.name for node in definitions} == names
    exec(compile(ast.Module(body=definitions, type_ignores=[]), filename, "exec"), namespace)


class SnapshotContainer(FakeContainer):
    def read_item(self, item, partition_key):
        return deepcopy(super().read_item(item, partition_key))


@pytest.fixture
def artifact_download(saved_chat):
    identity = {"user_id": "reader", "allowed": True, "approved": True}
    metadata = {
        "is_generated_chat_artifact": True,
        "generated_artifact_output_format": "csv",
        "generated_artifact_content_sha256": hashlib.sha256(CSV).hexdigest(),
        **saved.analysis_artifact_metadata({
            "kind": "chat", "conversation_id": CONVERSATION, "message_id": "assistant-1",
        }),
    }
    artifact = {
        "id": ARTIFACT, "conversation_id": CONVERSATION, "role": "file",
        "filename": "review.json", "file_content_source": "blob",
        "blob_container": "chat-files", "blob_path": "owner/conversation/generated/review.csv",
        "_etag": "artifact-v1", "metadata": metadata,
    }
    conversations = SnapshotContainer({CONVERSATION: {"id": CONVERSATION, "user_id": "owner"}})
    messages = SnapshotContainer({ARTIFACT: artifact})
    reads = []
    state = {"content": CSV, "failure": None, "after_read": None}
    logs = []

    def participate(user_id, conversation):
        if not identity["allowed"] or user_id not in ("owner", "reader"):
            raise PermissionError("PRIVATE_CONVERSATION_DETAIL")
        assert conversation["id"] == CONVERSATION
        return {"is_owner": user_id == "owner", "user_id": user_id}

    def approval(user_id, message):
        if not identity["approved"]:
            raise PermissionError("PRIVATE_APPROVAL_DETAIL")

    def authorize_analysis(user_id, message):
        return saved.authorize_analysis_artifact(
            user_id, message, parents_loader=lambda *args: [saved_chat["message"]],
            result_reader=lambda actor, context: saved.load_saved_analysis(actor, context, **read_options(saved_chat)),
        )

    publication = load_operation_helpers(conversations.items[CONVERSATION], artifact)
    publication["authorize_analysis_artifact"] = authorize_analysis

    def get_blob_client(*, container, blob):
        reads.append((container, blob))
        assert (container, blob) == ("chat-files", "owner/conversation/generated/review.csv")

        def readall():
            if state["failure"]:
                raise state["failure"]
            content = state["content"]
            if state["after_read"]:
                state["after_read"]()
            return content

        return SimpleNamespace(download_blob=lambda: SimpleNamespace(readall=readall))

    namespace = {
        "hashlib": hashlib, "logging": logging, "mimetypes": mimetypes, "os": os,
        "quote": quote, "secure_filename": secure_filename,
        "Response": Response, "jsonify": jsonify, "request": request,
        "AzureError": AzureError, "ResourceNotFoundError": ResourceNotFoundError,
        "CosmosResourceNotFoundError": FakeNotFound,
        "CLIENTS": {"storage_account_office_docs_client": SimpleNamespace(get_blob_client=get_blob_client)},
        "cosmos_conversations_container": conversations, "cosmos_messages_container": messages,
        "build_conversation_participation_context": participate,
        "assert_generated_file_approval_allows_download": approval,
        "assert_generated_chat_artifact_is_published_for_user": publication["assert_generated_chat_artifact_is_published_for_user"],
        "get_current_user_id": lambda: identity["user_id"],
        "log_event": lambda message, **kwargs: logs.append((message, kwargs)),
        "debug_print": lambda *args: None,
        "serve_enhanced_citation_content": lambda *args, **kwargs: pytest.fail(
            "A generated chat artifact must not enter workspace-document admission."
        ),
    }
    load_definitions("functions_simplechat_operations.py", {"download_blob_content"}, namespace)
    load_definitions("route_enhanced_citations.py", {
        "_get_authorized_chat_artifact_message", "_resolve_generated_artifact_file_name",
        "_normalize_response_file_name", "_build_content_disposition",
        "_serve_chat_artifact_download", "download_chat_artifact",
    }, namespace)
    app = Flask(__name__)
    app.add_url_rule("/api/chat_artifacts/download", view_func=namespace["download_chat_artifact"])
    return SimpleNamespace(
        client=app.test_client(), artifact=artifact, identity=identity, messages=messages,
        conversations=conversations, reads=reads, state=state, saved=saved_chat,
        namespace=namespace, logs=logs,
    )


@pytest.mark.parametrize("format,content,content_type,filename", [
    ("csv", CSV, "text/csv", "review.csv"),
    ("md", MARKDOWN, "text/markdown", "review.md"),
])
def test_download_returns_exact_bytes_and_server_owned_filename(artifact_download, format, content, content_type, filename):
    fixture = artifact_download
    fixture.state["content"] = content
    fixture.artifact["metadata"].update(
        generated_artifact_output_format=format,
        generated_artifact_content_sha256=hashlib.sha256(content).hexdigest(),
    )
    response = fixture.client.get(DOWNLOAD + "&blob_container=foreign&blob_path=private&filename=forged.txt")
    assert response.status_code == 200
    assert response.data == content
    assert response.mimetype == content_type
    assert int(response.headers["Content-Length"]) == len(content)
    assert f'filename="{filename}"' in response.headers["Content-Disposition"]
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert fixture.saved["state"]["resolutions"] >= 2
    assert fixture.reads == [("chat-files", "owner/conversation/generated/review.csv")]


@pytest.mark.parametrize("denial", ["conversation", "source", "approval", "staged", "deleted_parent"])
def test_denial_happens_before_blob_read(artifact_download, denial):
    fixture = artifact_download
    if denial == "conversation":
        fixture.identity["allowed"] = False
    elif denial == "source":
        fixture.saved["state"]["source_allowed"] = False
    elif denial == "approval":
        fixture.identity["approved"] = False
    elif denial == "staged":
        fixture.artifact["metadata"]["generated_artifact_lifecycle_state"] = "staged"
    else:
        fixture.saved["message"]["metadata"]["masked_ranges"] = [{"start": 0, "end": 10}]
    response = fixture.client.get(DOWNLOAD)
    assert response.status_code == 403
    assert fixture.reads == []
    assert b"PRIVATE" not in response.data and CSV not in response.data


@pytest.mark.parametrize("change", ["source", "membership", "approval", "reference", "revision"])
def test_access_or_identity_changes_during_read_never_release_bytes(artifact_download, change):
    fixture = artifact_download

    def change_during_read():
        if change == "source":
            fixture.saved["state"]["source_allowed"] = False
        elif change == "membership":
            fixture.identity["allowed"] = False
        elif change == "approval":
            fixture.identity["approved"] = False
        elif change == "reference":
            fixture.artifact["blob_path"] = "different-reference"
        else:
            fixture.artifact["_etag"] = "artifact-v2"

    fixture.state["after_read"] = change_during_read
    response = fixture.client.get(DOWNLOAD)
    assert response.status_code == (404 if change in ("reference", "revision") else 403)
    assert response.is_json and CSV not in response.data


@pytest.mark.parametrize("missing", ["conversation", "message", "reference", "blob"])
def test_missing_artifact_has_a_safe_not_found_response(artifact_download, missing):
    fixture = artifact_download
    if missing == "conversation":
        fixture.conversations.items.clear()
    elif missing == "message":
        fixture.messages.items.clear()
    elif missing == "reference":
        fixture.artifact.pop("blob_path")
    else:
        fixture.state["failure"] = ResourceNotFoundError("PRIVATE_STORAGE_DETAIL")
    response = fixture.client.get(DOWNLOAD)
    assert response.status_code == 404
    assert b"PRIVATE" not in response.data


@pytest.mark.parametrize("missing_client", [False, True])
def test_unavailable_storage_reports_retry_without_exposing_sdk_details(artifact_download, missing_client):
    fixture = artifact_download
    if missing_client:
        fixture.namespace["CLIENTS"].clear()
    else:
        fixture.state["failure"] = AzureError("PRIVATE_STORAGE_DETAIL")
    response = fixture.client.get(DOWNLOAD)
    assert response.status_code == 503
    assert b"PRIVATE" not in response.data
    assert fixture.logs and "error_type" in fixture.logs[-1][1]["extra"]


def test_legacy_artifact_without_saved_analysis_or_hash_remains_readable(artifact_download):
    fixture = artifact_download
    fixture.artifact["metadata"] = {"is_generated_chat_artifact": True}
    fixture.artifact["filename"] = "legacy.csv"
    fixture.saved["state"]["source_allowed"] = False
    response = fixture.client.get(DOWNLOAD)
    assert response.status_code == 200 and response.data == CSV


def test_modified_blob_bytes_do_not_pass_the_saved_content_digest(artifact_download):
    fixture = artifact_download
    fixture.state["content"] = b"Replaced private content"
    response = fixture.client.get(DOWNLOAD)
    assert response.status_code == 404
    assert b"Replaced private content" not in response.data
