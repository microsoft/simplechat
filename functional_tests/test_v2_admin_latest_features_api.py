#!/usr/bin/env python3
# test_v2_admin_latest_features_api.py
"""
Functional test for the Latest Features catalogues served to the V2 admin surface.
Version: 0.261.273
Implemented in: 0.261.273

The server-rendered Help tabs resolve each Latest Features shortcut with
``url_for`` and each screenshot with the static route while rendering Jinja. The
V2 surface can do neither, so ``functions_support_latest_features`` resolves
both catalogues once and ``GET /api/v2/admin/latest-features`` serves them.

These checks pin what the browser relies on:

- both catalogues keep their release groups, order and announcements;
- every admin shortcut names a live tab, following the same legacy aliases as
  the classic page, so V2 can jump to the card or fall back to the classic tab;
- page and external shortcuts are plain same-origin paths or http(s) addresses,
  and anything else is dropped rather than reaching an href;
- user shortcuts keep ``requires_settings`` so the preview can follow the draft;
- the application title is applied once, not twice;
- the Python alias map cannot drift from ``admin_sidebar_nav.js``;
- the route is registered on the admin blueprint behind the admin guards.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import get_tab_ids
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
SIDEBAR_JS = APP_ROOT / "static" / "js" / "admin" / "admin_sidebar_nav.js"
ROUTE_FILE = APP_ROOT / "route_backend_v2.py"
REDIRECT_BLOCK_RE = re.compile(r"const LEGACY_TAB_REDIRECTS = \{(?P<body>.*?)\};", re.DOTALL)
REDIRECT_ENTRY_RE = re.compile(r"'([a-z0-9-]+)'\s*:\s*'([a-z0-9-]+)'")

payload_module = import_app_module("functions_support_latest_features")
nav_module = import_app_module("admin_settings_nav")
support_menu_config = import_app_module("support_menu_config")

ENDPOINTS = {
    "frontend_chats.chats": "/chats",
    "frontend_profile.profile": "/profile",
    "frontend_support.support_latest_features": "/support/latest-features",
    "frontend_support.support_send_feedback": "/support/send-feedback",
}


def build(settings=None, endpoints=None):
    resolved = ENDPOINTS if endpoints is None else endpoints
    return payload_module.build_latest_features_payload(
        settings if settings is not None else {"enable_semantic_kernel": True},
        resolve_endpoint_url=lambda endpoint: resolved.get(endpoint, ""),
        resolve_static_url=lambda path: f"/static/{path}",
        version="0.261.273",
    )


def iter_actions(groups):
    for group in groups:
        for feature in group["features"]:
            for action in feature["actions"]:
                yield feature, action


def test_catalogues_keep_their_release_groups():
    """Both catalogues arrive whole and in release order."""
    print("Testing catalogue shape...")

    assert_app_version_at_least("0.261.273")

    payload = build()
    assert payload["version"] == "0.261.273"
    for side, source in (
        ("admin", support_menu_config.get_admin_latest_feature_release_groups_for_settings({})),
        ("user", support_menu_config.get_support_latest_feature_release_groups()),
    ):
        groups = payload[side]
        assert [group["id"] for group in groups] == [group["id"] for group in source], side
        assert [len(group["features"]) for group in groups] == [len(group["features"]) for group in source], side
        assert groups[0]["default_expanded"] is True
        assert all(group["default_expanded"] is False for group in groups[1:])
        for group in groups:
            for feature in group["features"]:
                for key in ("id", "title", "summary", "details", "why", "icon"):
                    assert isinstance(feature[key], str), f"{side} {feature.get('id')} {key}"
                assert isinstance(feature["guidance"], list)
                for image in feature["images"]:
                    assert image["url"].startswith("/static/images/features/"), image["url"]

    print("  Admin and user catalogues keep their groups and announcements.")
    return True


def test_user_announcements_carry_their_default_visibility():
    """The preview reads the same defaults the user page falls back to."""
    print("\nTesting default visibility...")

    defaults = support_menu_config.get_default_support_latest_features_visibility()
    user_features = [feature for group in build()["user"] for feature in group["features"]]
    assert user_features, "No user announcements were served."
    for feature in user_features:
        assert feature["default_visible"] is defaults.get(feature["id"], True), feature["id"]
    assert any(feature["default_visible"] is False for feature in user_features), (
        "Deployment and Redis start hidden; the defaults did not come through."
    )

    admin_features = [feature for group in build()["admin"] for feature in group["features"]]
    assert all("default_visible" not in feature for feature in admin_features), (
        "Admin announcements are not shared with users, so they carry no visibility."
    )

    print(f"  {len(user_features)} user announcement(s) carry their default.")
    return True


def test_admin_shortcuts_resolve_to_live_tabs():
    """V2 can only jump to, or fall back to, a tab that exists."""
    print("\nTesting admin shortcut targets...")

    tab_ids = set(get_tab_ids())
    admin_actions = [action for _feature, action in iter_actions(build()["admin"]) if action["kind"] == "admin"]
    assert admin_actions, "No admin shortcuts were served."

    for action in admin_actions:
        assert action["admin_tab"] in tab_ids, action
        assert action["href"] == f"/admin/settings#{action['admin_tab']}", action
        section = action["admin_section"]
        assert section is None or re.fullmatch(r"[A-Za-z0-9_-]+", section), action

    # A pre-rework id is followed rather than dropped.
    assert nav_module.resolve_admin_tab_id("#scale") == "redis-caching"
    assert nav_module.resolve_admin_tab_id("general") == "branding"
    assert nav_module.resolve_admin_tab_id("#backup") == "backup"
    assert nav_module.resolve_admin_tab_id("#no-such-tab") is None
    assert nav_module.resolve_admin_tab_id("") is None

    print(f"  {len(admin_actions)} admin shortcut(s) name a live tab.")
    return True


def test_page_and_external_shortcuts_are_safe_destinations():
    """Only same-origin paths and http(s) addresses may reach an href."""
    print("\nTesting page and external shortcuts...")

    payload = build()
    checked = 0
    for side in ("admin", "user"):
        for _feature, action in iter_actions(payload[side]):
            if action["kind"] == "page":
                assert action["href"].startswith("/") and not action["href"].startswith("//"), action
            elif action["kind"] == "external":
                assert action["href"].startswith(("https://", "http://")), action
            checked += 1

    serialize = payload_module._serialize_action
    resolve = lambda endpoint: ENDPOINTS.get(endpoint, "")  # noqa: E731
    for href in ("javascript:alert(1)", "//evil.example/path", "data:text/html,hi", "#loose-fragment"):
        assert serialize({"label": "Bad", "href": href}, resolve) is None, href
    assert serialize({"label": "Gone", "endpoint": "frontend_missing.page"}, resolve) is None
    assert serialize({"href": "/chats"}, resolve) is None, "A shortcut without a label is dropped."

    endpoint_action = serialize(
        {"label": "Open Chat", "endpoint": "frontend_chats.chats", "fragment": "chatbox"}, resolve
    )
    assert endpoint_action["kind"] == "page" and endpoint_action["href"] == "/chats#chatbox", endpoint_action

    print(f"  {checked} shortcut(s) are safe; unsafe shapes are dropped.")
    return True


def test_user_shortcuts_keep_their_requirements():
    """The preview hides a shortcut whose switch is off in the draft, not the store."""
    print("\nTesting shortcut requirements...")

    stored_off = build({"enable_support_latest_feature_documentation_links": False})
    gated = [
        action
        for _feature, action in iter_actions(stored_off["user"])
        if "enable_support_latest_feature_documentation_links" in action["requires_settings"]
    ]
    assert gated, (
        "Documentation guide shortcuts were filtered against the stored settings; the "
        "preview needs them all so it can follow an unsaved switch."
    )
    assert all(action["kind"] == "external" for action in gated), gated

    print(f"  {len(gated)} documentation shortcut(s) keep their requirement.")
    return True


def test_application_title_is_applied_once():
    """A title containing the product name must not be substituted twice."""
    print("\nTesting application title personalization...")

    payload = build({"app_title": "SimpleChat Contoso"})
    for side in ("user", "admin"):
        text = repr(payload[side])
        assert "SimpleChat Contoso" in text, side
        assert "SimpleChat Contoso Contoso" not in text, f"The title was applied twice in the {side} catalogue."

    plain = repr(build({"app_title": "Contoso Chat"})["user"])
    assert "Contoso Chat" in plain and "SimpleChat" not in plain

    print("  The application title is applied once.")
    return True


def test_alias_map_matches_the_classic_sidebar():
    """Two alias maps that disagree would send a shortcut to different tabs."""
    print("\nTesting LEGACY_TAB_REDIRECTS against admin_sidebar_nav.js...")

    block = REDIRECT_BLOCK_RE.search(SIDEBAR_JS.read_text(encoding="utf-8"))
    assert block, "LEGACY_TAB_REDIRECTS not found in admin_sidebar_nav.js"
    js_map = dict(REDIRECT_ENTRY_RE.findall(block.group("body")))
    assert js_map, "The JavaScript alias map parsed as empty."
    assert nav_module.LEGACY_TAB_REDIRECTS == js_map, (
        "admin_settings_nav.LEGACY_TAB_REDIRECTS and admin_sidebar_nav.js disagree:\n"
        f"  python: {nav_module.LEGACY_TAB_REDIRECTS}\n  javascript: {js_map}"
    )

    print(f"  {len(js_map)} alias(es) agree.")
    return True


def test_route_is_admin_guarded():
    """The catalogue route sits on the admin blueprint behind every admin guard."""
    print("\nTesting the route registration...")

    tree = ast.parse(ROUTE_FILE.read_text(encoding="utf-8"))
    registrar = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_v2_admin"
    )
    route = next(
        (
            node
            for node in ast.walk(registrar)
            if isinstance(node, ast.FunctionDef) and node.name == "v2_admin_get_latest_features"
        ),
        None,
    )
    assert route, "v2_admin_get_latest_features is not registered on the admin blueprint."

    decorators = [ast.unparse(decorator) for decorator in route.decorator_list]
    assert decorators[0] == "bp.route('/api/v2/admin/latest-features', methods=['GET'])", decorators
    assert decorators[1] == "swagger_route(security=get_auth_security())", decorators
    assert decorators[2:] == ["login_required", "admin_required"], decorators

    source = ast.unparse(route)
    assert "str(exc)" not in source, "Exception text must not reach the client."

    print("  The route is admin guarded and returns no exception text.")
    return True


if __name__ == "__main__":
    tests = [
        test_catalogues_keep_their_release_groups,
        test_user_announcements_carry_their_default_visibility,
        test_admin_shortcuts_resolve_to_live_tabs,
        test_page_and_external_shortcuts_are_safe_destinations,
        test_user_shortcuts_keep_their_requirements,
        test_application_title_is_applied_once,
        test_alias_map_matches_the_classic_sidebar,
        test_route_is_admin_guarded,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
