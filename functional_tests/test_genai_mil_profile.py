# test_genai_mil_profile.py
"""
GenAI.mil protocol, origin approval, safe errors, streaming, and nullable usage.
Version: 0.261.052
Implemented in: 0.261.052

Uses actual profile/policy/SDK adapters with external HTTP replaced locally.
No live GenAI.mil access, tokens, deployment files, or billable inference.
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
from openai import APIStatusError, OpenAI
import pytest

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_model_endpoint_urls import resolve_model_endpoint_route
from model_endpoint_clients import (
    OpenAIStyleChatCompletionClient, bind_model_endpoint_request_policy,
    sanitize_custom_async_openai_client,
)
from model_endpoint_profiles import (
    GENAI_MIL_API_BASE, GENAI_MIL_PROFILE, GENAI_MIL_PORTAL, GenAIMilRequestError,
    ModelEndpointProfileError, merge_profile_credential_approval, prepare_genai_request,
    validate_genai_profile,
)
from model_endpoint_usage import project_completion_token_usage


def endpoint():
    return {
        "id": "genai-endpoint", "provider": "custom", "profile": GENAI_MIL_PROFILE,
        "routing_schema_version": 2, "name": "GenAI.mil",
        "approved_origin": "https://api.genai.mil",
        "connection": {"endpoint": GENAI_MIL_API_BASE},
        "auth": {"type": "api_key", "api_key": "synthetic-genai-key"},
        "models": [{
            "id": "model-one", "modelName": "authorized-id", "api_type": "openai",
            "url_mode": "auto", "capabilities": {"toolCalling": True, "processesImages": True},
        }],
    }


def test_profile_cannot_gain_tools_or_vision_from_catalog_or_overrides():
    record = endpoint()
    validate_genai_profile(record)
    route = resolve_model_endpoint_route(record, record["models"][0])
    assert route["operation_url"] == "https://api.genai.mil/v1/chat/completions"
    assert route["custom_profile"] == GENAI_MIL_PROFILE
    assert route["capabilities"]["supportsStreaming"] is True
    assert route["capabilities"]["toolCalling"] is False
    assert route["capabilities"]["processesImages"] is False
    record["models"][0]["api_type"] = "anthropic"
    with pytest.raises(ValueError, match="Chat Completions"):
        resolve_model_endpoint_route(record, record["models"][0])


def test_origin_changes_require_new_key_and_explicit_approval():
    existing = endpoint()
    incoming = {"profile": GENAI_MIL_PROFILE, "connection": {"endpoint": "https://approved.example/v1"}, "auth": {"api_key": ""}}
    merged = {**existing, "connection": incoming["connection"]}
    with pytest.raises(ModelEndpointProfileError, match="re-entry"):
        merge_profile_credential_approval(existing, incoming, merged)
    incoming["auth"]["api_key"] = "new-synthetic-key"
    with pytest.raises(ModelEndpointProfileError, match="explicit approval"):
        merge_profile_credential_approval(existing, incoming, merged)
    incoming["credential_origin_approved"] = True
    merge_profile_credential_approval(existing, incoming, merged)
    assert merged["approved_origin"] == "https://approved.example"
    assert "credential_origin_approved" not in merged
    validate_genai_profile(merged)
    invalid = deepcopy(merged)
    invalid["connection"]["endpoint"] = "http://approved.example/v1"
    with pytest.raises(ModelEndpointProfileError, match="HTTPS"):
        validate_genai_profile(invalid)


@pytest.mark.parametrize("extension", (
    {"tools": [{"type": "function"}]},
    {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example/image"}}]}]},
    {"response_format": {"type": "json_object"}},
    {"extra_body": {"unsafe_option": "value"}},
    {"stream": "false"},
    {"max_tokens": 20, "max_completion_tokens": 30},
))
def test_unsupported_semantics_are_rejected_before_dispatch(extension):
    request = {"model": "authorized-id", "messages": [{"role": "user", "content": "synthetic"}], **extension}
    with pytest.raises(ModelEndpointProfileError):
        prepare_genai_request(request)


def test_sdk_default_projection_uses_documented_body_and_keeps_usage_null():
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "completion-one", "object": "chat.completion", "created": 1,
            "model": "authorized-id", "choices": [{"index": 0, "message": {"role": "assistant", "content": "text"}, "finish_reason": "stop"}],
            "usage": None,
        })

    sdk = OpenAI(
        api_key="synthetic-genai-key", base_url=GENAI_MIL_API_BASE,
        max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    client = OpenAIStyleChatCompletionClient(sdk, sanitize_errors=True, api_type="openai", custom_profile=GENAI_MIL_PROFILE)
    record = endpoint()
    client = bind_model_endpoint_request_policy(client, resolve_model_endpoint_route(record, record["models"][0]))
    try:
        result = client.chat.completions.create(
            model="authorized-id", messages=[{"role": "user", "content": "synthetic"}],
            max_completion_tokens=50, temperature=0.4, top_p=0.9,
            stream=False, stream_options={"include_usage": True},
        )
    finally:
        sdk.close()
    body = json.loads(requests[0].content)
    assert set(body) == {"model", "messages", "temperature", "max_tokens", "stream"}
    assert body["max_tokens"] == 50
    assert requests[0].headers["Authorization"] == "Bearer synthetic-genai-key"
    assert result.usage is None
    usage = project_completion_token_usage(result.usage, "timestamp")
    assert usage is None
    measured_zero = project_completion_token_usage({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "timestamp")
    assert measured_zero["total_tokens"] == 0


@pytest.mark.parametrize("status, code", [
    (401, "genai_key_action_required"), (403, "genai_model_denied"),
    (404, "genai_model_unavailable"), (429, "genai_rate_limited"),
    (502, "genai_upstream_failure"),
])
def test_error_status_is_safe_and_not_retried(status, code, monkeypatch):
    calls, logs = [], []
    monkeypatch.setattr("functions_model_endpoint_diagnostics.log_event", lambda *args, **kwargs: logs.append((args, kwargs)))

    def create(**kwargs):
        calls.append(kwargs)
        response = httpx.Response(status, request=httpx.Request("POST", GENAI_MIL_API_BASE), headers={"Retry-After": "12"})
        raise APIStatusError("Echo synthetic-genai-key https://attacker.example/unlock", response=response, body={"unlock_url": "https://attacker.example/unlock"})

    raw = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client = OpenAIStyleChatCompletionClient(raw, sanitize_errors=True, api_type="openai", custom_profile=GENAI_MIL_PROFILE)
    with pytest.raises(GenAIMilRequestError) as caught:
        client.chat.completions.create(model="authorized-id", messages=[{"role": "user", "content": "synthetic"}])
    assert caught.value.code == code
    assert len(calls) == 1
    assert "synthetic-genai-key" not in str(caught.value)
    assert "attacker.example" not in str(caught.value)
    assert "synthetic-genai-key" not in repr(logs)
    if status == 401:
        assert caught.value.payload["portal_url"] == GENAI_MIL_PORTAL
    if status == 429:
        assert caught.value.payload["retry_after_seconds"] == 12


def test_async_stream_errors_preserve_cancellation_and_close(monkeypatch):
    monkeypatch.setattr("functions_model_endpoint_diagnostics.log_event", lambda *args, **kwargs: None)

    class Stream:
        closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise asyncio.CancelledError()

        async def close(self):
            self.closed = True

    async def run():
        stream = Stream()

        async def create(**kwargs):
            return stream

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        client = sanitize_custom_async_openai_client(client, custom_profile=GENAI_MIL_PROFILE)
        result = await client.chat.completions.create(
            model="authorized-id", messages=[{"role": "user", "content": "synthetic"}], stream=True,
        )
        with pytest.raises(asyncio.CancelledError):
            await result.__anext__()
        await result.close()
        assert stream.closed is True

    asyncio.run(run())
