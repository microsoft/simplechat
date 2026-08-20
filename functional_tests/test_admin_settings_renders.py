#!/usr/bin/env python3
"""
Functional test that the Admin Settings page actually renders.
Version: 0.260.019
Implemented in: 0.260.019

Every other Admin Settings test inspects the template as text: field names, card
ids, tag balance, navigation parity. None of them execute it. A template can
satisfy all of those and still raise the moment Flask renders it, which is
exactly what happened when a card moved to a new tab and left the `{% set %}` it
depended on behind in its old pane.

This test renders the whole page through Jinja with the same undefined handling
Flask uses, so an UndefinedError surfaces here instead of as a 500 in the
browser.

The context is built from the route's own render_template call and the app
context processors, so it cannot drift as those change. Values are permissive
stand-ins: the point is to prove the template executes and that every name it
reaches for exists, not to assert on rendered content.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from jinja2 import Environment, FileSystemLoader  # noqa: E402

APP_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
)
TEMPLATE_DIR = os.path.join(APP_ROOT, "templates")
ROUTE_FILE = os.path.join(APP_ROOT, "route_frontend_admin_settings.py")
APP_FILE = os.path.join(APP_ROOT, "app.py")

if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import admin_settings_nav as admin_nav_module  # noqa: E402


class Permissive(dict):
    """Stand-in that yields another Permissive for any access.

    Settings are deeply nested and optional, so a fixed fixture would either be
    enormous or wrong. This lets the template walk any path it likes while still
    failing on a name that was never supplied at all.
    """

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Permissive()

    def __getitem__(self, name):
        return Permissive()

    def get(self, name, default=None):
        return Permissive()

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    def __str__(self):
        return ""

    def __html__(self):
        return ""

    def __call__(self, *args, **kwargs):
        return Permissive()

    def items(self):
        return []

    def keys(self):
        return []


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _context_names():
    """Names the real page is rendered with, read from the app rather than listed."""
    names = set()

    route = _read(ROUTE_FILE)
    anchor = route.index("render_template(\n                'admin_settings.html'")
    block = route[anchor:route.index("\n            )", anchor)]
    names.update(re.findall(r"^\s+([a-z_][a-z0-9_]*)=", block, re.M))

    app_source = _read(APP_FILE)
    for match in re.finditer(r"@app\.context_processor", app_source):
        chunk = app_source[match.start():match.start() + 6000]
        end = chunk.find("\n@")
        names.update(re.findall(r"^\s+([a-z_][a-z0-9_]*)=", chunk[:end if end != -1 else len(chunk)], re.M))

    return names


def _render():
    """Render admin_settings.html the way Flask would."""
    # Default undefined, matching Flask: attribute access on a missing name
    # raises, which is the failure this test exists to catch.
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    env.globals.update(
        url_for=lambda *a, **k: "/static/stub",
        get_flashed_messages=lambda *a, **k: [],
        config={"VERSION": "0.0.0-test"},
        session=Permissive(),
        request=Permissive(),
        g=Permissive(),
        csrf_token=lambda: "test-token",
    )

    names = _context_names()
    assert "settings" in names, "Sanity check failed: route context not parsed"
    assert "admin_landing_tab" in names, "Sanity check failed: context processors not parsed"

    context = {name: Permissive() for name in names}
    # The navigation drives which tabs and panes exist, so use the real thing.
    context["admin_nav"] = admin_nav_module.ADMIN_NAV
    context["admin_landing_tab"] = admin_nav_module.get_landing_tab_id()
    context["mcp_ui_enabled"] = True

    return env.get_template("admin_settings.html").render(**context)


def test_admin_settings_renders_without_error():
    """The page must execute, not merely parse."""
    print("Testing Admin Settings renders...")

    markup = _render()
    assert len(markup) > 100_000, f"Rendered output looks truncated: {len(markup)} chars"

    print(f"Admin Settings rendered ({len(markup):,} characters).")
    return True


def test_every_navigation_tab_renders_a_pane():
    """A tab in the map with no pane is a dead end in the UI."""
    print("Testing every navigation tab renders a pane...")

    markup = _render()
    rendered = set(re.findall(r'<div class="tab-pane[^"]*" id="([a-z0-9-]+)" role="tabpanel"', markup))

    missing = sorted(set(admin_nav_module.get_tab_ids()) - rendered)
    assert not missing, f"Tabs in the navigation map that rendered no pane: {missing}"

    print(f"All {len(admin_nav_module.get_tab_ids())} navigation tabs rendered a pane.")
    return True


def test_exactly_one_admin_pane_is_active():
    """Landing on no tab, or on two, are both broken states."""
    print("Testing exactly one Admin Settings pane is active...")

    markup = _render()
    active = re.findall(
        r'<div class="tab-pane fade show active" id="([a-z0-9-]+)" role="tabpanel"', markup
    )

    # Nested tab widgets, such as the governance info panel, carry their own
    # active tab and are not part of the Admin Settings navigation.
    tab_ids = set(admin_nav_module.get_tab_ids())
    active_admin = [tab for tab in active if tab in tab_ids]

    assert len(active_admin) == 1, (
        f"Expected exactly one active Admin Settings pane, got {active_admin}"
    )
    assert active_admin[0] == admin_nav_module.get_landing_tab_id(), (
        f"Active pane '{active_admin[0]}' is not the landing tab "
        f"'{admin_nav_module.get_landing_tab_id()}'"
    )
    assert active_admin[0] != "latest-features", (
        "Latest Features must never be the pane an admin lands on"
    )

    print(f"Exactly one active pane, and it is the landing tab '{active_admin[0]}'.")
    return True


def test_render_catches_a_planted_undefined():
    """A guard that cannot fail is worthless, so prove it catches the real bug."""
    print("Testing the render catches a planted undefined variable...")

    pane = os.path.join(TEMPLATE_DIR, "admin", "_panes", "actions.html")
    original = _read(pane)
    assert "{% set analyze_capability" in original, (
        "Expected actions.html to declare analyze_capability locally"
    )

    planted = re.sub(r"{%-?\s*set\s+analyze_capability\s*=.*?%}", "", original)
    try:
        with open(pane, "w", encoding="utf-8", newline="") as handle:
            handle.write(planted)
        try:
            _render()
        except Exception as error:  # noqa: BLE001 - this is the expected path
            assert "analyze_capability" in str(error), (
                f"Render failed, but not for the planted reason: {error}"
            )
            print("The render catches a planted undefined variable.")
            return True
        raise AssertionError(
            "Removing a required declaration did not break the render, so this "
            "test would not have caught the original bug"
        )
    finally:
        with open(pane, "w", encoding="utf-8", newline="") as handle:
            handle.write(original)


if __name__ == "__main__":
    tests = [
        test_admin_settings_renders_without_error,
        test_every_navigation_tab_renders_a_pane,
        test_exactly_one_admin_pane_is_active,
        test_render_catches_a_planted_undefined,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
