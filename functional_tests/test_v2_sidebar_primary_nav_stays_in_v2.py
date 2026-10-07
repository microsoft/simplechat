#!/usr/bin/env python3
"""
Functional test for the V2 rail's primary navigation staying inside the V2 interface.
Version: 0.261.290
Implemented in: 0.261.290

Every primary link in the V2 rail -- Chats, Agents, My Workspace, Group Workspaces, Public
Workspaces, Approval requests and Content review -- opened the classic interface instead of
its V2 page (#1698).

The rail passed each destination through `safeSameOriginUrl(item.to, window.location.origin)`
from lib/adminOperations.ts, which returns a full URL such as `https://host/workspace`.
React Router only routes an absolute URL in-app when its path sits under the router's
basename. `/workspace` is outside `/v2`, so `<Link>` rendered a plain external anchor and the
browser loaded the classic Flask page at that path. The active highlight never matched
either. Two parallel fixes for the same XSS sink check had edited the line, and the merge
kept the one with the absolute URL. Both helper names satisfy the checker, so nothing failed.

This test ensures that:
  - every rail destination is a root-relative path with a matching V2 route,
  - the rail links are built by the relative `safeNavHref` allowlist rather than from the
    page origin,
  - no router link anywhere in the V2 source is built from the page origin, apart from the
    workspace section rail's `normalizeWorkspaceUrl`, which is checked to return a bare
    pathname.

These are source-level assertions, so they run without a deployment.
ui_tests/test_v2_sidebar_primary_nav_links.py clicks the rendered links against a live tenant.
"""

import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
SIDEBAR_PATH = V2_SRC / "components" / "layout" / "Sidebar.tsx"

# The one helper that may receive the page origin in a router `to=` prop, because it
# validates against that origin and then hands back only the URL's pathname.
ORIGIN_SAFE_ROUTE_HELPERS = ("normalizeWorkspaceUrl(",)


def _read(path):
    return path.read_text(encoding="utf-8")


def _nav_items_block(sidebar_source):
    """Return the NAV_ITEMS literal."""
    match = re.search(r"const NAV_ITEMS: NavItem\[\] = \[(.*?)\n\];", sidebar_source, re.DOTALL)
    assert match, "NAV_ITEMS could not be located in Sidebar.tsx"
    return match.group(1)


def _nav_item_paths(sidebar_source):
    paths = re.findall(r"\bto:\s*'([^']*)'", _nav_items_block(sidebar_source))
    assert paths, "NAV_ITEMS declares no destinations"
    return paths


def _balanced_expression(source, open_index):
    """Return the text between the brace at ``open_index`` and its matching close brace."""
    depth = 0
    for index in range(open_index, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[open_index + 1:index]
    raise AssertionError("Unbalanced braces after a to= attribute")


def _to_expressions(source):
    """Yield ``(line_number, expression)`` for every ``to={...}`` attribute in a TSX file."""
    for match in re.finditer(r"(?<![\w$.-])to=\{", source):
        open_index = match.end() - 1
        line_number = source.count("\n", 0, match.start()) + 1
        yield line_number, _balanced_expression(source, open_index)


def _primary_nav_to_expression(sidebar_source):
    """Return the `to=` expression on the NavLink rendered for each NAV_ITEMS entry."""
    start = sidebar_source.find("{NAV_ITEMS.map((item) => (")
    assert start != -1, "The rail no longer renders NAV_ITEMS with NAV_ITEMS.map"
    region = sidebar_source[start:]
    link = region.find("<NavLink")
    assert link != -1, "The primary navigation entries are no longer NavLinks"
    expressions = list(_to_expressions(region[link:]))
    assert expressions, "The primary NavLink has no to={...} expression"
    return expressions[0][1].strip()


def _function_body(source, name):
    match = re.search(rf"function {name}\([^)]*\)[^{{]*\{{", source)
    assert match, f"{name} could not be located"
    return _balanced_expression(source, match.end() - 1)


def test_primary_nav_paths_are_relative_v2_routes():
    """Every rail destination is a path under the router, with a V2 page behind it."""
    print("Testing primary navigation destinations...")

    sidebar = _read(SIDEBAR_PATH)
    app = _read(V2_SRC / "App.tsx")
    routes = set(re.findall(r'<Route\s+path="([^"]+)"', app))
    assert routes, "No routes could be read from App.tsx"

    for path in _nav_item_paths(sidebar):
        assert path.startswith("/") and not path.startswith("//"), (
            f"Rail destination {path!r} must be a root-relative path, resolved against the "
            "router's /v2 base"
        )
        assert ":" not in path, f"Rail destination {path!r} must not carry a URL scheme"
        assert path in routes, (
            f"Rail destination {path!r} has no V2 route, so the router would send it to the "
            "catch-all instead of a page"
        )

    print("Primary navigation destinations test passed!")
    return True


def test_primary_nav_links_are_never_absolute_urls():
    """An absolute URL outside /v2 is an external link to React Router: the classic page."""
    print("Testing primary navigation link targets...")

    sidebar = _read(SIDEBAR_PATH)
    expression = _primary_nav_to_expression(sidebar)

    assert expression == "safeNavHref(item.to)", (
        "The rail's NavLink must route through the relative safeNavHref allowlist, got "
        f"to={{{expression}}}"
    )
    assert "origin" not in expression and "safeSameOriginUrl" not in expression, (
        "The rail's NavLink must not build its target from the page origin: an absolute URL "
        "outside /v2 renders as an external anchor and reloads the classic interface (#1698)"
    )
    assert "lib/adminOperations" not in sidebar, (
        "Sidebar.tsx must not import from lib/adminOperations. Its safeSameOriginUrl returns "
        "a full URL, which is what sent every rail link to the classic interface"
    )

    print("Primary navigation link targets test passed!")
    return True


def test_safe_nav_href_returns_the_relative_path():
    """The allowlist hands back the path it was given, never a URL derived from it."""
    print("Testing safeNavHref...")

    sidebar = _read(SIDEBAR_PATH)
    body = _function_body(sidebar, "safeNavHref")

    assert "NAV_ITEMS.some((item) => item.to === value)" in body, (
        "safeNavHref must only accept destinations the rail itself declares"
    )
    assert "? value :" in body, (
        "safeNavHref must return the allowlisted path unchanged, so it stays relative"
    )
    fallback = re.search(r":\s*'([^']*)'\s*;", body)
    assert fallback and fallback.group(1) in _nav_item_paths(sidebar), (
        "safeNavHref's fallback must itself be a rail destination"
    )
    for forbidden in ("new URL", "origin", ".href", "location"):
        assert forbidden not in body, (
            f"safeNavHref must not use {forbidden!r}; turning the path into a full URL is "
            "the defect this guards against"
        )

    print("safeNavHref test passed!")
    return True


def test_router_links_are_not_built_from_the_page_origin():
    """No V2 router link builds its target from the page origin."""
    print("Testing router link targets across the V2 source...")

    offenders = []
    checked = 0
    for path in sorted(V2_SRC.rglob("*.tsx")):
        source = _read(path)
        for line_number, expression in _to_expressions(source):
            checked += 1
            uses_origin = re.search(r"\blocation\s*\.\s*origin\b|\bsafeSameOriginUrl\s*\(", expression)
            if not uses_origin:
                continue
            if any(helper in expression for helper in ORIGIN_SAFE_ROUTE_HELPERS) and (
                "safeSameOriginUrl" not in expression
            ):
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{relative}:{line_number}: to={{{' '.join(expression.split())}}}")

    assert checked, "No to={...} attributes were found in the V2 source"
    assert not offenders, (
        "Router links must take a path relative to the /v2 base. A target built from the page "
        "origin becomes an absolute URL, which React Router renders as an external link that "
        "reloads the classic page (#1698):\n  " + "\n  ".join(offenders)
    )

    # The exemption above is only sound while the helper still returns a bare pathname.
    workspace_context = _read(V2_SRC / "lib" / "workspaceContext.ts")
    helper = _function_body(workspace_context, "normalizeWorkspaceUrl")
    returns = re.findall(r"\breturn\s+([^;]+);", helper)
    assert returns == ["target.pathname"], (
        "normalizeWorkspaceUrl is exempt from the origin check because it returns only "
        f"target.pathname; it now returns {returns!r}"
    )

    print(f"Router link targets test passed ({checked} to= attributes checked)!")
    return True


def test_version_is_at_least_the_fix_version():
    """The application carries at least the version this fix arrived in."""
    print("Testing version...")
    assert_app_version_at_least(
        "0.261.290",
        reason="The V2 rail's primary links stay inside V2 from 0.261.290 (#1698).",
    )
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_primary_nav_paths_are_relative_v2_routes,
        test_primary_nav_links_are_never_absolute_urls,
        test_safe_nav_href_returns_the_relative_path,
        test_router_links_are_not_built_from_the_page_origin,
        test_version_is_at_least_the_fix_version,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
