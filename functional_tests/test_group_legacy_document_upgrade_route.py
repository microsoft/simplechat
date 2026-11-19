# test_group_legacy_document_upgrade_route.py
"""
Functional test for the group workspace legacy document upgrade route.
Version: 0.261.448
Implemented in: 0.261.448

``POST /api/groups/<group_id>/documents/upgrade_legacy`` backfills a group's documents that
predate progress tracking. The classic route does the same for the saved active group, so a V2
Documents section that names its own group in the path needs a route that never consults that
preference. The real route, access and policy modules run in the group document harness, with
the upgrade's one write seam recording what it is asked.

These tests pin that the route:

- upgrades the named group's legacy documents for its Owner, Admin and DocumentManager, and
  refuses an ordinary member and a stranger without writing;
- is authorized as a metadata edit, so an inactive, locked or upload-disabled group refuses it;
- never consults the account's saved active group;
- refuses a request body or query parameters, an unknown group and a malformed group id;
- reports a document that could not be updated as a partial result.
"""

import importlib.util
import sys
from copy import deepcopy

import pytest

from test_group_document_management import management  # noqa: F401  (pytest fixture)
from test_group_document_read_apis import APP_ROOT, document, environment  # noqa: F401  (environment is a fixture)
from test_support.versioning import assert_app_version_at_least


ROUTE = "/api/groups/group-a/documents/upgrade_legacy"


def load_upgrade_module(patch):
    name = "functions_legacy_document_upgrade"
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    patch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def legacy(identifier, group_id="group-a"):
    record = document(identifier, group_id)
    del record["percentage_complete"]
    return record


@pytest.fixture
def upgrade(management):  # noqa: F811
    env = management
    env.source.records["legacy-1"] = legacy("legacy-1")
    env.source.records["legacy-2"] = legacy("legacy-2")
    env.source.records["legacy-elsewhere"] = legacy("legacy-elsewhere", "group-b")
    install_upgrade_seams(env)
    return env


def install_upgrade_seams(env):
    """Serve the upgrade's owner-scoped query from the harness store, record its one write, and bind
    the route to a fresh copy of the upgrade module that uses both."""
    patch = env.scoped_monkeypatch
    env.updates = []
    env.failing = set()

    def update_document(**kwargs):
        if kwargs["document_id"] in env.failing:
            raise RuntimeError("PRIVATE-PROVIDER-DIAGNOSTIC")
        record = env.source.records[kwargs["document_id"]]
        assert record["group_id"] == kwargs["group_id"], "A write must stay in the group it names."
        record["percentage_complete"] = kwargs["percentage_complete"]
        env.updates.append(deepcopy(kwargs))

    original_query = env.source.query_items

    def query_items(query, parameters=None, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        if "@owner" not in values:
            return original_query(query, parameters, **kwargs)
        assert "c.group_id = @owner" in query and "NOT IS_DEFINED(c.percentage_complete)" in query, query
        return [
            deepcopy(record) for record in env.source.records.values()
            if record.get("group_id") == values["@owner"] and "percentage_complete" not in record
        ][:values["@limit"]]

    env.source.query_items = query_items
    module = load_upgrade_module(patch)
    patch.setattr(module, "update_document", update_document)
    patch.setattr(env.route, "upgrade_legacy_scope_documents", module.upgrade_legacy_scope_documents)
    env.upgrade_module = module


def actor(env, oid):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": oid, "roles": ["User"]}


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.448")


@pytest.mark.parametrize("oid", ["owner", "admin", "manager"])
def test_a_content_manager_upgrades_the_named_groups_legacy_documents(upgrade, oid):
    env = upgrade
    actor(env, oid)

    response = env.client.post(ROUTE)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json() == {
        "message": "Upgraded 2 group document(s) to the new format.",
        "upgraded_count": 2, "remaining": False, "errors": [], "group_id": "group-a",
    }
    assert "no-store" in response.headers["Cache-Control"]
    assert sorted(update["document_id"] for update in env.updates) == ["legacy-1", "legacy-2"]
    assert all(update["user_id"] == oid and update["group_id"] == "group-a" for update in env.updates)
    assert "percentage_complete" not in env.source.records["legacy-elsewhere"]
    env.route.invalidate_group_search_cache.assert_called_once_with("group-a")


def test_the_saved_active_group_is_never_consulted(upgrade):
    env = upgrade
    env.active_group = "group-b"

    response = env.client.post(ROUTE)

    assert response.status_code == 200, response.get_data(as_text=True)
    env.user_settings.assert_not_called()
    assert response.get_json()["group_id"] == "group-a"
    assert "percentage_complete" not in env.source.records["legacy-elsewhere"]


@pytest.mark.parametrize("oid", ["reader", "stranger"])
def test_an_ordinary_member_and_a_stranger_are_refused_without_a_write(upgrade, oid):
    env = upgrade
    actor(env, oid)

    response = env.client.post(ROUTE)

    assert response.status_code == 403, response.get_data(as_text=True)
    assert env.updates == [] and env.source.writes == []
    env.route.invalidate_group_search_cache.assert_not_called()


@pytest.mark.parametrize("status", ["locked", "upload_disabled", "inactive", "unknown"])
def test_a_group_that_is_not_active_refuses_the_upgrade(upgrade, status):
    env = upgrade
    env.groups["group-a"]["status"] = status

    response = env.client.post(ROUTE)

    assert response.status_code == 403, response.get_data(as_text=True)
    assert env.updates == []


def test_an_unknown_group_is_not_found_and_a_malformed_id_is_refused(upgrade):
    env = upgrade

    assert env.client.post("/api/groups/no-such-group/documents/upgrade_legacy").status_code == 404
    assert env.client.post("/api/groups/bad%2Cid/documents/upgrade_legacy").status_code == 400
    assert env.updates == []


@pytest.mark.parametrize("request_arguments", [
    {"json": {"group_id": "group-b"}}, {"query_string": {"group_id": "group-b"}},
    {"query_string": {"unexpected": "1"}},
])
def test_a_request_body_or_query_is_refused(upgrade, request_arguments):
    env = upgrade

    response = env.client.post(ROUTE, **request_arguments)

    assert response.status_code == 400, response.get_data(as_text=True)
    assert env.updates == []
    assert "percentage_complete" not in env.source.records["legacy-elsewhere"]


def test_a_document_that_could_not_be_updated_is_a_partial_result(upgrade):
    env = upgrade
    env.failing.add("legacy-1")

    response = env.client.post(ROUTE)

    assert response.status_code == 207, response.get_data(as_text=True)
    body = response.get_json()
    assert body["upgraded_count"] == 1
    assert body["message"] == "Upgraded 1 group document(s) to the new format. 1 could not be updated."
    assert [(error["document_id"], error["error"]) for error in body["errors"]] == [("legacy-1", "legacy_upgrade_failed")]
    assert "PRIVATE-PROVIDER-DIAGNOSTIC" not in response.get_data(as_text=True)
    assert "percentage_complete" not in env.source.records["legacy-1"]
    env.route.invalidate_group_search_cache.assert_called_once_with("group-a")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
