# test_group_document_etag_guard.py
"""
Functional test for the conditional group-document writer.
Version: 0.261.154
Implemented in: 0.261.140
No-bump commits (``cache_reason=None``): 0.261.146
Native membership writers' cache reasons: 0.261.151
Classic membership writers on the guard: 0.261.151
Group settings writers: 0.261.154

``update_group_document_with_etag_guard`` is the group-document equivalent of the
File Sync ``_write_with_etag_guard`` (``fae9d6ef``). The real ``functions_group``
module runs against the ``FakeContainer`` from
``test_file_sync_concurrent_write_safety.py``, which refuses a stale etag with 412
and a missing record with 404 and never creates. Concurrent writers are landed
deterministically between the guarded read and its replace.

It pins that a concurrent membership change is re-read and kept (no conflict), that
a deleted group is reported as missing and never recreated, that a writer which
keeps losing gets a conflict with nothing written, that a lost-response commit is
recognised, and that the legacy ``update_group_model_endpoints`` is still the
unconditional upsert it was.

``cache_reason`` is a required keyword. ``None`` commits without bumping the chat
bootstrap cache, which the group directory's join and cancel use because no
bootstrap payload reads pending requests, and which the group logo and retention
writes use because the classic writers never bumped for them; every other caller
names a reason. The model endpoint writes still bump once per commit, which
``test_group_endpoint_apis.py::test_each_committed_write_bumps_the_chat_bootstrap_cache_once``
pins end to end.
"""

import ast
from pathlib import Path

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError

from test_support.group_endpoint_harness import GROUP_A, group_endpoint_environment


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def add_description(document):
    document["description"] = "Edited by the guarded writer"
    return document


def land_membership_change(env):
    def concurrent():
        record = env.stored_group(GROUP_A)
        record["users"].append({"userId": "late-member", "email": "", "displayName": "Late"})
        env.groups.seed(record)
    return concurrent


def test_a_concurrent_membership_change_is_kept_and_the_change_applied(env):
    env.seed_group(GROUP_A)
    env.groups.before_replace.append(land_membership_change(env))
    applied = []

    def apply(document):
        applied.append([user["userId"] for user in document["users"]])
        return add_description(document)

    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, apply, cache_reason="test_reason")
    stored = env.stored_group(GROUP_A)
    assert stored["description"] == "Edited by the guarded writer"
    assert "late-member" in [user["userId"] for user in stored["users"]]
    assert written["description"] == stored["description"]
    # The change was applied twice: once to the stale copy and once to the re-read one.
    assert len(applied) == 2 and "late-member" not in applied[0] and "late-member" in applied[1]
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]
    assert env.bumps == ["test_reason"]


def test_a_group_deleted_mid_write_is_reported_missing_and_never_recreated(env):
    env.seed_group(GROUP_A)
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason="test_reason")
    assert written is None
    assert env.stored_group(GROUP_A) is None
    assert not [call for call in env.groups.calls if call[0] in ("create_item", "upsert_item")]
    assert env.bumps == []


def test_a_missing_group_is_never_created(env):
    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason="test_reason")
    assert written is None
    assert env.write_calls() == []


def test_a_writer_that_keeps_losing_gets_a_conflict_with_nothing_written(env):
    env.seed_group(GROUP_A)
    attempts = env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS
    env.groups.before_replace.extend([land_membership_change(env)] * attempts)
    with pytest.raises(env.modules.group.GroupDocumentWriteConflict):
        env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason="test_reason")
    stored = env.stored_group(GROUP_A)
    assert stored["description"] == "Shared connections"
    assert len([call for call in env.groups.calls if call[0] == "replace_item"]) == attempts
    assert env.bumps == []


def test_an_apply_that_raises_writes_nothing(env):
    env.seed_group(GROUP_A)

    def refuse(document):
        raise ValueError("refused by the change itself")

    with pytest.raises(ValueError):
        env.modules.group.update_group_document_with_etag_guard(GROUP_A, refuse, cache_reason="test_reason")
    assert env.write_calls() == []
    assert env.bumps == []


def test_a_lost_response_commit_is_recognised_rather_than_retried(env, monkeypatch):
    """A transport retry of a committed replace fails its own precondition (412)."""
    env.seed_group(GROUP_A)
    original = env.groups.replace_item
    committed = []

    def replace_then_lose_the_response(item, body, etag=None, match_condition=None, **kwargs):
        stored = original(item, body, etag=etag, match_condition=match_condition, **kwargs)
        committed.append(stored)
        raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed")

    monkeypatch.setattr(env.groups, "replace_item", replace_then_lose_the_response)
    applied = []

    def apply(document):
        applied.append(True)
        return add_description(document)

    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, apply, cache_reason="test_reason")
    assert len(applied) == 1, "the committed change must not be re-applied"
    assert written["description"] == "Edited by the guarded writer"
    assert written["_etag"] == committed[0]["_etag"]
    assert env.bumps == ["test_reason"]


def test_the_legacy_collection_writer_is_still_an_unconditional_upsert(env):
    """Recorded, not changed: M7B moves the legacy writers onto the guarded helper."""
    env.seed_group(GROUP_A)
    env.modules.group.update_group_model_endpoints(GROUP_A, [])
    assert [call[0] for call in env.write_calls()] == ["upsert_item"]
    assert env.bumps == ["group_model_endpoints_updated"]


def test_a_none_cache_reason_commits_without_a_bump(env):
    env.seed_group(GROUP_A)
    env.groups.before_replace.append(land_membership_change(env))
    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason=None)
    assert written["description"] == "Edited by the guarded writer"
    assert env.stored_group(GROUP_A)["description"] == "Edited by the guarded writer"
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]
    assert env.bumps == []


def test_a_none_cache_reason_lost_response_commit_is_recognised_without_a_bump(env, monkeypatch):
    env.seed_group(GROUP_A)
    original = env.groups.replace_item

    def replace_then_lose_the_response(item, body, etag=None, match_condition=None, **kwargs):
        original(item, body, etag=etag, match_condition=match_condition, **kwargs)
        raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed")

    monkeypatch.setattr(env.groups, "replace_item", replace_then_lose_the_response)
    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason=None)
    assert written["description"] == "Edited by the guarded writer"
    assert env.bumps == []


def test_cache_reason_is_a_required_keyword(env):
    env.seed_group(GROUP_A)
    with pytest.raises(TypeError):
        env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description)
    with pytest.raises(TypeError):
        env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, None)
    assert env.write_calls() == []


def _guard_calls():
    calls = []
    for path in sorted(APP_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
                if name == "update_group_document_with_etag_guard":
                    calls.append((path.name, node))
    return calls


def test_every_guarded_writer_names_its_cache_reason():
    """The group directory, the logo and the retention writes opt out of the bump; the
    model endpoint writes keep theirs, and the membership and settings modules forward
    each write's own reason (pinned below)."""
    reasons = {}
    for file_name, call in _guard_calls():
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "cache_reason" in keywords, f"{file_name} must pass cache_reason explicitly"
        value = keywords["cache_reason"]
        reasons.setdefault(file_name, set()).add(
            "None" if isinstance(value, ast.Constant) and value.value is None else ast.unparse(value)
        )
    assert reasons == {
        "functions_group_endpoint_access.py": {"GROUP_ENDPOINT_CACHE_REASON"},
        "functions_group_directory.py": {"None"},
        "functions_group_membership.py": {"cache_reason"},
        # The native group settings writes name theirs at each _write call.
        "functions_group_settings.py": {"cache_reason"},
        "functions_simplechat_operations.py": {"'group_member_added'"},
        "route_backend_groups.py": {"cache_reason", "'group_updated'", "None"},
        "route_backend_retention_policy.py": {"None"},
    }


def _forwarded_reasons(file_name, writer):
    """``cache_reason`` per innermost calling function, for a module's own guarded-write wrapper."""
    tree = ast.parse((APP_DIR / file_name).read_text(encoding="utf-8"))
    reasons = {}

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == writer:
                [value] = [keyword.value for keyword in child.keywords if keyword.arg == "cache_reason"]
                assert owner not in reasons, f"{owner} calls {writer} more than once"
                reasons[owner] = value.value
            visit(child, owner)

    visit(tree, None)
    return reasons


def test_the_classic_membership_writers_keep_their_cache_reasons():
    """Converted to the guard with the bumps they always had: approve bumps after
    the commit (the action is read inside the change), removal only when a member
    was removed, and the classic join and reject never."""
    assert _forwarded_reasons("route_backend_groups.py", "_guarded_group_write") == {
        "request_to_join": None,
        "approve_reject_request": None,
        "remove_member": None,
        "update_member_role": "group_member_role_updated",
        "transfer_ownership": "group_ownership_transferred",
    }
    source = (APP_DIR / "route_backend_groups.py").read_text(encoding="utf-8")
    assert source.count('bump_chat_bootstrap_global_cache_version(reason="group_member_request_approved")') == 1
    assert source.count('bump_chat_bootstrap_global_cache_version(reason="group_member_removed")') == 1


def _membership_write_reasons():
    return _forwarded_reasons("functions_group_membership.py", "_write")


def test_the_membership_writes_keep_the_classic_cache_reasons():
    """Each native write bumps exactly as its classic counterpart does; removal bumps
    itself only when a ``users[]`` entry was removed."""
    assert _membership_write_reasons() == {
        "add_group_member": "group_member_added",
        "change_group_member_role": "group_member_role_updated",
        "remove_group_member": None,
        "approve_join_request": "group_member_request_approved",
        "reject_join_request": None,
        "transfer_group_ownership": "group_ownership_transferred",
    }
    source = (APP_DIR / "functions_group_membership.py").read_text(encoding="utf-8")
    assert source.count('bump_chat_bootstrap_global_cache_version(reason="group_member_removed")') == 1


def _cache_reasons_by_function(file_name, callee):
    """``{innermost enclosing function: {cache_reason source}}`` for each call to ``callee``."""
    tree = ast.parse((APP_DIR / file_name).read_text(encoding="utf-8"))
    found = {}

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                function = child.func
                name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
                if name == callee:
                    value = {keyword.arg: keyword.value for keyword in child.keywords}["cache_reason"]
                    found.setdefault(owner, set()).add(ast.unparse(value))
            visit(child, owner)

    visit(tree, None)
    return found


@pytest.mark.parametrize("file_name,callee,expected", [
    ("functions_group_settings.py", "update_group_document_with_etag_guard", {"_write": {"cache_reason"}}),
    ("functions_group_settings.py", "_write", {
        "update_group_profile": {"'group_updated'"},
        "update_group_downloads": {"'group_updated'"},
        "replace_group_logo": {"None"},
        "remove_group_logo": {"None"},
        "update_group_retention": {"None"},
    }),
    ("route_backend_groups.py", "update_group_document_with_etag_guard", {
        # The membership writers forward their reasons through this wrapper (pinned above).
        "_guarded_group_write": {"cache_reason"},
        "api_update_group": {"'group_updated'"},
        "api_update_group_download_settings": {"'group_updated'"},
        "api_upload_group_logo": {"None"},
    }),
    ("route_backend_retention_policy.py", "update_group_document_with_etag_guard", {
        "update_group_retention_settings": {"None"},
        "force_push_retention_defaults": {"None"},
    }),
])
def test_each_group_settings_writer_names_the_classic_cache_reason(file_name, callee, expected):
    """The name, description, color and download writes bump group_updated, as the classic
    writers did; the logo and retention writes bump nothing, as they never did."""
    assert _cache_reasons_by_function(file_name, callee) == expected


def test_the_model_endpoint_cache_reason_is_a_real_reason(env):
    assert env.modules.access.GROUP_ENDPOINT_CACHE_REASON == "group_model_endpoints_updated"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
