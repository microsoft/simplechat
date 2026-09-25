# test_public_workspace_settings_writer_safety.py
"""
Functional test for the guarded public-workspace settings, logo, download and retention writers.
Version: 0.261.174
Implemented in: 0.261.174

The classic settings writers ``api_update_public_workspace_download_settings``,
``api_update_public_workspace`` and ``api_upload_public_workspace_logo`` (and the
retention writers ``force_push_retention_defaults`` and
``update_public_workspace_retention_settings``) were moved onto
``update_public_workspace_document_with_etag_guard`` so a settings edit never restores
the rest of the workspace document -- membership, status, retention -- from a stale copy.

The rulings this pins, run against the real guard and the etag-enforcing
``FakeContainer`` where the reshaped logic lives:

- R5.1: the classic download-settings route always sent the checkbox's boolean; a body
  that is not that boolean now changes nothing rather than turning downloads on through
  ``bool(...)`` coercion.
- R5.2: the classic public retention route now refuses a body that is not a JSON object
  and merges the values sent into the stored policy rather than replacing it.
- R5.4 (mirroring ``GROUP_SETTINGS_ERROR_TEXT_FIX``): update, download and logo answer
  reviewed, data-free text; a storage failure is logged with only its error type and
  status code under ``[PUBLIC_SETTINGS]`` and never leaks the Cosmos message; and every
  decoding failure of an uploaded logo, including a decompression bomb, is the same 400.

Only the Cosmos container, the chat-bootstrap bump, the branding helpers and the Flask
``request``/``jsonify`` shims are fakes; no network is touched.
"""

import ast
import copy
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions
from PIL import Image

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT
from test_support.versioning import assert_app_version_at_least


APP_DIR = Path(APP_ROOT)
ROUTE_FILE = "route_backend_public_workspaces.py"
RETENTION_FILE = "route_backend_retention_policy.py"
WORKSPACES_FILE = "functions_public_workspaces.py"
REGISTER = "register_route_backend_public_workspaces"
RETENTION_REGISTER = "register_route_backend_retention_policy"
WS_ID = "ws-1"
SECRET = "AccountKey=abc123; https://account.documents.azure.com:443/"


assert_app_version_at_least("0.261.132")


# --------------------------------------------------------------------------- #
# Shared AST execution helpers (module-level defs and nested route handlers).
# --------------------------------------------------------------------------- #

def _exec_names(filename, names, namespace):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    selected, found = [], set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in names for t in targets):
                selected.append(node)
                found.update(t for t in targets if t in names)
    assert found == set(names), f"Missing definitions in {filename}: {set(names) - found}"
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)


def _exec_nested_handlers(filename, container_func, names, namespace):
    """Execute route handlers defined inside ``container_func`` with their decorators stripped."""
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    register = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == container_func
    )
    found = set()
    for node in register.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            stripped = copy.deepcopy(node)
            stripped.decorator_list = []
            exec(compile(ast.Module(body=[stripped], type_ignores=[]), filename, "exec"), namespace)
            found.add(node.name)
    assert found == set(names), f"Missing nested handlers: {set(names) - found}"
    return {name: namespace[name] for name in names}


class _Request:
    def __init__(self, body=None, files=None):
        self._body = body
        self.files = files or {}

    def get_json(self, silent=False):
        return self._body


class _UploadFile:
    def __init__(self, content, filename):
        self._content = content
        self.filename = filename

    def read(self):
        return self._content


def _exec_guard(namespace, container, bumps):
    """Execute the real guard and its constants against ``container`` into ``namespace``."""
    namespace.update({
        "copy": copy,
        "MatchConditions": MatchConditions,
        "exceptions": cosmos_exceptions,
        "cosmos_public_workspaces_container": container,
        "bump_chat_bootstrap_global_cache_version": lambda *, reason: bumps.append(reason),
    })
    _exec_names(
        WORKSPACES_FILE,
        {
            "PUBLIC_DOCUMENT_WRITE_ATTEMPTS", "PublicWorkspaceDocumentWriteConflict",
            "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE", "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE",
            "_stored_public_workspace_fields", "update_public_workspace_document_with_etag_guard",
            "get_user_role_in_public_workspace",
        },
        namespace,
    )


# --------------------------------------------------------------------------- #
# Route-file environment: download / update / logo through the real guard.
# --------------------------------------------------------------------------- #

def _bomb():
    def _raise(*_args, **_kwargs):
        raise Image.DecompressionBombError("Image size exceeds limit")
    return _raise


def _route_env(*, download_admin_enabled=True, prepare=None):
    container = FakeContainer(name="public", partition_field="id")
    bumps, logs = [], []
    namespace = {
        "datetime": datetime,
        "logging": logging,
        "jsonify": lambda payload=None: payload,
        "log_event": lambda message, **kw: logs.append((message, kw.get("level"), kw.get("extra"))),
        "debug_print": lambda *a, **k: None,
        "get_settings": lambda: {},
        "find_public_workspace_by_id": lambda ws_id: container.get(ws_id, ws_id),
        "is_public_workspace_file_download_admin_enabled": lambda settings, ws: download_admin_enabled,
        "normalize_workspace_hero_color": lambda color, fallback="#0078d4": color or fallback,
        "DEFAULT_WORKSPACE_HERO_COLOR": "#0078d4",
        "is_allowed_workspace_logo_file": lambda filename: str(filename).lower().endswith((".png", ".jpg", ".jpeg")),
        "prepare_workspace_logo_image_for_storage": prepare or (lambda data, filename: {"base64_str": "STORED"}),
        "get_workspace_logo_metadata": lambda ws: {"logoVersion": ws.get("logoVersion", 0)},
    }
    _exec_guard(namespace, container, bumps)
    _exec_names(ROUTE_FILE, {"_PublicClassicResponse", "_guarded_public_write"}, namespace)
    handlers = _exec_nested_handlers(
        ROUTE_FILE, REGISTER,
        {"api_update_public_workspace_download_settings", "api_update_public_workspace",
         "api_upload_public_workspace_logo"},
        namespace,
    )
    return SimpleNamespace(container=container, bumps=bumps, logs=logs, namespace=namespace, handlers=handlers)


def _as_owner(env, user_id="owner"):
    env.namespace["get_current_user_info"] = lambda: {
        "userId": user_id, "email": f"{user_id}@example.test", "displayName": user_id.title(),
    }


def _set_body(env, body=None, files=None):
    env.namespace["request"] = _Request(body, files)


def _workspace(**extra):
    document = {
        "id": WS_ID,
        "name": "Public One",
        "description": "First",
        "status": "active",
        "heroColor": "#0078d4",
        "logoVersion": 3,
        "disable_file_downloads": False,
        "owner": {"userId": "owner", "displayName": "Owner One", "email": "owner@example.test"},
        "admins": [],
        "documentManagers": [],
        "pendingDocumentManagers": [],
    }
    document.update(extra)
    return document


def _fail_replace_with_cosmos(container, status_code=503):
    def unavailable(*args, **kwargs):
        raise cosmos_exceptions.CosmosHttpResponseError(status_code=status_code, message=SECRET)
    container.replace_item = unavailable


# --------------------------------------------------------------------------- #
# Source-level: the five converted writers forward through the guard and keep
# no raw container upsert.
# --------------------------------------------------------------------------- #

def _owner_calls_to(filename, writer):
    """The innermost function owning each call to ``writer`` in ``filename``."""
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    owners = []

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == writer:
                owners.append(owner)
            visit(child, owner)

    visit(tree, None)
    return owners


def _raw_upserts(filename, targets):
    """Owners of ``cosmos_public_workspaces_container.upsert_item`` calls limited to ``targets``."""
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    raw = []

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                func = child.func
                if (getattr(func, "attr", "") == "upsert_item"
                        and getattr(getattr(func, "value", None), "id", "") == "cosmos_public_workspaces_container"
                        and owner in targets):
                    raw.append(owner)
            visit(child, owner)

    visit(tree, None)
    return raw


def test_the_settings_writers_forward_through_the_guard_wrapper():
    owners = _owner_calls_to(ROUTE_FILE, "_guarded_public_write")
    for handler in ("api_update_public_workspace_download_settings", "api_update_public_workspace",
                    "api_upload_public_workspace_logo"):
        assert handler in owners, f"{handler} does not forward through _guarded_public_write"


def test_the_settings_writers_keep_no_raw_container_upsert():
    targets = {"api_update_public_workspace_download_settings", "api_update_public_workspace",
               "api_upload_public_workspace_logo"}
    assert _raw_upserts(ROUTE_FILE, targets) == []


def test_the_retention_writers_use_the_public_guard():
    owners = _owner_calls_to(RETENTION_FILE, "update_public_workspace_document_with_etag_guard")
    for handler in ("force_push_retention_defaults", "update_public_workspace_retention_settings"):
        assert handler in owners, f"{handler} does not use the public etag guard"


def test_the_retention_writers_keep_no_raw_container_upsert():
    targets = {"force_push_retention_defaults", "update_public_workspace_retention_settings"}
    assert _raw_upserts(RETENTION_FILE, targets) == []


def test_the_force_push_public_branch_skips_a_deleted_workspace():
    """The guard returns None for a workspace deleted mid-run, and only a real write counts."""
    source = (APP_DIR / RETENTION_FILE).read_text(encoding="utf-8")
    branch = source[source.index("Force push to public workspaces"):]
    branch = branch[:branch.index("details['public']")]
    assert "update_public_workspace_document_with_etag_guard(" in branch
    assert "if written is not None:" in branch
    assert "public_count += 1" in branch


# --------------------------------------------------------------------------- #
# R5.1: the classic download-settings route only accepts the checkbox's boolean.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("body", [
    {"disable_file_downloads": "true"}, {"disable_file_downloads": 1},
    {"disable_file_downloads": None}, {}, None,
], ids=["string", "int", "null", "missing", "not-json"])
def test_a_non_boolean_download_setting_is_refused(body):
    env = _route_env()
    env.container.seed(_workspace())
    _as_owner(env)
    _set_body(env, body)

    result = env.handlers["api_update_public_workspace_download_settings"](WS_ID)

    assert result == ({"error": "Set disable_file_downloads to true or false."}, 400)
    assert env.container.get(WS_ID, WS_ID)["disable_file_downloads"] is False
    assert env.bumps == []


@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_download_setting_is_stored(value):
    env = _route_env()
    env.container.seed(_workspace(disable_file_downloads=not value))
    _as_owner(env)
    _set_body(env, {"disable_file_downloads": value})

    payload, status = env.handlers["api_update_public_workspace_download_settings"](WS_ID)

    assert status == 200 and payload["disable_file_downloads"] is value
    assert env.container.get(WS_ID, WS_ID)["disable_file_downloads"] is value
    assert env.bumps == ["public_workspace_updated"]


# --------------------------------------------------------------------------- #
# R5.4: reviewed, data-free storage-failure text and logging.
# --------------------------------------------------------------------------- #

STORAGE_FAILURES = [
    ("api_update_public_workspace_download_settings", {"disable_file_downloads": True},
     "The download settings could not be saved. Try again.",
     "[PUBLIC_SETTINGS] Classic download settings save failed.", ["public_workspace_updated"]),
    ("api_update_public_workspace", {"name": "Renamed"},
     "The workspace could not be saved. Try again.",
     "[PUBLIC_SETTINGS] Classic public workspace update failed.", ["public_workspace_updated"]),
]


@pytest.mark.parametrize("handler,body,message,log_message,cache_when_ok", STORAGE_FAILURES)
def test_a_storage_failure_answers_reviewed_text_and_logs_no_detail(handler, body, message, log_message, cache_when_ok):
    env = _route_env()
    env.container.seed(_workspace())
    _as_owner(env)
    _set_body(env, body)
    _fail_replace_with_cosmos(env.container)

    payload, status = env.handlers[handler](WS_ID)

    assert (payload, status) == ({"error": message}, 400)
    assert "AccountKey" not in repr(payload)
    assert env.logs[-1] == (log_message, logging.ERROR,
                            {"workspace_id": WS_ID, "error_type": "CosmosHttpResponseError", "status_code": 503})
    assert "AccountKey" not in repr(env.logs)
    assert env.bumps == []


def test_a_logo_storage_failure_answers_reviewed_text_and_does_not_bump():
    env = _route_env()
    env.container.seed(_workspace())
    _as_owner(env)
    _set_body(env, files={"logo_file": _UploadFile(b"PNGDATA", "brandmark.png")})
    _fail_replace_with_cosmos(env.container)

    payload, status = env.handlers["api_upload_public_workspace_logo"](WS_ID)

    assert (payload, status) == ({"error": "The logo could not be saved. Try again."}, 400)
    assert env.logs[-1] == ("[PUBLIC_SETTINGS] Classic public workspace logo save failed.", logging.ERROR,
                            {"workspace_id": WS_ID, "error_type": "CosmosHttpResponseError", "status_code": 503})
    assert env.bumps == []


def test_a_workspace_update_stores_the_fields_and_bumps():
    env = _route_env()
    env.container.seed(_workspace())
    _as_owner(env)
    _set_body(env, {"name": "Renamed", "description": "Second"})

    payload, status = env.handlers["api_update_public_workspace"](WS_ID)

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["name"] == "Renamed" and stored["description"] == "Second"
    assert env.bumps == ["public_workspace_updated"]


def test_a_logo_upload_stores_and_increments_the_version():
    env = _route_env()
    env.container.seed(_workspace(logoVersion=3))
    _as_owner(env)
    _set_body(env, files={"logo_file": _UploadFile(b"PNGDATA", "brandmark.png")})

    payload, status = env.handlers["api_upload_public_workspace_logo"](WS_ID)

    assert status == 200 and payload["logoVersion"] == 4
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["logoBase64"] == "STORED" and stored["logoVersion"] == 4
    assert env.bumps == []


# --------------------------------------------------------------------------- #
# R5.4: every decoding failure of an uploaded logo, including a bomb, is one 400.
# --------------------------------------------------------------------------- #

def test_an_unreadable_logo_including_a_bomb_answers_reviewed_text():
    """A DecompressionBombError is neither a ValueError nor an OSError; the handler now
    catches every decoding failure of the untrusted image as the same 400 and writes nothing."""
    env = _route_env(prepare=_bomb())
    env.container.seed(_workspace())
    _as_owner(env)
    _set_body(env, files={"logo_file": _UploadFile(b"BOMB", "brandmark.png")})

    payload, status = env.handlers["api_upload_public_workspace_logo"](WS_ID)

    assert (payload, status) == ({"error": "The logo image could not be read. Upload a PNG or JPEG image."}, 400)
    text = repr(payload).lower()
    for detail in ("decompression", "bomb", "exceeds", "pixels"):
        assert detail not in text, detail
    assert env.container.get(WS_ID, WS_ID)["logoVersion"] == 3
    assert [entry for entry in env.logs if entry[1] == logging.ERROR] == []
    assert env.bumps == []


# --------------------------------------------------------------------------- #
# R5.2: the classic public retention route requires a JSON object and merges.
# --------------------------------------------------------------------------- #

def _retention_env():
    container = FakeContainer(name="public", partition_field="id")
    bumps, logs = [], []

    module = ModuleType("functions_public_workspaces")
    _exec_guard(module.__dict__, container, bumps)
    module.find_public_workspace_by_id = lambda ws_id: container.get(ws_id, ws_id)
    sys.modules["functions_public_workspaces"] = module

    namespace = {
        "logging": logging,
        "jsonify": lambda payload=None: payload,
        "log_event": lambda message, **kw: logs.append((message, kw.get("level"), kw.get("extra"))),
        "debug_print": lambda *a, **k: None,
        "get_settings": lambda: {},
        "cosmos_public_workspaces_container": container,
    }
    handlers = _exec_nested_handlers(
        RETENTION_FILE, RETENTION_REGISTER,
        {"update_public_workspace_retention_settings"},
        namespace,
    )
    return SimpleNamespace(container=container, bumps=bumps, logs=logs, namespace=namespace, handlers=handlers)


def _retention_actor(env, user_id="owner"):
    env.namespace["get_current_user_id"] = lambda: user_id


def _retention_workspace(**extra):
    document = {
        "id": WS_ID,
        "status": "active",
        "owner": {"userId": "owner", "displayName": "Owner One", "email": "owner@example.test"},
        "admins": [],
        "documentManagers": [],
        "pendingDocumentManagers": [],
        "retention_policy": {"conversation_retention_days": 30, "document_retention_days": 90},
    }
    document.update(extra)
    return document


@pytest.fixture
def retention_env():
    env = _retention_env()
    yield env
    sys.modules.pop("functions_public_workspaces", None)


@pytest.mark.parametrize("body", ["not json", ["x"], 5, None], ids=["string", "list", "int", "null"])
def test_a_retention_body_that_is_not_an_object_is_refused(retention_env, body):
    retention_env.container.seed(_retention_workspace())
    _retention_actor(retention_env)
    retention_env.namespace["request"] = _Request(body)

    payload, status = retention_env.handlers["update_public_workspace_retention_settings"](WS_ID)

    assert (payload, status) == (
        {"success": False, "error": "A JSON object is required for this request."}, 400)
    assert retention_env.container.get(WS_ID, WS_ID)["retention_policy"] == {
        "conversation_retention_days": 30, "document_retention_days": 90}


def _outcome(result):
    """Normalize a handler return: a bare payload means an implicit Flask 200."""
    if isinstance(result, tuple):
        return result
    return result, 200


def test_the_values_sent_are_merged_into_the_stored_policy(retention_env):
    retention_env.container.seed(_retention_workspace(
        retention_policy={"conversation_retention_days": 30, "document_retention_days": 90,
                          "kept_from_elsewhere": "yes"}))
    _retention_actor(retention_env)
    retention_env.namespace["request"] = _Request({"conversation_retention_days": 45})

    payload, status = _outcome(retention_env.handlers["update_public_workspace_retention_settings"](WS_ID))

    assert status == 200 and payload["success"] is True
    assert retention_env.container.get(WS_ID, WS_ID)["retention_policy"] == {
        "conversation_retention_days": 45, "document_retention_days": 90, "kept_from_elsewhere": "yes"}


def test_a_non_member_cannot_change_retention(retention_env):
    retention_env.container.seed(_retention_workspace())
    _retention_actor(retention_env, "stranger")
    retention_env.namespace["request"] = _Request({"conversation_retention_days": 45})

    payload, status = retention_env.handlers["update_public_workspace_retention_settings"](WS_ID)

    assert status == 403
    assert retention_env.container.get(WS_ID, WS_ID)["retention_policy"] == {
        "conversation_retention_days": 30, "document_retention_days": 90}


def test_a_missing_workspace_is_not_recreated(retention_env):
    _retention_actor(retention_env)
    retention_env.namespace["request"] = _Request({"conversation_retention_days": 45})

    payload, status = retention_env.handlers["update_public_workspace_retention_settings"]("ws-missing")

    assert (payload, status) == ({"success": False, "error": "Public workspace not found"}, 404)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
