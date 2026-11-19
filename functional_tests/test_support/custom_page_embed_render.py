# custom_page_embed_render.py
"""Render the real custom page embed templates without standing up Azure.

Version: 0.261.448
Implemented in: 0.261.448

The embed shell is a Jinja document, so the cheapest honest way to test it is to render the real
files. This builds a minimal Flask application that serves the same ``templates`` and ``static``
folders and registers the two endpoints the templates and the navigation builder link to,
``custom_pages.custom_page`` and ``custom_pages.custom_page_asset``. Everything else (settings,
roles, the page itself) is passed in, so a test states exactly what the template was given.
Nothing in here imports ``config`` or opens a connection.
"""

from pathlib import Path

from flask import Blueprint, Flask, render_template, session


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "application" / "single_app"
TEMPLATE_DIR = APP_ROOT / "templates"
STATIC_DIR = APP_ROOT / "static"

EMBED_SHELL_TEMPLATE = "custom_page_embed_shell.html"
EMBED_BASE_TEMPLATE = "custom_page_embed_base.html"
CLASSIC_SHELL_TEMPLATE = "custom_page_shell.html"


def build_embed_app(version="0.261.448"):
    """Return a Flask app that can render the embed templates and build their asset URLs."""
    app = Flask(
        "custom_page_embed_probe",
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )
    app.config["VERSION"] = version
    app.secret_key = "custom-page-embed-probe"

    blueprint = Blueprint("custom_pages", __name__)

    @blueprint.route("/custom/<slug>")
    def custom_page(slug):
        return "", 204

    @blueprint.route("/custom/assets/<slug>/<folder>/<path:filename>")
    def custom_page_asset(slug, folder, filename):
        return "", 204

    app.register_blueprint(blueprint)
    return app


def static_page(slug="probe", **overrides):
    """A static page's metadata, as ``normalize_custom_page_metadata`` shapes it."""
    page = {
        "id": slug,
        "slug": slug,
        "title": "Probe page",
        "description": "A page the tests render.",
        "enabled": True,
        "entry_type": "static",
        "access_level": "app_user",
        "nav_label": "Probe",
        "nav_icon": "bi-file-earmark-text",
        "nav_order": 100,
        "roles": [],
        "show_in_nav": True,
        "open_in_new_tab": False,
        "html_file": f"{slug}.html",
        "css_files": [],
        "js_files": [],
        "asset_files": [],
        "json_files": [],
        "source": "cosmos",
    }
    page.update(overrides)
    return page


def render_template_in_app(app, template, *, roles=("User",), **context):
    """Render ``template`` inside a request whose session carries ``roles``."""
    with app.test_request_context("/custom/probe"):
        session["user"] = {"oid": "probe-user", "roles": list(roles)}
        return render_template(template, **context)


def render_embed_shell(
    app,
    page,
    html,
    *,
    standalone=False,
    roles=("User",),
    app_settings=None,
    user_settings=None,
):
    """Render ``custom_page_embed_shell.html`` the way the route does for a static page."""
    return render_template_in_app(
        app,
        EMBED_SHELL_TEMPLATE,
        roles=roles,
        custom_page=page,
        custom_page_html=html,
        embed_standalone=standalone,
        app_settings={"app_title": "Contoso Chat", **(app_settings or {})},
        user_settings=user_settings if user_settings is not None else {},
    )
