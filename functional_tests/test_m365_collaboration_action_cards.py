# test_m365_collaboration_action_cards.py
"""
Shared-conversation action-card projection and live stream regression tests.
Version: 0.261.055
Implemented in: 0.261.055

The fresh-process probe imports the real routes with network access blocked and
reuses scoped storage/Graph fixtures. It verifies owner-only details never enter
the shared event cache, shared refresh stays read-only, and model errors retain
the saved card under the visible conversation ID.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_scenarios():
    # Source paths and external-I/O seams must be installed before application imports.
    import json
    from copy import deepcopy
    from flask import Response
    from azure.cosmos.exceptions import CosmosHttpResponseError
    from test_support.offline_bootstrap import offline_app_imports
    from test_m365_action_card_api import cards
    from test_collaboration_group_agent_stream_fix import build_group_agent_stream_test_app
    import functions_m365_pending_delivery as delivery

    with offline_app_imports(), pytest.MonkeyPatch.context() as monkeypatch:
        import route_backend_collaboration as routes

        harness = cards.__wrapped__(monkeypatch)
        created = harness.create("send_mail", shared=True)
        owner_card = harness.client.get(f"/api/msgraph/pending-actions/{created['id']}").get_json()["pending_action"]
        visible_id = "shared-agent-conversation-001"
        viewers = {"owner", "viewer"}

        def authorize_conversation(viewer, conversation_id):
            if viewer not in viewers or conversation_id not in {visible_id, "conversation"}:
                raise PermissionError("The current viewer cannot access this conversation.")
            return "conversation"

        monkeypatch.setitem(delivery._dependencies, "conversation_authorizer", authorize_conversation)
        monkeypatch.setattr(routes, "get_chat_pending_action_cards", harness.service.get_chat_pending_action_cards)
        monkeypatch.setattr(routes, "hydrate_m365_pending_action_cards", harness.service.hydrate_m365_pending_action_cards)
        app, registry, restore = build_group_agent_stream_test_app()
        try:
            actor = {"user_id": "owner", "display_name": "Owner", "email": "owner@example.test"}
            monkeypatch.setattr(routes, "_get_current_collaboration_user", lambda: deepcopy(actor))
            original_source = routes._read_source_message_doc
            original_mirror = routes.mirror_source_message_to_collaboration

            def source(*args):
                message = original_source(*args)
                message["metadata"].update(m365_pending_action_ids=[created["id"]], m365_request_id="request")
                return routes.make_json_serializable(message)

            def mirror(*args, **kwargs):
                message, conversation, saved = original_mirror(*args, **kwargs)
                message["metadata"].update(m365_pending_action_ids=[created["id"]], m365_request_id="request")
                return routes.make_json_serializable(message), conversation, saved

            monkeypatch.setattr(routes, "_read_source_message_doc", source)
            monkeypatch.setattr(routes, "mirror_source_message_to_collaboration", mirror)
            frames = [
                {
                    "type": "m365_pending_action", "pending_action": owner_card,
                    "conversation_id": "conversation", "request_id": "request", "user_message_id": "source-user",
                },
                {"error": "Model response interrupted", "done": True, "request_id": "request"},
            ]

            def internal_stream():
                return Response(
                    [f"data: {json.dumps(frame)}\n\n" for frame in frames],
                    mimetype="text/event-stream",
                )

            app.view_functions["chat_stream_api"] = internal_stream
            response = app.test_client().post(
                f"/api/collaboration/conversations/{visible_id}/stream", json={"content": "Prepare an email"},
            )
            payloads = [
                json.loads(line[5:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data:")
            ]
            live = next(payload for payload in payloads if payload.get("type") == "m365_pending_action")
            check(live["conversation_id"] == visible_id, "Live card used the hidden source conversation.")
            check(live["pending_action"]["conversation_id"] == visible_id, "Card DTO retained a hidden UI destination.")
            check(live["user_message_id"] == "shared-user-message-001", "Live card was not anchored to the shared user message.")
            check(payloads[-1]["m365_pending_actions"][0]["id"] == created["id"], "Unpersisted model error dropped a saved card.")
            notice = next(event for _, event in registry.events if event["event_type"] == "collaboration.m365.pending_action")
            check(notice["payload"]["m365_pending_action_ids"] == [created["id"]], "Shared notification lost its action reference.")
            check("private@example.test" not in json.dumps(registry.events), "The shared cache received sender BCC details.")
            check("Exact reviewed content" not in json.dumps(registry.events), "The shared cache received sender body content.")

            frames[:] = [{
                "done": True, "message_id": "source-agent-message-001",
                "user_message_id": "source-user-message-001", "request_id": "request",
                "m365_pending_actions": [owner_card],
            }]
            response = app.test_client().post(
                f"/api/collaboration/conversations/{visible_id}/stream", json={"content": "Prepare an email"},
            )
            payloads = [
                json.loads(line[5:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data:")
            ]
            check(payloads[-1]["m365_pending_actions"][0]["viewer_is_owner"], "The requesting owner lost the confirmation card.")
            final_event = [
                event for _, event in registry.events
                if event["event_type"] == "collaboration.message.created"
                and event["payload"]["message"].get("role") == "assistant"
            ][-1]
            check("m365_pending_actions" not in final_event["payload"]["message"], "An owner DTO entered the shared event cache.")
            cached = f"data: {json.dumps(final_event)}\n\n"
            replayed = list(routes._collaboration_events_for_viewer([cached], "viewer", visible_id))
            shared_card = json.loads(replayed[0][5:])["payload"]["message"]["m365_pending_actions"][0]
            check(not shared_card["viewer_is_owner"] and not shared_card["can_send_now"], "A shared subscriber inherited sender controls.")
            check("body_preview" not in shared_card["summary"], "A shared subscriber inherited private body content.")
            check("bcc_recipients" not in shared_card["summary"], "A shared subscriber inherited BCC recipients.")

            def can_view(user_id, conversation, **kwargs):
                authorize_conversation(user_id, conversation["id"])

            monkeypatch.setattr(routes, "assert_user_can_view_collaboration_conversation", can_view)
            monkeypatch.setattr(routes, "list_collaboration_messages", lambda conversation_id: [deepcopy(final_event["payload"]["message"])])
            actor["user_id"] = "viewer"
            history = app.test_client().get(f"/api/collaboration/conversations/{visible_id}/messages")
            history_payload = history.get_json()
            check(history.status_code == 200, "Shared history could not be loaded.")
            check(not history_payload["messages"][0]["m365_pending_actions"][0]["can_cancel"], "Shared history exposed Cancel.")

            viewers.remove("viewer")
            before = len(harness.container.queries)
            revoked = list(routes._collaboration_events_for_viewer([cached], "viewer", visible_id))
            check(revoked == [cached], "Projection failure did not preserve the collaboration event.")
            check("private@example.test" not in revoked[0] and len(harness.container.queries) == before, "Revoked subscriber read pending data.")
            viewers.add("viewer")
            harness.container.query_error = CosmosHttpResponseError(status_code=503, message="private storage details")
            unavailable = list(routes._collaboration_events_for_viewer([cached], "viewer", visible_id))
            check(unavailable == [cached], "Storage failure did not preserve the collaboration event.")
            check("private storage details" not in unavailable[0], "Provider diagnostics reached the event stream.")
            check(not harness.writes, "Rendering or replaying a shared card sent an action.")
        finally:
            monkeypatch.undo()
            restore()


def test_shared_cards_use_authorized_projections_and_reference_only_broadcasts():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--probe"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    sys.path.insert(0, str(APP))
    sys.path.insert(0, str(TESTS))
    if "--probe" in sys.argv:
        run_scenarios()
    else:
        sys.exit(pytest.main([str(Path(__file__).resolve())]))
