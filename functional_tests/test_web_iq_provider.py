# test_web_iq_provider.py
"""
Functional tests for Web IQ discovery, policy, authentication and configuration.
Version: 0.261.405
Implemented in: 0.261.405

Exercise real bootstrap-free provider and Gather contracts without network calls.
Refs microsoft/simplechat#1887.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_web_iq import (
    WebIQError, available_web_iq_types, normalize_web_iq_response,
    resolve_web_iq_types, search_web_iq, select_manual_web_iq_types,
    validate_web_iq_ready, web_iq_configuration_snapshot, resolve_web_iq_credentials,
)
from functions_orchestration_external_configuration import project_external_configuration
from functions_orchestration_registry import (
    build_planner_capability_projection, resolve_available_capabilities,
)
from functions_orchestration_results import ResultUnavailableError


def settings():
    return {
        "enable_web_search": True, "web_search_provider": "web_iq",
        "web_iq_consent_accepted": True, "azure_environment": "public",
        "web_iq_news_enabled": True, "web_iq_image_mode": "text_only",
        "web_iq_video_mode": "with_media",
        "web_iq": {"key": "synthetic-test-key"},
    }


def response(payload, status=200, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    result._content_consumed = True
    result.headers.update(headers or {})
    return result


def transport(responses):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.side_effect = responses
    return client


def test_enabled_types_and_explicit_manual_intent():
    config = settings()
    actual = available_web_iq_types(config)
    assert actual == ["web", "news", "image", "video"]
    plain = select_manual_web_iq_types(config, "Explain the architecture")
    visual = select_manual_web_iq_types(config, "Find images and video tutorials in the news")
    assert plain == ["web"]
    assert visual == ["web", "news", "image", "video"]
    excluded = select_manual_web_iq_types(config, "Explain video encoding without images or videos")
    assert excluded == ["web"]
    config["web_iq_image_mode"] = "off"
    with pytest.raises(WebIQError, match="result_type_disabled"):
        resolve_web_iq_types(config, ["image"])
    for types in ([], ["web", "web"], ["auto"], "news", [1]):
        with pytest.raises(WebIQError):
            resolve_web_iq_types(config, types)


@pytest.mark.parametrize("cloud", ["usgovernment", "AzureUSGovernment", "custom", "", None])
def test_unsupported_cloud_never_calls_provider(cloud):
    config = settings()
    config["azure_environment"] = cloud
    with patch("functions_web_iq.requests.Session") as session:
        with pytest.raises(WebIQError, match="unsupported_cloud"):
            search_web_iq(config, "public query")
        session.assert_not_called()


def test_consent_and_endpoint_are_not_interchangeable():
    config = settings()
    config["web_iq_consent_accepted"] = False
    config["web_search_consent_accepted"] = True
    with pytest.raises(WebIQError, match="consent_required"):
        validate_web_iq_ready(config)
    config["web_iq_consent_accepted"] = True
    config["web_iq"]["endpoint"] = "https://example.com/v3"
    with pytest.raises(WebIQError, match="invalid_endpoint"):
        validate_web_iq_ready(config)


def test_typed_requests_share_result_budget_and_omit_key_appid():
    client = transport([
        response({"webResults": [{"url": "https://example.com/article", "title": "Article", "content": "Passage"}]}),
        response({"newsResults": []}),
        response({"imageResults": []}),
        response({"videoResults": []}),
    ])
    captured = []
    with patch("functions_web_iq.requests.Session", return_value=client):
        result = search_web_iq(settings(), "public query", ["web", "news", "image", "video"],
                               invocation_capture=lambda *args, **kwargs: captured.append(kwargs["source"]))
    assert len(client.post.call_args_list) == 4
    total = 0
    for call in client.post.call_args_list:
        kwargs = call.kwargs
        assert kwargs["params"] is None
        assert kwargs["headers"]["x-apikey"] == "synthetic-test-key"
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        total += kwargs["json"]["maxResults"]
        if call.args[0].endswith("/news"):
            assert "safeSearch" not in kwargs["json"]
        else:
            assert kwargs["json"]["safeSearch"] == "strict"
    assert total == 10
    assert result["citations"][0]["description"] == "Passage"
    assert all(run["provider"] == "web_iq" for run in result["runs"])
    assert [item["phase"] for item in captured] == ["definition", "run"]


def test_entra_scope_and_appid_are_distinct():
    config = settings()
    config["web_iq"] = {
        "authentication_type": "service_principal", "tenant_id": "tenant",
        "client_id": "client", "client_secret": "synthetic-secret", "app_id": "bound-appid",
    }
    client = transport([response({"webResults": []})])
    credential = Mock()
    credential.get_token.return_value.token = "synthetic-token"
    with patch("functions_web_iq.ClientSecretCredential", return_value=credential), \
            patch("functions_web_iq.requests.Session", return_value=client):
        result = search_web_iq(config, "public query")
    credential.get_token.assert_called_once_with("https://api.microsoft.ai/.default")
    credential.close.assert_called_once()
    assert client.post.call_args.kwargs["params"] == {"APPID": "bound-appid"}
    assert "x-apikey" not in client.post.call_args.kwargs["headers"]
    assert result["citations"] == []


def test_key_vault_references_resolve_strictly_without_outbound_reference_names():
    config = settings()
    reference = "web-iq--model-endpoint--global--s-synthetic"
    config["web_iq"]["key"] = reference
    scope_check = Mock(return_value=True)
    retrieve = Mock(return_value="synthetic-resolved-key")
    vault = SimpleNamespace(
        secret_reference_matches_context=scope_check,
        retrieve_secret_from_key_vault_by_full_name=retrieve,
    )
    client = transport([response({"webResults": []})])
    with patch.dict(sys.modules, {"functions_keyvault": vault}), \
            patch("functions_web_iq.requests.Session", return_value=client):
        snapshot = web_iq_configuration_snapshot(config)
        result = search_web_iq(config, "query")
    assert snapshot["credential_references"]["key"] == reference
    assert snapshot["connection"]["key"] == "synthetic-resolved-key"
    retrieve.assert_called_with(reference, strict=True)
    scope_check.assert_called_with(
        reference, scope_value="web-iq", scope="global", allowed_sources={"model-endpoint"},
    )
    assert client.post.call_args.kwargs["headers"]["x-apikey"] == "synthetic-resolved-key"
    assert reference not in str(result)
    scope_check.return_value = False
    retrieve.reset_mock()
    with patch.dict(sys.modules, {"functions_keyvault": vault}):
        with pytest.raises(WebIQError, match="credential_scope_mismatch"):
            resolve_web_iq_credentials(config)
    retrieve.assert_not_called()
    scope_check.return_value = True
    retrieve.side_effect = ValueError("unavailable")
    with patch.dict(sys.modules, {"functions_keyvault": vault}):
        with pytest.raises(WebIQError, match="credential_unavailable"):
            resolve_web_iq_credentials(config)


def test_text_only_never_contains_media_resources():
    item = {
        "hostPageUrl": "https://example.com/photo-page", "url": "https://example.com/photo.jpg",
        "thumbnailUrl": "https://example.com/thumb.jpg", "caption": "Provider caption",
    }
    text = normalize_web_iq_response({"imageResults": [item]}, "image")[0]
    media = normalize_web_iq_response({"imageResults": [item]}, "image", mode="with_media")[0]
    assert text["url"] == item["hostPageUrl"]
    assert text["description_origin"] == "provider_metadata"
    assert "image_url" not in text and "thumbnail_url" not in text
    assert media["image_url"] == item["url"]
    assert media["thumbnail_url"] == item["thumbnailUrl"]


def test_untrusted_urls_and_provider_dates():
    payload = {"webResults": [
        {"url": "javascript:alert(1)", "content": "Unsafe"},
        {"url": "https://127.0.0.1/internal", "content": "Internal"},
        {"url": "https://example.com/a", "content": "A", "crawledAt": "2026-06-01"},
        {"url": "https://example.com/a", "content": "Duplicate"},
    ]}
    actual = normalize_web_iq_response(payload, "web")
    assert len(actual) == 1
    assert actual[0]["crawled_at"] == "2026-06-01"
    assert "published_at" not in actual[0]


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503])
def test_http_failures_are_safe_and_not_empty_success(status):
    client = transport([response({"secret": "provider-private"}, status, {"Retry-After": "120"})])
    with patch("functions_web_iq.requests.Session", return_value=client):
        with pytest.raises(WebIQError) as failed:
            search_web_iq(settings(), "public query")
    assert failed.value.provider_status == status
    assert "provider-private" not in str(failed.value)
    assert client.post.call_count == 1


def test_bounded_retry_cancellation_and_malformed_response():
    client = transport([response({}, 429, {"Retry-After": "0"}), response({"webResults": []})])
    with patch("functions_web_iq.requests.Session", return_value=client):
        result = search_web_iq(settings(), "query")
    assert result["runs"][0]["success"] is True
    assert client.post.call_count == 2
    with patch("functions_web_iq.requests.Session") as session:
        with pytest.raises(InterruptedError):
            search_web_iq(settings(), "query", cancel_requested=lambda: True)
        session.assert_not_called()
    malformed = transport([response({"unexpected": []})])
    with patch("functions_web_iq.requests.Session", return_value=malformed):
        with pytest.raises(WebIQError, match="invalid_response"):
            search_web_iq(settings(), "query")


def test_query_and_response_limits_are_enforced():
    with patch("functions_web_iq.requests.Session") as session:
        with pytest.raises(WebIQError, match="invalid_query"):
            search_web_iq(settings(), "x" * 1001)
        session.assert_not_called()
    config = settings()
    config["web_iq"]["max_results"] = 1
    with patch("functions_web_iq.requests.Session") as session:
        with pytest.raises(WebIQError, match="result_budget_too_small"):
            search_web_iq(config, "query", ["web", "news"])
        session.assert_not_called()
    oversized = response({"webResults": []})
    oversized._content = b"x" * 2_000_001
    client = transport([oversized])
    with patch("functions_web_iq.requests.Session", return_value=client):
        with pytest.raises(WebIQError, match="response_limit_exceeded"):
            search_web_iq(settings(), "query")


def test_gather_projection_contains_actual_discovery_policy():
    config = settings()
    capabilities = resolve_available_capabilities(config, candidate_ids={"web_search"}, include_runtime_bindings=False)
    projected = build_planner_capability_projection(capabilities)
    web = next(item for item in projected if item["id"] == "web_search")
    assert web["role"] == "gather"
    assert web["discovery"]["provider"] == "web_iq"
    assert web["discovery"]["result_types"] == ["web", "news", "image", "video"]
    assert web["discovery"]["media_policy"]["image"] == "text_only"
    config["web_search_provider"] = "foundry"
    legacy = build_planner_capability_projection(resolve_available_capabilities(
        config, candidate_ids={"web_search"}, include_runtime_bindings=False,
    ))
    web = next(item for item in legacy if item["id"] == "web_search")
    assert web["discovery"]["result_types"] == ["web"]


def test_configuration_proof_changes_with_policy_and_credentials():
    config = settings()
    source = {"version": "orchestration-external-acquisition-v1", "kind": "web_iq", "phase": "run",
              "configuration": web_iq_configuration_snapshot(config), "result_types": ["web"]}
    digest = lambda value: __import__("hashlib").sha256(value).hexdigest()
    original = project_external_configuration("web", settings=config, source=source, private_digest=digest)
    changed = deepcopy(config)
    changed["web_iq_image_mode"] = "with_media"
    source["configuration"] = web_iq_configuration_snapshot(changed)
    revised = project_external_configuration("web", settings=changed, source=source, private_digest=digest)
    assert original.revision != revised.revision
    assert "synthetic-test-key" not in str(original)
    with pytest.raises(ResultUnavailableError) as unavailable:
        project_external_configuration("web", settings=config, source=source, private_digest=digest)
    assert unavailable.value.code == "external_configuration_selection_mismatch"
