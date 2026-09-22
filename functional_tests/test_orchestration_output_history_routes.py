# test_orchestration_output_history_routes.py
"""Verify retained file history and conversation-cleanup classification.

Version: 0.261.127
Implemented in: 0.261.127

Exercise conversation ownership, the public screening/history pipeline, current
output authorization and committed cards. Only external storage/authority I/O
is doubled; history reads must not render, publish or mutate saved messages.
"""

import importlib
from copy import deepcopy
from types import SimpleNamespace

import pytest
from flask import Blueprint
from werkzeug.test import Client
from werkzeug.wrappers import Response

from content_screening.contracts import ScreeningConfigurationError, ScreeningError
from functions_orchestration_artifacts import ORCHESTRATION_ARTIFACT_KEY_PREFIX, ORCHESTRATION_ARTIFACT_KIND
from functions_orchestration_external_identity import ExternalIdentityServiceError
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401


@pytest.fixture
def history_runtime(lifecycle, monkeypatch):
    routes = importlib.import_module("route_backend_conversations")
    authentication = importlib.import_module("functions_authentication")
    monkeypatch.setattr(routes, "cosmos_conversations_container", lifecycle.conversations)
    monkeypatch.setattr(routes, "cosmos_messages_container", lifecycle.messages)
    app = lifecycle.app
    app.config.update(TESTING=True, SECRET_KEY="local-history-test")
    blueprint = Blueprint("backend_conversations", __name__)
    blueprint.before_request(authentication.user_required_blueprint())
    routes.register_route_backend_conversations(blueprint)
    app.register_blueprint(blueprint)
    client = Client(app, Response)
    serializer = app.session_interface.get_signing_serializer(app)
    cookie = serializer.dumps({"user": {"oid": "owner", "roles": ["Admin"]}})
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie)
    return SimpleNamespace(world=lifecycle, routes=routes, app=app, client=client)


def read_history(runtime):
    return runtime.client.get("/api/get_messages", query_string={"conversation_id": "conversation-1"})


@pytest.mark.parametrize("role,metadata,retained", [
    ("file", {"generated_artifact_source": {"kind": ORCHESTRATION_ARTIFACT_KIND}}, True),
    ("file", {"generated_artifact_origin": ORCHESTRATION_ARTIFACT_KIND}, True),
    ("file", {"generated_artifact_idempotency_key": ORCHESTRATION_ARTIFACT_KEY_PREFIX + "private-intent"}, True),
    ("file", {"generated_artifact_source": {"kind": "workflow_saved_output"}}, False),
    ("file", {"generated_artifact_idempotency_key": "generated-export:v1:workflow-intent"}, False),
    ("file", {"generated_artifact_origin": "ordinary_chat"}, False),
    ("file", {}, False),
    ("file", None, False),
    ("file", "legacy-metadata", False),
    ("assistant", {"generated_artifact_origin": ORCHESTRATION_ARTIFACT_KIND}, False),
    ("user", {"generated_artifact_source": {"kind": ORCHESTRATION_ARTIFACT_KIND}}, False),
])
def test_only_retained_file_records_bypass_legacy_conversation_purges(history_runtime, role, metadata, retained):
    message = {
        "id": "message-1", "role": role, "metadata": metadata,
        "file_name": ORCHESTRATION_ARTIFACT_KEY_PREFIX + "not-an-authority-marker",
    }
    before = deepcopy(message)
    result = history_runtime.routes._is_retained_orchestration_file(message)
    assert result is retained
    assert message == before


@pytest.mark.parametrize("revocation", ["source", "screening"])
def test_history_refreshes_current_siblings_without_writing_or_replaying(history_runtime, revocation):
    world = history_runtime.world
    restricted_source = world.retain_source("document-2")
    restricted = world.run(world.prepare("json", reference=restricted_source))
    available = world.run(world.prepare("csv"))
    message = world.output_history()
    message["metadata"]["orchestration"]["outputs"][0]["source_ref"] = "PRIVATE cached binding"
    world.messages.create_item(message)
    stored_messages = deepcopy(world.messages.items)
    writes = (world.runs.sequence, world.results.container.sequence, world.messages.sequence)
    if revocation == "source":
        world.results.denied.add("document-2")
    else:
        world.results.held.add("document-2")
    response = read_history(history_runtime)
    body = response.get_json()
    assert response.status_code == 200, body
    restored = next(item for item in body["messages"] if item["id"] == message["id"])
    current = {item["output_id"]: item for item in restored["metadata"]["orchestration"]["outputs"]}
    assert current[restricted["output_id"]]["state"] == "completed"
    assert current[restricted["output_id"]]["available"] is False
    assert current[restricted["output_id"]]["artifact_message_id"] is None
    assert current[available["output_id"]]["available"] is True
    assert [card["artifact_message_id"] for card in restored["generated_artifacts"]] == [
        available["artifact_message_id"],
    ]
    assert "PRIVATE cached binding" not in response.get_data(as_text=True)
    assert restored["content"] == message["content"] and not restored.get("content_unavailable")
    assert world.messages.items == stored_messages
    assert (world.runs.sequence, world.results.container.sequence, world.messages.sequence) == writes
    assert len(world.render_calls) == world.blobs.uploads == 2


@pytest.mark.parametrize("failure", [
    "source_io", "source_unverified", "screening_configuration", "screening_transient",
    "directory", "output_storage", "result_storage", "message_storage",
    "configuration", "configuration_invalid",
])
def test_history_outage_is_not_a_screening_hold_missing_conversation_or_empty_success(history_runtime, failure):
    world = history_runtime.world
    world.run(world.prepare())
    message = world.output_history()
    world.messages.create_item(message)
    stored_messages = deepcopy(world.messages.items)
    if failure == "output_storage":
        world.runs.fail_reads = True
    elif failure == "result_storage":
        world.results.container.fail_reads = True
    elif failure == "message_storage":
        world.messages.fail_reads = True
    elif failure in ("configuration", "configuration_invalid"):
        code = (
            "external_configuration_metadata_invalid" if failure == "configuration_invalid"
            else "external_configuration_timeout"
        )
        error = history_runtime.routes.ExternalConfigurationServiceError(code)

        def fail(*args, **kwargs):
            raise error

        world.service.authorize_execution = fail
    else:
        error = {
            "source_io": TimeoutError("PRIVATE source outage"),
            "source_unverified": ValueError("PRIVATE malformed authority"),
            "screening_configuration": ScreeningConfigurationError("PRIVATE screening configuration"),
            "screening_transient": ScreeningError("PRIVATE screening outage"),
            "directory": ExternalIdentityServiceError("external_identity_timeout"),
        }[failure]

        def fail(*args, **kwargs):
            raise error

        if failure == "directory":
            world.service.authorize_execution = fail
        else:
            world.service.results.access.source_metadata_reader = fail
    response = read_history(history_runtime)
    body = response.get_json()
    assert response.status_code == 503, body
    assert body["code"] == "output_status_unavailable"
    assert "messages" not in body
    assert "PRIVATE" not in response.get_data(as_text=True)
    assert world.messages.items == stored_messages
    assert len(world.render_calls) == world.blobs.uploads == 1


def test_history_does_not_expose_files_to_another_conversation_viewer(history_runtime):
    world = history_runtime.world
    world.run(world.prepare())
    world.messages.create_item(world.output_history())
    serializer = history_runtime.app.session_interface.get_signing_serializer(history_runtime.app)
    cookie = serializer.dumps({"user": {"oid": "someone-else", "roles": ["Admin"]}})
    history_runtime.client.set_cookie(history_runtime.app.config["SESSION_COOKIE_NAME"], cookie)
    response = read_history(history_runtime)
    assert response.status_code == 403
    assert "messages" not in response.get_json()
