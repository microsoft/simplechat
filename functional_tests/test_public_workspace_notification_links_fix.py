#!/usr/bin/env python3
# test_public_workspace_notification_links_fix.py
"""
Functional test for the public workspace notification links.
Version: 0.261.146
Implemented in: 0.261.146

Two public workspace notifications linked to
``/manage_public_workspace?workspace_id=<id>``, a path no route serves: the
member-added notification and the role-changed notification, both sent from
``route_backend_public_workspaces.py``. The public workspace management page is
``/public_workspaces/<workspace_id>``, served by
``route_frontend_public_workspaces.manage_public_workspace``.

This test pins that:

- no application code builds a ``/manage_public_workspace`` path, in Python,
  JavaScript, templates or the V2 sources;
- the management page route is the one the links name;
- every literal public-workspace page link a notification carries anywhere in the
  application resolves to a registered page, and the two fixed links resolve to
  the management page.
"""

import ast
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_SOURCE_ROOT = REPO_ROOT / "application" / "v2_ui" / "src"
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".html"}
# ``/manage_public_workspace`` as a path; ``manage_public_workspace.js`` and
# ``manage_public_workspace.html`` are file names.
MANAGE_PUBLIC_PATH = re.compile(r"/manage_public_workspace(?![\w.-])")
PUBLIC_PAGE_PREFIXES = ("/public_workspaces", "/public_directory", "/v2/public", "/manage_public_workspace")
MANAGE_ENDPOINT = "route_frontend_public_workspaces.py:manage_public_workspace"
WORKSPACE_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
FIXED_SITE = "route_backend_public_workspaces.py"


def _application_sources():
    for root in (APP_ROOT, V2_SOURCE_ROOT):
        for path in sorted(root.rglob("*")):
            if path.suffix in SOURCE_SUFFIXES and not {"vendor", "node_modules"} & set(path.parts):
                yield path


def _route_decorators():
    for path in sorted(APP_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "route" and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)
                ):
                    yield path.name, node.name, decorator.args[0].value


@pytest.fixture(scope="module")
def pages():
    """Every registered route, matched as a browser follows a link (GET)."""
    return Map([
        Rule(route_path, endpoint=f"{file_name}:{function_name}")
        for file_name, function_name, route_path in _route_decorators()
    ]).bind("simplechat.test")


def resolve(pages, link_url):
    parts = urlsplit(link_url)
    assert not parts.scheme and not parts.netloc, link_url
    return pages.match(parts.path, method="GET")


def _rendered(node):
    """A literal or f-string link with each interpolation replaced by a sample id."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else WORKSPACE_ID
            for part in node.values
        )
    return None


def _public_page_links():
    links = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg not in ("link_url", "decision_link_url"):
                    continue
                link = _rendered(keyword.value)
                if link and link.startswith(PUBLIC_PAGE_PREFIXES):
                    links.append((path.name, node.lineno, link))
    return links


def test_no_application_code_builds_a_manage_public_workspace_path():
    offenders = []
    scanned = 0
    for path in _application_sources():
        scanned += 1
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if MANAGE_PUBLIC_PATH.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    assert scanned > 500, "the scan must cover the application sources"
    assert offenders == []


def test_the_manage_page_route_is_the_one_the_links_name(pages):
    assert resolve(pages, f"/public_workspaces/{WORKSPACE_ID}") == (
        MANAGE_ENDPOINT, {"workspace_id": WORKSPACE_ID},
    )
    with pytest.raises((NotFound, MethodNotAllowed)):
        resolve(pages, "/manage_public_workspace")


def test_every_literal_public_page_link_resolves_to_a_registered_page(pages):
    links = _public_page_links()
    unresolved = []
    for file_name, line_number, link in links:
        try:
            endpoint, arguments = resolve(pages, link)
        except (NotFound, MethodNotAllowed):
            unresolved.append((f"{file_name}:{line_number}", link))
            continue
        if urlsplit(link).path.startswith("/public_workspaces/"):
            assert (endpoint, arguments) == (MANAGE_ENDPOINT, {"workspace_id": WORKSPACE_ID}), (
                file_name, line_number, link,
            )
    assert unresolved == []
    # Not vacuous: both fixed notifications are found and link to the management page.
    fixed = [link for file_name, _line, link in links if file_name == FIXED_SITE]
    assert fixed.count(f"/public_workspaces/{WORKSPACE_ID}") >= 2, fixed


def test_the_fixed_links_quote_the_workspace_id():
    """The id is URL-encoded, as the group management links are."""
    tree = ast.parse((APP_ROOT / FIXED_SITE).read_text(encoding="utf-8"))
    quoted = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "link_url" or not isinstance(keyword.value, ast.JoinedStr):
                continue
            parts = keyword.value.values
            if not (parts and isinstance(parts[0], ast.Constant) and parts[0].value == "/public_workspaces/"):
                continue
            [interpolation] = [part for part in parts if isinstance(part, ast.FormattedValue)]
            call = interpolation.value
            assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "quote", ast.dump(call)
            assert any(
                keyword_arg.arg == "safe" and isinstance(keyword_arg.value, ast.Constant)
                and keyword_arg.value.value == ""
                for keyword_arg in call.keywords
            ), ast.dump(call)
            quoted += 1
    assert quoted == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
