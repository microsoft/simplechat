#!/usr/bin/env python3
# test_azure_maps_tile_token_refresh_fix.py
"""
Functional test for the Azure Maps tile token refresh fix.
Version: 0.241.063
Implemented in: 0.241.063

This test ensures expired Azure Maps tile proxy URLs embedded in stored agent
citations are reissued automatically during hydration so older chat messages can
still render their inline maps.
"""

import importlib.util
import json
import os
import sys
import traceback
import types
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELPER_FILE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "functions_azure_maps.py",
)
ARTIFACTS_FILE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "functions_message_artifacts.py",
)
ROUTE_FILE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "route_frontend_conversations.py",
)
INLINE_MAPS_FILE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "static",
    "js",
    "chat",
    "chat-inline-maps.js",
)


def _install_test_stubs():
    config_module = types.ModuleType("config")
    config_module.SECRET_KEY = "functional-test-secret"
    sys.modules["config"] = config_module

    functions_appinsights_module = types.ModuleType("functions_appinsights")
    functions_appinsights_module.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = functions_appinsights_module


def _load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_modules():
    _install_test_stubs()
    helper_module = _load_module("functions_azure_maps", HELPER_FILE)
    artifacts_module = _load_module("functions_message_artifacts", ARTIFACTS_FILE)
    return helper_module, artifacts_module


def _read(path):
    with open(path, encoding="utf-8") as file_handle:
        return file_handle.read()


def _build_expired_tile_url_template(helper_module, subscription_key="maps-secret-key"):
    expired_payload = {
        "subscription_key": subscription_key,
        "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    expired_token = helper_module._build_fernet_cipher().encrypt(
        json.dumps(expired_payload).encode("utf-8")
    ).decode("utf-8")
    return helper_module.build_tile_proxy_url_template(
        expired_token,
        tileset_id="microsoft.base.road",
        language="en-US",
        view="Auto",
        tile_size=256,
    )


def test_refresh_tile_proxy_url_template_reissues_expired_tokens():
    """Expired Azure Maps tile templates should be reissued with a fresh proxy token."""
    print("Testing Azure Maps tile proxy URL refresh...")
    helper_module, _ = _load_modules()

    expired_template = _build_expired_tile_url_template(helper_module)
    expired_token = (parse_qs(urlparse(expired_template).query).get("token") or [""])[0]
    if helper_module.decode_tile_proxy_token(expired_token) is not None:
        raise AssertionError("Expected the original tile proxy token to be expired.")

    refreshed_template = helper_module.refresh_tile_proxy_url_template(expired_template)
    if not refreshed_template:
        raise AssertionError("Expected a refreshed tile proxy URL template.")

    refreshed_query = parse_qs(urlparse(refreshed_template).query)
    refreshed_token = (refreshed_query.get("token") or [""])[0]
    decoded_token = helper_module.decode_tile_proxy_token(refreshed_token)
    if not decoded_token:
        raise AssertionError("Expected the refreshed tile proxy token to decode successfully.")

    if decoded_token.get("subscription_key") != "maps-secret-key":
        raise AssertionError("Expected the refreshed token to preserve the subscription key.")

    if (refreshed_query.get("tilesetId") or [""])[0] != "microsoft.base.road":
        raise AssertionError("Expected the refreshed URL template to preserve tilesetId.")

    print("  Tile proxy URL refresh passed.")
    return True


def test_hydrate_agent_citations_refreshes_expired_azure_maps_urls():
    """Artifact hydration should refresh expired Azure Maps tile URLs before returning citations."""
    print("Testing Azure Maps citation hydration refresh...")
    helper_module, artifacts_module = _load_modules()

    expired_template = _build_expired_tile_url_template(helper_module)
    messages = [
        {
            "id": "assistant-msg-map-1",
            "role": "assistant",
            "agent_citations": [
                {
                    "artifact_id": "assistant-msg-map-1_artifact_1",
                    "raw_payload_externalized": True,
                }
            ],
        }
    ]
    artifact_payload_map = {
        "assistant-msg-map-1_artifact_1": {
            "citation": {
                "tool_name": "Map: Court Coverage Map",
                "function_name": "create_map_visualization",
                "plugin_name": "AzureMapsOpenLayersPlugin",
                "function_result": {
                    "success": True,
                    "render_type": helper_module.AZURE_MAPS_RENDER_TYPE,
                    "map_payload": {
                        "title": "Court Coverage Map",
                        "summary": "Explore district courts and the service polygon.",
                        "map_provider": "azure_maps",
                        "map_library": "openlayers",
                        "tileset_id": "microsoft.base.road",
                        "tile_url_template": expired_template,
                        "tile_attribution": helper_module.AZURE_MAPS_TILE_ATTRIBUTION,
                        "view": {
                            "center": [-97.7431, 30.2672],
                            "zoom": 11,
                            "max_zoom": 15,
                            "fit_to_features": True,
                        },
                        "markers": [
                            {
                                "label": "Central Court",
                                "longitude": -97.7431,
                                "latitude": 30.2672,
                            }
                        ],
                        "paths": [],
                        "areas": [],
                        "source_action_name": "court_mapper",
                    },
                },
            }
        }
    }

    hydrated_messages = artifacts_module.hydrate_agent_citations_from_artifacts(messages, artifact_payload_map)
    hydrated_citation = hydrated_messages[0]["agent_citations"][0]
    refreshed_result = hydrated_citation["function_result"]
    refreshed_template = refreshed_result["map_payload"]["tile_url_template"]
    refreshed_token = (parse_qs(urlparse(refreshed_template).query).get("token") or [""])[0]
    decoded_token = helper_module.decode_tile_proxy_token(refreshed_token)
    if not decoded_token:
        raise AssertionError("Expected hydrated citations to contain a fresh Azure Maps tile proxy token.")

    if hydrated_citation.get("artifact_id") != "assistant-msg-map-1_artifact_1":
        raise AssertionError("Expected hydrated citation to preserve artifact_id.")

    if hydrated_citation.get("raw_payload_externalized") is not True:
        raise AssertionError("Expected hydrated citation to preserve raw_payload_externalized.")

    print("  Citation hydration refresh passed.")
    return True


def test_refresh_message_content_reissues_embedded_tile_proxy_urls():
    """Legacy inline {{map:...}} blocks should also get refreshed tile proxy URLs."""
    print("Testing Azure Maps inline message content refresh...")
    helper_module, _ = _load_modules()

    expired_template = _build_expired_tile_url_template(helper_module)
    message_content = (
        "I created a map centered on Virginia.\n\n"
        "{{map:{\"title\":\"Virginia Highlight\",\"tile_url_template\":\""
        + expired_template
        + "\",\"markers\":[{\"label\":\"Virginia\",\"longitude\":-78.6569,\"latitude\":37.4316}],\"paths\":[],\"areas\":[],\"view\":{\"center\":[-78.6569,37.4316],\"zoom\":6,\"max_zoom\":15,\"fit_to_features\":true}}}}"
    )

    refreshed_content = helper_module.refresh_azure_maps_message_content(message_content)
    if refreshed_content == message_content:
        raise AssertionError("Expected inline Azure Maps message content to be refreshed.")

    refreshed_token = (parse_qs(urlparse(refreshed_content).query).get("token") or [""])[0]
    decoded_token = helper_module.decode_tile_proxy_token(refreshed_token)
    if not decoded_token:
        raise AssertionError("Expected refreshed inline message content to contain a valid tile proxy token.")

    print("  Inline message content refresh passed.")
    return True


def test_conversation_load_path_hydrates_artifacts_before_rendering():
    """Conversation loading should hydrate citations and inline maps should prefer artifacts."""
    print("Testing Azure Maps conversation load hydration contract...")
    route_content = _read(ROUTE_FILE)
    inline_maps_content = _read(INLINE_MAPS_FILE)
    chat_messages_content = _read(
        os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "chat", "chat-messages.js")
    )

    route_expectations = [
        "hydrate_agent_citations_from_artifacts(messages, artifact_payload_map)",
        "hydrate_agent_citations_from_artifacts(all_items, artifact_payload_map)",
        "refresh_azure_maps_citation_payloads(",
        "refresh_azure_maps_message_content(",
    ]
    inline_expectations = [
        "const shouldPreferArtifact = Boolean(citation?.artifact_id && conversationId);",
    ]
    message_render_expectations = [
        'normalizedContent.includes("{{map:")',
        '.replace(/\\n?\\{\\{map:[\\s\\S]*?\\}\\}\\n?/g, "\\n")',
    ]

    for fragment in route_expectations:
        if fragment not in route_content:
            raise AssertionError(f"Missing conversation hydration fragment: {fragment}")

    for fragment in inline_expectations:
        if fragment not in inline_maps_content:
            raise AssertionError(f"Missing inline renderer artifact-preference fragment: {fragment}")

    for fragment in message_render_expectations:
        if fragment not in chat_messages_content:
            raise AssertionError(f"Missing AI message Azure Maps cleanup fragment: {fragment}")

    print("  Conversation load hydration contract passed.")
    return True


def test_chat_fetches_bypass_stale_cache_after_token_refresh():
    """Conversation and artifact fetches should bypass browser caches after token refresh changes."""
    print("Testing Azure Maps chat fetch cache-bypass contract...")
    route_content = _read(ROUTE_FILE)
    inline_maps_content = _read(INLINE_MAPS_FILE)
    chat_messages_content = _read(os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "chat", "chat-messages.js"))
    chat_citations_content = _read(os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "chat", "chat-citations.js"))

    route_expectations = [
        "response.headers['Cache-Control'] = 'no-store, max-age=0'",
        "response.headers['Pragma'] = 'no-cache'",
        "response.headers['Expires'] = '0'",
    ]
    client_expectations = [
        'fetch(`/conversation/${conversationId}/messages?ts=${Date.now()}`, {',
        'cache: "no-store"',
        'fetchAgentCitationArtifact(conversationId, artifactId)',
        '`/api/conversation/${encodeURIComponent(conversationId)}/agent-citation/${encodeURIComponent(artifactId)}?ts=${Date.now()}`',
    ]

    for fragment in route_expectations:
        if fragment not in route_content:
            raise AssertionError(f"Missing no-store response fragment: {fragment}")

    for fragment in client_expectations[:2]:
        if fragment not in chat_messages_content:
            raise AssertionError(f"Missing chat message cache-bypass fragment: {fragment}")

    if client_expectations[2] not in inline_maps_content:
        raise AssertionError(f"Missing inline map artifact fetch fragment: {client_expectations[2]}")

    if client_expectations[3] not in chat_citations_content or client_expectations[1] not in chat_citations_content:
        raise AssertionError("Missing artifact fetch no-store fragments in chat-citations.js")

    print("  Chat fetch cache-bypass contract passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_refresh_tile_proxy_url_template_reissues_expired_tokens,
        test_hydrate_agent_citations_refreshes_expired_azure_maps_urls,
        test_refresh_message_content_reissues_embedded_tile_proxy_urls,
        test_conversation_load_path_hydrates_artifacts_before_rendering,
        test_chat_fetches_bypass_stale_cache_after_token_refresh,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print('=' * 60)
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"ERROR: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} tests passed")
    print('=' * 60)
    sys.exit(0 if all(results) else 1)