#!/usr/bin/env python3
# test_admin_settings_dependencies.py
"""
Functional test for Admin Settings dependency announcements.
Version: 0.260.008
Implemented in: 0.260.008

Some Admin Settings options only work when a different option is enabled, and
those two options often live in different tabs. That relationship used to be
communicated only in prose, in a tooltip, or in a flash message after saving,
so an admin could switch something on and have nothing happen with no visible
reason.

A dependent card now declares its prerequisite, and a shared module renders an
inline notice containing a mirror of the prerequisite control plus a link to
its card. This test pins the contract:

  1. Every declared prerequisite control exists.
  2. Every declared link target is a real card.
  3. The mirror control cannot double-post the prerequisite's value.
  4. Field-level dependencies declare a scope so unrelated controls in the same
     card are not disabled.
  5. The module is wired into the page and the backend stays authoritative.
"""

import re
import sys
from pathlib import Path

from test_support.templates import (
    ADMIN_SETTINGS_TEMPLATE,
    read_admin_settings_template,
)
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
DEPENDENCIES_JS = APP_ROOT / "static" / "js" / "admin" / "admin_settings_dependencies.js"
ADMIN_ROUTE = APP_ROOT / "route_frontend_admin_settings.py"

CARD_RE = re.compile(r'<div[^>]*\bid="(?P<card>[^"]+)"[^>]*\bdata-requires="(?P<req>[^"]+)"[^>]*>')
ATTR_RE = re.compile(r'(?P<name>data-requires-[\w-]+)="(?P<value>[^"]*)"')


def _declared_dependencies(markup):
    """Return every card that declares a prerequisite, with its attributes."""
    found = []
    for match in re.finditer(r"<div\b[^>]*data-requires=[^>]*>", markup):
        tag = match.group(0)
        card_id = re.search(r'\bid="([^"]+)"', tag)
        prerequisite = re.search(r'\bdata-requires="([^"]+)"', tag)
        if not card_id or not prerequisite:
            continue
        attrs = {m.group("name"): m.group("value") for m in ATTR_RE.finditer(tag)}
        found.append(
            {
                "card": card_id.group(1),
                "requires": prerequisite.group(1),
                "attrs": attrs,
            }
        )
    return found


def test_declared_dependencies_resolve():
    """A dependency pointing at a missing control or card is dead weight."""
    print("Testing Admin Settings dependency declarations...")

    assert_app_version_at_least("0.260.008")
    composed = read_admin_settings_template()
    element_ids = set(re.findall(r'\sid="([^"]+)"', composed))

    dependencies = _declared_dependencies(composed)
    assert dependencies, "Expected Admin Settings to declare dependencies"

    problems = []
    for dep in dependencies:
        if dep["requires"] not in element_ids:
            problems.append(
                f"{dep['card']} requires missing control '{dep['requires']}'"
            )

        target = dep["attrs"].get("data-requires-target", "")
        if target and target not in element_ids:
            problems.append(f"{dep['card']} links to missing card '{target}'")

        if not dep["attrs"].get("data-requires-label"):
            problems.append(f"{dep['card']} has no data-requires-label")

    assert not problems, "\n  ".join(["Dependency declaration problems:"] + problems)

    print(f"All {len(dependencies)} dependency declaration(s) resolve.")


def test_dependency_mirror_cannot_double_post():
    """The inline mirror must never carry a name, or settings post twice."""
    print("Testing Admin Settings dependency mirror safety...")

    source = DEPENDENCIES_JS.read_text(encoding="utf-8")

    # The proxy is built in JavaScript, so assert on how it is constructed.
    assert "proxy.setAttribute('data-dependency-proxy-for'" in source, (
        "Mirror control should record which input it proxies"
    )
    assert "proxy.name" not in source and 'proxy.setAttribute("name"' not in source, (
        "Mirror control must not be given a name attribute, otherwise the "
        "prerequisite would be submitted twice"
    )
    assert "data-ignore-settings-change" in source, (
        "Mirror control should be excluded from unsaved-change tracking"
    )

    print("Mirror control is name-less and cannot double-post.")


def test_field_level_dependencies_declare_scope():
    """Blanket-disabling a mixed card would switch off unrelated settings."""
    print("Testing Admin Settings dependency scoping...")

    composed = read_admin_settings_template()

    for dep in _declared_dependencies(composed):
        mode = dep["attrs"].get("data-requires-mode", "block")
        scope = dep["attrs"].get("data-requires-scope", "")

        if dep["card"] != "permissions-section":
            continue

        # Permissions holds both the SafetyViolationAdmin and FeedbackAdmin
        # toggles, and only the latter depends on User Feedback.
        assert mode == "block", "Permissions dependency should gate its control"
        assert scope == "#require_member_of_feedback_admin", (
            "Permissions dependency must scope to the FeedbackAdmin toggle so "
            f"the SafetyViolationAdmin toggle stays usable, got '{scope}'"
        )

    print("Field-level dependencies are correctly scoped.")


def test_dependency_module_is_wired_and_advisory_only():
    """Client-side gating is a courtesy; the backend must still enforce."""
    print("Testing Admin Settings dependency wiring...")

    assert DEPENDENCIES_JS.is_file(), f"Missing module at {DEPENDENCIES_JS}"

    parent = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    assert "js/admin/admin_settings_dependencies.js" in parent, (
        "Dependency module is not loaded by admin_settings.html"
    )

    # File Sync remains save-then-reconcile, so the backend keeps warning.
    route = ADMIN_ROUTE.read_text(encoding="utf-8")
    assert "file_sync_settings['redis_ready']" in route, (
        "Backend must still validate the File Sync Redis prerequisite; the "
        "client-side notice is advisory only"
    )

    print("Dependency module is wired and the backend still enforces.")


if __name__ == "__main__":
    tests = [
        test_declared_dependencies_resolve,
        test_dependency_mirror_cannot_double_post,
        test_field_level_dependencies_declare_scope,
        test_dependency_module_is_wired_and_advisory_only,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
