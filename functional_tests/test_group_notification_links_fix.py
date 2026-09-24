# test_group_notification_links_fix.py
"""
Functional test for the group notification links.
Version: 0.261.147
Implemented in: 0.261.147

Four group notifications linked to ``/manage_group/<id>``, a path no route serves:
the group-created notification, the two member-added notifications (to the new
member and to the person who added them) and the role-changed notification. The
group management page is ``/groups/<group_id>``, served by
``route_frontend_groups.manage_group``.

This test pins that:

- no application code builds a ``/manage_group`` path, in Python, JavaScript,
  templates or the V2 sources;
- each of those notifications, sent by the real helper or the real classic route,
  links to ``/groups/<group_id>`` for the group it concerns, and that link resolves
  against the application's registered routes to ``manage_group``;
- every literal group-page link a notification carries anywhere in the application
  resolves to a registered page.
"""

import ast
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule

from test_support.group_directory_harness import group_directory_environment, person


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_SOURCE_ROOT = REPO_ROOT / "application" / "v2_ui" / "src"
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".html"}
# ``/manage_group`` as a path; ``manage_group.js`` and ``manage_group.html`` are file names.
MANAGE_GROUP_PATH = re.compile(r"/manage_group(?![\w.-])")
GROUP_PAGE_PREFIXES = ("/groups", "/group_workspaces", "/v2/groups", "/manage_group")
MANAGE_ENDPOINT = "route_frontend_groups.py:manage_group"
GROUP_ID = "5b0f3c1e-8d7a-4c1b-9f2e-0a1b2c3d4e5f"


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


def assert_links_to_the_manage_page(pages, notification, group_id):
    assert notification["link_url"] == f"/groups/{group_id}"
    endpoint, arguments = resolve(pages, notification["link_url"])
    assert (endpoint, arguments) == (MANAGE_ENDPOINT, {"group_id": group_id})


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def test_no_application_code_builds_a_manage_group_path():
    offenders = []
    scanned = 0
    for path in _application_sources():
        scanned += 1
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if MANAGE_GROUP_PATH.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    assert scanned > 500, "the scan must cover the application sources"
    assert offenders == []


def test_the_manage_page_route_is_the_one_the_links_name(pages):
    assert resolve(pages, f"/groups/{GROUP_ID}") == (MANAGE_ENDPOINT, {"group_id": GROUP_ID})
    with pytest.raises((NotFound, MethodNotAllowed)):
        resolve(pages, f"/manage_group/{GROUP_ID}")


def test_the_group_created_notification_links_to_the_new_group(env, pages):
    env.as_user("outsider-1")
    for response in (
        env.create({"name": "Native group"}),
        env.call("POST", "/api/groups", {"name": "Classic group"}),
    ):
        assert response.status_code == 201
    created_ids = [notification["metadata"]["group_id"] for notification in env.notifications]
    assert len(created_ids) == 2 and all(created_ids)
    for notification, group_id in zip(env.notifications, created_ids):
        assert notification["notification_type"] == "group_created"
        assert notification["link_context"] == {"workspace_type": "group", "group_id": group_id}
        assert_links_to_the_manage_page(pages, notification, group_id)


def test_both_member_added_notifications_link_to_the_group(env, pages):
    group = {"id": GROUP_ID, "name": "Operations"}
    env.operations_namespace["_notify_group_member_addition"](
        group_doc=group,
        member_doc=person("member-1"),
        member_role="user",
        added_by_email="olive.owner@example.test",
        actor_user={"userId": "owner-1"},
    )
    assert [notification["user_id"] for notification in env.notifications] == ["member-1", "owner-1"]
    for notification in env.notifications:
        assert notification["notification_type"] == "group_member_added"
        assert notification["link_context"] == {"workspace_type": "group", "group_id": GROUP_ID}
        assert_links_to_the_manage_page(pages, notification, GROUP_ID)


def test_the_role_changed_notification_links_to_the_group(env, pages):
    env.seed_group(GROUP_ID, "Operations")
    env.as_user("owner-1")
    response = env.call("PATCH", f"/api/groups/{GROUP_ID}/members/member-1", {"role": "Admin"})
    assert response.status_code == 200, response.get_json()
    [notification] = env.notifications
    assert (notification["user_id"], notification["title"]) == ("member-1", "Role Changed")
    assert notification["metadata"]["group_id"] == GROUP_ID
    assert_links_to_the_manage_page(pages, notification, GROUP_ID)


def _rendered(node):
    """A literal or f-string link with each interpolation replaced by ``x``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "x" for part in node.values)
    return None


def test_every_literal_group_page_link_resolves_to_a_registered_page(pages):
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
                if link and link.startswith(GROUP_PAGE_PREFIXES):
                    links.append((f"{path.name}:{node.lineno}", link))
    unresolved = []
    for location, link in links:
        try:
            endpoint, _arguments = resolve(pages, link)
        except (NotFound, MethodNotAllowed):
            unresolved.append((location, link))
            continue
        if urlsplit(link).path.startswith("/groups/"):
            assert endpoint == MANAGE_ENDPOINT, (location, link)
    assert unresolved == []
    # The scan is not vacuous: the classic role route and the group document links are found.
    assert any(link.startswith("/groups/") for _location, link in links)
    assert any(link.startswith("/group_workspaces") for _location, link in links)
    assert any(link.startswith("/v2/groups/") for _location, link in links)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
