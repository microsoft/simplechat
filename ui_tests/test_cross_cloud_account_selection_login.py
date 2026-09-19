# test_cross_cloud_account_selection_login.py
"""
UI test for cross-cloud account-selection login.
Version: 0.261.030
Implemented in: 0.261.028

This test ensures an authenticated user without an app role can initiate the
controlled account-selection flow with sufficient dark-theme contrast while
ordinary unauthenticated sign-in stays unchanged.
"""

from pathlib import Path

from flask import Flask, render_template, session
from jinja2 import ChoiceLoader, DictLoader
from playwright.sync_api import expect
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "application" / "single_app" / "templates"
BOOTSTRAP_STYLES = REPO_ROOT / "application" / "single_app" / "static" / "css" / "bootstrap.min.css"
SIMPLECHAT_STYLES = REPO_ROOT / "application" / "single_app" / "static" / "css" / "styles.css"


def _build_test_app():
    """Create a minimal Flask app that renders the real landing-page template."""
    app = Flask(__name__, template_folder=str(TEMPLATE_ROOT))
    app.secret_key = "test-secret"
    app.jinja_loader = ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        app.jinja_loader,
    ])
    app.jinja_env.filters["nl2br"] = lambda value: value
    app.add_url_rule("/login", endpoint="frontend_authentication.login", view_func=lambda: "login")
    app.add_url_rule("/chats", endpoint="frontend_chats.chats", view_func=lambda: "chats")
    return app


def _render_landing_page(app, user=None, signed_in_account=None):
    """Render the landing page with or without an authenticated user."""
    app_settings = {
        "app_title": "SimpleChat",
        "show_logo": False,
        "access_denied_message": "Access denied.",
        "access_request_button_enabled": False,
        "access_request_page_url": "",
    }

    with app.test_request_context("/"):
        if user:
            session["user"] = user
        return render_template(
            "index.html",
            app_settings=app_settings,
            landing_html="Welcome",
            signed_in_account=signed_in_account or {},
        )


def _relative_luminance(rgb):
    """Return WCAG relative luminance for an RGB color triplet."""
    channels = []
    for value in rgb:
        normalized = value / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return (0.2126 * channels[0]) + (0.7152 * channels[1]) + (0.0722 * channels[2])


def _contrast_ratio(first, second):
    """Return the WCAG contrast ratio between two RGB color triplets."""
    lighter = max(_relative_luminance(first), _relative_luminance(second))
    darker = min(_relative_luminance(first), _relative_luminance(second))
    return (lighter + 0.05) / (darker + 0.05)


def _get_button_colors(account_switch):
    """Return the rendered button and page background RGB values."""
    return account_switch.evaluate(
        r"""element => {
            const buttonStyle = getComputedStyle(element);
            const bodyStyle = getComputedStyle(document.body);
            return {
                foreground: buttonStyle.color.match(/\d+/g).slice(0, 3).map(Number),
                background: bodyStyle.backgroundColor.match(/\d+/g).slice(0, 3).map(Number),
                buttonBackground: buttonStyle.backgroundColor.match(/\d+/g).slice(0, 3).map(Number),
            };
        }"""
    )


@pytest.mark.ui
def test_access_denied_user_can_select_another_account(page):
    """Validate the denied-state account switch URL and dark-theme contrast."""
    app = _build_test_app()
    rendered_html = _render_landing_page(
        app,
        {"oid": "denied-user", "roles": []},
        {
            "name": "Gov Administrator <script>alert('x')</script>",
            "account": "admin@govtenant.onmicrosoft.us",
        },
    )

    page.set_content(rendered_html)
    page.add_style_tag(path=BOOTSTRAP_STYLES)
    page.add_style_tag(path=SIMPLECHAT_STYLES)
    page.evaluate("document.documentElement.setAttribute('data-bs-theme', 'dark')")

    account_switch = page.get_by_role("link", name="Sign in with another account")
    expect(account_switch).to_be_visible()
    expect(account_switch).to_have_attribute("href", "/login?select_account=1")
    expect(page.get_by_label("Current signed-in account")).to_contain_text(
        "Gov Administrator <script>alert('x')</script>"
    )
    expect(page.get_by_label("Current signed-in account")).to_contain_text(
        "admin@govtenant.onmicrosoft.us"
    )
    expect(page.locator("script")).to_have_count(0)

    expect(account_switch).to_have_css("color", "rgb(248, 249, 250)")
    expect(account_switch).to_have_css("border-color", "rgb(248, 249, 250)")
    colors = _get_button_colors(account_switch)
    assert _contrast_ratio(colors["foreground"], colors["background"]) >= 4.5

    account_switch.hover()
    expect(account_switch).to_have_css("background-color", "rgb(248, 249, 250)")
    hover_colors = _get_button_colors(account_switch)
    assert _contrast_ratio(hover_colors["foreground"], hover_colors["buttonBackground"]) >= 4.5


@pytest.mark.ui
def test_unauthenticated_user_keeps_ordinary_sign_in(page):
    """Validate ordinary sign-in remains visible and does not force account selection."""
    app = _build_test_app()
    rendered_html = _render_landing_page(app)

    page.set_content(rendered_html)

    ordinary_sign_in = page.get_by_role("link", name="sign in", exact=True)
    expect(ordinary_sign_in).to_be_visible()
    expect(ordinary_sign_in).to_have_attribute("href", "/login")
    expect(page.get_by_role("link", name="Sign in with another account")).to_have_count(0)