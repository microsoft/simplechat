#!/usr/bin/env python3
# test_v2_bootstrap_branding_and_navigation.py
"""
Functional test for the V2 bootstrap branding and navigation blocks.
Version: 0.261.047
Implemented in: 0.261.047

The V2 SPA cannot read Jinja context, so everything the classic interface gets from
``app_settings`` and the ``inject_settings`` context processor has to arrive in the
bootstrap payload instead. Three things were missing, and each one made an
Appearance setting look broken rather than merely absent:

  - No favicon URL, so a custom icon never replaced the shipped one. The static
    file keeps a stable name, so only the version counter tells a browser to
    fetch it again -- which is exactly what ``base.html`` does and the compiled
    SPA shell could not.
  - No landing page fields, so the landing text, its alignment and the home page
    logo size configured a page that did not exist in V2.
  - No navigation block, so Custom Pages and External Links were invisible in the
    V2 rail no matter how they were configured.

``route_backend_v2`` cannot be imported in a test environment: it reaches
``config.py``, which builds live Azure clients at import time. Rather than assert
on the shape of its source, this test lifts the three builders out with ``ast``
and runs them against injected dependencies, so the assertions are about what the
functions actually return.
"""

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
BACKEND_V2 = APP_ROOT / "route_backend_v2.py"

# The builders under test. There is no module-level constant to lift: the landing copy
# is passed through exactly as stored, deliberately.
LIFTED_FUNCTIONS = ("_build_branding", "_coerce_logo_scale", "_menu_name", "_build_navigation")

branding_urls = import_app_module("functions_branding_urls")
fields_module = import_app_module("admin_settings_fields")


def load_builders(custom_pages_nav=None, nav_raises=False):
    """Execute the bootstrap builders in isolation from the Flask application.

    Only the names the lifted functions actually reference are provided. Anything
    they reach for that is not supplied here raises, which keeps the injection
    honest: the test cannot quietly diverge from the real dependency set.
    """
    tree = ast.parse(BACKEND_V2.read_text(encoding="utf-8"))

    wanted = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in LIFTED_FUNCTIONS
    ]

    lifted_names = {node.name for node in wanted}
    missing = set(LIFTED_FUNCTIONS) - lifted_names
    assert not missing, (
        "route_backend_v2.py no longer defines these bootstrap builders, so the SPA "
        f"cannot be receiving what this test checks: {sorted(missing)}"
    )

    def fake_get_custom_pages_nav(_settings):
        if nav_raises:
            raise RuntimeError("custom page metadata unavailable")
        return list(custom_pages_nav or [])

    namespace = {
        "logging": __import__("logging"),
        "log_event": lambda *args, **kwargs: None,
        "get_custom_pages_nav": fake_get_custom_pages_nav,
        "build_custom_logo_urls": branding_urls.build_custom_logo_urls,
        "build_favicon_url": branding_urls.build_favicon_url,
        "is_safe_external_link_url": fields_module.is_safe_external_link_url,
        "LANDING_PAGE_ALIGNMENTS": fields_module.LANDING_PAGE_ALIGNMENTS,
        "LOGO_SCALE_DEFAULT_PERCENT": fields_module.LOGO_SCALE_DEFAULT_PERCENT,
        "LOGO_SCALE_MIN_PERCENT": fields_module.LOGO_SCALE_MIN_PERCENT,
        "LOGO_SCALE_MAX_PERCENT": fields_module.LOGO_SCALE_MAX_PERCENT,
    }

    module = ast.Module(body=wanted, type_ignores=[])
    exec(compile(module, str(BACKEND_V2), "exec"), namespace)
    return namespace


def test_favicon_url_is_versioned_only_for_a_custom_icon():
    """Without the version, a replaced favicon keeps serving from cache."""
    print("Testing the favicon URL...")

    assert_app_version_at_least("0.261.047")

    build = load_builders()["_build_branding"]

    default = build({}, {})
    assert default["favicon_url"] == "/static/images/favicon.ico", (
        f"The shipped favicon must be served unversioned, got {default['favicon_url']!r}"
    )

    custom = build({"custom_favicon_base64": "AAAA", "favicon_version": 9}, {})
    assert custom["favicon_url"] == "/static/images/favicon.ico?v=9", (
        f"A custom favicon must carry its version, got {custom['favicon_url']!r}"
    )

    # An upload that has not bumped the counter yet must still produce a usable URL
    # rather than "?v=None".
    unversioned = build({"custom_favicon_base64": "AAAA"}, {})
    assert unversioned["favicon_url"] == "/static/images/favicon.ico?v=1", (
        f"A missing version must fall back to 1, got {unversioned['favicon_url']!r}"
    )

    print("  Favicon URLs are versioned exactly when a custom icon is stored.")
    return True


def test_logo_urls_follow_show_logo_and_the_dark_fallback():
    """Only a stored logo is advertised, and only while Show Logo is on."""
    print("\nTesting logo URLs...")

    build = load_builders()["_build_branding"]

    hidden = build(
        {"show_logo": False, "custom_logo_base64": "AAAA", "logo_version": 2}, {}
    )
    assert hidden["logo_url"] is None and hidden["logo_dark_url"] is None, (
        "Show Logo off must not advertise a logo URL"
    )

    light_only = build(
        {"show_logo": True, "custom_logo_base64": "AAAA", "logo_version": 2}, {}
    )
    assert light_only["logo_url"] == "/static/images/custom_logo.png?v=2"
    # One upload has to work in both themes, matching the server-rendered templates.
    assert light_only["logo_dark_url"] == light_only["logo_url"], (
        "A light-only logo must be reused in dark mode"
    )

    both = build(
        {
            "show_logo": True,
            "custom_logo_base64": "AAAA",
            "logo_version": 2,
            "custom_logo_dark_base64": "BBBB",
            "logo_dark_version": 5,
        },
        {},
    )
    assert both["logo_dark_url"] == "/static/images/custom_logo_dark.png?v=5", (
        f"A dedicated dark logo must be used, got {both['logo_dark_url']!r}"
    )

    print("  Logo URLs respect Show Logo and the dark-variant fallback.")
    return True


def test_classification_banner_requires_text():
    """An enabled banner with no text would render as a coloured empty strip."""
    print("\nTesting the classification banner...")

    build = load_builders()["_build_branding"]

    assert build({"classification_banner_enabled": True}, {})["classification_banner"] is None, (
        "An enabled banner with no text must not be sent"
    )
    assert build({"classification_banner_text": "SECRET"}, {})["classification_banner"] is None, (
        "Banner text alone must not enable the banner"
    )

    banner = build(
        {"classification_banner_enabled": True, "classification_banner_text": "SECRET"},
        {},
    )["classification_banner"]
    assert banner == {
        "enabled": True,
        "text": "SECRET",
        "color": "#ffc107",
        "text_color": "#ffffff",
    }, f"Unexpected banner payload: {banner!r}"

    print("  The banner is sent only when it is enabled and has text.")
    return True


def test_landing_page_fields_are_sent_and_bounded():
    """The home page renders from these three values on first paint."""
    print("\nTesting the landing page fields...")

    build = load_builders()["_build_branding"]

    # Cleared copy stays cleared. ``get_settings`` merges the seeded default into every
    # document, so a blank value is an administrator's deletion, and restoring default
    # wording -- which asserts acceptance of an acceptable use policy -- would put a
    # statement back on the page that they removed on purpose.
    for cleared in ("", "   ", None):
        assert build({"landing_page_text": cleared}, {})["landing_page_text"] == "", (
            f"Cleared landing copy must stay cleared, {cleared!r} did not"
        )

    blank = build({}, {})
    assert blank["landing_page_alignment"] == "left"
    assert blank["landing_page_logo_scale_percent"] == fields_module.LOGO_SCALE_DEFAULT_PERCENT

    configured = build(
        {
            "landing_page_text": "# Welcome",
            "landing_page_alignment": "center",
            "landing_page_logo_scale_percent": 250,
        },
        {},
    )
    assert configured["landing_page_text"] == "# Welcome"
    assert configured["landing_page_alignment"] == "center"
    assert configured["landing_page_logo_scale_percent"] == 250

    # A value outside the slider's range would render an unusable page rather than
    # being rejected at the door, so it is clamped to what the slider offers.
    assert build({"landing_page_logo_scale_percent": 5000}, {})[
        "landing_page_logo_scale_percent"
    ] == fields_module.LOGO_SCALE_MAX_PERCENT
    assert build({"landing_page_logo_scale_percent": "nonsense"}, {})[
        "landing_page_logo_scale_percent"
    ] == fields_module.LOGO_SCALE_DEFAULT_PERCENT
    assert build({"landing_page_alignment": "diagonal"}, {})[
        "landing_page_alignment"
    ] == "left", "An unknown alignment must fall back rather than reach the browser"

    print("  Landing page fields are passed through, defaulted and bounded.")
    return True


def test_unsafe_external_link_urls_are_dropped():
    """A stored javascript: URL would execute from every user's rail."""
    print("\nTesting external link URL schemes...")

    build = load_builders()["_build_navigation"]

    # Only the V2 settings PATCH applies the scheme rule on write. The server-rendered
    # admin form stores any non-empty string, so the read path cannot assume the
    # document is already clean.
    unsafe = [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)  ",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "vbscript:msgbox(1)",
    ]
    for url in unsafe:
        group = build(
            {
                "enable_external_links": True,
                "external_links": [{"label": "Trap", "url": url}],
            },
            ["User"],
        )["external_links"]
        assert group["items"] == [], f"{url!r} should have been dropped, got {group['items']!r}"

    safe = [
        "https://example.invalid/policies",
        "http://example.invalid/policies",
        "/custom/handbook",
    ]
    for url in safe:
        group = build(
            {
                "enable_external_links": True,
                "external_links": [{"label": "Policies", "url": url}],
            },
            ["User"],
        )["external_links"]
        assert [item["url"] for item in group["items"]] == [url], (
            f"{url!r} should have been kept, got {group['items']!r}"
        )

    print(f"  {len(unsafe)} unsafe URL scheme(s) dropped, {len(safe)} safe URL(s) kept.")
    return True


def test_external_links_are_gated_by_role_and_validated():
    """The classic rail shows these only to holders of a real application role."""
    print("\nTesting the external links group...")

    build = load_builders()["_build_navigation"]

    settings = {
        "enable_external_links": True,
        "external_links_menu_name": "Handbook",
        "external_links_force_menu": True,
        "external_links": [
            {"label": "Policies", "url": "https://example.invalid/policies"},
            {"label": "  ", "url": "https://example.invalid/blank-label"},
            {"label": "No URL", "url": "   "},
            "not-a-dict",
        ],
    }

    allowed = build(settings, ["User"])["external_links"]
    assert [item["label"] for item in allowed["items"]] == ["Policies"], (
        f"Malformed link entries must be dropped, got {allowed['items']!r}"
    )
    assert allowed["menu_name"] == "Handbook"
    assert allowed["force_menu"] is True

    for roles in ([], ["Viewer"], None):
        denied = build(settings, roles)["external_links"]
        assert denied["items"] == [], (
            f"External links must not be sent to roles {roles!r}"
        )

    assert build(settings, ["Admin"])["external_links"]["items"], (
        "Administrators must still see external links"
    )

    disabled = build({**settings, "enable_external_links": False}, ["User"])
    assert disabled["external_links"]["items"] == []
    assert disabled["external_links"]["enabled"] is False

    blank_name = build({**settings, "external_links_menu_name": "  "}, ["User"])
    assert blank_name["external_links"]["menu_name"] == "External Links", (
        "A blank menu name must fall back rather than render an unlabelled group"
    )

    print("  External links are role-gated, validated and named.")
    return True


def test_custom_pages_group_survives_a_failing_lookup():
    """A degraded rail is acceptable; a failed bootstrap is not."""
    print("\nTesting the custom pages group...")

    pages = [
        {
            "slug": "handbook",
            "label": "Handbook",
            "icon": "bi-book",
            "url": "/custom/handbook",
            "open_in_new_tab": True,
        },
        {"slug": "broken", "label": "No URL"},
    ]

    build = load_builders(custom_pages_nav=pages)["_build_navigation"]
    group = build(
        {"enable_custom_pages": True, "custom_pages_menu_name": "Guides"}, ["User"]
    )["custom_pages"]

    assert [item["slug"] for item in group["items"]] == ["handbook"], (
        f"A page with no URL cannot be linked to, got {group['items']!r}"
    )
    assert group["items"][0]["open_in_new_tab"] is True
    assert group["menu_name"] == "Guides"

    disabled = load_builders(custom_pages_nav=pages)["_build_navigation"](
        {"enable_custom_pages": False}, ["User"]
    )
    assert disabled["custom_pages"]["items"] == [], (
        "Custom pages must not be listed while the capability is off"
    )
    assert disabled["custom_pages"]["menu_name"] == "Custom Pages"

    failing = load_builders(nav_raises=True)["_build_navigation"]
    recovered = failing({"enable_custom_pages": True}, ["User"])
    assert recovered["custom_pages"]["items"] == [], (
        "A failed custom page lookup must degrade to an empty group"
    )
    assert recovered["external_links"]["items"] == []

    print("  Custom pages are listed, filtered and fail safely.")
    return True


def test_bootstrap_payload_carries_the_navigation_block():
    """The rail reads navigation from bootstrap; nothing else supplies it."""
    print("\nTesting the bootstrap payload wiring...")

    source = BACKEND_V2.read_text(encoding="utf-8")

    assert '"navigation": _build_navigation(settings, current_user_roles)' in source, (
        "The bootstrap payload must carry a navigation block built from the caller's "
        "roles, or Custom Pages and External Links cannot appear in the V2 rail"
    )

    print("  The bootstrap payload includes the navigation block.")
    return True


if __name__ == "__main__":
    tests = [
        test_favicon_url_is_versioned_only_for_a_custom_icon,
        test_logo_urls_follow_show_logo_and_the_dark_fallback,
        test_classification_banner_requires_text,
        test_landing_page_fields_are_sent_and_bounded,
        test_unsafe_external_link_urls_are_dropped,
        test_external_links_are_gated_by_role_and_validated,
        test_custom_pages_group_survives_a_failing_lookup,
        test_bootstrap_payload_carries_the_navigation_block,
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
