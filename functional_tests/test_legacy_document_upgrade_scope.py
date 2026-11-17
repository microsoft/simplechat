# test_legacy_document_upgrade_scope.py
"""
Functional test for the scope-explicit legacy document upgrade.
Version: 0.261.448
Implemented in: 0.261.448

The classic upgrade routes backfill the saved active group or public workspace, and the public
path of ``upgrade_legacy_documents`` writes through its personal branch, so a V2 workspace that
names its scope in the path needs its own upgrade. These tests run the real
``functions_legacy_document_upgrade`` module against stored documents to pin that it:

- upgrades exactly the named group's or public workspace's legacy documents, through the right
  container and the right scope keyword;
- writes the same fields the classic upgrade writes, so both interfaces leave a document alike;
- records a failing document against that document and still upgrades the rest;
- asks its authorizer before the first read and before every document, and lets a refusal stop it;
- stays bounded to one request's worth of documents and says when more remain.
"""

import ast
import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from werkzeug.exceptions import Forbidden

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.agent_delegation import APP_ROOT, module_stub
from test_support.versioning import assert_app_version_at_least


class LegacyContainer:
    """Answers the upgrade's one query shape and remembers what it was asked."""

    def __init__(self, scope_field, records):
        self.scope_field = scope_field
        self.records = records
        self.queries = []

    def query_items(self, query, parameters=None, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        assert "NOT IS_DEFINED(c.percentage_complete)" in query, query
        assert f"c.{self.scope_field} = @owner" in query, query
        self.queries.append((query, deepcopy(values), kwargs))
        matching = [
            record for record in self.records.values()
            if record.get(self.scope_field) == values["@owner"] and "percentage_complete" not in record
        ]
        return deepcopy(matching[:values["@limit"]])


class Environment:
    def __init__(self, monkeypatch):
        self.updates = []
        self.failing = set()
        self.logs = []
        self.group_container = LegacyContainer("group_id", {})
        self.public_container = LegacyContainer("public_workspace_id", {})

        def update_document(**kwargs):
            if kwargs["document_id"] in self.failing:
                raise RuntimeError("PRIVATE-PROVIDER-DIAGNOSTIC")
            # The real update_document finds the document in the container its scope keyword names
            # and nowhere else; a write against the wrong scope is a document that is not found.
            container = self.public_container if "public_workspace_id" in kwargs else (
                self.group_container if "group_id" in kwargs else None
            )
            record = container.records.get(kwargs["document_id"]) if container else None
            if record is None:
                raise LookupError("Document not found")
            record["percentage_complete"] = kwargs["percentage_complete"]
            self.updates.append(deepcopy(kwargs))
            return {"updated": True}

        def log_event(message, extra=None, level=None, **kwargs):
            self.logs.append((message, deepcopy(extra), level))

        monkeypatch.setitem(sys.modules, "config", module_stub(
            "config", cosmos_group_documents_container=self.group_container,
            cosmos_public_documents_container=self.public_container,
        ))
        monkeypatch.setitem(sys.modules, "functions_appinsights", module_stub("functions_appinsights", log_event=log_event))
        monkeypatch.setitem(sys.modules, "functions_documents", module_stub("functions_documents", update_document=update_document))
        name = "functions_legacy_document_upgrade_under_test"
        spec = importlib.util.spec_from_file_location(name, APP_ROOT / "functions_legacy_document_upgrade.py")
        self.module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, self.module)
        spec.loader.exec_module(self.module)

    def add(self, container, identifier, **fields):
        record = {"id": identifier, "file_name": f"{identifier}.pdf", **fields}
        container.records[identifier] = record
        return record


@pytest.fixture
def env(monkeypatch):
    return Environment(monkeypatch)


def seed_group(env):
    scope = env.group_container
    env.add(scope, "legacy-a", group_id="group-a", number_of_pages=3, num_chunks=7)
    env.add(scope, "legacy-b", group_id="group-a")
    env.add(scope, "current-a", group_id="group-a", percentage_complete=100)
    env.add(scope, "legacy-elsewhere", group_id="group-b")


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.448")


def test_group_scope_upgrades_only_the_named_groups_legacy_documents(env):
    seed_group(env)
    checks = []

    receipt, status = env.module.upgrade_legacy_scope_documents(
        "manager", group_id="group-a", authorize=lambda: checks.append("checked"),
    )

    assert status == 200
    assert receipt == {
        "message": "Upgraded 2 group document(s) to the new format.",
        "upgraded_count": 2, "remaining": False, "errors": [], "group_id": "group-a",
    }
    assert [update["document_id"] for update in env.updates] == ["legacy-a", "legacy-b"]
    for update in env.updates:
        assert update["group_id"] == "group-a" and update["user_id"] == "manager"
        assert "public_workspace_id" not in update
        assert update["percentage_complete"] == 100 and update["status"] == "Processing complete"
        assert update["shared_group_ids"] == []
    (query, values, kwargs), = env.group_container.queries
    assert values["@owner"] == "group-a" and kwargs == {"enable_cross_partition_query": True}
    assert env.public_container.queries == []
    # The pages come from the document, falling back to its chunks, then to one.
    assert env.updates[0]["number_of_pages"] == 3 and env.updates[0]["num_chunks"] == 3
    assert env.updates[0]["current_file_chunk"] == 7
    assert env.updates[1]["number_of_pages"] == 1 and env.updates[1]["current_file_chunk"] == 1
    # Nothing is asked before the first read and again before each of the two documents.
    assert checks == ["checked"] * 3


def test_public_scope_writes_through_the_public_branch_not_the_personal_one(env):
    scope = env.public_container
    env.add(scope, "legacy-public", public_workspace_id="public-a", num_chunks=2)
    env.add(scope, "legacy-other", public_workspace_id="public-b")

    receipt, status = env.module.upgrade_legacy_scope_documents(
        "manager", public_workspace_id="public-a", authorize=lambda: None,
    )

    assert status == 200
    assert receipt["message"] == "Upgraded 1 public workspace document(s) to the new format."
    assert receipt["public_workspace_id"] == "public-a" and "group_id" not in receipt
    [update] = env.updates
    # update_document picks the public container from public_workspace_id; without it the write
    # looks the document up in the personal container, where a public document is never found.
    assert update["public_workspace_id"] == "public-a" and update["document_id"] == "legacy-public"
    assert "group_id" not in update and "shared_group_ids" not in update
    assert env.group_container.queries == []


def classic_update_fields():
    """The keyword names and constant values the classic group upgrade writes."""
    tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade_legacy_documents"
    )
    loop = next(node for node in ast.walk(function) if isinstance(node, ast.For))
    branch = next(
        node for node in ast.walk(loop)
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "is_group"
    )
    call = next(node for node in ast.walk(branch) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "update_document")
    fields = {}
    for keyword in call.keywords:
        try:
            fields[keyword.arg] = ast.literal_eval(keyword.value)
        except ValueError:
            fields[keyword.arg] = None
    return fields


def test_both_interfaces_write_the_same_fields(env):
    """Upgrading in V2 must leave a group document as the classic upgrade does."""
    classic = classic_update_fields()
    assert "percentage_complete" in classic and "shared_group_ids" in classic, classic
    env.add(env.group_container, "legacy-a", group_id="group-a")

    env.module.upgrade_legacy_scope_documents("manager", group_id="group-a", authorize=lambda: None)

    [update] = env.updates
    assert set(update) == set(classic)
    for name, value in classic.items():
        if value is not None:
            assert update[name] == value, f"{name}: V2 writes {update[name]!r}, classic writes {value!r}"


def test_a_failing_document_is_reported_and_does_not_block_the_rest(env):
    seed_group(env)
    env.failing.add("legacy-a")

    receipt, status = env.module.upgrade_legacy_scope_documents(
        "manager", group_id="group-a", authorize=lambda: None,
    )

    assert status == 207
    assert receipt["upgraded_count"] == 1
    assert receipt["message"] == "Upgraded 1 group document(s) to the new format. 1 could not be updated."
    assert receipt["errors"] == [{
        "document_id": "legacy-a", "file_name": "legacy-a.pdf",
        "error": "legacy_upgrade_failed", "message": "Unable to update this document.",
    }]
    assert [update["document_id"] for update in env.updates] == ["legacy-b"]
    # The cause is logged with its type only; the diagnostic never reaches the receipt or the log.
    assert "PRIVATE-PROVIDER-DIAGNOSTIC" not in repr(receipt) + repr(env.logs)
    assert any(extra.get("exception_type") == "RuntimeError" for _message, extra, _level in env.logs if extra)


def test_a_refusal_part_way_through_stops_the_upgrade(env):
    seed_group(env)
    calls = []

    def authorize():
        calls.append(1)
        if len(calls) == 3:
            raise Forbidden("You do not have permission to manage this group's documents.")

    with pytest.raises(Forbidden):
        env.module.upgrade_legacy_scope_documents("manager", group_id="group-a", authorize=authorize)

    # The read and the first document were authorized; the second was refused before its write.
    assert [update["document_id"] for update in env.updates] == ["legacy-a"]


def test_a_refusal_before_the_read_never_queries_the_workspace(env):
    seed_group(env)

    def refuse():
        raise Forbidden("This operation is unavailable for the selected group.")

    with pytest.raises(Forbidden):
        env.module.upgrade_legacy_scope_documents("reader", group_id="group-a", authorize=refuse)

    assert env.group_container.queries == [] and env.updates == []


def test_one_request_is_bounded_and_says_when_more_remain(env, monkeypatch):
    monkeypatch.setattr(env.module, "MAX_LEGACY_UPGRADE_DOCUMENTS", 3)
    for index in range(5):
        env.add(env.group_container, f"legacy-{index}", group_id="group-a")

    receipt, status = env.module.upgrade_legacy_scope_documents(
        "manager", group_id="group-a", authorize=lambda: None,
    )

    assert status == 200 and receipt["upgraded_count"] == 3 and receipt["remaining"] is True
    assert receipt["message"].endswith("More older documents remain; update again to continue.")
    assert env.group_container.queries[0][1]["@limit"] == 4, "one more than the cap tells whether any remain"
    # The next request continues with what is left.
    receipt, status = env.module.upgrade_legacy_scope_documents(
        "manager", group_id="group-a", authorize=lambda: None,
    )
    assert status == 200 and receipt["upgraded_count"] == 2 and receipt["remaining"] is False
    assert not receipt["message"].endswith("update again to continue.")
    assert sorted(update["document_id"] for update in env.updates) == [f"legacy-{index}" for index in range(5)]


def test_exactly_one_scope_is_required(env):
    for arguments in ({}, {"group_id": "group-a", "public_workspace_id": "public-a"}):
        with pytest.raises(ValueError):
            env.module.upgrade_legacy_scope_documents("manager", authorize=lambda: None, **arguments)
    assert env.group_container.queries == [] and env.public_container.queries == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
