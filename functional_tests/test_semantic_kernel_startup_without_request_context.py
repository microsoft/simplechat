#!/usr/bin/env python3
# test_semantic_kernel_startup_without_request_context.py
"""
Functional test for the Semantic Kernel startup request-context guard.
Version: 0.260.023
Implemented in: 0.260.023

Semantic Kernel initialization runs outside a Flask request context when SimpleChat is started
directly (python app.py). Loading an agent that has actions assigned previously called
get_current_user_id() unguarded, which reads the Flask session proxy and raised
"RuntimeError: Working outside of request context", aborting startup.

This test ensures that:
  1. get_current_user_id() still raises outside a request context, so authorization callers keep
     failing loudly rather than silently resolving to an unauthenticated identity.
  2. get_current_user_id_or_none() returns None outside a request context.
  3. get_current_user_id_or_none() still resolves the session identity inside a request context, so
     hosted (gunicorn) behavior is unchanged.
  4. semantic_kernel_loader.py routes every identity lookup through the safe helper, and never hands
     a possibly-missing identity straight to require_active_group() or get_user_settings().

Refs: issue #1327.
"""

import ast
import os
import sys
import traceback
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
LOADER_FILE = APP_DIR / "semantic_kernel_loader.py"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_DIR))

from test_support.versioning import assert_app_version_at_least

IMPLEMENTED_IN_VERSION = "0.260.023"

# Identity-optional helper that call sites are expected to use.
SAFE_IDENTITY_HELPER = "get_current_user_id_or_none"
# Fail-loud helper that must not be called directly by the loader.
STRICT_IDENTITY_HELPER = "get_current_user_id"
# Callers that perform a Cosmos read keyed on the identity, so None must never reach them.
IDENTITY_CONSUMING_CALLS = ("require_active_group", "get_user_settings")


def install_authentication_stubs():
    """Install the minimal module stubs needed to import functions_authentication.

    config.py builds live Azure Cosmos clients at import time, so the real module cannot be
    imported without deployed infrastructure. The stub re-exports the same Flask names config.py
    re-exports, because functions_authentication reaches `session` through `from config import *`.
    """
    import flask
    from flask import Flask

    config_stub = types.ModuleType("config")
    config_stub._is_test_stub = True
    # Mirror the Flask names config.py re-exports (see config.py "from flask import (...)").
    for flask_name in (
        "Flask",
        "flash",
        "request",
        "jsonify",
        "render_template",
        "redirect",
        "url_for",
        "session",
        "send_from_directory",
        "send_file",
        "current_app",
    ):
        setattr(config_stub, flask_name, getattr(flask, flask_name))
    config_stub.app = Flask(__name__)
    config_stub.app.secret_key = "functional-test-secret"
    sys.modules["config"] = config_stub

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = appinsights_stub

    settings_stub = types.ModuleType("functions_settings")
    settings_stub.get_settings = lambda *args, **kwargs: {}
    settings_stub.get_user_settings = lambda *args, **kwargs: {"settings": {}}
    settings_stub.update_user_settings = lambda *args, **kwargs: None
    sys.modules["functions_settings"] = settings_stub

    debug_stub = types.ModuleType("functions_debug")
    debug_stub.debug_print = lambda *args, **kwargs: None
    sys.modules["functions_debug"] = debug_stub

    return config_stub.app


def test_identity_helpers_outside_and_inside_request_context():
    """The safe helper degrades to None outside a request context; the strict helper still raises."""
    print("🔍 Testing identity helper behavior with and without a request context...")

    try:
        flask_app = install_authentication_stubs()

        import functions_authentication

        assert hasattr(functions_authentication, SAFE_IDENTITY_HELPER), (
            f"functions_authentication must expose {SAFE_IDENTITY_HELPER}()"
        )
        safe_helper = getattr(functions_authentication, SAFE_IDENTITY_HELPER)
        strict_helper = getattr(functions_authentication, STRICT_IDENTITY_HELPER)

        # 1. The strict helper must keep failing loudly outside a request context.
        try:
            strict_helper()
        except RuntimeError:
            pass
        else:
            raise AssertionError(
                f"{STRICT_IDENTITY_HELPER}() must still raise RuntimeError outside a request "
                "context so authorization callers do not silently degrade to no identity."
            )

        # 2. The safe helper must degrade to None instead of raising. This is the startup fix.
        assert safe_helper() is None, (
            f"{SAFE_IDENTITY_HELPER}() must return None outside a request context."
        )

        # 3. Hosted behavior must be unchanged: an authenticated request still resolves the oid.
        from flask import session

        with flask_app.test_request_context("/"):
            session["user"] = {"oid": "user-oid-1327"}
            assert safe_helper() == "user-oid-1327", (
                f"{SAFE_IDENTITY_HELPER}() must resolve the session identity inside a request context."
            )

        # 4. An unauthenticated request still resolves to None without raising.
        with flask_app.test_request_context("/favicon.ico"):
            assert safe_helper() is None, (
                f"{SAFE_IDENTITY_HELPER}() must return None for an unauthenticated request."
            )

        print("✅ Identity helper behavior verified.")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def _call_name(node):
    """Return the dotted callee name for an ast.Call node, or '' when it is not a plain name."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def test_loader_uses_only_the_safe_identity_helper():
    """The Semantic Kernel loader must never call the fail-loud identity helper directly."""
    print("🔍 Testing that semantic_kernel_loader.py uses only the request-context-safe helper...")

    try:
        loader_source = LOADER_FILE.read_text(encoding="utf-8")
        loader_tree = ast.parse(loader_source)

        strict_calls = []
        safe_calls = []
        leaked_identity_arguments = []

        for node in ast.walk(loader_tree):
            if not isinstance(node, ast.Call):
                continue

            callee = _call_name(node)
            if callee == STRICT_IDENTITY_HELPER:
                strict_calls.append(node.lineno)
            elif callee == SAFE_IDENTITY_HELPER:
                safe_calls.append(node.lineno)

            # Passing an unresolved identity straight through would only trade the RuntimeError
            # for a Cosmos lookup keyed on None, so each call site must short-circuit first.
            if callee in IDENTITY_CONSUMING_CALLS:
                for argument in node.args:
                    if isinstance(argument, ast.Call) and _call_name(argument) in (
                        STRICT_IDENTITY_HELPER,
                        SAFE_IDENTITY_HELPER,
                    ):
                        leaked_identity_arguments.append((node.lineno, callee))

        assert not strict_calls, (
            f"semantic_kernel_loader.py must not call {STRICT_IDENTITY_HELPER}() directly; found at "
            f"line(s) {strict_calls}. Startup runs outside a request context, so use "
            f"{SAFE_IDENTITY_HELPER}() instead."
        )

        assert safe_calls, (
            f"semantic_kernel_loader.py should resolve identity through {SAFE_IDENTITY_HELPER}()."
        )

        assert not leaked_identity_arguments, (
            "A possibly-missing identity is passed straight into a Cosmos-backed lookup at "
            f"{leaked_identity_arguments}. Resolve the identity first and skip the lookup when it "
            "is absent."
        )

        # The safe helper must actually be imported rather than resolved dynamically.
        imported_names = set()
        for node in ast.walk(loader_tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)

        assert SAFE_IDENTITY_HELPER in imported_names, (
            f"semantic_kernel_loader.py must import {SAFE_IDENTITY_HELPER}."
        )

        print(f"✅ Loader routes all {len(safe_calls)} identity lookups through the safe helper.")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


def test_version_is_at_least_implementation_version():
    """The application version must be at least the version this fix shipped in."""
    print("🔍 Testing application version...")

    try:
        app_version = assert_app_version_at_least(
            IMPLEMENTED_IN_VERSION,
            reason="Semantic Kernel startup request-context guard shipped in this version.",
        )
        print(f"✅ Application version {app_version} is at least {IMPLEMENTED_IN_VERSION}.")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_identity_helpers_outside_and_inside_request_context,
        test_loader_uses_only_the_safe_identity_helper,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
