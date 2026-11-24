# test_chat_visio_upload.py
"""
Regression tests for Visio chat uploads.
Version: 0.261.053
Implemented in: pending application version update

These tests exercise workspace handoff and chat-local extraction using the
actual upload route body and the shared Visio parser.
"""

import ast
import io
import logging
import os
import random
import subprocess
import sys
import tempfile
import time
import types
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from flask import Flask, current_app, jsonify, request, session
from jinja2 import Template
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_visio import build_visio_page_markdown, parse_vsdx_pages


class FakeContainer:
    def __init__(self):
        self.items = []

    def query_items(self, **kwargs):
        return []

    def upsert_item(self, item):
        self.items.append(item.copy())


@pytest.fixture
def upload_route():
    config_tree = ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))
    extension_names = {
        "BASE_ALLOWED_EXTENSIONS", "DOCUMENT_EXTENSIONS", "IMAGE_EXTENSIONS",
        "TABULAR_EXTENSIONS", "SCHEMA_EXTENSIONS", "VISIO_EXTENSIONS", "EMAIL_EXTENSIONS",
        "VIDEO_EXTENSIONS", "AUDIO_EXTENSIONS", "ONENOTE_EXTENSIONS",
    }
    definitions = [
        node for node in config_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in extension_names for target in node.targets)
    ]
    definitions.extend(
        node for node in config_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"get_allowed_extensions", "get_allowed_extension_categories"}
    )
    document_tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
    definitions.extend(
        node for node in document_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"allowed_file", "get_workspace_upload_extensions"}
    )
    route_tree = ast.parse((APP_ROOT / "route_frontend_chats.py").read_text(encoding="utf-8"))
    definitions.extend(
        node for node in route_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CHAT_WORKSPACE_UPLOAD_EXTENSIONS" for target in node.targets)
    )
    definitions.extend(
        node for node in route_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_is_setting_enabled", "_build_chat_upload_formats"}
    )
    upload = next(
        node for node in ast.walk(route_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "upload_file"
    )
    upload.decorator_list = []
    messages = FakeContainer()
    conversations = FakeContainer()
    queued = []
    settings = {"max_file_size_mb": 10}
    group = {"id": "group-1", "name": "Group"}
    conversation = {"id": "conversation-1", "title": "Existing"}
    namespace = {
        "os": os, "random": random, "tempfile": tempfile, "time": time,
        "uuid": uuid, "datetime": datetime, "logging": logging,
        "jsonify": jsonify, "request": request, "session": session,
        "secure_filename": secure_filename, "get_settings": lambda: settings,
        "get_current_user_id": lambda: "user-1",
        "get_current_user_info": lambda: {"userId": "user-1"},
        "_normalize_upload_group_ids": lambda values: values,
        "_resolve_chat_upload_context": lambda *args: {
            "conversation_item": conversation, "conversation_id": "conversation-1",
            "response_conversation_id": "conversation-1",
            "collaboration_conversation": None,
        },
        "_is_group_chat_upload_context": lambda *args, **kwargs: bool(settings.get("group_target")),
        "_resolve_group_workspace_upload_target": lambda **kwargs: group,
        "_apply_group_context_to_new_upload_conversation": lambda *args: None,
        "build_chat_upload_workspace_tags": lambda conversation_id: ["conversations"],
        "invalidate_group_search_cache": lambda group_id: None,
        "invalidate_personal_search_cache": lambda user_id: None,
        "cosmos_messages_container": messages,
        "cosmos_conversations_container": conversations,
        "parse_vsdx_pages": parse_vsdx_pages,
        "build_visio_page_markdown": build_visio_page_markdown,
        "log_event": lambda *args, **kwargs: None,
        "debug_print": lambda *args, **kwargs: None,
        "chat_upload_origin": lambda **kwargs: kwargs,
        "ALLOWED_EXTENSIONS": set().union(*(
            ast.literal_eval(node.value)
            for node in definitions if isinstance(node, ast.Assign)
            and all(isinstance(target, ast.Name) and target.id in extension_names for target in node.targets)
        )),
        "XsdIngestionCapabilityError": type("XsdIngestionCapabilityError", (Exception,), {}),
    }

    def queue_upload(**kwargs):
        queued.append(kwargs)
        return {"document_id": "doc-1", "file_name": kwargs["original_filename"], "group_id": kwargs.get("group_id")}

    namespace["queue_personal_workspace_upload_from_temp_file"] = queue_upload
    namespace["queue_group_workspace_upload_from_temp_file"] = queue_upload
    module = ast.Module(body=definitions + [upload], type_ignores=[])
    exec(compile(module, str(APP_ROOT / "route_frontend_chats.py"), "exec"), namespace)
    app = Flask(__name__)
    app.secret_key = "test"
    app.add_url_rule("/upload", view_func=namespace["upload_file"], methods=["POST"])
    return app.test_client(), settings, messages, queued


def post_upload(client, data, name="architecture.vsdx"):
    return client.post("/upload", data={"file": (io.BytesIO(data), name)})


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_visio_upload_uses_workspace_handoff(upload_route, scope):
    client, settings, messages, queued = upload_route
    settings["enable_user_workspace"] = scope == "personal"
    settings["enable_group_workspaces"] = scope == "group"
    settings["group_target"] = scope == "group"
    response = post_upload(client, (ROOT / "artifacts" / "architecture.vsdx").read_bytes(), "ARCHITECTURE.VSDX")
    assert response.status_code == 200
    assert response.json["workspace_scope"] == scope
    assert len(queued) == 1
    assert queued[0]["original_filename"] == "ARCHITECTURE.VSDX"
    assert messages.items[0]["file_content_source"] == "workspace"
    assert messages.items[0]["workspace_document_id"] == "doc-1"


def test_visio_upload_without_workspace_extracts_page_content(upload_route):
    client, settings, messages, queued = upload_route
    response = post_upload(client, (ROOT / "artifacts" / "architecture.vsdx").read_bytes())
    assert response.status_code == 200
    assert not queued
    assert "# Visio page 1: High level" in messages.items[0]["file_content"]
    assert "Shape count:" in messages.items[0]["file_content"]


def test_invalid_visio_upload_returns_safe_error(upload_route):
    client, settings, messages, queued = upload_route
    response = post_upload(client, b"not a visio file")
    assert response.status_code == 500
    assert response.json["error"] == "Unable to process the Visio file."
    assert not messages.items


def test_unsupported_upload_remains_rejected(upload_route):
    client, settings, messages, queued = upload_route
    response = post_upload(client, b"data", "file.unsupported")
    assert response.status_code == 400
    assert response.json["error"] == "Unsupported file type"


@pytest.mark.parametrize("filename", ["page.html", "page.htm"])
def test_html_chat_without_workspace_uses_existing_extractor(upload_route, filename):
    client, settings, messages, queued = upload_route
    namespace = client.application.view_functions["upload_file"].__globals__
    calls = []

    def extract(path, **kwargs):
        calls.append(kwargs)
        return ([{"page_number": 1, "content": "HTML content"}], "document_intelligence", "")

    namespace["extract_content_with_extraction_engine"] = extract
    response = post_upload(client, b"<p>HTML content</p>", filename)
    assert response.status_code == 200
    assert calls and not queued
    assert "HTML content" in messages.items[0]["file_content"]


def test_v2_picker_and_validation_accept_html_and_office_templates():
    v2_dir = ROOT / "application" / "v2_ui"
    if not (v2_dir / "node_modules" / "esbuild").is_dir():
        pytest.skip("V2 dependencies are not installed")
    script = """
const { buildSync } = require('esbuild');
const Module = require('module');
const result = buildSync({
    entryPoints: ['src/lib/chatUploads.ts'], bundle: true, platform: 'node',
    format: 'cjs', write: false, logLevel: 'silent',
});
const bundled = new Module('upload-test');
bundled.paths = Module._nodeModulePaths(process.cwd());
bundled._compile(result.outputFiles[0].text, 'upload-test.cjs');
const formats = {personal: ['html', 'htm', 'dotx', 'potx'], group: []};
const extensions = bundled.exports.chatUploadExtensions(formats, null, null, false, []);
for (const extension of ['html', 'htm', 'dotx', 'potx']) {
    const error = bundled.exports.chatUploadValidationError({name: 'file.' + extension, size: 10}, true, 10, extensions);
    if (error) throw new Error(extension + ': ' + error);
}
"""
    subprocess.run(["node", "-e", script], cwd=v2_dir, check=True, capture_output=True, text=True)


@pytest.mark.parametrize("citations,storage", [(False, False), (False, True), (True, False), (True, True)])
def test_chat_format_policy_applies_schema_storage_gate(upload_route, citations, storage):
    client, settings, _, _ = upload_route
    settings.update({
        "enable_user_workspace": True, "enable_group_workspaces": True,
        "enable_enhanced_citations": citations, "azure_openai_key": "test-secret",
    })
    namespace = client.application.view_functions["upload_file"].__globals__
    formats = namespace["_build_chat_upload_formats"](settings, storage)
    for extensions in formats.values():
        assert ("xsd" in extensions) == (citations and storage)
        assert {"vsdx", "dotx", "potx", "htm"}.issubset(extensions)
        assert "test-secret" not in extensions


def test_chat_format_policy_handles_string_feature_settings(upload_route):
    client, settings, _, _ = upload_route
    settings.update({
        "enable_user_workspace": "false", "enable_group_workspaces": "true",
        "enable_enhanced_citations": "false", "enable_video_file_support": "true",
    })
    namespace = client.application.view_functions["upload_file"].__globals__
    formats = namespace["_build_chat_upload_formats"](settings, True)
    assert "mp4" not in formats["personal"]
    assert "one" not in formats["personal"]
    assert "mp4" in formats["group"]
    assert "xsd" not in formats["group"]


def test_v2_bootstrap_projects_the_shared_chat_upload_policy():
    tree = ast.parse((APP_ROOT / "route_backend_v2.py").read_text(encoding="utf-8"))
    bootstrap = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "v2_bootstrap"
    )
    payload = next(
        node.value for node in ast.walk(bootstrap)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "payload" for target in node.targets)
    )
    projection = next(
        value for key, value in zip(payload.keys, payload.values)
        if isinstance(key, ast.Constant) and key.value == "chat_uploads"
    )
    assert ast.unparse(projection) == "chat_uploads"
    binding = next(
        node.value for node in ast.walk(bootstrap)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "chat_uploads" for target in node.targets)
    )
    assert isinstance(binding, ast.Call)
    assert ast.unparse(binding.func) == "_build_chat_upload_formats"


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize(
    "filename,feature",
    [("diagram.vsdx", None), ("slides.ppt", None), ("sheet.xls", None),
     ("template.dotx", None), ("template.potx", None), ("page.htm", None),
     ("image.heic", None), ("audio.wav", "enable_audio_file_support"),
     ("video.mp4", "enable_video_file_support")],
)
def test_workspace_formats_are_accepted_by_chat(upload_route, scope, filename, feature):
    client, settings, messages, queued = upload_route
    settings["enable_user_workspace"] = scope == "personal"
    settings["enable_group_workspaces"] = scope == "group"
    settings["group_target"] = scope == "group"
    if feature:
        settings[feature] = True
    response = post_upload(client, b"file data", filename.upper())
    assert response.status_code == 200
    assert response.json["workspace_scope"] == scope
    assert queued[0]["original_filename"] == filename.upper()


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("filename", ["audio.wav", "video.mp4"])
def test_disabled_media_is_rejected_by_chat(upload_route, scope, filename):
    client, settings, messages, queued = upload_route
    settings["enable_user_workspace"] = scope == "personal"
    settings["enable_group_workspaces"] = scope == "group"
    settings["group_target"] = scope == "group"
    response = post_upload(client, b"file data", filename)
    assert response.status_code == 400
    assert not queued


@pytest.mark.parametrize(
    "route_file,function_name",
    [
        ("route_backend_documents.py", "api_user_upload_document"),
        ("route_backend_group_documents.py", "api_upload_group_document"),
        ("route_backend_public_documents.py", "api_upload_public_document"),
        ("route_external_public_documents.py", "external_upload_public_document"),
    ],
)
@pytest.mark.parametrize("filename,feature", [("audio.wav", "enable_audio_file_support"), ("video.mp4", "enable_video_file_support"), ("page.htm", None), ("template.dotx", None), ("template.potx", None)])
@pytest.mark.parametrize("enabled", [False, True])
def test_direct_workspace_media_policy_matches_chat(upload_route, monkeypatch, route_file, function_name, filename, feature, enabled):
    chat_client, settings, messages, queued = upload_route
    if feature:
        settings[feature] = enabled
    namespace = chat_client.application.view_functions["upload_file"].__globals__.copy()
    group_module = types.ModuleType("functions_group")
    group_module.check_group_status_allows_operation = lambda *args: (True, None)
    monkeypatch.setitem(sys.modules, "functions_group", group_module)
    saved_files = []

    class FakeExecutor:
        def submit_stored(self, task_id, function, **kwargs):
            saved_files.append(kwargs["temp_file_path"])

        def submit(self, function, **kwargs):
            saved_files.append(kwargs["temp_file_path"])

    namespace.update({
        "current_app": current_app,
        "_require_active_group_document_context": lambda *args, **kwargs: ("group-1", {}, None, None),
        "_require_active_public_workspace_response": lambda *args, **kwargs: ("public-1", {}, "Owner", None),
        "_require_external_public_workspace_context": lambda *args, **kwargs: ("user-1", "public-1", {}, "Owner", None),
        "PUBLIC_WORKSPACE_MANAGER_ROLES": ("Owner", "Admin", "DocumentManager"),
        "PUBLIC_WORKSPACE_EXTERNAL_MANAGER_ROLES": ("Owner", "Admin", "DocumentManager"),
        "check_public_workspace_status_allows_operation": lambda *args: (True, None),
        "create_document": lambda **kwargs: None,
        "update_document": lambda **kwargs: None,
        "prepare_document_upload": lambda **kwargs: None,
        "process_document_upload_background": lambda **kwargs: None,
        "log_document_upload": lambda **kwargs: None,
        "invalidate_public_workspace_search_cache": lambda *args: None,
    })
    route_tree = ast.parse((APP_ROOT / route_file).read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(route_tree) if isinstance(node, ast.FunctionDef) and node.name == function_name)
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), route_file, "exec"), namespace)
    app = Flask(function_name)
    app.extensions["executor"] = FakeExecutor()
    app.add_url_rule("/upload", view_func=namespace[function_name], methods=["POST"])
    try:
        response = post_upload(app.test_client(), b"file data", filename)
        accepted = enabled or feature is None
        assert response.status_code == (200 if accepted else 400), response.get_json()
        assert bool(saved_files) == accepted
    finally:
        for path in saved_files:
            os.remove(path)


@pytest.mark.parametrize("audio,video", [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize("xsd_available", [False, True])
@pytest.mark.parametrize("workspace_enabled", [False, True])
@pytest.mark.parametrize("group_enabled", [False, True])
def test_chat_picker_matches_workspace_categories(upload_route, audio, video, xsd_available, workspace_enabled, group_enabled):
    client, settings, messages, queued = upload_route
    settings.update({
        "enable_user_workspace": workspace_enabled,
        "enable_group_workspaces": group_enabled,
        "enable_audio_file_support": audio,
        "enable_video_file_support": video,
    })
    namespace = client.application.view_functions["upload_file"].__globals__.copy()
    settings["enable_enhanced_citations"] = xsd_available
    formats = namespace["_build_chat_upload_formats"](settings, xsd_available)
    template = (APP_ROOT / "templates" / "chats.html").read_text(encoding="utf-8")
    input_markup = next(line for line in template.splitlines() if 'id="file-input"' in line)
    rendered = Template(input_markup).render(
        chat_upload_extensions=formats["personal"],
        chat_group_upload_extensions=formats["group"],
    )
    accepted = rendered.split('accept="', 1)[1].split('"', 1)[0].split(",")
    expected = namespace["get_allowed_extensions"](enable_audio=audio, enable_video=video)
    if not xsd_available or not workspace_enabled:
        expected -= namespace["SCHEMA_EXTENSIONS"]
    if not workspace_enabled:
        expected -= namespace["AUDIO_EXTENSIONS"] | namespace["VIDEO_EXTENSIONS"] | namespace["ONENOTE_EXTENSIONS"]
    assert set(accepted) == {f".{extension}" for extension in expected}
    group_accepted = rendered.split('data-group-accept="', 1)[1].split('"', 1)[0].split(",")
    group_expected = namespace["get_allowed_extensions"](enable_audio=audio, enable_video=video) if group_enabled else set()
    if not xsd_available:
        group_expected -= namespace["SCHEMA_EXTENSIONS"]
    assert set(filter(None, group_accepted)) == {f".{extension}" for extension in group_expected}
    if workspace_enabled:
        categories = namespace["get_allowed_extension_categories"](
            enable_audio=audio, enable_video=video, enable_xsd=xsd_available
        )
        for template_name, input_id in [
            ("workspace.html", "workspace-file-input"),
            ("group_workspaces.html", "file-input"),
            ("public_workspaces.html", "file-input"),
        ]:
            workspace_template = (APP_ROOT / "templates" / template_name).read_text(encoding="utf-8")
            workspace_markup = next(line for line in workspace_template.splitlines() if f'id="{input_id}"' in line)
            workspace_rendered = Template(workspace_markup).render(allowed_extension_categories=categories)
            workspace_accepted = workspace_rendered.split('accept="', 1)[1].split('"', 1)[0].split(",")
            assert set(workspace_accepted) == set(accepted)
