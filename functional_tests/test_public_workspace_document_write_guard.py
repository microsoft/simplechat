# test_public_workspace_document_write_guard.py
"""
Functional test for the conditional public-workspace writer.
Version: 0.261.173
Implemented in: 0.261.173

``update_public_workspace_document_with_etag_guard`` (``functions_public_workspaces``)
is the public-workspace equivalent of ``update_group_document_with_etag_guard``
(``functions_group``): it re-reads the whole workspace document, re-applies one
change and writes it back conditionally on the read's ``_etag``, so a writer that
touches one field never restores the rest of the document (membership, status,
settings) from a stale copy.

The two guards are separate copies, so this test drives the **same** table of
behaviours through **both** of them against the etag-enforcing ``FakeContainer``
from ``test_file_sync_concurrent_write_safety.py`` (``replace_item`` refuses a
stale etag with 412 and a missing record with 404, and never creates). Any drift
between the group and public implementations fails at least one row.

The real function bodies are executed unchanged from their source files with
``execute_functions``; only the Cosmos container and the chat-bootstrap cache bump
are recording fakes, and no network is touched. The behaviours pinned are: a plain
commit bumps once; a concurrent change is re-read and re-applied; a lost response
is recognised as the committed write, not retried; ``attempts`` losses raise the
scope's own conflict with nothing written; a document deleted mid-write returns
``None`` and is never recreated; and an ``apply`` that raises writes nothing.
"""

import ast
import copy

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT


WS_ID = "ws-1"


def _exec_names(filename, names, namespace):
    """Execute the named module-level definitions (function, class or assignment) unchanged.

    ``execute_functions`` only selects functions, but the guard's ``attempts`` default
    is a module constant evaluated at def time and the conflict class is module level,
    so both must be present in the namespace before the guard's ``def`` runs.
    """
    tree = ast.parse((APP_ROOT / filename).read_text(encoding="utf-8"))
    selected = []
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(target in names for target in targets):
                selected.append(node)
                found.update(target for target in targets if target in names)
    assert found == set(names), f"Missing definitions in {filename}: {set(names) - found}"
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)


def _load_guard(filename, guard_name, helper_name, conflict_name, attempts_name, container):
    """Execute one guard (its helper, conflict class and attempts constant) with fakes."""
    bumps = []
    namespace = {
        "copy": copy,
        "MatchConditions": MatchConditions,
        "exceptions": cosmos_exceptions,
        "bump_chat_bootstrap_global_cache_version": lambda *, reason: bumps.append(reason),
    }
    container_global = (
        "cosmos_groups_container" if "group" in filename else "cosmos_public_workspaces_container"
    )
    namespace[container_global] = container
    _exec_names(filename, {attempts_name, conflict_name, helper_name, guard_name}, namespace)
    return {
        "guard": namespace[guard_name],
        "conflict": namespace[conflict_name],
        "attempts": namespace[attempts_name],
        "container": container,
        "bumps": bumps,
    }


@pytest.fixture(params=["group", "public"])
def guard(request):
    """One scope's real guard bound to a fresh fake container, keyed by ``id``."""
    container = FakeContainer(name=request.param, partition_field="id")
    if request.param == "group":
        loaded = _load_guard(
            "functions_group.py",
            "update_group_document_with_etag_guard",
            "_stored_group_fields",
            "GroupDocumentWriteConflict",
            "GROUP_DOCUMENT_WRITE_ATTEMPTS",
            container,
        )
    else:
        loaded = _load_guard(
            "functions_public_workspaces.py",
            "update_public_workspace_document_with_etag_guard",
            "_stored_public_workspace_fields",
            "PublicWorkspaceDocumentWriteConflict",
            "PUBLIC_DOCUMENT_WRITE_ATTEMPTS",
            container,
        )
    loaded["scope"] = request.param
    return loaded


def _seed(container):
    return container.seed({"id": WS_ID, "description": "Original"})


def _edit(document):
    document["description"] = "Edited by the guarded writer"
    return document


def _land_concurrent_change(container):
    def concurrent():
        record = container.get(WS_ID, WS_ID)
        record["members"] = record.get("members", []) + ["late-member"]
        container.seed(record)
    return concurrent


def test_a_plain_commit_writes_the_change_and_bumps_once(guard):
    _seed(guard["container"])
    written = guard["guard"](WS_ID, _edit, cache_reason="test_reason")
    stored = guard["container"].get(WS_ID, WS_ID)
    assert written["description"] == "Edited by the guarded writer"
    assert stored["description"] == "Edited by the guarded writer"
    assert [call[0] for call in guard["container"].writes("replace_item")] == ["replace_item"]
    assert guard["bumps"] == ["test_reason"]


def test_a_concurrent_change_is_re_read_and_the_edit_re_applied(guard):
    _seed(guard["container"])
    guard["container"].before_replace.append(_land_concurrent_change(guard["container"]))
    applied = []

    def apply(document):
        applied.append(list(document.get("members", [])))
        return _edit(document)

    written = guard["guard"](WS_ID, apply, cache_reason="test_reason")
    stored = guard["container"].get(WS_ID, WS_ID)
    assert stored["description"] == "Edited by the guarded writer"
    assert "late-member" in stored["members"]
    assert written["description"] == stored["description"]
    assert len(applied) == 2 and "late-member" not in applied[0] and "late-member" in applied[1]
    assert [call[0] for call in guard["container"].writes("replace_item")] == [
        "replace_item", "replace_item",
    ]
    assert guard["bumps"] == ["test_reason"]


def test_a_lost_response_is_recognised_rather_than_retried(guard, monkeypatch):
    _seed(guard["container"])
    original = guard["container"].replace_item
    committed = []

    def replace_then_lose_the_response(item, body, etag=None, match_condition=None, **kwargs):
        stored = original(item, body, etag=etag, match_condition=match_condition, **kwargs)
        committed.append(stored)
        raise cosmos_exceptions.CosmosAccessConditionFailedError(status_code=412, message="Precondition failed")

    monkeypatch.setattr(guard["container"], "replace_item", replace_then_lose_the_response)
    applied = []

    def apply(document):
        applied.append(True)
        return _edit(document)

    written = guard["guard"](WS_ID, apply, cache_reason="test_reason")
    assert len(applied) == 1, "the committed change must not be re-applied"
    assert written["description"] == "Edited by the guarded writer"
    assert written["_etag"] == committed[0]["_etag"]
    assert guard["bumps"] == ["test_reason"]


def test_a_writer_that_keeps_losing_raises_the_conflict_with_nothing_written(guard):
    _seed(guard["container"])
    attempts = guard["attempts"]
    guard["container"].before_replace.extend([_land_concurrent_change(guard["container"])] * attempts)
    with pytest.raises(guard["conflict"]):
        guard["guard"](WS_ID, _edit, cache_reason="test_reason")
    stored = guard["container"].get(WS_ID, WS_ID)
    assert stored["description"] == "Original"
    assert len(guard["container"].writes("replace_item")) == attempts
    assert guard["bumps"] == []


def test_a_document_deleted_mid_write_returns_none_and_is_never_recreated(guard):
    _seed(guard["container"])
    guard["container"].before_replace.append(lambda: guard["container"].records.clear())
    written = guard["guard"](WS_ID, _edit, cache_reason="test_reason")
    assert written is None
    assert guard["container"].get(WS_ID, WS_ID) is None
    assert not [call for call in guard["container"].calls if call[0] in ("create_item", "upsert_item")]
    assert guard["bumps"] == []


def test_an_apply_that_raises_writes_nothing(guard):
    _seed(guard["container"])

    def refuse(document):
        raise ValueError("refused by the change itself")

    with pytest.raises(ValueError):
        guard["guard"](WS_ID, refuse, cache_reason="test_reason")
    assert guard["container"].writes("replace_item") == []
    assert guard["bumps"] == []


def test_cache_reason_is_a_required_keyword(guard):
    _seed(guard["container"])
    with pytest.raises(TypeError):
        guard["guard"](WS_ID, _edit)
    with pytest.raises(TypeError):
        guard["guard"](WS_ID, _edit, None)
    assert guard["container"].writes("replace_item") == []


def test_a_none_cache_reason_commits_without_a_bump(guard):
    _seed(guard["container"])
    written = guard["guard"](WS_ID, _edit, cache_reason=None)
    assert written["description"] == "Edited by the guarded writer"
    assert guard["container"].get(WS_ID, WS_ID)["description"] == "Edited by the guarded writer"
    assert guard["bumps"] == []


def test_the_public_conflict_carries_the_reviewed_code_and_message():
    source = (APP_ROOT / "functions_public_workspaces.py").read_text(encoding="utf-8")
    assert 'PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE = "public_workspace_write_conflict"' in source
    assert (
        'PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE = '
        '"The public workspace changed while your request was being saved. Try again."'
    ) in source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
