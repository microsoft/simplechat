# test_web_iq_research.py
"""
Functional tests for real Web IQ chat and research acquisition.
Version: 0.261.405
Implemented in: 0.261.405

Reuse the network-blocked application bootstrap and actual capture/reader fixtures.
Refs microsoft/simplechat#1887.
"""

from copy import deepcopy
from unittest.mock import patch

from flask import Flask
import pytest

from test_orchestration_external_configuration_capture import (
    capture_runtime, gather_modules, run_gather,
)
from test_orchestration_external_metadata import metadata_world
from test_orchestration_research_capture import research
from test_web_iq_provider import response, settings, transport


def configure(runtime):
    runtime.settings.update(settings())


def test_actual_web_gather_keeps_typed_evidence_and_capture(capture_runtime):
    runtime = capture_runtime
    configure(runtime)
    client = transport([response({"imageResults": [{
        "hostPageUrl": "https://example.com/source", "url": "https://example.com/photo.jpg",
        "caption": "A documented visual example",
    }]})])
    with patch("functions_web_iq.requests.Session", return_value=client):
        _, result = run_gather(runtime, arguments={"query": "Find visual examples", "result_types": ["image"]})
    assert result["status"] == "completed", result
    assert result["citations"][0]["provider"] == "web_iq"
    assert result["citations"][0]["delivery_mode"] == "text_only"
    assert "image_url" not in result["citations"][0]
    assert runtime.state.web == []
    assert client.post.call_args.args[0].endswith("/images")


def test_actual_deep_research_uses_existing_reader_and_recovers(research):
    state = research
    runtime = state.runtime
    configure(runtime)
    runtime.settings["deep_research_max_search_queries_per_turn"] = 2
    state.step["arguments"]["result_types"] = ["web", "news"]
    state.world.run["plan"]["steps"] = [deepcopy(state.step)]
    client = transport([
        response({"webResults": [{"url": "https://example.com/source", "title": "Source", "content": "Evidence"}]}),
        response({"newsResults": [{"url": "https://example.com/news", "title": "News", "content": "News evidence"}]}),
    ])
    with patch("functions_web_iq.requests.Session", return_value=client):
        _, result = run_gather(runtime, "deep_research", arguments=state.step["arguments"])
    assert result["status"] == "completed", result
    assert runtime.state.web == []
    assert runtime.state.pages
    sources = [source for _, source in state.events if source and source["kind"] == "web_iq"]
    assert [source["phase"] for source in sources] == ["definition", "run"]
    assert all(source["result_types"] == ["web", "news"] for source in sources)
    assert any(citation.get("source_kind") == "news" for citation in result["citations"])
    retained = state.retention.retain_gather_result(state.step, state.context, result, source_manifest=[])
    fresh = state.make_attestor()
    provider = state.world.provider(read_configuration=fresh.current, configuration_admitter=None)
    service = state.world.service(provider)
    recovered = service.recover_task_result(
        producer=state.context.result_producer(state.step), input_fingerprint=state.fingerprint,
    )
    assert recovered == retained
    reader = service.open_result(recovered.output("prepared"), require_current_sources=True)
    recovered_value = reader.read_value()
    assert recovered_value == state.admissions[0][0]
    state.planner_calls.assert_not_called()


def test_web_gather_cancellation_is_not_a_provider_failure(capture_runtime):
    runtime = capture_runtime
    configure(runtime)
    state = {"cancelled": False}
    client = transport([])

    def reply(*args, **kwargs):
        state["cancelled"] = True
        return response({"webResults": []})

    client.post.side_effect = reply
    with patch("functions_web_iq.requests.Session", return_value=client):
        _, result = run_gather(runtime, cancel_requested=lambda: state["cancelled"])
    assert result["status"] == "cancelled", result


@pytest.mark.parametrize("v2", [False, True])
def test_manual_v2_boundary_and_current_message_only(capture_runtime, v2):
    runtime = capture_runtime
    configure(runtime)
    messages, citations, runs = [], [], []
    client = transport([response({"webResults": []}), response({"newsResults": []})])
    web = runtime.modules.web
    app = Flask(__name__)
    headers = {"X-SimpleChat-UI": "v2"} if v2 else {}
    with app.test_request_context("/", headers=headers), patch("functions_web_iq.requests.Session", return_value=client):
        success = web.perform_web_search(
            settings=runtime.settings, conversation_id="conversation-1", user_id="owner",
            user_message="Find recent news", user_message_id="message", chat_type="personal",
            document_scope="all", active_group_id=None, active_public_workspace_id=None,
            web_search_query_text="Find recent news", system_messages_for_augmentation=messages,
            agent_citations_list=[], web_search_citations_list=citations, web_search_runs_list=runs,
        )
    assert success is v2
    if v2:
        assert client.post.call_count == 2
        assert all(call.kwargs["json"]["query"] == "Find recent news" for call in client.post.call_args_list)
        assert all(set(call.kwargs["json"]) <= {
            "query", "maxResults", "language", "region", "contentFormat", "maxLength", "safeSearch",
        } for call in client.post.call_args_list)
    else:
        client.post.assert_not_called()
        assert runs[0]["error_type"] == "v2_required"
