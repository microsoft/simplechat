# test_orchestration_external_root_runtime.py
"""
Actual HTTP external Gather through the default root and explicit JSON Render.
Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139

The real schema, claim, headless runner, source review, configuration attestor,
provider, retained store, renderer and publication run with only directory
identity, page and storage I/O doubled. Separate bootstrap tests exercise the
real Graph HTTP protocol. Restart/history/download must not reacquire content.
Refs microsoft/simplechat#1509.
"""

import asyncio
import importlib
import json
from copy import deepcopy

import pytest
from azure.core import MatchConditions

from functions_orchestration_external_sources import CurrentExternalSourceIdentity
from test_orchestration_harness_routes import modules, real_http_harness
from test_support.orchestration_harness_execution import render_step


@pytest.mark.parametrize("revoke_after_completion", [False, True])
def test_actual_http_default_root_gather_retains_renders_and_rechecks_after_restart(
    real_http_harness, modules, monkeypatch, revoke_after_completion,
):
    runtime = real_http_harness
    harness = runtime.harness
    # Source-review imports require the initialized application fixture.
    review = importlib.import_module("functions_source_review")
    screening = importlib.import_module("content_screening.access")
    authority = {"roles": ("User",)}
    identity_calls = []
    page_calls = []
    url = "https://example.com/source"
    content = "The original first line.\n" + "Verified source sentence. " * 100
    content += "\nThe original final line: caf\u00e9."
    harness.settings.update({
        "enable_url_access": True, "require_member_of_url_access_user": False,
        "source_review_allow_js_rendering": False,
        "source_review_enable_llm_planning": False,
    })
    harness.turn["content"] = f"Review {url} and export the retained findings as JSON."
    stored_turn = harness.messages.read_item(harness.turn["id"], "conversation-1")
    stored_turn["content"] = harness.turn["content"]
    harness.messages.replace_item(
        stored_turn["id"], stored_turn,
        etag=stored_turn["_etag"], match_condition=MatchConditions.IfNotModified,
    )

    def read_identity(*, user_id, conversation_id):
        identity_calls.append((user_id, conversation_id))
        if (user_id, conversation_id) != ("owner", "conversation-1"):
            raise AssertionError("The external reader must keep its original actor.")
        return CurrentExternalSourceIdentity(
            user_id, authority["roles"], True, "owner@example.test",
        )

    def identity_factory(user_id, conversation_id):
        if (user_id, conversation_id) != ("owner", "conversation-1"):
            raise AssertionError("The initialized factory must keep its original actor.")
        return read_identity

    async def fetch_page(**kwargs):
        page_calls.append(kwargs["url"])
        return {
            "status": "reviewed", "url": kwargs["url"], "title": "Original source",
            "content_type": "text/html", "depth": 0, "text_char_count": len(content),
            "excerpts": [content], "links": [], "truncated": False,
        }

    monkeypatch.setattr(harness.bootstrap, "build_external_identity_reader", identity_factory)
    monkeypatch.setattr(review, "_fetch_source_page", fetch_page)
    monkeypatch.setattr(asyncio, "run", modules.execution_loop.run_until_complete)
    record = harness.create(steps=[
        {
            "step_id": "gather", "capability_id": "url_fetch",
            "arguments": {"urls": [url]},
        },
        render_step("findings", "json", source="gather", output="prepared", profile="structured_value_v1"),
    ])
    assert identity_calls == [] and page_calls == []
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    body = response.get_data(as_text=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in body.split("\n\n") if frame.startswith("data:")
    ]
    assert response.status_code == 200, body
    saved = harness.read()
    assert frames[-1]["status"] == saved["status"] == "completed", frames
    assert page_calls == [url]
    assert identity_calls
    assert harness.model_calls == []
    assert harness.blobs.file_uploads == 1
    assert saved["execution_lease"] is None
    assert all(client.closed for client in harness.clients)

    message = harness.messages.read_item(frames[-1]["message_id"], "conversation-1")
    assert len(message["generated_artifacts"]) == len(frames[-1]["outputs"]) == 1
    output_id = frames[-1]["outputs"][0]["output_id"]

    async def no_page_replay(**kwargs):
        raise AssertionError("Stored-result reads must not reacquire the URL.")

    monkeypatch.setattr(review, "_fetch_source_page", no_page_replay)
    if revoke_after_completion:
        authority["roles"] = ()
    services = harness.services()
    original_rows = deepcopy(harness.runs.items)
    with harness.publication_only(services):
        detail = runtime.client.get(
            f"/api/v2/orchestration/runs/{record['id']}",
            query_string={"conversation_id": "conversation-1"},
        )
        current = detail.get_json()
        assert detail.status_code == 200, current
        outputs = current["run"]["outputs"]
        assert len(outputs) == 1 and outputs[0]["output_id"] == output_id
        assert outputs[0]["state"] == "completed"
        assert outputs[0]["available"] is not revoke_after_completion
        with runtime.app.test_request_context():
            history = screening.public_history_messages([message], "owner")
        if revoke_after_completion:
            assert current["run"]["generated_artifacts"] == []
            assert history[0]["generated_artifacts"] == []
            with pytest.raises(PermissionError):
                with services.rendering.open_download(output_id):
                    raise AssertionError("A revoked source must never open a file.")
        else:
            assert len(current["run"]["generated_artifacts"]) == 1
            assert history[0]["generated_artifacts"] == current["run"]["generated_artifacts"]
            with services.rendering.open_download(output_id) as stream:
                downloaded = stream.read()
            prepared = json.loads(downloaded)
            text = json.dumps(prepared, ensure_ascii=False)
            assert prepared["version"] == "orchestration-gathered-content-v1"
            assert prepared["capability_id"] == "url_fetch"
            assert prepared["content_scope"] == "reported_external_content"
            assert "The original first line." in text
            assert "The original final line: caf\u00e9." in text
            assert outputs[0]["size_bytes"] == len(downloaded)
    stored_message = harness.messages.read_item(message["id"], "conversation-1")
    assert harness.runs.items == original_rows
    assert stored_message == message
    assert harness.model_calls == []
    assert harness.blobs.file_uploads == 1 and len(page_calls) == 1
