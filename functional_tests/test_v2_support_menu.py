#!/usr/bin/env python3
# test_v2_support_menu.py
"""
Functional test for the V2 Support menu: Latest Features and Send Feedback for end users.
Version: 0.261.294
Implemented in: 0.261.294

Administrators configure the Support menu in Admin Settings, and the classic navigation
offers it to users. V2 had only a Latest Features link that bounced users out to the
classic page, and no Send Feedback at all. It now has a Support group in the rail and its
own pages for both destinations.

These checks pin what the pages rely on:

- ``build_user_latest_features_payload`` sends only what an administrator shared, drops a
  release with nothing shared, filters shortcuts against the stored settings, applies the
  application title once, and passes only safe URLs;
- ``GET /api/v2/support/latest-features`` sits on the V2 blueprint behind the same gates as
  the classic page and returns no exception text;
- the shortcut endpoint resolver is shared by the admin and user routes;
- the SPA registers both pages, the rail draws the Support menu, and the Send Feedback page
  posts to the existing support endpoint;
- the TypeScript logic (rail state, shortcut translation, static renders) passes, including a
  cross-check that every shortcut in the real user catalogue can be followed from V2.
"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
ROUTE_FILE = APP_ROOT / "route_backend_v2.py"
SETTINGS_ROUTE_FILE = APP_ROOT / "route_backend_settings.py"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_support_menu_logic.ts"

payload_module = import_app_module("functions_support_latest_features")
support_menu_config = import_app_module("support_menu_config")

# Real Flask paths for the endpoints the catalogue names.
ENDPOINTS = {
    "frontend_chats.chats": "/chats",
    "frontend_profile.profile": "/profile",
    "frontend_workspace.workspace": "/workspace",
    "frontend_support.support_latest_features": "/support/latest-features",
    "frontend_support.support_send_feedback": "/support/send-feedback",
}


def resolve_endpoint(endpoint):
    return ENDPOINTS.get(endpoint, "")


def build_user(settings):
    return payload_module.build_user_latest_features_payload(
        settings,
        resolve_endpoint_url=resolve_endpoint,
        resolve_static_url=lambda path: f"/static/{path}",
        version="0.261.294",
    )


def user_features(payload):
    return [feature for group in payload["groups"] for feature in group["features"]]


def iter_actions(payload):
    for feature in user_features(payload):
        for action in feature["actions"]:
            yield feature, action


def _function(tree, name):
    return next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        ),
        None,
    )


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_version_is_at_least_the_implementing_release():
    """The application carries at least the version the V2 Support menu arrived in."""
    print("Testing the application version...")
    assert_app_version_at_least("0.261.294")
    return True


def test_user_payload_shares_only_what_administrators_shared():
    """Hidden announcements, and releases with nothing left, never reach users."""
    print("\nTesting announcement visibility...")

    defaults = support_menu_config.get_default_support_latest_features_visibility()
    default_ids = {feature["id"] for feature in user_features(build_user({}))}
    expected_default = {feature_id for feature_id, visible in defaults.items() if visible}
    assert default_ids == expected_default, (
        "With nothing stored, users must see exactly the catalogue's default selection"
    )
    assert "deployment" not in default_ids and "redis_key_vault" not in default_ids, (
        "Infrastructure announcements start hidden"
    )

    catalogue = support_menu_config.get_support_latest_feature_release_groups()
    archive_ids = [feature["id"] for feature in catalogue[-1]["features"]]
    hidden = {feature_id: False for feature_id in archive_ids}
    hidden["release_250_charts"] = False
    payload = build_user({"support_latest_features_visibility": hidden})
    shown_ids = {feature["id"] for feature in user_features(payload)}
    assert "release_250_charts" not in shown_ids
    assert catalogue[-1]["id"] not in [group["id"] for group in payload["groups"]], (
        "A release with every announcement hidden must not appear as an empty group"
    )

    for feature in user_features(payload):
        assert "default_visible" not in feature, (
            "Users receive only shared announcements; the admin-only default flag is not sent"
        )

    everything_hidden = build_user(
        {"support_latest_features_visibility": {feature_id: False for feature_id in defaults}}
    )
    assert everything_hidden["groups"] == [], "Hiding everything leaves nothing to draw"
    assert everything_hidden["version"] == "0.261.294"

    print(f"  {len(default_ids)} default announcement(s); hidden ones and empty releases are dropped.")
    return True


def test_user_payload_filters_shortcuts_by_stored_settings():
    """Users see only shortcuts whose switches are on, as on the classic page."""
    print("\nTesting shortcut filtering...")

    docs_key = "enable_support_latest_feature_documentation_links"
    docs_off = build_user({"enable_semantic_kernel": True, docs_key: False})
    docs_on = build_user({"enable_semantic_kernel": True, docs_key: True})

    def documentation(payload):
        return [action for _feature, action in iter_actions(payload) if docs_key in action["requires_settings"]]

    assert documentation(docs_off) == [], "Documentation links must stay hidden while their switch is off"
    assert documentation(docs_on), "Documentation links must appear once their switch is on"
    assert all(action["kind"] == "external" for action in documentation(docs_on))

    agents_off = build_user({"enable_semantic_kernel": False})
    agent_links = [
        action
        for _feature, action in iter_actions(agents_off)
        if "enable_semantic_kernel" in action["requires_settings"]
    ]
    assert agent_links == [], "Agent shortcuts must stay hidden while agents are off"

    print(f"  {len(documentation(docs_on))} documentation shortcut(s) follow their switch.")
    return True


def test_user_payload_urls_are_safe():
    """Only same-origin paths, http(s) addresses and static screenshots reach the browser."""
    print("\nTesting shortcut and screenshot URLs...")

    payload = build_user(
        {
            "enable_semantic_kernel": True,
            "enable_support_latest_feature_documentation_links": True,
        }
    )
    checked = 0
    for feature, action in iter_actions(payload):
        href = action["href"]
        if action["kind"] == "external":
            assert href.startswith(("https://", "http://")), (feature["id"], href)
        else:
            assert action["kind"] == "page", (feature["id"], action)
            assert href.startswith("/") and not href.startswith("//") and "\\" not in href, href
        checked += 1
    for feature in user_features(payload):
        for image in feature["images"]:
            assert image["url"].startswith("/static/images/features/"), image["url"]

    assert checked > 20, f"Only {checked} shortcut(s) were checked; the catalogue looks empty."
    print(f"  {checked} shortcut(s) are safe destinations.")
    return True


def test_user_payload_applies_the_title_once():
    """A title containing the product name must not be substituted twice."""
    print("\nTesting application title personalization...")

    text = repr(build_user({"app_title": "SimpleChat Contoso"}))
    assert "SimpleChat Contoso" in text
    assert "SimpleChat Contoso Contoso" not in text, "The title was applied twice."

    plain = repr(build_user({"app_title": "Contoso Chat"}))
    assert "Contoso Chat" in plain and "SimpleChat" not in plain

    print("  The application title is applied once.")
    return True


def test_route_follows_the_classic_gates():
    """The user route sits on the V2 blueprint behind the classic page's gates."""
    print("\nTesting the route registration...")

    tree = ast.parse(_read(ROUTE_FILE))
    registrar = _function(tree, "register_route_backend_v2")
    assert registrar, "register_route_backend_v2 is missing"
    route = _function(registrar, "v2_support_latest_features")
    assert route, "v2_support_latest_features is not registered on the V2 user blueprint"

    decorators = [ast.unparse(decorator) for decorator in route.decorator_list]
    assert decorators == [
        "bp.route('/api/v2/support/latest-features', methods=['GET'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
        "enabled_required('enable_support_menu')",
    ], decorators

    source = ast.unparse(route)
    for needle in (
        "enable_support_latest_features",
        "build_user_latest_features_payload",
        "'Admin', 'User'",
        "_latest_feature_endpoint_url",
    ):
        assert needle in source, f"The route must use {needle}"
    assert "str(exc)" not in source and "repr(exc)" not in source, (
        "Exception text must not reach the client."
    )
    assert "latestFeaturesHiddenVersion" not in source, (
        "Hiding the rail shortcut must not hide the page, as on the classic page"
    )

    module_level = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "_latest_feature_endpoint_url" in module_level, (
        "The endpoint resolver must be shared at module level by the admin and user routes"
    )
    admin_registrar = _function(tree, "register_route_backend_v2_admin")
    assert _function(admin_registrar, "_latest_feature_endpoint_url") is None, (
        "The admin registrar must not keep a second copy of the resolver"
    )
    assert "_latest_feature_endpoint_url" in ast.unparse(
        _function(admin_registrar, "v2_admin_get_latest_features")
    )

    print("  The route is gated like the classic page and returns no exception text.")
    return True


def test_spa_wires_the_support_pages():
    """The rail draws the menu and both destinations are V2 routes."""
    print("\nTesting the SPA wiring...")

    app = _read(V2_SRC / "App.tsx")
    assert '<Route path="/support/latest-features" element={<SupportLatestFeaturesPage />} />' in app
    assert '<Route path="/support/send-feedback" element={<SupportSendFeedbackPage />} />' in app

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    assert "<SupportMenu collapsed={collapsed} />" in sidebar
    assert not (V2_SRC / "components" / "layout" / "LatestFeaturesLink.tsx").exists(), (
        "The classic-page link is replaced by the Support menu"
    )

    menu = _read(V2_SRC / "components" / "layout" / "SupportMenu.tsx")
    for needle in (
        "const MENU_STATE_KEY = 'support';",
        "readSidebarMenuExpanded",
        "withSidebarMenuExpanded",
        "aria-expanded={expanded}",
        "latestFeaturesHiddenVersion: version",
        "if (settingsLoading)",
        # A failed preference load leaves the store empty; writing the menu state from it would
        # replace the stored object and erase every other menu's choice.
        "state.error !== null",
        "if (settingsLoadFailed)",
        "useUserSettingsStore.getState().settings.sidebarMenuState",
    ):
        assert needle in menu, f"SupportMenu.tsx must keep {needle!r}"

    shared_keys = _read(V2_SRC / "lib" / "sidebarMenuState.ts")
    assert "'support'," in shared_keys, "The menu's state key must be one the classic interface keeps"

    # The two endpoints the pages call are the ones the server registers.
    support_feedback = _read(V2_SRC / "lib" / "supportFeedback.ts")
    match = re.search(r"SUPPORT_FEEDBACK_ENDPOINT = '([^']+)'", support_feedback)
    assert match and match.group(1) == "/api/support/send_feedback_email"
    assert "@bp.route('/api/support/send_feedback_email', methods=['POST'])" in _read(SETTINGS_ROUTE_FILE)

    latest = _read(V2_SRC / "lib" / "latestFeatures.ts")
    match = re.search(r"USER_LATEST_FEATURES_ENDPOINT = '([^']+)'", latest)
    assert match and match.group(1) == "/api/v2/support/latest-features"

    for page in ("SupportLatestFeaturesPage.tsx", "SupportSendFeedbackPage.tsx"):
        assert "display:none" not in _read(V2_SRC / "pages" / page).replace(" ", "")

    print("  The rail, routes and endpoints line up.")
    return True


def _catalogue_hrefs():
    """Every user shortcut with all of its switches on, as the server would resolve it."""
    payload = payload_module.build_latest_features_payload(
        {
            "enable_semantic_kernel": True,
            "enable_support_latest_feature_documentation_links": True,
        },
        resolve_endpoint_url=resolve_endpoint,
        resolve_static_url=lambda path: f"/static/{path}",
        version="0.261.294",
    )
    return sorted(
        {
            action["href"]
            for group in payload["user"]
            for feature in group["features"]
            for action in feature["actions"]
        }
    )


def test_support_logic_checks_pass():
    """Execute the TypeScript checks, skipping when the front-end toolchain is absent."""
    print("\nTesting Support menu logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript Support menu checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node
    # can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-support-menu-check.mjs"
    hrefs_file = V2_DIR / "node_modules" / ".cache-support-menu-hrefs.json"
    hrefs_file.write_text(json.dumps(_catalogue_hrefs()), encoding="utf-8")
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # apiClient reads import.meta.env, which only Vite provides.
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            env={**os.environ, "SUPPORT_MENU_CATALOGUE_HREFS": str(hrefs_file)},
            shell=(sys.platform == "win32"),
        )
    finally:
        for path in (bundle, hrefs_file):
            if path.exists():
                path.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript Support menu checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 25, f"Only {passed} Support menu checks ran; the runner likely broke."
    assert "catalogue cross-check skipped" not in result.stdout, (
        "The real catalogue shortcuts were not checked"
    )
    print(f"  ok  {passed} TypeScript Support menu checks passed")
    return True


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_user_payload_shares_only_what_administrators_shared,
        test_user_payload_filters_shortcuts_by_stored_settings,
        test_user_payload_urls_are_safe,
        test_user_payload_applies_the_title_once,
        test_route_follows_the_classic_gates,
        test_spa_wires_the_support_pages,
        test_support_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
