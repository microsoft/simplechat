# test_ui_interface_selection.py
"""Browser coverage for classic switching, Appearance controls and modern pre-auth terms.

Version: 0.261.449
Implemented in: 0.261.449
"""

from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
TEMPLATES = STATIC.parent / "templates"
ORIGIN = "https://simplechat.test"
pytestmark = pytest.mark.ui


def render(template, **context):
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    env.globals["url_for"] = lambda endpoint, **values: (
        f"/static/{values['filename']}" if endpoint == "static"
        else "/terms-of-use/accept" if endpoint.endswith(".accept_terms_of_use")
        else "/terms-of-use/decline" if endpoint.endswith(".decline_terms_of_use")
        else "/"
    )
    return env.get_template(template).render(config={"VERSION": "0.261.449"}, **context)


@pytest.mark.parametrize("width", [390, 1280])
def test_classic_switch_saves_before_navigating_and_handles_failure(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    markup = render("_ui_switch.html", ui_policy={"can_switch": True}, modern_ui_switch_path="/v2/workspace")
    shell = (
        '<!doctype html><html lang="en"><link rel="stylesheet" href="/static/css/bootstrap.min.css">'
        '<body><main><div class="dropdown"><button data-bs-toggle="dropdown">Account menu</button>'
        '<div class="dropdown-menu">' + markup + '</div></div></main>'
        '<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>'
        '<script src="/static/js/ui-switch.js"></script></body></html>'
    )
    saved = []
    fail = [True]

    def handle(route):
        path = urlsplit(route.request.url).path
        if path == "/api/user/settings":
            saved.append(route.request.post_data_json)
            route.fulfill(status=500 if fail[0] else 200, json={"message": "saved"})
        elif path.startswith("/static/"):
            file = STATIC / path.removeprefix("/static/")
            route.fulfill(path=str(file))
        else:
            route.fulfill(content_type="text/html", body=shell)

    page.route("**/*", handle)
    page.goto(f"{ORIGIN}/workspace#documents-tab")
    page.get_by_role("button", name="Account menu").click()
    switch = page.get_by_role("button", name="Switch to modern UI")
    switch.click()
    expect(page.get_by_role("alert")).to_contain_text("could not be saved")
    expect(page).to_have_url(f"{ORIGIN}/workspace#documents-tab")
    expect(switch).to_be_enabled()
    fail[0] = False
    switch.focus()
    page.keyboard.press("Enter")
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace#documents-tab")
    assert saved == [{"settings": {"preferredUiMode": "modern"}}] * 2


def test_classic_appearance_exposes_the_shared_policy_choices(page):
    html = render("admin/_panes/branding.html", settings={}, admin_landing_tab="branding")
    page.set_content(html)
    available = page.get_by_label("Available interfaces")
    expect(available).to_have_value("both")
    available.select_option("modern")
    expect(available).to_have_value("modern")
    available.select_option("classic")
    expect(available).to_have_value("classic")
    expect(page.get_by_label("Default interface")).to_have_value("modern")


@pytest.mark.parametrize("width", [390, 1280])
def test_modern_appearance_saves_policy_and_default(page, width):
    fixture = AdminSettingsFixture(
        page, sections={"appearance": ("appearance-section",)}, validate_updates=True,
    )
    try:
        fixture.open(width=width, ready_region="Appearance")
        available = page.get_by_label("Available interfaces")
        default = page.get_by_label("Default interface", exact=True)
        expect(available).to_have_value("both")
        expect(default).to_have_value("modern")
        for policy, initial in (("modern", "classic"), ("classic", "modern"), ("both", "classic")):
            available.select_option(policy)
            default.select_option(initial)
            page.get_by_role("button", name="Save changes").click()
            expect(page.get_by_role("button", name="Save changes")).to_have_count(0)
            assert fixture.settings["ui_mode_policy"] == policy
            assert fixture.settings["ui_default_mode"] == initial
        overflow = page.get_by_test_id("admin-settings-scroll").evaluate(
            "element => element.scrollWidth - element.clientWidth"
        )
        assert overflow <= 1
    finally:
        fixture.assert_clean()


@pytest.mark.parametrize("width", [390, 1280])
def test_modern_pre_auth_terms_are_escaped_readable_and_submittable(page, width):
    html = render(
        "modern/terms_of_use.html",
        app_settings={"app_title": "SimpleChat"},
        terms={
            "title": "Usage agreement", "message": "<script>throw new Error('unsafe')</script>\n" + "Terms text. " * 400,
            "accept_button_text": "Accept and continue", "decline_button_text": "Cancel",
        },
    )
    posts = []

    def handle(route):
        path = urlsplit(route.request.url).path
        if path.startswith("/static/"):
            route.fulfill(path=str(STATIC / path.removeprefix("/static/")))
        elif route.request.method == "POST":
            posts.append(path)
            route.fulfill(body="Accepted", content_type="text/html")
        else:
            route.fulfill(body=html, content_type="text/html")

    page.set_viewport_size({"width": width, "height": 844})
    page.route("**/*", handle)
    page.goto(f"{ORIGIN}/terms-of-use")
    expect(page.get_by_role("heading", name="Usage agreement")).to_be_visible()
    region = page.get_by_role("region", name="Agreement text")
    expect(region).to_contain_text("<script>")
    region.focus()
    assert region.evaluate("(element) => element.scrollHeight > element.clientHeight")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("button", name="Accept and continue").click()
    expect(page.get_by_text("Accepted")).to_be_visible()
    assert posts == ["/terms-of-use/accept"]
