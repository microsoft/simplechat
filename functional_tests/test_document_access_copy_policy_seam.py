#!/usr/bin/env python3
# test_document_access_copy_policy_seam.py
"""
Functional test for the seam between the V2 explorer's access copy and the document policy.
Version: 0.261.167
Implemented in: 0.261.167

The V2 explorer tells a viewer who can't change a shared workspace's documents who can: its
"owner, admins and document managers". It also says that no one can add documents while the
workspace has uploads disabled or is locked, and that a locked workspace's documents can't be
changed (application/v2_ui/src/lib/documentAccessCopy.ts). Those are claims about the server's
policy, so this test holds them to the real policy functions,
functions_group_document_policy.group_document_management_operations and
functions_public_document_policy.public_document_management_operations: if the policy ever changes
who manages documents or when uploads are taken, the copy must change with it. It also holds the
public browser fixture's document_management hint, which the public suites render the copy from,
to the same policy.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
COPY = REPO_ROOT / "application" / "v2_ui" / "src" / "lib" / "documentAccessCopy.ts"
for candidate in (REPO_ROOT, REPO_ROOT / "ui_tests", REPO_ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.public_workspace import public_document_management  # noqa: E402

ROLES = ("Owner", "Admin", "DocumentManager", "User")
STATUSES = ("active", "upload_disabled", "locked")
SETTINGS = {"enable_group_workspaces": True, "enable_public_workspaces": True, "enable_extract_meta_data": True}
# The document manager roles, as the copy names them.
NAMED_ROLES = ("Owner", "Admin", "DocumentManager")
NAMED_ROLES_TEXT = "owner, admins and document managers"
MUTATIONS = {"upload", "edit_metadata", "tag_documents", "manage_tags", "delete", "extract_metadata", "reprocess"}


def _load(file_name):
    spec = importlib.util.spec_from_file_location(f"access_copy_seam_{file_name[:-3]}", APP_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def operations(monkeypatch):
    """The management operations each scope's real policy grants a role in a status."""
    monkeypatch.syspath_prepend(str(APP_DIR))
    # The public policy reads only this marker from the publication module, and only to recognize a
    # publication, never to decide a management operation; the module itself needs Cosmos clients.
    monkeypatch.setitem(sys.modules, "functions_artifact_publication_readiness", types.SimpleNamespace(
        PUBLICATION_BINDING="generated_artifact_publication_binding",
    ))
    group = _load("functions_group_document_policy.py")
    public = _load("functions_public_document_policy.py")
    policies = {
        "group": group.group_document_management_operations,
        "public": public.public_document_management_operations,
    }

    def granted(scope, role, status):
        return set(policies[scope]({"id": "workspace", "status": status}, role, SETTINGS, download_enabled=True))

    return granted


@pytest.mark.parametrize("scope", ["group", "public"])
def test_only_the_roles_the_copy_names_manage_documents(operations, scope):
    for status in STATUSES:
        assert {role for role in ROLES if operations(scope, role, status)} == set(NAMED_ROLES), status
    copy = COPY.read_text(encoding="utf-8")
    noun = "group" if scope == "group" else "public workspace"
    assert f"This {noun}'s {NAMED_ROLES_TEXT} can add documents." in copy
    assert f"Only this {noun}'s {NAMED_ROLES_TEXT} can manage its documents." in copy


@pytest.mark.parametrize("scope", ["group", "public"])
def test_uploads_are_taken_only_while_the_workspace_is_active(operations, scope):
    for status in STATUSES:
        uploaders = {role for role in ROLES if "upload" in operations(scope, role, status)}
        assert uploaders == (set(NAMED_ROLES) if status == "active" else set()), status


@pytest.mark.parametrize("scope", ["group", "public"])
def test_a_locked_workspace_changes_no_document(operations, scope):
    for role in ROLES:
        assert not operations(scope, role, "locked") & MUTATIONS, role


def test_the_public_browser_fixture_sends_the_servers_hint(operations):
    """The public document suites render this copy from the fixture's hint, so it must be the one
    build_public_workspace_context sends (the group fixture's is pinned by
    test_group_context_fixture_parity.py)."""
    for role in ROLES:
        for status in (*STATUSES, "inactive", "unknown"):
            hint = public_document_management(role, status)
            assert hint["schema_version"] == 1
            assert set(hint["operations"]) == operations("public", role, status), (role, status)
