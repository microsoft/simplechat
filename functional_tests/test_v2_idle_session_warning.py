#!/usr/bin/env python3
# test_v2_idle_session_warning.py
"""
Functional test for the V2 idle-session warning.
Version: 0.261.445
Implemented in: 0.261.445

The server signs a session out when nothing has refreshed it for the administrator's
timeout, and only a page load or the heartbeat route refreshes it. V2 is one page load followed
by API calls, so it used to sign active users out at the timeout, with no warning. It now reads
the timeout from the bootstrap payload, reports activity through the heartbeat route and warns
before the sign-out, as the classic page does.

These checks pin what the two sides rely on:

- the idle helpers moved out of app.py into functions_idle_timeout, which loads cold, offline,
  in every order the application reaches it, with no import cycle through it, and which both
  app.py and the V2 bootstrap route use;
- the helpers normalize the four settings as the admin schema, the settings defaults and the
  sanitiser describe them, and the bootstrap block is built from the sanitized settings only;
- the bootstrap route sends the block under ``session`` and nothing else new;
- the page's endpoints are the server's heartbeat and local sign-out routes, the heartbeat goes
  through the API client, and every block the server builds is one the page acts on;
- the page's thresholds, throttles, countdown and endings behave as classic's do (executed
  against a fake clock under node).
"""

import ast
import functools
import json
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least

# Reused so the real bootstrap route runs against the mocks that file already maintains.
from test_v2_scope_and_bootstrap_timings import environment  # noqa: F401,E402


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
TESTS = REPO_ROOT / "functional_tests"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
LOGIC_CHECK_TS = TESTS / "test_v2_idle_session_warning_logic.ts"
IDLE_MODULE = "functions_idle_timeout"

IDLE_KEYS = ("enable_idle_timeout", "idle_timeout_minutes", "idle_warning_minutes", "idle_warning_message")
BLOCK_KEYS = {"enabled", "timeout_minutes", "warning_minutes", "warning_message"}
DEFAULT_MESSAGE = "You've been inactive for a while."


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def idle():
    return import_app_module(IDLE_MODULE)


# ---------------------------------------------------------------------------
# The helpers
# ---------------------------------------------------------------------------

def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.445")


@pytest.mark.parametrize("settings,expected", [
    ({}, (30, 28)),
    ({"idle_timeout_minutes": 45, "idle_warning_minutes": 40}, (45, 40)),
    ({"idle_timeout_minutes": "20", "idle_warning_minutes": "15"}, (20, 15)),
    ({"idle_timeout_minutes": 5, "idle_warning_minutes": 3}, (10, 3)),
    ({"idle_timeout_minutes": 5, "idle_warning_minutes": 28}, (10, 10)),
    ({"idle_timeout_minutes": 30, "idle_warning_minutes": -4}, (30, 0)),
    ({"idle_timeout_minutes": 30, "idle_warning_minutes": 99}, (30, 30)),
    ({"idle_timeout_minutes": "soon", "idle_warning_minutes": "later"}, (30, 28)),
    ({"idle_timeout_minutes": None, "idle_warning_minutes": None}, (30, 28)),
    ({"idle_timeout_minutes": 1440, "idle_warning_minutes": 1439}, (1440, 1439)),
])
def test_the_minutes_are_normalized_as_the_server_enforces_them(settings, expected):
    assert idle().get_idle_timeout_settings(settings) == expected


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), (None, False), (0, False), (1, True),
    ("true", True), ("TRUE", True), (" yes ", True), ("on", True), ("1", True),
    ("false", False), ("off", False), ("", False), ("no", False),
])
def test_the_switch_reads_as_the_server_reads_it(value, expected):
    assert idle().is_idle_timeout_enabled({"enable_idle_timeout": value}) is expected
    assert idle().is_idle_timeout_enabled({}) is False


def test_the_warning_sentence_is_text_with_a_default_and_a_cap():
    message = idle().get_idle_warning_message
    assert message({}) == DEFAULT_MESSAGE
    assert message({"idle_warning_message": None}) == DEFAULT_MESSAGE
    assert message({"idle_warning_message": 42}) == DEFAULT_MESSAGE
    assert message({"idle_warning_message": "   "}) == DEFAULT_MESSAGE
    assert message({"idle_warning_message": "  Are you still there?  "}) == "Are you still there?"
    assert message({"idle_warning_message": "x" * 500}) == "x" * 200
    assert message({"idle_warning_message": "<b>Still</b> here?"}) == "<b>Still</b> here?", (
        "The sentence is returned as typed: the browser renders it as text"
    )


def test_invalid_values_are_logged_under_a_documented_tag():
    module = import_app_module(IDLE_MODULE)
    events = []
    module.log_event = lambda message, **kwargs: events.append((message, kwargs))
    assert module.get_idle_timeout_settings({"idle_timeout_minutes": "x", "idle_warning_minutes": 3}) == (30, 3)
    assert module.get_idle_timeout_settings({"idle_timeout_minutes": 5, "idle_warning_minutes": 28}) == (10, 10)
    assert [message for message, _ in events] == [
        "[IDLE_TIMEOUT] Invalid idle timeout value detected; using default.",
        "[IDLE_TIMEOUT] Idle timeout value normalized to minimum allowed value.",
        "[IDLE_TIMEOUT] Idle warning value adjusted to not exceed idle timeout.",
    ]
    assert events[0][1]["extra"]["setting"] == "idle_timeout_minutes"
    assert "`[IDLE_TIMEOUT]`" in _read(REPO_ROOT / "docs" / "reference" / "logging-tags.md")


def test_the_bootstrap_block_carries_only_the_four_normalized_values():
    build = idle().build_idle_timeout_bootstrap
    block = build({
        "enable_idle_timeout": True, "idle_timeout_minutes": 5, "idle_warning_minutes": 50,
        "idle_warning_message": "  Still there?  ", "azure_openai_gpt_key": "SECRET", "anything": 1,
    })
    assert block == {"enabled": True, "timeout_minutes": 10, "warning_minutes": 10, "warning_message": "Still there?"}
    assert "SECRET" not in json.dumps(block)
    assert build({}) == {"enabled": False, "timeout_minutes": 30, "warning_minutes": 28, "warning_message": DEFAULT_MESSAGE}


def test_the_settings_match_the_admin_schema_the_defaults_and_the_sanitiser():
    module = idle()
    fields = import_app_module("admin_settings_fields")
    schema = {field["key"]: field for field in fields.get_admin_settings_fields()["idle-timeout-section"]}
    assert set(schema) == set(IDLE_KEYS), "The Session section describes exactly the four idle settings"
    assert schema["enable_idle_timeout"]["default"] is False
    assert schema["idle_timeout_minutes"]["default"] == 30 and schema["idle_warning_minutes"]["default"] == 28
    assert schema["idle_warning_message"]["default"] == DEFAULT_MESSAGE == module.IDLE_WARNING_DEFAULT_MESSAGE
    assert schema["idle_warning_message"]["max_length"] == module.IDLE_WARNING_MESSAGE_MAX_LENGTH
    assert schema["idle_timeout_minutes"]["min"] == fields.IDLE_TIMEOUT_MIN_MINUTES == module.IDLE_TIMEOUT_MIN_MINUTES
    assert schema["idle_warning_minutes"]["min"] == fields.IDLE_WARNING_MIN_MINUTES == module.IDLE_WARNING_MIN_MINUTES
    assert module.get_idle_timeout_settings({}) == (schema["idle_timeout_minutes"]["default"],
                                                   schema["idle_warning_minutes"]["default"])

    stored_defaults = _read(APP_ROOT / "functions_settings.py")
    for marker in ("'enable_idle_timeout': False", "'idle_timeout_minutes': 30", "'idle_warning_minutes': 28",
                   "'idle_warning_message': \"You've been inactive for a while.\""):
        assert marker in stored_defaults, f"Stored defaults changed: {marker}"


# ---------------------------------------------------------------------------
# No import cycle, and the two consumers use the one module
# ---------------------------------------------------------------------------

def _module_name(path):
    dotted = ".".join(path.relative_to(APP_ROOT).with_suffix("").parts)
    return dotted[: -len(".__init__")] if dotted.endswith(".__init__") else dotted


def _imports(tree, *, include_functions):
    """Dotted names a module imports: its body and branches, and optionally its functions too."""
    found = []

    def walk(nodes):
        for node in nodes:
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level:
                found.append(node.module or "")
                found.extend(f"{node.module}.{alias.name}" for alias in node.names)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and not include_functions:
                continue
            for field in ("body", "orelse", "finalbody"):
                walk(getattr(node, field, None) or [])
            for handler in getattr(node, "handlers", None) or []:
                walk(handler.body)

    walk(tree.body)
    return found


@functools.lru_cache(maxsize=1)
def _graph():
    modules = {_module_name(path): path for path in APP_ROOT.rglob("*.py") if "__pycache__" not in path.parts}
    edges = {}
    for module, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        targets = set()
        for name in _imports(tree, include_functions=True):
            parts = name.split(".")
            for end in range(1, len(parts) + 1):
                candidate = ".".join(parts[:end])
                if candidate in modules and candidate != module:
                    targets.add(candidate)
        edges[module] = targets
    return edges


def _cycle_through(start):
    edges = _graph()
    queue, seen = deque([[start]]), set()
    while queue:
        path = queue.popleft()
        for target in sorted(edges.get(path[-1], ())):
            if target == start:
                return path + [start]
            if target not in seen:
                seen.add(target)
                queue.append(path + [target])
    return None


def test_the_idle_module_depends_only_on_logging_and_cannot_be_in_a_cycle():
    tree = ast.parse(_read(APP_ROOT / f"{IDLE_MODULE}.py"))
    imported = {name.split(".")[0] for name in _imports(tree, include_functions=True)}
    assert imported == {"logging", "functions_appinsights"}, (
        "functions_idle_timeout must stay below config, settings and the routes in the import graph"
    )
    cycle = _cycle_through(IDLE_MODULE)
    assert cycle is None, "An import cycle passes through functions_idle_timeout: " + " -> ".join(cycle or [])


def test_route_modules_do_not_import_the_application_and_both_consumers_share_the_helpers():
    for name in ("route_backend_v2.py", f"{IDLE_MODULE}.py"):
        tree = ast.parse(_read(APP_ROOT / name))
        imported = {item.split(".")[0] for item in _imports(tree, include_functions=True)}
        assert "app" not in imported, f"{name} imports app, which imports it"

    route = _read(APP_ROOT / "route_backend_v2.py")
    assert "from functions_idle_timeout import build_idle_timeout_bootstrap" in route

    application = ast.parse(_read(APP_ROOT / "app.py"))
    imported_names = {
        alias.name: alias.asname
        for node in application.body
        if isinstance(node, ast.ImportFrom) and node.module == IDLE_MODULE
        for alias in node.names
    }
    assert imported_names == {
        "get_idle_timeout_settings": "resolve_idle_timeout_settings",
        "is_idle_timeout_enabled": "resolve_idle_timeout_enabled",
    }
    wrappers = {
        node.name: node for node in application.body
        if isinstance(node, ast.FunctionDef) and node.name in ("get_idle_timeout_settings", "is_idle_timeout_enabled")
    }
    assert set(wrappers) == {"get_idle_timeout_settings", "is_idle_timeout_enabled"}, (
        "app.py keeps the existing names, which its enforcement, template context and heartbeat call"
    )
    for name, delegate in (("get_idle_timeout_settings", "resolve_idle_timeout_settings"),
                           ("is_idle_timeout_enabled", "resolve_idle_timeout_enabled")):
        source = ast.unparse(wrappers[name])
        assert f"return {delegate}(settings)" in source, f"{name} no longer delegates to the shared module"
        assert "settings = get_request_settings()" in source, f"{name} lost its request-settings default"


PROBE = r'''
import importlib
import json
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3].split(","):
        importlib.import_module(name)
    idle = importlib.import_module("functions_idle_timeout")
    route = importlib.import_module("route_backend_v2")
    settings_module = importlib.import_module("functions_settings")
    if route.build_idle_timeout_bootstrap is not idle.build_idle_timeout_bootstrap:
        raise AssertionError("route_backend_v2 resolved a different idle module")

    raw = {
        "enable_idle_timeout": True, "idle_timeout_minutes": 45, "idle_warning_minutes": 40,
        "idle_warning_message": "Still there?", "azure_openai_gpt_key": "KEY-VALUE-SECRET",
    }
    public = settings_module.sanitize_settings_for_user(raw)
    for key in ("enable_idle_timeout", "idle_timeout_minutes", "idle_warning_minutes", "idle_warning_message"):
        if public.get(key) != raw[key]:
            raise AssertionError(f"The sanitiser changed or dropped {key}")
    block = route._build_session(public)
    expected = {"idle_timeout": {
        "enabled": True, "timeout_minutes": 45, "warning_minutes": 40, "warning_message": "Still there?",
    }}
    if block != expected:
        raise AssertionError(f"Unexpected session block: {block}")
    if "KEY-VALUE-SECRET" in json.dumps(block):
        raise AssertionError("The session block carried a secret")

    if "app" in sys.argv[3].split(","):
        web = sys.modules["app"]
        if web.get_idle_timeout_settings({"idle_timeout_minutes": 5, "idle_warning_minutes": 50}) != (10, 10):
            raise AssertionError("app.get_idle_timeout_settings no longer normalizes")
        if web.is_idle_timeout_enabled({"enable_idle_timeout": "on"}) is not True:
            raise AssertionError("app.is_idle_timeout_enabled no longer reads the switch")
    if environment.network_attempts:
        raise AssertionError("A cold import swallowed a network attempt")
print("PASS: idle timeout cold imports")
'''

ORDERS = {
    "idle-module-first": "functions_idle_timeout",
    "v2-route-first": "route_backend_v2",
    "web-app-first": "app",
}


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", list(ORDERS.values()), ids=list(ORDERS))
def test_the_modules_load_cold_offline_in_every_order_and_agree(order, optimized):
    command = [sys.executable, "-B", *(["-O"] if optimized else []), "-c", PROBE, str(APP_ROOT), str(TESTS), order]
    process = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    assert process.returncode == 0, process.stdout[-8000:] + process.stderr[-8000:]
    assert "PASS:" in process.stdout


# ---------------------------------------------------------------------------
# The bootstrap route
# ---------------------------------------------------------------------------

def test_the_bootstrap_route_sends_the_block_built_from_the_sanitized_settings(environment):  # noqa: F811
    module = idle()
    tree = ast.parse(_read(APP_ROOT / "route_backend_v2.py"))
    build_session = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_build_session")
    scope = {"build_idle_timeout_bootstrap": module.build_idle_timeout_bootstrap}
    exec(compile(ast.Module(body=[build_session], type_ignores=[]), "route_backend_v2.py", "exec"), scope)

    namespace = environment.namespace
    namespace["_build_session"] = scope["_build_session"]
    # The raw settings and the sanitized ones disagree, so the block shows which it read.
    namespace["get_settings"].return_value = {
        "enable_idle_timeout": True, "idle_timeout_minutes": 99, "idle_warning_minutes": 90,
        "azure_openai_gpt_key": "RAW-SECRET",
    }
    namespace["sanitize_settings_for_user"].return_value = {
        "enable_idle_timeout": True, "idle_timeout_minutes": 45, "idle_warning_minutes": 40,
        "idle_warning_message": "Still there?",
    }
    response = environment.client.get("/api/v2/bootstrap")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["session"] == {"idle_timeout": {
        "enabled": True, "timeout_minutes": 45, "warning_minutes": 40, "warning_message": "Still there?",
    }}
    assert "RAW-SECRET" not in response.get_data(as_text=True)


def test_the_bootstrap_adds_only_the_session_block_and_a_timing_mark():
    route = _read(APP_ROOT / "route_backend_v2.py")
    assert '"session": session_block,' in route
    assert "session_block = _build_session(public_settings)" in route, "Built from the sanitized settings"
    assert 'timer.mark("session")' in route
    tree = ast.parse(route)
    build_session = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_build_session")
    assert ast.unparse(build_session.body[-1]) == "return {'idle_timeout': build_idle_timeout_bootstrap(public_settings)}"

    types = _read(V2_SRC / "lib" / "types.ts")
    block = re.search(r"export interface IdleTimeoutBootstrap \{(.*?)\n\}", types, re.DOTALL)
    assert block, "types.ts must describe the block"
    assert set(re.findall(r"^\s+(\w+): ", block.group(1), re.MULTILINE)) == BLOCK_KEYS, (
        "The TypeScript block must carry the keys the server builds"
    )
    assert re.search(r"session\?: \{\s*idle_timeout\?: IdleTimeoutBootstrap;", types), (
        "An older server sends no session block, which must read as no warning"
    )


# ---------------------------------------------------------------------------
# The page's endpoints and wiring
# ---------------------------------------------------------------------------

def test_the_page_calls_the_servers_heartbeat_and_sign_out_routes_through_the_api_client():
    session_ts = _read(V2_SRC / "lib" / "idleSession.ts")
    runtime_ts = _read(V2_SRC / "lib" / "idleSessionRuntime.ts")
    app_py = _read(APP_ROOT / "app.py")

    heartbeat = re.search(r"IDLE_HEARTBEAT_ENDPOINT = '([^']+)'", session_ts).group(1)
    assert f"@session_api_bp.route('{heartbeat}', methods=['POST'])" in app_py, (
        "The heartbeat is a POST on the route the page calls"
    )
    tree = ast.parse(app_py)
    route = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "session_heartbeat")
    assert [ast.unparse(decorator) for decorator in route.decorator_list] == [
        f"session_api_bp.route('{heartbeat}', methods=['POST'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
    ]
    assert not re.search(r"request\.(get_json|json|data|form|args|files)", ast.unparse(route)), (
        "The heartbeat reads nothing from the request, so the page's empty body is all it needs"
    )
    assert "session_api_bp.before_request(login_required_blueprint())" in app_py

    sign_out = re.search(r"IDLE_SIGN_OUT_PATH = '([^']+)'", session_ts).group(1)
    assert f"@bp.route('{sign_out}')" in _read(APP_ROOT / "route_frontend_authentication.py")
    config = _read(APP_ROOT / "config.py")
    exempt = re.search(r"IDLE_TIMEOUT_EXEMPT_PATHS = \{(.*?)\}", config, re.DOTALL).group(1)
    assert f"'{sign_out}'" in exempt, "The sign-out itself must not be turned away by the idle check"

    assert "api.post<unknown>(IDLE_HEARTBEAT_ENDPOINT, {})" in runtime_ts, "An empty JSON body, through apiClient"
    assert "from './apiClient'" in runtime_ts
    for source in (session_ts, runtime_ts):
        assert "fetch(" not in source, "Every call goes through the API client"
        assert "dangerouslySetInnerHTML" not in source and "display:none" not in source.replace(" ", "")


def test_classic_signs_out_locally_for_both_buttons_and_so_does_the_page():
    """Classic's Logout now and its timeout both use logoutNow(), which prefers the local sign-out."""
    classic = _read(APP_ROOT / "static" / "js" / "idle-logout-warning.js")
    assert "const logoutTarget = mergedConfig.localLogoutUrl || mergedConfig.fullSsoLogoutUrl || mergedConfig.logoutUrl" in classic
    assert classic.count("logoutNow()") >= 3
    base = _read(APP_ROOT / "templates" / "base.html")
    assert "'localLogoutUrl': url_for('frontend_authentication.local_logout')" in base
    assert re.search(r"IDLE_SIGN_OUT_PATH = '/logout/local'", _read(V2_SRC / "lib" / "idleSession.ts"))


def test_the_dialog_is_mounted_once_below_the_point_where_a_session_has_loaded():
    app = _read(V2_SRC / "App.tsx")
    assert app.count("<IdleSessionDialogHost />") == 1
    assert app.index("<IdleSessionDialogHost />") > app.index("if (error || !data)"), (
        "Only a loaded session reaches the shell, so only a loaded session is timed"
    )
    assert app.index("<IdleSessionDialogHost />") > app.index("<AppShell>")
    dialog = _read(V2_SRC / "components" / "layout" / "IdleSessionDialog.tsx")
    for required in ('role="alertdialog"', 'aria-modal="true"', "aria-labelledby", "aria-describedby",
                     'role="status"', "autoFocus", "event.stopPropagation()", "createPortal"):
        assert required in dialog, f"The dialog lost {required}"
    compact = dialog.replace(" ", "")
    for forbidden in ("dangerouslySetInnerHTML", "innerHTML", "display:none", "alert(", "console."):
        assert forbidden not in compact, f"The dialog uses {forbidden}"
    assert "{message}" in dialog, "The administrator's sentence is rendered as a text child"


# ---------------------------------------------------------------------------
# The page's behaviour, executed
# ---------------------------------------------------------------------------

def _server_blocks():
    """Blocks the real helper builds for a spread of stored settings."""
    cases = {
        "off by default": {},
        "off with values": {"enable_idle_timeout": False, "idle_timeout_minutes": 15, "idle_warning_minutes": 10},
        "defaults on": {"enable_idle_timeout": True},
        "warning equal to timeout": {"enable_idle_timeout": True, "idle_timeout_minutes": 15, "idle_warning_minutes": 15},
        "warning after timeout": {"enable_idle_timeout": True, "idle_timeout_minutes": 15, "idle_warning_minutes": 40},
        "timeout under the minimum": {"enable_idle_timeout": True, "idle_timeout_minutes": 3, "idle_warning_minutes": 2},
        "warning of zero": {"enable_idle_timeout": True, "idle_timeout_minutes": 20, "idle_warning_minutes": 0},
        "negative warning": {"enable_idle_timeout": True, "idle_timeout_minutes": 20, "idle_warning_minutes": -5},
        "numbers as strings": {"enable_idle_timeout": "true", "idle_timeout_minutes": "25", "idle_warning_minutes": "20"},
        "garbage numbers": {"enable_idle_timeout": "yes", "idle_timeout_minutes": "x", "idle_warning_minutes": None},
        "the longest timeout": {"enable_idle_timeout": True, "idle_timeout_minutes": 1440, "idle_warning_minutes": 1438},
        "padded sentence": {"enable_idle_timeout": True, "idle_warning_message": "   Are you there?   "},
        "blank sentence": {"enable_idle_timeout": True, "idle_warning_message": "  "},
        "oversize sentence": {"enable_idle_timeout": True, "idle_warning_message": "y" * 400},
        "markup sentence": {"enable_idle_timeout": True, "idle_warning_message": "<img src=x onerror=1>"},
    }
    return [{"label": label, "block": idle().build_idle_timeout_bootstrap(settings)} for label, settings in cases.items()]


def test_the_page_logic_passes_against_a_fake_clock_and_every_server_block():
    """Execute the TypeScript checks, skipping when the front-end toolchain is absent."""
    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return
    assert LOGIC_CHECK_TS.exists(), "The TypeScript idle-session checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node
    # can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-idle-session-check.mjs"
    blocks_file = V2_DIR / "node_modules" / ".cache-idle-session-blocks.json"
    blocks_file.write_text(json.dumps(_server_blocks()), encoding="utf-8")
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(LOGIC_CHECK_TS), "--bundle", "--platform=node", "--format=esm",
                "--packages=external",
                # apiClient reads import.meta.env, which only Vite provides.
                "--define:import.meta.env={}", f"--outfile={bundle}", "--log-level=error",
            ],
            cwd=str(V2_DIR), check=True, shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)], cwd=str(V2_DIR), capture_output=True, text=True,
            env={**os.environ, "IDLE_SESSION_SERVER_BLOCKS": str(blocks_file)},
            shell=(sys.platform == "win32"),
        )
    finally:
        for path in (bundle, blocks_file):
            if path.exists():
                path.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript idle-session checks failed")
    passed = result.stdout.count("  ok  ")
    assert passed >= 38, f"Only {passed} idle-session checks ran; the runner likely broke."
    assert "  skip  " not in result.stdout, "The server-block cross-check was skipped"
    print(f"  ok  {passed} TypeScript idle-session checks passed")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
