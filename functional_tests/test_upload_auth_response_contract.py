# test_upload_auth_response_contract.py
"""
Functional regression for multipart authentication response negotiation.
Version: 0.261.354
Implemented in: 0.261.354

Real authentication decorators and the actual idle middleware source run on Flask
with network access blocked. Only external bootstrap I/O, settings and logging
are controlled. The idle function is loaded without app.py's unrelated startup;
this tests its response/activity contract, not application import safety.
Fresh-process probes also run under optimized Python with explicit checks.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import ast
import io
import logging
from pathlib import Path
import sys
import time
from unittest.mock import patch

from flask import Blueprint, Flask, jsonify, redirect, request, session, url_for

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import _test_client, check

with offline_app_imports():
    import functions_authentication as auth

    settings = {"idle_timeout_minutes": 30}
    clock = 2000000000
    activity = []
    handled = []
    source_path = root / "application" / "single_app" / "app.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
    idle = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "enforce_idle_session_timeout")
    idle.decorator_list = []
    scope = dict(
        request=request, session=session, jsonify=jsonify, redirect=redirect, url_for=url_for,
        time=type("Clock", (), {"time": staticmethod(lambda: clock)}), logging=logging,
        log_event=lambda *args, **kwargs: None,
        _is_idle_timeout_exempt=lambda path: path == "/logout/local",
        get_request_settings=lambda: settings,
        is_idle_timeout_enabled=lambda value: True,
        get_idle_timeout_settings=lambda value: (30, 28),
        maybe_log_authenticated_browser_request=lambda: activity.append(request.path),
    )
    exec(compile(ast.Module(body=[idle], type_ignores=[]), str(source_path), "exec"), scope)
    app = Flask("upload-response-contract")
    app.secret_key = "offline-test-only"
    app.config["TESTING"] = True
    app.before_request(scope["enforce_idle_session_timeout"])
    auth_routes = Blueprint("frontend_authentication", __name__)
    auth_routes.add_url_rule("/login", "login", lambda: "Sign in")
    auth_routes.add_url_rule("/logout/local", "local_logout", lambda: "Signed out")
    app.register_blueprint(auth_routes)

    @auth.login_required
    @auth.user_required
    def upload():
        handled.append(request.files["file"].read())
        return jsonify({"success": True})

    app.add_url_rule("/upload", "upload", upload, methods=["POST"])
    app.add_url_rule("/api/documents/upload", "workspace_upload", upload, methods=["POST"])
    app.add_url_rule("/chats", "chats", auth.login_required(lambda: "Chats"))
    client = _test_client(app)

    def seed(kind, roles=("User",)):
        with client.session_transaction() as state:
            state.clear()
            if kind != "missing":
                state["user"] = {"oid": "synthetic-user", "roles": list(roles)}
                state["last_activity_epoch"] = clock - (3600 if kind == "expired" else 100)

    def post(path, accept):
        return client.post(path, headers={"Accept": accept},
                           data={"file": (io.BytesIO(b"program,amount\nA,10\n"), "ledger.csv")})

    with patch.object(auth, "check_user_access_status", return_value=(True, None)), \
         patch.object(auth, "debug_print", lambda *args, **kwargs: None), \
         patch("functions_settings.get_settings", return_value={}):
        for path in ("/upload", "/api/documents/upload"):
            for kind in ("missing", "expired"):
                for accept in ("application/json", "*/*", "text/html", "application/json,text/html"):
                    seed(kind)
                    response = post(path, accept)
                    expects_json = path.startswith("/api/") or accept == "application/json"
                    check(response.status_code == (401 if expects_json else 302),
                          f"{path} {kind} {accept}: {response.status_code}")
                    if expects_json:
                        check(response.is_json, "API authentication failure must be JSON")
                        check("Location" not in response.headers, "JSON auth error redirected")
                        body = response.get_json()
                        if kind == "expired":
                            check(body.get("requires_reauth") is True, "Missing reauth marker")
                            check(body.get("error") == "Session expired", "Idle error contract changed")
                        else:
                            check(body.get("message") == "Authentication required", "Login error changed")
                    else:
                        target = "/login" if kind == "missing" else "/logout/local"
                        check(response.headers.get("Location") == target, "Navigation redirect changed")
                    if kind == "expired":
                        with client.session_transaction() as state:
                            check("user" not in state, "Expired identity survived")
        check(not handled, "Denied upload entered the handler")
        check(not activity, "Denied upload recorded activity")

        for path in ("/upload", "/api/documents/upload"):
            seed("active")
            response = post(path, "application/json")
            check(response.status_code == 200, "Valid upload denied")
            check(response.get_json() == {"success": True}, "Success contract changed")
            with client.session_transaction() as state:
                expected = clock if path == "/upload" else clock - 100
                check(state["last_activity_epoch"] == expected, "Activity semantics changed")
        check(len(handled) == 2, "Expected exactly two accepted uploads")
        check(all(body == b"program,amount\nA,10\n" for body in handled), "File body changed")
        check(activity == ["/upload"], "API traffic started refreshing idle activity")

        seed("active", roles=())
        denied = post("/upload", "application/json")
        check(denied.status_code == 403 and denied.is_json, "Role denial changed")
        check(len(handled) == 2, "Role-denied upload entered handler")

        for kind in ("missing", "expired"):
            seed(kind)
            navigation = client.get("/chats", headers={"Accept": "text/html"})
            check(navigation.status_code == 302, "HTML navigation stopped redirecting")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_upload_authentication_response_contract(optimized):
    """JSON upload callers get 401 while browser redirects/activity remain intact."""
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", PROBE, str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
