# test_chat_inline_azure_maps_rendering.py
"""
UI test for inline Azure Maps rendering in chat.
Version: 0.241.050
Implemented in: 0.241.050

This test ensures that assistant messages can hydrate an Azure Maps agent
citation artifact, render the inline map card inside the chat bubble, and keep
the standard citation button available for the same tool invocation.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}

OPENLAYERS_STUB = """
window.ol = {
  proj: {
    fromLonLat(coords) {
      if (!Array.isArray(coords) || coords.length < 2 || !Number.isFinite(Number(coords[0])) || !Number.isFinite(Number(coords[1]))) {
        throw new TypeError('Invalid coordinates for fromLonLat');
      }
      return coords;
    }
  },
  extent: {
    isEmpty() {
      return false;
    }
  },
  Feature: function Feature(properties) {
    this.properties = { ...(properties || {}) };
    this.getProperties = () => this.properties;
    this.setStyle = () => {};
  },
  geom: {
    Point: function Point(coords) {
      this.coords = coords;
    },
    Polygon: function Polygon(coords) {
      this.coords = coords;
    }
  },
  style: {
    Style: function Style(config) {
      this.config = config;
    },
    Circle: function Circle(config) {
      this.config = config;
    },
    Fill: function Fill(config) {
      this.config = config;
    },
    Stroke: function Stroke(config) {
      this.config = config;
    }
  },
  source: {
    XYZ: function XYZ(config) {
      this.config = config;
    },
    Vector: function Vector() {
      this.features = [];
      this.addFeatures = (features) => {
        this.features.push(...features);
      };
      this.getExtent = () => [0, 0, 1, 1];
    }
  },
  layer: {
    Tile: function Tile(config) {
      this.config = config;
    },
    Vector: function Vector(config) {
      this.config = config;
    }
  },
  Overlay: function Overlay(config) {
    this.config = config;
    this.position = undefined;
    this.setPosition = (position) => {
      this.position = position;
    };
  },
  View: function View(config) {
    this.config = config;
    this.fit = () => {};
  },
  control: {
    defaults() {
      return {};
    }
  },
  Map: function Map(config) {
    this.config = config;
    this.handlers = {};
    this.on = (eventName, handler) => {
      this.handlers[eventName] = handler;
    };
    this.forEachFeatureAtPixel = () => null;
    this.hasFeatureAtPixel = () => false;
    this.getTargetElement = () => config.target;
    this.getView = () => config.view;
    this.updateSize = () => {};
  }
};
"""


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _build_full_map_citation():
    return {
        "tool_name": "AzureMapsOpenLayersPlugin.create_map_visualization",
        "function_name": "create_map_visualization",
        "plugin_name": "AzureMapsOpenLayersPlugin",
        "function_arguments": json.dumps(
            {
                "title": "Court Coverage Map",
                "summary": "Explore district courts and the service polygon.",
            }
        ),
        "function_result": json.dumps(
            {
                "success": True,
                "render_type": "azure_maps_openlayers",
                "summary": "Prepared an interactive Azure Maps view with 2 markers and 1 area.",
                "map_payload": {
                    "title": "Court Coverage Map",
                    "summary": "Explore district courts and the service polygon.",
                    "map_provider": "azure_maps",
                    "map_library": "openlayers",
                    "tileset_id": "microsoft.base.road",
                    "tile_url_template": "/api/azure-maps/tile?token=test-token&api-version=2024-04-01&tilesetId=microsoft.base.road&zoom={z}&x={x}&y={y}&tileSize=256&language=en-US&view=Auto",
                    "tile_attribution": "© Microsoft Corporation © OpenStreetMap contributors",
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
                            "description": "Main district courthouse",
                            "color": "#1d4ed8",
                        },
                        {
                            "label": "North Annex",
                            "longitude": -97.7331,
                            "latitude": 30.3072,
                            "description": "Overflow hearings and records",
                            "color": "#0ea5e9",
                        },
                    ],
                    "areas": [
                        {
                            "label": "Service Area",
                            "description": "Primary district coverage boundary",
                            "coordinates": [
                                [-97.82, 30.21],
                                [-97.67, 30.21],
                                [-97.67, 30.35],
                                [-97.82, 30.35],
                                [-97.82, 30.21],
                            ],
                            "stroke_color": "#b91c1c",
                            "fill_color": "rgba(185, 28, 28, 0.18)",
                        }
                    ],
                    "source_action_name": "court_mapper",
                },
            }
        ),
        "artifact_id": "assistant-msg-map-1_artifact_1",
    }


@pytest.mark.ui
def test_chat_inline_azure_maps_rendering(playwright):
    """Validate inline Azure Maps cards render inside assistant chat messages."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    compact_citation = {
        "tool_name": "AzureMapsOpenLayersPlugin.create_map_visualization",
        "function_arguments": {"title": "Court Coverage Map"},
      "function_result": {
        "success": True,
        "render_type": "azure_maps_openlayers",
        "summary": "Prepared an interactive Azure Maps view.",
        "map_payload": {
          "title": "Court Coverage Map",
          "summary": "Compacted payload preview.",
          "map_provider": "azure_maps",
          "map_library": "openlayers",
          "tileset_id": "microsoft.base.road",
          "tile_url_template": "/api/azure-maps/tile?token=test-token&api-version=2024-04-01&tilesetId=microsoft.base.road&zoom={z}&x={x}&y={y}&tileSize=256&language=en-US&view=Auto",
          "view": {
            "center": "<list with 2 items>",
            "zoom": 11,
            "max_zoom": 15,
            "fit_to_features": True,
          },
          "markers": ["<dict with 6 keys>", "<dict with 6 keys>"],
          "areas": [],
          "source_action_name": "court_mapper",
        },
      },
        "artifact_id": "assistant-msg-map-1_artifact_1",
        "raw_payload_externalized": True,
    }

    page.route(
        "**/api/user/settings",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"selected_agent": None, "settings": {"enable_agents": False}}),
        ),
    )
    page.route(
        "**/api/get_conversations",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"conversations": []})),
    )
    page.route(
        "https://cdn.jsdelivr.net/npm/ol@10.6.1/ol.css",
        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
    )
    page.route(
        "https://cdn.jsdelivr.net/npm/ol@10.6.1/dist/ol.js",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=OPENLAYERS_STUB),
    )
    page.route(
        "**/api/conversation/test-convo/agent-citation/assistant-msg-map-1_artifact_1",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"citation": _build_full_map_citation()}),
        ),
    )

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /chats."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Chat page unavailable in this environment (HTTP {response.status}).")

        if "login" in page.url.lower():
            pytest.skip("Inline Azure Maps UI test requires an authenticated chat session.")

        page.wait_for_selector("#chatbox")

        with page.expect_response("**/api/conversation/test-convo/agent-citation/assistant-msg-map-1_artifact_1"):
            page.evaluate(
                """
                async (payload) => {
                    currentConversationId = 'test-convo';
                    window.currentConversationId = 'test-convo';
                    const messagesModule = await import('/static/js/chat/chat-messages.js');
                    messagesModule.appendMessage(
                        'AI',
                        'Court coverage answer',
                        null,
                        'assistant-msg-map-1',
                        false,
                        [],
                        [],
                        [payload],
                        null,
                        null,
                        {
                            id: 'assistant-msg-map-1',
                            role: 'assistant',
                            content: 'Court coverage answer',
                            agent_citations: [payload],
                        },
                        true
                    );
                }
                """,
                compact_citation,
            )

        message_scope = page.locator('[data-message-id="assistant-msg-map-1"]')
        expect(message_scope.locator('.inline-map-card')).to_be_visible()
        expect(message_scope.locator('.inline-map-card-title')).to_have_text('Court Coverage Map')
        expect(message_scope.locator('.inline-map-card-summary')).to_contain_text('Explore district courts and the service polygon.')
        expect(message_scope.locator('.inline-map-badges')).to_contain_text('Markers: 2')
        expect(message_scope.locator('.inline-map-badges')).to_contain_text('Areas: 1')
        expect(message_scope.locator('.inline-map-footer')).to_contain_text('court_mapper')
        expect(message_scope.locator('.inline-map-canvas')).to_be_visible()
        expect(message_scope.locator('.inline-map-fallback')).to_have_count(0)
        expect(message_scope.locator('a.agent-citation-link')).to_have_count(1)
    finally:
        context.close()
        browser.close()