# test_v2_inline_maps.py
"""
UI test for interactive Azure Maps cards in the V2 chat.
Version: 0.261.223
Implemented in: 0.261.223

This test ensures that an assistant reply carrying an Azure Maps action result draws an
interactive OpenLayers map under the reply: tiles load only through the SimpleChat tile proxy,
hovering a marker shows its details and a click keeps them open, the map can be expanded, a
compact citation is fetched before it is drawn, everything on the map is also listed as text,
a legacy {{map:...}} block is hidden from the reply text, and a readable fallback is shown when
OpenLayers cannot load. Only HTTP boundaries are mocked; the real MessageList, map card and
vendored OpenLayers build run in Chromium with production CSS.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_inline_maps.py -q
"""

import base64
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
REPO_ROOT = Path(__file__).resolve().parents[1]
OPENLAYERS = REPO_ROOT / "application" / "v2_ui" / "public" / "vendor" / "openlayers-10.6.1"
CONVERSATION = "map-chat"
TILE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
TEMPLATE = (
    "/api/azure-maps/tile?token=ui-test&api-version=2024-04-01&tilesetId=microsoft.base.road"
    "&zoom={z}&x={x}&y={y}&tileSize=256&language=en-US&view=Auto"
)


def map_citation(title, markers, paths=None, areas=None, view=None, **payload):
    return {
        "tool_name": f"Map: {title}",
        "function_name": "create_map_visualization",
        "plugin_name": "AzureMapsOpenLayersPlugin",
        "success": True,
        "function_result": {
            "success": True,
            "render_type": "azure_maps_openlayers",
            "map_payload": {
                "title": title,
                "map_provider": "azure_maps",
                "source_action_name": "case_map",
                "tile_attribution": "\u00a9 Microsoft Corporation \u00a9 OpenStreetMap contributors",
                "tile_url_template": TEMPLATE,
                "markers": markers,
                "paths": paths or [],
                "areas": areas or [],
                "view": view or {"fit_to_features": True, "max_zoom": 15},
                **payload,
            },
        },
    }


ROUTE_MAP = map_citation(
    "Documented vehicle movement",
    markers=[
        {"label": "Rental pickup 15:04", "description": "Counter RA-7741302", "latitude": 33.6538, "longitude": -84.4709},
        {"label": "Toll read 16:41", "description": "Northbound", "latitude": 34.01, "longitude": -84.2},
        {"label": "Bridge read 22:15", "description": "Queens-bound", "latitude": 40.8, "longitude": -73.83},
    ],
    paths=[{"label": "Ordered reads", "coordinates": [[-84.4709, 33.6538], [-84.2, 34.01], [-73.83, 40.8]]}],
    summary="Straight lines join recorded sites.",
)
HOVER_MAP = map_citation(
    "Single stop",
    markers=[{"label": "Plate read <b>CVK2281</b>", "description": "Camera 4 <img src=x>", "latitude": 40.7, "longitude": -74.0}],
    view={"fit_to_features": True, "max_zoom": 12},
)
HYDRATED = map_citation(
    "Search area",
    markers=[],
    areas=[{"label": "Search box", "coordinates": [[-84.5, 33.6], [-84.3, 33.6], [-84.3, 33.8], [-84.5, 33.8]]}],
)
COMPACT = {
    "tool_name": "Map: Search area",
    "function_name": "create_map_visualization",
    "plugin_name": "AzureMapsOpenLayersPlugin",
    "artifact_id": "artifact-search-area",
    "raw_payload_externalized": True,
    "function_result": "Map with 1 area",
}
LEGACY_BLOCK = '{{map:{"title":"Old copy","tile_url_template":"/api/azure-maps/tile?token=old&zoom={z}&x={x}&y={y}"}}'


def assistant(message_id, citations, content="Here is the map."):
    return {
        "id": message_id,
        "conversation_id": CONVERSATION,
        "role": "assistant",
        "content": content,
        "timestamp": "2026-10-02T16:12:20Z",
        "agent_citations": citations,
        "metadata": {},
    }


class MapApi:
    def __init__(self, assets, openlayers_available=True):
        self.assets = assets
        self.openlayers_available = openlayers_available
        self.tiles = []
        self.citation_requests = []
        self.unexpected = []
        self.errors = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path.startswith("/vendor/openlayers-10.6.1/"):
            if not self.openlayers_available:
                route.fulfill(status=404, body="")
                return
            route.fulfill(path=str(OPENLAYERS / path.rsplit("/", 1)[-1]))
            return
        if path == "/api/azure-maps/tile":
            self.tiles.append(f"{path}?{parsed.query}")
            route.fulfill(status=200, body=TILE, content_type="image/png")
            return
        if path == f"/api/conversation/{CONVERSATION}/agent-citation/artifact-search-area":
            self.citation_requests.append(path)
            route.fulfill(json={"citation": HYDRATED})
            return
        if request.method == "GET" and re.fullmatch(r"/api/message/[^/]+/metadata", path):
            route.fulfill(json={"message_details": {"message_id": path.split("/")[3]}})
            return
        if request.method == "GET" and path in {"/api/get_messages", "/api/v2/chat/messages"}:
            route.fulfill(json={"messages": []})
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})


def open_map_ui(editor_browser, editor_assets, **api_options):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 1000})
    page = context.new_page()
    api = MapApi(editor_assets, **api_options)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("dialog", lambda dialog: (api.errors.append(f"dialog: {dialog.message}"), dialog.dismiss()))
    return context, page, api


@pytest.fixture
def map_ui(editor_browser, editor_assets):
    context, page, api = open_map_ui(editor_browser, editor_assets)
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not api.errors, api.errors


def mount_messages(page, api, messages):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.223',
                settings: {},
                branding: { app_title: 'SimpleChat' },
                features: {},
                user: { id: 'ui-user', display_name: 'Map Tester' },
                scope: { groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation,
                activeConversationKind: 'personal',
                messagesLoading: false,
                messagesError: null,
                streaming: false,
                streamingContent: '',
                streamError: null,
                thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Map chat' }],
                messages: spec.messages,
            });
            H.mount('test-root', 'MessageList');
        }""",
        {"conversation": CONVERSATION, "messages": messages},
    )


def map_card(page, title):
    return page.locator("figure").filter(has=page.get_by_text(title, exact=True))


def test_map_draws_from_the_tool_result_with_tiles_from_the_proxy(map_ui):
    page, api = map_ui
    content = f"The vehicle moved north.\n\n{LEGACY_BLOCK}\n\nSee the map below."
    mount_messages(page, api, [assistant("route-reply", [{"tool_name": "lookup"}, ROUTE_MAP], content)])

    card = map_card(page, "Documented vehicle movement")
    expect(card).to_be_visible()
    expect(card.get_by_text("Straight lines join recorded sites.")).to_be_visible()
    expect(card.get_by_text("3 markers \u00b7 1 path")).to_be_visible()
    region = card.get_by_role("region", name=re.compile("Interactive map: Documented vehicle movement"))
    expect(region.locator(".ol-viewport")).to_have_count(1)
    expect(card.get_by_text("Loading map\u2026")).to_have_count(0)

    # Zoom and expand controls are present; OpenLayers' HTML attribution control is not, and the
    # attribution is shown as text instead.
    expect(region.locator(".ol-zoom-in")).to_be_visible()
    expect(region.get_by_role("button", name="Full screen")).to_be_visible()
    expect(region.locator(".ol-attribution")).to_have_count(0)
    expect(card.get_by_text("\u00a9 Microsoft Corporation \u00a9 OpenStreetMap contributors")).to_be_visible()

    page.wait_for_function("() => document.querySelectorAll('figure canvas').length > 0")
    assert api.tiles, "the map requested no tiles"
    assert all(tile.startswith("/api/azure-maps/tile?token=ui-test&") for tile in api.tiles), api.tiles

    # The reply text keeps its words but not the legacy block's raw JSON.
    bubble_text = page.locator("#test-root").inner_text()
    assert "The vehicle moved north." in bubble_text and "See the map below." in bubble_text
    assert "{{map:" not in bubble_text and "Old copy" not in bubble_text


def test_hover_shows_details_and_a_click_keeps_them_open(map_ui):
    page, api = map_ui
    mount_messages(page, api, [assistant("hover-reply", [HOVER_MAP])])

    card = map_card(page, "Single stop")
    region = card.get_by_role("region", name=re.compile("Interactive map: Single stop"))
    expect(region.locator(".ol-viewport")).to_have_count(1)
    page.wait_for_timeout(300)  # the fit to features runs on the next animation frame
    box = region.bounding_box()
    center = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    away = (box["x"] + box["width"] - 40, box["y"] + box["height"] - 40)

    popup = card.locator(".ol-overlay-container > div")
    page.mouse.move(*center)
    expect(popup).to_be_visible()
    expect(popup).to_contain_text("Plate read <b>CVK2281</b>")
    expect(popup).to_contain_text("Camera 4 <img src=x>")
    assert card.locator(".ol-overlay-container b, .ol-overlay-container img").count() == 0

    page.mouse.move(*away)
    expect(popup).to_be_hidden()

    page.mouse.click(*center)
    page.mouse.move(*away)
    expect(popup).to_be_visible()

    region.press("Escape")
    expect(popup).to_be_hidden()


def test_compact_citation_is_fetched_and_the_map_is_listed_as_text(map_ui):
    page, api = map_ui
    mount_messages(page, api, [assistant("compact-reply", [COMPACT, HOVER_MAP])])

    card = map_card(page, "Search area")
    expect(card).to_be_visible()
    expect(card.get_by_text("1 area", exact=True)).to_be_visible()
    assert api.citation_requests == [f"/api/conversation/{CONVERSATION}/agent-citation/artifact-search-area"]

    listed = map_card(page, "Single stop")
    listed.get_by_text("List what the map shows").click()
    expect(listed.get_by_text("Plate read <b>CVK2281</b>")).to_be_visible()
    expect(listed.get_by_text("\u2014 Camera 4 <img src=x>")).to_be_visible()


def test_map_falls_back_to_text_when_openlayers_cannot_load(editor_browser, editor_assets):
    context, page, api = open_map_ui(editor_browser, editor_assets, openlayers_available=False)
    try:
        mount_messages(page, api, [assistant("fallback-reply", [ROUTE_MAP])])
        card = map_card(page, "Documented vehicle movement")
        expect(card.get_by_text("This map could not be drawn in this browser. Everything it shows is listed below.")).to_be_visible()
        card.get_by_text("List what the map shows").click()
        expect(card.get_by_text("Bridge read 22:15")).to_be_visible()
        assert not api.tiles
        assert not api.unexpected, api.unexpected
        assert not api.errors, api.errors
    finally:
        context.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
