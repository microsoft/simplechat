#!/usr/bin/env python3
# test_log_injection_codeql_alerts_fix.py
"""
Functional test for the py/log-injection CodeQL alerts fix.
Version: 0.261.216
Implemented in: 0.261.216

This test ensures that the log lines CodeQL flagged for log injection keep request-derived
identifiers and exception text on one line while an ordinary identifier is logged exactly as
before, that ``sanitize_log_message`` returns exactly what it returned in 0.261.213 now that its
line-break removal is visible to static analysis, and that the admin plugin-settings route logs
the size of its payload instead of the payload. It also checks that the edited modules load in
fresh normal and optimized interpreters, in either order, with every network socket blocked.
"""

import ast
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import logging
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from azure.cosmos.exceptions import CosmosResourceNotFoundError
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
for search_path in (str(TESTS), str(APP)):
    if search_path not in sys.path:
        sys.path.insert(0, search_path)

import functions_appinsights  # noqa: E402  (path setup must precede this import)
from test_support.app_source import definitions, run_definitions  # noqa: E402
from test_support.log_sanitizer import real_sanitize_log_message  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


# sanitize_log_message exactly as released in 0.261.213, kept as reference data.
FROZEN_REDACTED_LOG_VALUE = "***REDACTED***"
FROZEN_MAX_LOG_STRING_LENGTH = 8192
FROZEN_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[-_]?key|access[-_]?token|client[-_]?secret|connection[-_]?string|password|secret|subscription[-_]?key|token|sig|signature)=([^&\s,;]+)"
)
FROZEN_AUTHORIZATION_VALUE_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
FROZEN_LOG_CONTROL_CHAR_RE = re.compile(r"[\r\n\t]+")


def frozen_sanitize_log_message(message):
    message_text = str(message)
    message_text = FROZEN_SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}={FROZEN_REDACTED_LOG_VALUE}",
        message_text,
    )
    message_text = FROZEN_AUTHORIZATION_VALUE_RE.sub(
        lambda match: f"{match.group(1)} {FROZEN_REDACTED_LOG_VALUE}",
        message_text,
    )
    message_text = FROZEN_LOG_CONTROL_CHAR_RE.sub(" ", message_text)
    if len(message_text) > FROZEN_MAX_LOG_STRING_LENGTH:
        return f"{message_text[:FROZEN_MAX_LOG_STRING_LENGTH]}... [truncated]"
    return message_text


SANITIZE_CORPUS = (
    "plain diagnostic text",
    "",
    "a\n\nb",
    "line one\r\nline two",
    "runs\r\n\r\n\r\nof CRLF",
    "lone\rcarriage return",
    "\r\n",
    "\n\r",
    "trailing newline\n",
    "tab\tseparated\t\tvalues",
    "mixed\t\r\n\t\r\ncontrol characters",
    "password=x",
    "api_key=sk-test-0123456789&next=1",
    "connection_string=AccountKey123;rest",
    "Authorization: Bearer abc.def-ghi_jkl",
    "Authorization: Basic dXNlcjpwYXNz",
    "token=abc\r\nBearer xyz\tpassword=hunter2",
    "x" * FROZEN_MAX_LOG_STRING_LENGTH,
    "x" * (FROZEN_MAX_LOG_STRING_LENGTH + 1),
    "y\n" * 6000,
    "z" * (FROZEN_MAX_LOG_STRING_LENGTH - 2) + "\r\n\r\nqq",
    ValueError("boom\r\nforged entry"),
    RuntimeError(),
    42,
    3.5,
    None,
    True,
    {"workflow_id": "wf-1\nforged", "password": "hunter2"},
    ["a\nb", 1],
    b"bytes\nvalue",
    "unicod\u00e9 \u2713 \u65e5\u672c\u8a9e \u2013 \U0001F680",
    "line separator\u2028paragraph separator\u2029next line\u0085",
    "vertical\x0btab and form\x0cfeed",
)


def test_version_is_at_least_the_fix_version():
    assert_app_version_at_least("0.261.216")


def test_sanitize_log_message_output_is_unchanged_from_0_261_213():
    sanitize = functions_appinsights.sanitize_log_message
    executed_sanitize = real_sanitize_log_message()
    for message in SANITIZE_CORPUS:
        expected = frozen_sanitize_log_message(message)
        actual = sanitize(message)
        executed = executed_sanitize(message)
        assert actual == expected, f"sanitize_log_message changed its output for {message!r:.80}"
        assert executed == expected, f"The harness helper disagrees with the module for {message!r:.80}"
        assert "\r" not in actual and "\n" not in actual


def test_sanitize_log_message_keeps_its_collapsing_masking_and_truncation():
    limit = functions_appinsights.MAX_LOG_STRING_LENGTH
    collapsed = functions_appinsights.sanitize_log_message("a\n\nb")
    crlf_runs = functions_appinsights.sanitize_log_message("a\r\n\r\nb\rc\td")
    masked = functions_appinsights.sanitize_log_message("api_key=sk-test-123 Bearer abc.def")
    truncated = functions_appinsights.sanitize_log_message("x" * (limit + 5))
    assert collapsed == "a b"
    assert crlf_runs == "a b c d"
    assert masked == "api_key=***REDACTED*** Bearer ***REDACTED***"
    assert truncated == "x" * limit + "... [truncated]"


def _sanitize_log_message_body():
    tree = ast.parse((APP / "functions_appinsights.py").read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "sanitize_log_message"
    )
    return function.body


def _assigns_message_text(statement):
    return (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "message_text"
    )


def _collapses_control_characters(statement):
    value = getattr(statement, "value", None)
    return (
        _assigns_message_text(statement)
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "sub"
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "LOG_CONTROL_CHAR_RE"
    )


def _replaced_literals(statement):
    """The literal first arguments of a ``message_text.replace(...)`` chain, else an empty set."""
    if not _assigns_message_text(statement):
        return set()
    literals = set()
    node = statement.value
    while (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        literals.add(node.args[0].value)
        node = node.func.value
    if isinstance(node, ast.Name) and node.id == "message_text":
        return literals
    return set()


def test_sanitize_log_message_keeps_the_line_break_replaces_after_the_regex():
    # CodeQL credits only a .replace("\r\n", ...) or .replace("\n", ...) call as a line-break
    # sanitizer. After the regex these calls change nothing, so only this check notices if a
    # refactor drops them or moves them ahead of the regex; either reopens four alerts.
    body = _sanitize_log_message_body()
    collapses = [index for index, statement in enumerate(body) if _collapses_control_characters(statement)]
    replaces = [
        index for index, statement in enumerate(body)
        if {"\r\n", "\n"} <= _replaced_literals(statement)
    ]
    returns = [
        index for index, statement in enumerate(body)
        if any(isinstance(node, ast.Return) for node in ast.walk(statement))
    ]
    assert len(collapses) == 1, "sanitize_log_message no longer collapses control characters with LOG_CONTROL_CHAR_RE"
    replaces_after_regex = [index for index in replaces if index > collapses[0]]
    assert replaces_after_regex, (
        'sanitize_log_message must call message_text.replace("\\r\\n", ...).replace("\\n", ...) '
        "after LOG_CONTROL_CHAR_RE.sub"
    )
    assert returns
    assert min(returns) > replaces_after_regex[0], "A return comes before the line-break replaces"


def test_log_event_writes_single_line_properties(monkeypatch):
    capture = RecordCapture()
    logger = logging.getLogger(f"{__name__}.appinsights")
    logger.handlers[:] = [capture]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    monkeypatch.setattr(functions_appinsights, "_load_logging_settings", lambda: {})
    monkeypatch.setattr(functions_appinsights, "get_appinsights_logger", lambda: logger)
    try:
        functions_appinsights.log_event(
            "Cancelling workflow wf-1\r\nFORGED entry",
            extra={"workflow_id": "wf-1\nFORGED", "error": "boom\r\nFORGED"},
        )
    finally:
        logger.handlers[:] = []
    records = list(capture.records)
    assert len(records) == 1
    properties = {
        name: value for name, value in vars(records[0]).items()
        if name.startswith("sc_") and isinstance(value, str)
    }
    assert properties["sc_message"] == "Cancelling workflow wf-1 FORGED entry"
    assert not [name for name, value in properties.items() if "\r" in value or "\n" in value]


class RecordCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class FrozenDatetime(datetime):
    """``datetime`` with a fixed ``now``, so the cache-write line's expiry time is known."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 2, 3, 4, 5, tzinfo=tz)


class CacheContainer:
    """The Cosmos DB container calls made on the logged utils_cache paths."""

    def __init__(self, *, error=None, items=(), cache_item=None):
        self.error = error
        self.items = list(items)
        self.cache_item = cache_item
        self.deleted = []
        self.upserted = []

    def query_items(self, **kwargs):
        if self.error is not None:
            raise self.error
        return list(self.items)

    def delete_item(self, item, partition_key):
        self.deleted.append((item, partition_key))

    def read_item(self, item, partition_key):
        return dict(self.cache_item)

    def upsert_item(self, body):
        self.upserted.append(body)
        return body


UTILS_CACHE_DEFINITIONS = (
    "get_group_document_fingerprint",
    "get_public_workspace_document_fingerprint",
    "get_cache_partition_key",
    "_normalize_cache_id_list",
    "get_cached_search_results",
    "cache_search_results",
    "invalidate_personal_search_cache",
    "invalidate_group_search_cache",
    "invalidate_public_workspace_search_cache",
)
CACHE_HIT = {"expiry_time": "2026-01-02T03:09:05Z", "results": [{"id": "result-1"}]}


def failing(message):
    return lambda: CacheContainer(error=RuntimeError(message))


def holding(*items):
    return lambda: CacheContainer(items=items, cache_item=CACHE_HIT)


def run_utils_cache(function_name, *args, container, **kwargs):
    """Call a utils_cache function executed from source and return its log lines."""
    capture = RecordCapture()
    logger = logging.getLogger(f"{__name__}.utils_cache")
    logger.handlers[:] = [capture]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    namespace = run_definitions("utils_cache.py", UTILS_CACHE_DEFINITIONS, {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "datetime": FrozenDatetime,
        "hashlib": hashlib,
        "timedelta": timedelta,
        "timezone": timezone,
        "logger": logger,
        "sanitize_log_message": functions_appinsights.sanitize_log_message,
        "_debug_print": lambda *debug_args, **debug_kwargs: None,
        "get_cache_settings": lambda: (True, 300),
        "cosmos_group_documents_container": container,
        "cosmos_public_documents_container": container,
        "cosmos_search_cache_container": container,
    })
    try:
        namespace[function_name](*args, **kwargs)
    finally:
        logger.handlers[:] = []
    return [record.getMessage() for record in capture.records]


# (function, args, kwargs, container, the line it logged before this fix)
ORDINARY_UTILS_CACHE_LINES = (
    (
        "get_group_document_fingerprint", ("group-1",), {}, failing("Cosmos query failed"),
        "Error generating group document fingerprint for group group-1: Cosmos query failed",
    ),
    (
        "get_public_workspace_document_fingerprint", ("workspace-1",), {}, failing("Cosmos query failed"),
        "Error generating public workspace document fingerprint for workspace workspace-1: Cosmos query failed",
    ),
    (
        "get_cached_search_results", ("cache-key-1", "user-1", "group"), {"active_group_ids": ["group-1"]},
        holding(),
        "Cache hit for key: cache-key-1 (scope: group, partition: group:group-1)",
    ),
    (
        "cache_search_results", ("cache-key-1", [{"id": "result-1"}], "user-1", "public"),
        {"active_public_workspace_id": "workspace-0123456789abcdef"}, holding(),
        "Cached search results with key: cache-key-1, scope: public, partition: public:workspace-01234567, "
        "ttl: 300s, expires at: 2026-01-02 03:09:05+00:00",
    ),
    (
        "invalidate_personal_search_cache", ("user-1",), {}, holding({"id": "cache-1"}),
        "Invalidated 1 cache entries for user user-1",
    ),
    (
        "invalidate_group_search_cache", ("group-1",), {}, holding({"id": "cache-1", "user_id": "group:group-1"}),
        "Invalidated 1 cache entries for group group-1",
    ),
    (
        "invalidate_public_workspace_search_cache", ("workspace-1",), {},
        holding({"id": "cache-1", "user_id": "public:workspace-1"}),
        "Invalidated 1 cache entries for public workspace workspace-1",
    ),
)

# Every value each flagged line writes carries a line break here.
INJECTED_UTILS_CACHE_LINES = (
    (
        "get_group_document_fingerprint", ("group-1\nFORGED",), {}, failing("Cosmos query failed\r\nFORGED entry"),
        "Error generating group document fingerprint for group group-1 FORGED: Cosmos query failed FORGED entry",
    ),
    (
        "get_public_workspace_document_fingerprint", ("workspace-1\r\nFORGED",), {},
        failing("Cosmos query failed\nFORGED entry"),
        "Error generating public workspace document fingerprint for workspace workspace-1 FORGED: "
        "Cosmos query failed FORGED entry",
    ),
    (
        "get_cached_search_results", ("cache-key-1\nFORGED", "user-1\r\nFORGED", "scope\nFORGED"), {}, holding(),
        "Cache hit for key: cache-key-1 FORGED (scope: scope FORGED, partition: user-1 FORGED)",
    ),
    (
        "cache_search_results", ("cache-key-1\r\nFORGED", [{"id": "result-1"}], "user-1\nFORGED", "scope\r\nFORGED"),
        {}, holding(),
        "Cached search results with key: cache-key-1 FORGED, scope: scope FORGED, partition: user-1 FORGED, "
        "ttl: 300s, expires at: 2026-01-02 03:09:05+00:00",
    ),
    (
        "invalidate_personal_search_cache", ("user-1\r\nFORGED",), {}, holding({"id": "cache-1"}),
        "Invalidated 1 cache entries for user user-1 FORGED",
    ),
    (
        "invalidate_group_search_cache", ("group-1\nFORGED",), {},
        holding({"id": "cache-1", "user_id": "group:group-1"}),
        "Invalidated 1 cache entries for group group-1 FORGED",
    ),
    (
        "invalidate_public_workspace_search_cache", ("workspace-1\r\nFORGED",), {},
        holding({"id": "cache-1", "user_id": "public:workspace-1"}),
        "Invalidated 1 cache entries for public workspace workspace-1 FORGED",
    ),
)


@pytest.mark.parametrize(
    "function_name, args, kwargs, container_factory, expected",
    ORDINARY_UTILS_CACHE_LINES,
    ids=[case[0] for case in ORDINARY_UTILS_CACHE_LINES],
)
def test_utils_cache_logs_an_ordinary_identifier_exactly_as_before(
    function_name, args, kwargs, container_factory, expected
):
    messages = run_utils_cache(function_name, *args, container=container_factory(), **kwargs)
    assert messages == [expected]


@pytest.mark.parametrize(
    "function_name, args, kwargs, container_factory, expected",
    INJECTED_UTILS_CACHE_LINES,
    ids=[case[0] for case in INJECTED_UTILS_CACHE_LINES],
)
def test_utils_cache_keeps_an_injected_identifier_on_one_line(
    function_name, args, kwargs, container_factory, expected
):
    messages = run_utils_cache(function_name, *args, container=container_factory(), **kwargs)
    assert messages == [expected]
    assert not [message for message in messages if "\r" in message or "\n" in message]


WORKFLOW_CANCEL_ROUTES = ("cancel_user_workflow_run", "cancel_active_group_workflow_run")

# (route, the failure it handles, response status, the line it logged before this fix)
WORKFLOW_CANCEL_LINES = (
    (
        "cancel_user_workflow_run", lambda namespace: LookupError("Workflow run was not found."), 404,
        "LookupError while cancelling personal workflow run. workflow_id={workflow_id} run_id={run_id} user_id=user-1",
    ),
    (
        "cancel_user_workflow_run",
        lambda namespace: namespace["WorkflowCancellationConflictError"]("This workflow run has already finished."),
        409,
        "WorkflowCancellationConflictError while cancelling personal workflow run. "
        "workflow_id={workflow_id} run_id={run_id} user_id=user-1",
    ),
    (
        "cancel_active_group_workflow_run", lambda namespace: ValueError("No active group."), 400,
        "Invalid group workflow request during cancellation. user_id=user-1 workflow_id={workflow_id}",
    ),
    (
        "cancel_active_group_workflow_run", lambda namespace: LookupError("Group not found."), 404,
        "Group workspace lookup failed during workflow cancellation. user_id=user-1 workflow_id={workflow_id}",
    ),
    (
        "cancel_active_group_workflow_run", lambda namespace: PermissionError("Not a group member."), 403,
        "Unauthorized group workflow cancellation attempt. user_id=user-1 workflow_id={workflow_id}",
    ),
)
WORKFLOW_CANCEL_IDS = [
    "personal-lookup", "personal-conflict", "group-invalid", "group-lookup", "group-permission",
]


def run_workflow_cancel_route(route_name, workflow_id, run_id, failure):
    """Call a cancellation route executed from source, decorators removed, and capture its log records."""
    module = definitions(
        "route_backend_workflows.py",
        {"WorkflowCancellationConflictError"},
        register="register_route_backend_workflows",
        nested=WORKFLOW_CANCEL_ROUTES,
    )
    for node in module.body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []

    def raise_failure(*args, **kwargs):
        raise failure(namespace)

    namespace = {
        "logging": logging,
        "jsonify": lambda body: body,
        "sanitize_log_message": functions_appinsights.sanitize_log_message,
        "get_current_user_id": lambda: "user-1",
        "get_personal_workflow": lambda user_id, requested_workflow_id: {"id": requested_workflow_id},
        "_request_workflow_run_cancellation": raise_failure,
        "_resolve_group_workflow_request_group": raise_failure,
    }
    exec(compile(module, "route_backend_workflows.py", "exec"), namespace)
    args = (workflow_id, run_id) if route_name == "cancel_user_workflow_run" else (workflow_id,)

    capture = RecordCapture()
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        response = namespace[route_name](*args)
    finally:
        root.removeHandler(capture)
    return response, [record for record in capture.records if record.name == "root"]


@pytest.mark.parametrize(
    "route_name, failure, status, expected", WORKFLOW_CANCEL_LINES, ids=WORKFLOW_CANCEL_IDS,
)
def test_workflow_cancellation_logs_an_ordinary_identifier_exactly_as_before(route_name, failure, status, expected):
    response, records = run_workflow_cancel_route(route_name, "wf-1", "run-1", failure)
    messages = [record.getMessage() for record in records]
    assert response[1] == status
    assert messages == [expected.format(workflow_id="wf-1", run_id="run-1")]


@pytest.mark.parametrize(
    "route_name, failure, status, expected", WORKFLOW_CANCEL_LINES, ids=WORKFLOW_CANCEL_IDS,
)
def test_workflow_cancellation_keeps_an_injected_identifier_on_one_line_with_its_traceback(
    route_name, failure, status, expected
):
    response, records = run_workflow_cancel_route(route_name, "wf-1\nFORGED", "run-1\r\nFORGED", failure)
    messages = [record.getMessage() for record in records]
    formatted = [logging.Formatter().format(record) for record in records]
    assert response[1] == status
    assert messages == [expected.format(workflow_id="wf-1 FORGED", run_id="run-1 FORGED")]
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None and records[0].exc_info[1] is not None
    assert "Traceback (most recent call last)" in formatted[0]


PLUGIN_SETTINGS_FIELDS = (
    "enable_time_plugin",
    "enable_http_plugin",
    "enable_wait_plugin",
    "enable_math_plugin",
    "enable_text_plugin",
    "enable_default_embedding_model_plugin",
    "allow_user_plugins",
    "allow_group_plugins",
)
FAKE_API_KEY = "sk-FAKE-log-injection-0123456789abcdef"


def run_plugin_settings_update(payload):
    """Call update_core_plugin_settings executed from source and capture everything it logs or prints."""
    module = definitions("route_backend_plugins.py", {"update_core_plugin_settings"})
    for node in module.body:
        node.decorator_list = []
    events = []
    saved = []

    def log_event(message, extra=None, **kwargs):
        events.append((message, extra, kwargs))

    def update_settings(updates):
        saved.append(updates)
        return True

    namespace = {
        "builtins": SimpleNamespace(),
        "jsonify": lambda body: body,
        "log_event": log_event,
        "logging": logging,
        "request": SimpleNamespace(get_json=lambda force=False: payload),
        "update_settings": update_settings,
    }
    exec(compile(module, "route_backend_plugins.py", "exec"), namespace)

    capture = RecordCapture()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    stdout = io.StringIO()
    try:
        with redirect_stdout(stdout):
            response = namespace["update_core_plugin_settings"]()
    finally:
        root.setLevel(previous_level)
        root.removeHandler(capture)
    return SimpleNamespace(
        response=response,
        events=events,
        saved=saved,
        log_lines=[record.getMessage() for record in capture.records],
        stdout=stdout.getvalue(),
        reload_requested=getattr(namespace["builtins"], "kernel_reload_needed", False),
    )


@pytest.mark.parametrize("payload, error", [
    (
        {**dict.fromkeys(PLUGIN_SETTINGS_FIELDS, True), "api_key": FAKE_API_KEY},
        "Unexpected field: api_key",
    ),
    (
        {**dict.fromkeys(PLUGIN_SETTINGS_FIELDS, True), "enable_http_plugin": f"api_key={FAKE_API_KEY}"},
        "Field 'enable_http_plugin' must be a boolean.",
    ),
], ids=["secret-field", "secret-value"])
def test_plugin_settings_update_logs_the_field_count_not_the_payload(payload, error):
    result = run_plugin_settings_update(payload)
    logged_text = repr(result.events) + "\n".join(result.log_lines) + result.stdout
    assert result.response == ({"error": error}, 400)
    assert result.events == [
        ("[PLUGINS] Received plugin settings update request.", {"field_count": len(payload)}, {}),
    ]
    assert FAKE_API_KEY not in logged_text
    assert result.saved == []


def test_plugin_settings_update_still_saves_a_valid_payload():
    payload = {**dict.fromkeys(PLUGIN_SETTINGS_FIELDS, False), "enable_fact_memory_plugin": True}
    result = run_plugin_settings_update(payload)
    expected_updates = dict.fromkeys(PLUGIN_SETTINGS_FIELDS, False)
    assert result.response == ({"success": True, "updated": expected_updates}, 200)
    assert result.saved == [expected_updates]
    assert result.reload_requested is True
    assert result.events == [
        ("[PLUGINS] Received plugin settings update request.", {"field_count": len(payload)}, {}),
    ]


PROBE = r'''
import importlib
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

EDITED = {
    "utils_cache": "sanitize_log_message",
    "route_backend_workflows": "sanitize_log_message",
    "route_backend_plugins": "log_event",
}

with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    appinsights = importlib.import_module("functions_appinsights")
    required = set(EDITED) if "app" in sys.argv[3:] else set(EDITED) & set(sys.argv[3:])
    for name, attribute in EDITED.items():
        module = sys.modules.get(name)
        if module is None:
            if name in required:
                raise AssertionError(f"{name} was not loaded")
            continue
        if getattr(module, attribute) is not getattr(appinsights, attribute):
            raise AssertionError(f"{name} resolved a different {attribute}")
    if appinsights.sanitize_log_message("wf-1\r\nFORGED") != "wf-1 FORGED":
        raise AssertionError("sanitize_log_message no longer keeps a log line on one line")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: log injection modules cold imports")
'''


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", [
    ("functions_appinsights", "utils_cache"),
    ("utils_cache", "functions_appinsights"),
    ("config", "utils_cache"),
    # app.py imports functions_authentication before any route module. Importing
    # route_backend_workflows first fails on the base too: functions_settings would load first,
    # and functions_authentication would copy it before enabled_required exists.
    ("functions_authentication", "route_backend_workflows"),
    ("route_backend_plugins",),
    ("app",),
], ids="+".join)
def test_the_edited_modules_load_cold_in_either_order(order, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    process = subprocess.run(
        command + ["-c", PROBE, str(APP), str(TESTS), *order],
        capture_output=True, text=True, timeout=300, check=False,
    )
    output = process.stdout[-8000:] + process.stderr[-8000:]
    assert process.returncode == 0, output
    assert "PASS:" in process.stdout, output


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
