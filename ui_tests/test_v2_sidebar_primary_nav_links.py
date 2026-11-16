# test_v2_sidebar_primary_nav_links.py
"""
UI test for the V2 rail's primary navigation staying inside the V2 interface.

Version: 0.261.290
Implemented in: 0.261.290

Every primary link in the V2 rail opened the classic interface instead of its V2 page
(#1698). The links had been given full URLs such as https://host/workspace. React Router
treats an absolute URL outside its /v2 basename as an external link, so it rendered a plain
anchor and the browser loaded the classic page at that path.

For each primary rail link this test checks that the href is under /v2, and that clicking it
routes inside the single-page application. A marker set on window survives, which a document
load would wipe. The address must land on the V2 route, and the link must then be highlighted
as the current page.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "") or os.getenv(
    "SIMPLECHAT_UI_ADMIN_STORAGE_STATE",
    "",
)

# (accessible name, V2 route). Public Workspaces is named by the administrator-configurable
# display name, so its label is read from bootstrap instead.
PRIMARY_LINKS = (
    ("Chats", "/chat"),
    ("Agents", "/agents"),
    ("My Workspace", "/workspace"),
    ("Group Workspaces", "/groups"),
    (None, "/public"),
    ("Approval requests", "/approvals"),
    ("Content review", "/content-review"),
)
DEFAULT_PUBLIC_PLURAL = "Public Workspaces"


def _require_environment():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a "
            "valid authenticated Playwright storage state file."
        )


@pytest.fixture
def v2_context(playwright):
    """An authenticated browser context pointed at the V2 interface."""
    _require_environment()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    try:
        yield context
    finally:
        context.close()
        browser.close()


def _open_v2(context, path="/v2"):
    """Load a V2 route and return ``(page, bootstrap_payload)``."""
    page = context.new_page()
    response = page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")

    assert response is not None, f"Expected a navigation response for {path}."
    if response.status in {401, 403}:
        pytest.skip("The configured session is not authorised for the V2 interface.")
    if response.status == 503:
        pytest.skip("The V2 bundle is not built in the environment under test.")
    assert response.ok, f"Expected {path} to load, got HTTP {response.status}."

    bootstrap = page.request.get(f"{BASE_URL}/api/v2/bootstrap")
    assert bootstrap.ok, f"Expected bootstrap to load, got HTTP {bootstrap.status}."

    # The rail only exists once bootstrap has resolved in the browser too.
    expect(page.get_by_role("navigation", name="Primary")).to_be_visible()

    return page, bootstrap.json()


def _public_plural(bootstrap):
    labels = (bootstrap.get("settings") or {}).get("public_workspace_labels") or {}
    plural = labels.get("plural")
    return plural if isinstance(plural, str) and plural.strip() else DEFAULT_PUBLIC_PLURAL


@pytest.mark.ui
@pytest.mark.parametrize(
    "label, route",
    PRIMARY_LINKS,
    ids=[route.strip("/") for _label, route in PRIMARY_LINKS],
)
def test_primary_rail_link_routes_within_v2(v2_context, label, route):
    """A rail link must open its V2 page in place, not reload into the classic interface."""
    # Starting from the home page means every link, Chats included, changes the route.
    page, bootstrap = _open_v2(v2_context)
    name = label or _public_plural(bootstrap)

    rail = page.get_by_role("navigation", name="Primary")
    link = rail.get_by_role("link", name=name, exact=True).first
    expect(link).to_be_visible()

    # The rendered href is what the browser follows. A full URL here is the defect: it lands
    # on the classic page at the same path.
    expect(link).to_have_attribute("href", f"/v2{route}")

    page.evaluate("window.__v2RailNavigationMarker = 'kept'")
    link.click()

    # Approval requests settles on its default category, so a deeper V2 path is acceptable.
    page.wait_for_url(re.compile(rf"^{re.escape(BASE_URL)}/v2{re.escape(route)}(?:[/?#]|$)"))

    assert page.evaluate("window.__v2RailNavigationMarker") == "kept", (
        f"{name} reloaded the document instead of routing inside the V2 application."
    )
    expect(page.get_by_role("navigation", name="Primary")).to_be_visible()
    expect(rail.get_by_role("link", name=name, exact=True).first).to_have_attribute(
        "aria-current", "page"
    )
