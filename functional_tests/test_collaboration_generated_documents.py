#!/usr/bin/env python3
# test_collaboration_generated_documents.py
"""
Functional test for listing and downloading documents agents generated in a shared conversation.
Version: 0.261.255
Implemented in: 0.261.255

This test ensures that only upload citations that really created a document are listed, that a
masked message's documents are not, and that a download follows the workspace's own rules: a
document-managing role and downloads allowed for a group document, ownership and personal
downloads allowed for a personal one. It also checks that both routes require an accepted
participant, that the download route only serves a document the conversation produced, and that
neither route returns exception text to the browser (CodeQL py/stack-trace-exposure).
"""

import ast
import contextlib
import importlib
import json
import os
import sys
import types

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
IMPLEMENTED_IN_VERSION = "0.261.255"
GROUP_ID = "group-aaaa-1111"
DOC_GROUP = "11111111-2222-3333-4444-555555555555"
DOC_PERSONAL = "66666666-7777-8888-9999-000000000000"


class FakeWorld:
    """In-memory groups and documents behind the module's three dependencies."""

    def __init__(self):
        self.groups = {GROUP_ID: {"id": GROUP_ID, "name": "Response cell"}}
        self.roles = {(GROUP_ID, "u-owner"): "Owner", (GROUP_ID, "u-member"): "User"}
        self.documents = {
            (DOC_GROUP, GROUP_ID): {"id": DOC_GROUP, "group_id": GROUP_ID},
            (DOC_PERSONAL, None, "u-owner"): {"id": DOC_PERSONAL, "user_id": "u-owner"},
        }

    def find_group_by_id(self, group_id):
        return self.groups.get(group_id)

    def assert_group_role(self, user_id, group_id, allowed_roles=("Owner", "Admin")):
        if group_id not in self.groups:
            raise LookupError("Group not found")
        role = self.roles.get((group_id, user_id))
        if not role:
            raise PermissionError("User is not a member of this group")
        if role.lower() not in {entry.lower() for entry in allowed_roles}:
            raise PermissionError("Insufficient permissions for this group")
        return role

    def get_document_record(self, user_id, document_id, group_id=None, public_workspace_id=None):
        if group_id is not None:
            return self.documents.get((document_id, group_id))
        return self.documents.get((document_id, None, user_id))


@contextlib.contextmanager
def generated_documents_module(world):
    """Import the real module against fake dependencies, restoring sys.modules afterwards."""
    names = ["functions_documents", "functions_group", "functions_settings", "functions_collaboration_generated_documents"]
    saved = {name: sys.modules.get(name) for name in names}
    sys.path.insert(0, APP_DIR)
    try:
        documents = types.ModuleType("functions_documents")
        documents.get_document_record = world.get_document_record
        group = types.ModuleType("functions_group")
        group.assert_group_role = world.assert_group_role
        group.find_group_by_id = world.find_group_by_id
        settings = types.ModuleType("functions_settings")
        settings.get_settings = lambda: {}
        settings.is_group_workspace_file_download_enabled = (
            lambda source, group_doc: bool(source.get("allow_group_workspace_file_downloads"))
            and not group_doc.get("disable_file_downloads")
        )
        settings.is_personal_workspace_file_download_enabled = (
            lambda source: bool(source.get("allow_personal_workspace_file_downloads"))
        )
        sys.modules.update({
            "functions_documents": documents,
            "functions_group": group,
            "functions_settings": settings,
        })
        sys.modules.pop("functions_collaboration_generated_documents", None)
        yield importlib.import_module("functions_collaboration_generated_documents")
    finally:
        sys.path.remove(APP_DIR)
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def upload_citation(function_name="upload_word_document", **result):
    payload = {
        "success": True,
        "document": {"id": DOC_GROUP, "file_name": "Watch brief.docx", "status": "Queued for processing"},
        "workspace_scope": "group",
        "group_id": GROUP_ID,
    }
    payload.update(result)
    return {
        "plugin_name": "SimpleChatPlugin",
        "function_name": function_name,
        "timestamp": "2026-05-01T12:00:00Z",
        "function_result": payload,
    }


def test_only_real_uploads_are_read():
    print("Testing which citations count as generated documents...")
    with generated_documents_module(FakeWorld()) as module:
        read = module.read_generated_document
        document = read(upload_citation())
        assert document == {
            "document_id": DOC_GROUP,
            "file_name": "Watch brief.docx",
            "workspace_scope": "group",
            "group_id": GROUP_ID,
            "preview": None,
        }, document

        as_text = upload_citation("upload_markdown_document", document={"id": DOC_PERSONAL, "file_name": "..\\..\\brief.md"},
                                  workspace_scope="personal", group_id="ignored")
        as_text["function_result"] = json.dumps(as_text["function_result"])
        personal = read(as_text)
        assert personal["file_name"] == "brief.md", "a path in the stored name is never kept"
        assert personal["preview"] == "markdown"
        assert personal["group_id"] is None, "a personal document carries no group"

        assert read(upload_citation(success=False)) is None, "a failed upload created nothing"
        assert read(upload_citation("search_documents")) is None
        assert read(upload_citation(document={"id": "../../etc"})) is None
        assert read(upload_citation(document={"id": DOC_GROUP}, workspace_scope="public")) is None
        assert read(upload_citation(group_id="")) is None, "a group document needs its group"
        assert read({"function_name": "upload_word_document", "function_result": "not json"}) is None
        assert read("not a citation") is None
    print("  ok  only successful uploads with a valid id and scope are read")


def test_documents_are_listed_once_and_masked_messages_hidden():
    print("Testing the conversation listing...")
    with generated_documents_module(FakeWorld()) as module:
        messages = [
            {"id": "m-1", "timestamp": "t1", "agent_citations": [upload_citation(), upload_citation()]},
            {"id": "m-2", "timestamp": "t2", "metadata": {"masked": True}, "agent_citations": [
                upload_citation(document={"id": "aaaaaaaa-0000-0000-0000-000000000000", "file_name": "secret.md"}),
            ]},
            {"id": "m-3", "timestamp": "t3", "agent_citations": [
                {**upload_citation("upload_markdown_document", document={"id": DOC_PERSONAL, "file_name": "brief.md"},
                                   workspace_scope="personal"), "timestamp": None},
            ]},
            {"id": "m-4", "agent_citations": "not a list"},
            "not a message",
        ]
        listed = module.collect_generated_documents(messages)
        assert [entry["document_id"] for entry in listed] == [DOC_GROUP, DOC_PERSONAL], listed
        assert listed[0]["message_id"] == "m-1" and listed[0]["created_at"] == "2026-05-01T12:00:00Z"
        assert listed[1]["created_at"] == "t3", "the message time is used when the citation has none"
    print("  ok  one entry per document, masked messages skipped")


def test_downloads_follow_the_workspace_rules():
    print("Testing download authorization...")
    world = FakeWorld()
    allowed = {
        "enable_group_workspaces": True,
        "enable_user_workspace": True,
        "allow_group_workspace_file_downloads": True,
        "allow_personal_workspace_file_downloads": True,
    }
    group_document = {"document_id": DOC_GROUP, "workspace_scope": "group", "group_id": GROUP_ID}
    personal_document = {"document_id": DOC_PERSONAL, "workspace_scope": "personal", "group_id": None}

    with generated_documents_module(world) as module:
        authorize = module.authorize_generated_document_download
        record, group_id = authorize("u-owner", group_document, settings=allowed)
        assert record["id"] == DOC_GROUP and group_id == GROUP_ID

        for user_id, expected in (("u-member", PermissionError), ("u-stranger", PermissionError)):
            try:
                authorize(user_id, group_document, settings=allowed)
            except expected:
                pass
            else:
                raise AssertionError(f"{user_id} must not download a group document")
        assert not module.can_download_generated_document("u-member", group_document, settings=allowed)

        for setting in ("enable_group_workspaces", "allow_group_workspace_file_downloads"):
            try:
                authorize("u-owner", group_document, settings={**allowed, setting: False})
            except PermissionError:
                pass
            else:
                raise AssertionError(f"{setting}=False must refuse the download")

        world.groups[GROUP_ID]["disable_file_downloads"] = True
        assert not module.can_download_generated_document("u-owner", group_document, settings=allowed)
        world.groups[GROUP_ID]["disable_file_downloads"] = False

        moved = {**group_document, "document_id": "99999999-0000-0000-0000-000000000000"}
        try:
            authorize("u-owner", moved, settings=allowed)
        except LookupError:
            pass
        else:
            raise AssertionError("a document outside the group must not be served")

        record, group_id = authorize("u-owner", personal_document, settings=allowed)
        assert record["id"] == DOC_PERSONAL and group_id is None
        try:
            authorize("u-member", personal_document, settings=allowed)
        except LookupError:
            pass
        else:
            raise AssertionError("another person's personal document must not be served")
        for setting in ("enable_user_workspace", "allow_personal_workspace_file_downloads"):
            assert not module.can_download_generated_document(
                "u-owner", personal_document, settings={**allowed, setting: False},
            ), setting

        assert module.GROUP_DOWNLOAD_ROLES == group_download_roles_of_group_route(), (
            "the roles must match the group workspace's own download route"
        )
    print("  ok  group roles and download settings, personal ownership")


def group_download_roles_of_group_route():
    with open(os.path.join(APP_DIR, "route_backend_group_documents.py"), "r", encoding="utf-8") as handle:
        module_ast = ast.parse(handle.read())
    for node in module_ast.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES not found")


def generated_document_route_functions():
    with open(os.path.join(APP_DIR, "route_backend_collaboration.py"), "r", encoding="utf-8") as handle:
        module_ast = ast.parse(handle.read())
    functions = {
        node.name: node for node in ast.walk(module_ast)
        if isinstance(node, ast.FunctionDef) and node.name in {
            "list_collaboration_generated_documents_api",
            "download_collaboration_generated_document_api",
        }
    }
    assert len(functions) == 2, sorted(functions)
    return functions


def test_routes_require_an_accepted_participant():
    print("Testing the routes...")
    functions = generated_document_route_functions()
    for name, node in functions.items():
        decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
        assert decorators[1:] == ["swagger_route(security=get_auth_security())", "login_required", "user_required"], (
            name, decorators,
        )
        source = ast.unparse(node)
        assert "assert_user_can_view_collaboration_conversation(current_user['user_id'], conversation_doc, allow_pending=False)" in source, name
        assert "_require_collaboration_feature_enabled()" in source, name

    list_source = ast.unparse(functions["list_collaboration_generated_documents_api"])
    assert "'group_id'" not in list_source, "the list does not reveal group ids"
    download_source = ast.unparse(functions["download_collaboration_generated_document_api"])
    assert "collect_generated_documents(list_collaboration_messages(conversation_id))" in download_source
    assert "candidate['document_id'] == document_id" in download_source, "only this conversation's documents are served"
    assert "authorize_generated_document_download(current_user['user_id'], document)" in download_source
    assert "build_document_download_response(" in download_source
    print("  ok  accepted participants only, scoped to the conversation")


def test_routes_never_return_exception_text():
    print("Testing that refusals and failures keep exception details in the server log...")
    for name, node in generated_document_route_functions().items():
        caught = {
            handler.name for handler in ast.walk(node)
            if isinstance(handler, ast.ExceptHandler) and handler.name
        }
        assert caught, name
        responses = [
            call for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "jsonify"
        ]
        assert responses, name
        for call in responses:
            names = {child.id for child in ast.walk(call) if isinstance(child, ast.Name)}
            assert not names & caught, (name, ast.unparse(call))
            assert "format_exc" not in ast.unparse(call), (name, ast.unparse(call))
    print("  ok  every error response is a fixed message")


if __name__ == "__main__":
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)
    tests = [
        test_only_real_uploads_are_read,
        test_documents_are_listed_once_and_masked_messages_hidden,
        test_downloads_follow_the_workspace_rules,
        test_routes_require_an_accepted_participant,
        test_routes_never_return_exception_text,
    ]
    for test in tests:
        test()
    print(f"\n{len(tests)} generated document checks passed")
