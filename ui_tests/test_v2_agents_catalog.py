# test_v2_agents_catalog.py
"""
Browser coverage for the native V2 Agents catalogue (Refs #1722, row 1).
Version: 0.261.305
Implemented in: 0.261.305

Load the real production SPA and local assets using the shared Azure-capable
workspace fixture. Only API responses are synthetic. Cover browsing, Popular
windows, search/tags, details, view persistence, error recovery, and real chat
launches for personal/global/group agents. Legacy page requests fail the closed
fixture boundary. Check light/dark at desktop and phone sizes.
"""

import copy
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Route, expect

# Shared fixtures retain flat imports from their fixture directory.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from ui_tests.fixtures.workspace_authoring import (
    AGENT_ID, GLOBAL_AGENT_ID, ORIGIN, SPA_INDEX, TARGET_ID, WorkspaceAuthoringFixture,
    connect_options,  # noqa: F401
)


pytestmark = pytest.mark.ui
CATALOG_ENDPOINT = "/api/v2/agents/catalog"
ARTIFACTS = Path(__file__).resolve().parent / "artifacts" / "v2_agents_catalog"
VIEW_KEY = "simplechat-agents-catalog-view"
GROUP_AGENT_ID = "00000000-0000-4000-8000-000000000111"


def _agent(identifier, name, scope="personal", **extra):
    record = {
        "id": identifier, "name": name.lower().replace(" ", "-"), "display_name": name,
        "description": f"{name} helps you work with approved sources.",
        "agent_type": "local", "scope_type": scope, "is_global": scope == "global",
        "is_group": scope == "group", "catalog_key": f"{scope}:{identifier}",
        "model_label": "Workspace GPT", "tags": [], "usage_count_all_time": 0,
        "usage_count_30_days": 0, "action_labels": ["Search approved sources"],
        "actions_to_load": ["internal-tool"], "instructions": "Review **carefully**.\n\nUse approved sources.",
        "icon": {"kind": "bootstrap", "value": "bi-robot"},
    }
    record.update(extra)
    return record


def _catalog():
    return {
        "page": {
            "title": "Choose an agent for your next task",
            "subtitle": "Find a specialist across your personal, group and enterprise agents.",
            "hero_color_mode": "two_tone",
            "hero_primary_color": "#173557",
            "hero_secondary_color": "#42648A",
            "disclaimer_markdown": "**Verify important answers.** Use only approved sources.",
            "show_instructions_in_details": True,
        },
        "agents": [
            _agent(AGENT_ID, "Policy reviewer", tags=["Finance", "Review"],
                   usage_count_all_time=200, usage_count_30_days=1,
                   icon={"kind": "bootstrap", "value": "bi-shield-check"}),
            _agent(TARGET_ID, "Quiet drafter", tags=["Writing"]),
            _agent(GLOBAL_AGENT_ID, "Knowledge guide", "global", tags=["Knowledge"],
                   is_promoted_popular=True, promoted_popular_window="both",
                   promoted_popular_rank=0, promoted_popular_order="before",
                   promoted_popular_tag_enabled=True, promoted_popular_tag_label="Featured"),
            _agent(GROUP_AGENT_ID, "Research helper", "group",
                   group_id="group-research", group_name="Research", scope_id="group-research",
                   catalog_key=f"group:group-research:{GROUP_AGENT_ID}",
                   tags=["Finance", "Research"], usage_count_all_time=100, usage_count_30_days=15),
            _agent(GROUP_AGENT_ID, "Operations helper", "group",
                   group_id="group-operations", group_name="Operations", scope_id="group-operations",
                   catalog_key=f"group:group-operations:{GROUP_AGENT_ID}",
                   tags=["Operations"], usage_count_all_time=10, usage_count_30_days=3),
        ],
    }


class AgentCatalogFixture(WorkspaceAuthoringFixture):
    """Reuse the shell, preferences, assets and chat API; add just the catalogue API."""

    def __init__(self, page):
        super().__init__(page)
        self.catalog = _catalog()
        self.chat_agents = copy.deepcopy(self.catalog["agents"])
        self.document_loads = 0
        self.groups.extend([
            {"id": "group-operations", "name": "Operations"},
            {"id": "group-research", "name": "Research"},
        ])

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = "0.261.305"
        payload["catalogs"]["agents"] = copy.deepcopy(self.chat_agents)
        payload["features"]["enable_group_workspaces"] = True
        payload["settings"]["allow_group_agents"] = True
        payload["scope"]["active_group_id"] = "group-operations"
        payload["scope"]["active_group_name"] = "Operations"
        return payload

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        if request.method == "GET" and f"{parsed.scheme}://{parsed.netloc}" == ORIGIN:
            if parsed.path.startswith("/v2/"):
                self.document_loads += 1
            if parsed.path == "/v2/agents":
                route.fulfill(path=str(SPA_INDEX), content_type="text/html")
                return
        super()._route(route)

    def _dispatch(self, route, entry):
        if entry.method == "GET" and entry.path == CATALOG_ENDPOINT:
            self._json(route, copy.deepcopy(self.catalog))
            return
        super()._dispatch(route, entry)

    def screenshots(self, name):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)

    def assert_catalogue_fits(self):
        self.assert_no_overflow()
        self.assert_content_fits(self.page.get_by_test_id("agents-catalog-scroll"), "Catalogue")

    def assert_content_fits(self, content, label):
        overflow = content.evaluate(
            "element => element.scrollWidth - element.clientWidth"
        )
        if overflow > 1:
            nodes = content.evaluate("""
                root => [...root.querySelectorAll('*')]
                    .filter(element => element instanceof HTMLElement && element.scrollWidth > element.clientWidth + 1)
                    .map(element => ({
                        tag: element.tagName,
                        classes: element.className,
                        text: element.textContent.slice(0, 40),
                        overflow: element.scrollWidth - element.clientWidth,
                        wrap: getComputedStyle(element).overflowWrap,
                        whiteSpace: getComputedStyle(element).whiteSpace,
                    }))
                    .slice(-8)
            """)
            raise AssertionError(f"{label} scrolls sideways by {overflow}px: {nodes}")


@pytest.fixture
def catalog_ui(page):
    fixture = AgentCatalogFixture(page)
    yield fixture
    fixture.assert_clean()


def _rows(page):
    return page.get_by_test_id("catalog-agent")


def _categories(page):
    return page.get_by_role("group", name="Agent categories")


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_catalogue_browsing_and_details_fit_both_themes(catalog_ui, theme, width, height):
    ui, page = catalog_ui, catalog_ui.page
    ui.open("/agents", theme=theme, width=width, height=height)
    expect(page.get_by_role("heading", level=1, name="Agents")).to_be_visible()
    expect(page.get_by_role("heading", name=ui.catalog["page"]["title"])).to_be_visible()
    expect(page.get_by_label("Agent catalogue disclaimer")).to_contain_text("Verify important answers.")
    expect(_rows(page)).to_have_count(4)
    assert _rows(page).locator("h3").all_text_contents() == [
        "Knowledge guide", "Policy reviewer", "Research helper", "Operations helper",
    ]
    expect(_categories(page).get_by_role("button", name="Popular")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_text("Featured", exact=True)).to_be_visible()
    ui.assert_catalogue_fits()
    ui.screenshots(f"catalogue-{theme}-{width}")

    page.get_by_role("button", name="Last 30 days", exact=True).click()
    assert _rows(page).locator("h3").all_text_contents() == [
        "Knowledge guide", "Research helper", "Operations helper", "Policy reviewer",
    ]
    _categories(page).get_by_role("button", name="Personal", exact=True).click()
    expect(_rows(page)).to_have_count(2)
    expect(page.get_by_role("link", name="New agent", exact=True)).to_have_attribute(
        "href", "/v2/workspace/agents/new"
    )
    opener = page.get_by_role("button", name="Details for Policy reviewer", exact=True)
    opener.press("Enter")
    dialog = page.get_by_role("dialog", name="Details for Policy reviewer")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("policy-reviewer")
    expect(dialog).to_contain_text("Workspace GPT")
    expect(dialog).to_contain_text("Search approved sources")
    expect(dialog).not_to_contain_text("internal-tool")
    expect(dialog.get_by_role("heading", name="Instructions")).to_be_visible()
    expect(dialog).to_contain_text("Review carefully.")
    expect(dialog.get_by_role("link", name="Chat with Policy reviewer")).to_have_attribute(
        "href", f"/v2/chat?agent_id={AGENT_ID}&agent_scope=personal&new=1"
    )
    page.keyboard.press("Shift+Tab")
    focused_inside = dialog.evaluate("element => element.contains(document.activeElement)")
    assert focused_inside, "Keyboard focus left the details dialog."
    ui.assert_no_overflow()
    ui.screenshots(f"details-{theme}-{width}")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()


def test_search_spans_scopes_restores_the_scope_and_keeps_tags_clearable(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.open("/agents")
    _categories(page).get_by_role("button", name="Group", exact=True).click()
    expect(_rows(page)).to_have_count(2)
    expect(page.get_by_role("link", name="New agent", exact=True)).to_have_attribute(
        "href", "/v2/groups/group-operations/agents"
    )
    tag_group = page.get_by_role("group", name="Filter agents by tag")
    tag_group.get_by_role("button", name="Finance", exact=True).click()
    expect(_rows(page)).to_have_count(1)
    search = page.get_by_role("searchbox", name="Search agents")
    search.fill("Policy")
    expect(page.get_by_role("heading", name="Policy reviewer", exact=True)).to_be_visible()
    expect(_categories(page).get_by_text("Search results", exact=True)).to_have_attribute("aria-current", "true")
    expect(_categories(page).get_by_role("button", name="Group", exact=True)).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_role("link", name="New agent", exact=True)).to_have_count(0)
    search.fill("")
    expect(page.get_by_role("heading", name="Research helper", exact=True)).to_be_visible()
    expect(_categories(page).get_by_role("button", name="Group", exact=True)).to_have_attribute("aria-pressed", "true")

    _categories(page).get_by_role("button", name="Personal", exact=True).click()
    expect(tag_group.get_by_role("button", name="Finance", exact=True)).to_have_attribute("aria-pressed", "false")
    tag_group.get_by_role("button", name="Finance", exact=True).click()
    tag_group.get_by_role("button", name="Review", exact=True).click()
    search.fill("nothing-matches-this")
    expect(page.get_by_text("No agents match the current view.", exact=True)).to_be_visible()
    expect(tag_group.get_by_role("button", name="Finance", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(tag_group.get_by_role("button", name="Review", exact=True)).to_have_attribute("aria-pressed", "true")
    tag_group.get_by_role("button", name="Review", exact=True).click()
    page.get_by_role("button", name="Clear filters", exact=True).click()
    expect(search).to_have_value("")
    expect(_rows(page)).to_have_count(2)


def test_card_view_is_shared_with_classic_and_survives_reload(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.open("/agents")
    page.get_by_role("button", name="Card view", exact=True).click()
    expect(page.get_by_role("list", name="Agents", exact=True)).to_have_attribute("data-view", "card")
    stored = page.evaluate("key => localStorage.getItem(key)", VIEW_KEY)
    assert stored == "card"
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("button", name="Card view", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("list", name="Agents", exact=True)).to_have_attribute("data-view", "card")
    page.get_by_role("button", name="List view", exact=True).click()
    expect(page.get_by_role("list", name="Agents", exact=True)).to_have_attribute("data-view", "list")


def test_view_controls_still_work_when_storage_is_unavailable(catalog_ui):
    page = catalog_ui.page
    page.add_init_script("""
        for (const method of ['getItem', 'setItem']) {
            const original = Storage.prototype[method];
            Storage.prototype[method] = function(key, ...args) {
                if (key === 'simplechat-agents-catalog-view') throw new DOMException('Storage unavailable', 'SecurityError');
                return original.call(this, key, ...args);
            };
        }
    """)
    catalog_ui.open("/agents")
    expect(_rows(page)).to_have_count(4)
    page.get_by_role("button", name="Card view", exact=True).click()
    expect(page.get_by_role("list", name="Agents", exact=True)).to_have_attribute("data-view", "card")


def test_details_honor_hidden_instructions_and_empty_action_labels(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.catalog["page"]["show_instructions_in_details"] = False
    ui.catalog["agents"][0]["action_labels"] = []
    ui.open("/agents")
    page.get_by_role("button", name="Details for Policy reviewer", exact=True).click()
    dialog = page.get_by_role("dialog", name="Details for Policy reviewer")
    expect(dialog.get_by_role("heading", name="Instructions")).to_have_count(0)
    expect(dialog).not_to_contain_text("Review carefully.")
    expect(dialog).to_contain_text("No actions assigned.")
    expect(dialog).not_to_contain_text("internal-tool")


@pytest.mark.parametrize("name,identifier,scope,group_id", [
    ("Policy reviewer", AGENT_ID, "personal", None),
    ("Knowledge guide", GLOBAL_AGENT_ID, "global", None),
    ("Research helper", GROUP_AGENT_ID, "group", "group-research"),
])
def test_chat_launch_uses_the_exact_agent_scope(catalog_ui, name, identifier, scope, group_id):
    ui, page = catalog_ui, catalog_ui.page
    ui.open("/agents")
    launch = page.get_by_role("link", name=f"Chat with {name}", exact=True)
    expected = f"/v2/chat?agent_id={identifier}&agent_scope={scope}"
    if group_id:
        expected += f"&agent_scope_id={group_id}"
    expected += "&new=1"
    expect(launch).to_have_attribute("href", expected)
    initial_bootstraps = len([request for request in ui.requests if request.path == "/api/v2/bootstrap"])
    launch.click()
    expect(page.locator("#composer-input")).to_be_enabled()
    refreshed = len([request for request in ui.requests if request.path == "/api/v2/bootstrap"])
    assert refreshed > initial_bootstraps, "Launch did not refresh the authorized catalogue."
    page.locator("#composer-input").fill("Review this with the selected agent.")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(page.get_by_text("Workspace review response.", exact=True)).to_be_visible()
    body = next(request.body for request in reversed(ui.requests) if request.path == "/api/chat/stream")
    assert body["agent_info"]["id"] == identifier
    assert body["agent_info"]["display_name"] == name
    assert body["agent_info"]["is_global"] == (scope == "global")
    assert body["agent_info"]["is_group"] == (scope == "group")
    if group_id:
        assert body["agent_info"]["group_id"] == group_id, "Chat used the active group instead of the agent's group."
    assert ui.document_loads == 1, "Chat launch left the SPA."


def test_a_revoked_agent_fails_visibly_after_the_launch_refresh(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.open("/agents")
    ui.chat_agents = [agent for agent in ui.chat_agents if agent["id"] != AGENT_ID]
    page.get_by_role("link", name="Chat with Policy reviewer", exact=True).click()
    expect(page.get_by_text("That agent is no longer available in this workspace.", exact=True)).to_be_visible()
    assert not any(request.path in ("/api/create_conversation", "/api/chat/stream") for request in ui.writes)


@pytest.mark.parametrize("status", [400, 403, 404])
def test_disabled_or_denied_catalogue_is_unavailable_not_empty(catalog_ui, status):
    catalog_ui.reject_next("GET", CATALOG_ENDPOINT, status=status, error="Unavailable.")
    catalog_ui.open("/agents")
    expect(catalog_ui.page.get_by_text("Agents are not available", exact=True)).to_be_visible()
    expect(catalog_ui.page.get_by_role("button", name="Try again", exact=True)).to_have_count(0)
    expect(catalog_ui.page.get_by_text("No agents are available.", exact=True)).to_have_count(0)


def test_server_failure_offers_retry_instead_of_an_empty_catalogue(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.reject_next("GET", CATALOG_ENDPOINT, status=500, error="Failed to load agents.")
    ui.open("/agents")
    expect(page.get_by_role("alert")).to_contain_text("Agents could not be loaded.")
    expect(page.get_by_text("No agents are available.", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Try again", exact=True).click()
    expect(_rows(page)).to_have_count(4)
    expect(page.get_by_role("alert")).to_have_count(0)


def test_empty_and_malformed_responses_have_different_states(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.catalog["agents"] = []
    ui.open("/agents")
    expect(page.get_by_text("No agents are available.", exact=True)).to_be_visible()
    ui.catalog = {"agents": []}
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("alert")).to_contain_text("Agents could not be loaded.")
    expect(page.get_by_text("No agents are available.", exact=True)).to_have_count(0)


def test_native_navigation_shows_loading_and_never_opens_legacy(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.open("/workspace/agents")
    ui.defer_next("GET", CATALOG_ENDPOINT)
    page.get_by_role("navigation", name="Primary").get_by_role("link", name="Agents", exact=True).click()
    expect(page.get_by_role("status", name="Loading agents")).to_be_visible()
    ui.release_responses()
    expect(_rows(page)).to_have_count(4)
    expect(page).to_have_url(f"{ORIGIN}/v2/agents")
    assert ui.document_loads == 1, "The catalogue navigation loaded another document."


def test_malformed_agent_can_be_inspected_but_not_launched(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.catalog["agents"].append(_agent("missing-group", "Incomplete agent", "group"))
    ui.open("/agents")
    _categories(page).get_by_role("button", name="Group", exact=True).click()
    expect(page.get_by_role("button", name="Chat with Incomplete agent", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Details for Incomplete agent", exact=True).click()
    expect(page.get_by_role("dialog", name="Details for Incomplete agent")).to_be_visible()


def test_long_content_and_markdown_cannot_escape_the_mobile_catalogue(catalog_ui):
    ui, page = catalog_ui, catalog_ui.page
    ui.catalog["page"]["title"] = "LongHeadline" * 10
    ui.catalog["page"]["disclaimer_markdown"] = (
        "**Read the guidance.**\n\n<script>window.catalogInjected = true</script>\n\n"
        "[Unsafe link](javascript:window.catalogInjected=true)\n\n" + "LongWord" * 45
    )
    ui.catalog["agents"][3]["group_name"] = "LongGroupName" * 20
    ui.catalog["agents"][3]["display_name"] = "LongAgentName" * 20
    ui.catalog["agents"][3]["tags"] = ["LongTag" * 30]
    ui.open("/agents", theme="dark", width=390, height=844)
    ui.assert_catalogue_fits()
    injected = page.evaluate("window.catalogInjected === true")
    assert not injected, "Human-authored Markdown executed JavaScript."
    expect(page.locator("a[href^='javascript:']")).to_have_count(0)
    page.get_by_role("button", name="Card view", exact=True).click()
    ui.assert_catalogue_fits()
    long_name = ui.catalog["agents"][3]["display_name"]
    page.get_by_role("button", name=f"Details for {long_name}", exact=True).click()
    dialog = page.get_by_role("dialog", name=f"Details for {long_name}")
    expect(dialog).to_be_visible()
    ui.assert_no_overflow()
    ui.assert_content_fits(dialog, "Details")
