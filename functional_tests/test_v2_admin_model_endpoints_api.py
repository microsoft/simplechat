#!/usr/bin/env python3
# test_v2_admin_model_endpoints_api.py
"""
Functional test for the V2 admin global model endpoint API.
Version: 0.261.059
Implemented in: 0.261.059

Global model endpoints were the only scope without per-resource routes. They were
written through a hidden ``model_endpoints_json`` field on the classic admin form, so
adding or editing one stored nothing until the whole settings page was submitted.

These checks pin the replacement:

  1. The five CRUD routes exist on the admin blueprint and are admin-gated.
  2. Every path that returns an endpoint sanitizes it first, so secrets never reach
     the browser.
  3. Every write goes through the shared persistence helper, which is what performs
     the Key Vault save, cleanup and delete passes.
  4. A default model selection is re-resolved against what was actually saved, so
     deleting or disabling the endpoint it names cannot leave it dangling.
"""

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
ROUTES_FILE = APP_DIR / "route_backend_v2.py"
SETTINGS_FILE = APP_DIR / "functions_settings.py"

EXPECTED_ROUTES = {
    ("/api/v2/admin/model-endpoints", "GET"): "v2_admin_list_model_endpoints",
    ("/api/v2/admin/model-endpoints", "POST"): "v2_admin_create_model_endpoint",
    ("/api/v2/admin/model-endpoints/<endpoint_id>", "GET"): "v2_admin_get_model_endpoint",
    ("/api/v2/admin/model-endpoints/<endpoint_id>", "PATCH"): "v2_admin_update_model_endpoint",
    ("/api/v2/admin/model-endpoints/<endpoint_id>", "DELETE"): "v2_admin_delete_model_endpoint",
}

REQUIRED_DECORATORS = {"swagger_route", "login_required", "admin_required"}


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _decorator_names(node):
    """Return the bare names of a function's decorators."""
    names = []
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names


def _route_declarations(node):
    """Return (path, method) pairs declared by ``@bp.route`` on a function."""
    declared = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if not (isinstance(target, ast.Attribute) and target.attr == "route"):
            continue
        if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
            continue
        path = decorator.args[0].value
        methods = ["GET"]
        for keyword in decorator.keywords:
            if keyword.arg == "methods" and isinstance(keyword.value, ast.List):
                methods = [
                    element.value
                    for element in keyword.value.elts
                    if isinstance(element, ast.Constant)
                ]
        declared.extend((path, method) for method in methods)
    return declared


def _find_functions(tree):
    """Return every function definition in the module, at any nesting depth."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found[node.name] = node
    return found


def _load_selection_helpers():
    """Exec the pure default-model helpers out of functions_settings.py.

    ``functions_settings`` builds Azure clients at import time and the shared test
    stub replaces the whole module, so the real functions cannot simply be imported.
    They are pure, so lifting just their source is enough and keeps the test honest
    about which implementation it is checking.
    """
    tree = _parse(SETTINGS_FILE)
    wanted_functions = {
        "normalize_default_model_selection",
        "resolve_default_model_selection",
    }
    wanted_constants = {"EMPTY_DEFAULT_MODEL_SELECTION"}

    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            selected.append(node)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & wanted_constants:
                selected.append(node)

    assert len(selected) == len(wanted_functions) + len(wanted_constants), (
        "Expected to find the default-model selection helpers in functions_settings.py, "
        f"found {[getattr(n, 'name', 'constant') for n in selected]}"
    )

    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SETTINGS_FILE), "exec"), namespace)
    return namespace


def test_crud_routes_exist_and_are_admin_gated():
    """A missing admin guard here would expose stored endpoint configuration."""
    print("Testing model endpoint route declarations...")

    assert_app_version_at_least("0.261.059")

    functions = _find_functions(_parse(ROUTES_FILE))

    declared = {}
    for name, node in functions.items():
        for route in _route_declarations(node):
            declared[route] = name

    for route, expected_name in EXPECTED_ROUTES.items():
        assert route in declared, f"Route {route[1]} {route[0]} is not declared"
        assert declared[route] == expected_name, (
            f"Route {route[1]} {route[0]} is handled by {declared[route]}, "
            f"expected {expected_name}"
        )

        decorators = set(_decorator_names(functions[expected_name]))
        missing = REQUIRED_DECORATORS - decorators
        assert not missing, f"{expected_name} is missing decorators: {sorted(missing)}"

    print(f"  All {len(EXPECTED_ROUTES)} routes declared and admin-gated.")
    return True


def test_endpoint_reads_are_sanitized():
    """A raw endpoint carries auth.api_key, which must never reach the browser."""
    print("Testing endpoint response sanitization...")

    functions = _find_functions(_parse(ROUTES_FILE))

    read_paths = [
        "v2_admin_list_model_endpoints",
        "v2_admin_get_model_endpoint",
        "_model_endpoint_response",
    ]
    for name in read_paths:
        assert name in functions, f"{name} is missing"
        source = ast.dump(functions[name])
        assert "sanitize_model_endpoints_for_frontend" in source, (
            f"{name} returns endpoint data without sanitizing it"
        )

    # The create and update routes answer with the saved endpoint, and must do so
    # through the sanitizing helper rather than jsonify-ing the stored object.
    for name in ("v2_admin_create_model_endpoint", "v2_admin_update_model_endpoint"):
        source = ast.dump(functions[name])
        assert "_model_endpoint_response" in source, (
            f"{name} should answer through _model_endpoint_response"
        )

    print("  Every endpoint read path sanitizes before responding.")
    return True


def test_writes_go_through_the_key_vault_persistence_helper():
    """Bypassing the helper would orphan secrets in Key Vault on delete."""
    print("Testing write persistence path...")

    functions = _find_functions(_parse(ROUTES_FILE))

    for name in (
        "v2_admin_create_model_endpoint",
        "v2_admin_update_model_endpoint",
        "v2_admin_delete_model_endpoint",
    ):
        source = ast.dump(functions[name])
        assert "_persist_global_model_endpoints" in source, (
            f"{name} does not persist through _persist_global_model_endpoints"
        )
        assert "normalize_model_endpoints" in source, (
            f"{name} does not normalize before persisting"
        )

    persist_source = ast.dump(functions["_persist_global_model_endpoints"])
    for helper in (
        "keyvault_model_endpoint_save_helper",
        "keyvault_model_endpoint_cleanup_helper",
        "keyvault_model_endpoint_delete_helper",
    ):
        assert helper in persist_source, f"_persist_global_model_endpoints skips {helper}"

    assert '"global"' in persist_source or "'global'" in persist_source, (
        "_persist_global_model_endpoints must use the global Key Vault scope"
    )

    print("  Writes normalize, persist and run all three Key Vault passes.")
    return True


def test_default_model_selection_is_revalidated():
    """A default pointing at a deleted endpoint silently changes which model answers."""
    print("Testing default model selection resolution...")

    helpers = _load_selection_helpers()
    resolve = helpers["resolve_default_model_selection"]

    endpoints = [
        {
            "id": "ep-1",
            "provider": "aoai",
            "enabled": True,
            "models": [
                {"id": "gpt-4o", "enabled": True},
                {"id": "gpt-4o-mini", "enabled": False},
            ],
        },
        {
            "id": "ep-2",
            "provider": "aifoundry",
            "enabled": False,
            "models": [{"id": "phi-4", "enabled": True}],
        },
    ]

    kept, reason = resolve(
        {"endpoint_id": "ep-1", "model_id": "gpt-4o", "provider": ""}, endpoints
    )
    assert reason is None, reason
    assert kept["endpoint_id"] == "ep-1" and kept["model_id"] == "gpt-4o", kept
    # Provider is refreshed from the endpoint so a stale value cannot mis-route.
    assert kept["provider"] == "aoai", kept

    missing, reason = resolve(
        {"endpoint_id": "ep-gone", "model_id": "gpt-4o"}, endpoints
    )
    assert missing["endpoint_id"] == "", missing
    assert reason and "endpoint" in reason.lower(), reason

    disabled_endpoint, reason = resolve(
        {"endpoint_id": "ep-2", "model_id": "phi-4"}, endpoints
    )
    assert disabled_endpoint["endpoint_id"] == "", disabled_endpoint
    assert reason and "endpoint" in reason.lower(), reason

    disabled_model, reason = resolve(
        {"endpoint_id": "ep-1", "model_id": "gpt-4o-mini"}, endpoints
    )
    assert disabled_model["model_id"] == "", disabled_model
    assert reason and "model" in reason.lower(), reason

    off, reason = resolve(
        {"endpoint_id": "ep-1", "model_id": "gpt-4o"},
        endpoints,
        multi_endpoint_enabled=False,
    )
    assert off == {"endpoint_id": "", "model_id": "", "provider": ""}, off
    assert reason is None, reason

    partial, reason = resolve({"endpoint_id": "ep-1", "model_id": ""}, endpoints)
    assert partial["endpoint_id"] == "", partial
    assert reason is None, reason

    print("  Selections resolve, clear and refresh provider as expected.")
    return True


def test_persistence_revalidates_the_default_selection():
    """The route layer has to apply the rule, not merely have it available."""
    print("Testing that persistence re-resolves the default...")

    functions = _find_functions(_parse(ROUTES_FILE))
    persist_source = ast.dump(functions["_persist_global_model_endpoints"])

    assert "resolve_default_model_selection" in persist_source, (
        "_persist_global_model_endpoints must re-resolve default_model_selection "
        "after saving, or deleting an endpoint leaves the default dangling"
    )
    assert "default_model_selection" in persist_source, persist_source[:200]

    print("  Persistence re-resolves the default model selection.")
    return True


def _load_persistence_helper():
    """Exec ``_persist_global_model_endpoints`` with its collaborators faked.

    The route module imports Azure clients transitively, so it cannot be imported in a
    test. The helper itself is ordinary Python over lists and dicts, so lifting its source
    and supplying fakes exercises the real ordering of the three Key Vault passes -- which
    is the part that silently orphans a secret when it is wrong.

    Returns ``(function, calls)`` where ``calls`` records what each fake was asked to do.
    """
    tree = _parse(ROUTES_FILE)
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_persist_global_model_endpoints"
        ),
        None,
    )
    assert target is not None, "_persist_global_model_endpoints was not found"

    calls = {
        "saved": [],
        "cleaned": [],
        "deleted": [],
        "updates": [],
        "settings": {
            "enable_multi_model_endpoints": True,
            "default_model_selection": {},
        },
    }

    def fake_save(endpoint, scope_value, scope="global", existing_endpoint=None):
        calls["saved"].append((endpoint.get("id"), scope, scope_value))
        return endpoint

    def fake_cleanup(previous, current, scope_value, scope="global"):
        calls["cleaned"].append((scope_value, scope))

    def fake_delete(endpoint, scope_value, scope="global"):
        calls["deleted"].append((scope_value, scope))

    def fake_update_settings(updates):
        calls["updates"].append(updates)
        calls["settings"].update(updates)
        return True

    selection_helpers = _load_selection_helpers()

    namespace = {
        "keyvault_model_endpoint_save_helper": fake_save,
        "keyvault_model_endpoint_cleanup_helper": fake_cleanup,
        "keyvault_model_endpoint_delete_helper": fake_delete,
        "get_settings": lambda: calls["settings"],
        "update_settings": fake_update_settings,
        "resolve_default_model_selection": selection_helpers[
            "resolve_default_model_selection"
        ],
    }
    exec(compile(ast.Module(body=[target], type_ignores=[]), str(ROUTES_FILE), "exec"), namespace)
    return namespace["_persist_global_model_endpoints"], calls


def test_persistence_runs_all_three_key_vault_passes():
    """A removed endpoint's secret must be deleted, not merely left out of the save."""
    print("Testing Key Vault pass ordering...")

    persist, calls = _load_persistence_helper()

    existing = [
        {"id": "ep-keep", "name": "Keep", "enabled": True, "models": []},
        {"id": "ep-drop", "name": "Drop", "enabled": True, "models": []},
    ]
    normalized = [{"id": "ep-keep", "name": "Keep", "enabled": True, "models": []}]

    saved = persist(normalized, existing)

    assert [entry[0] for entry in calls["saved"]] == ["ep-keep"], calls["saved"]
    # Global scope keys its secrets by endpoint id, matching the classic form.
    assert calls["saved"][0][1] == "global", calls["saved"]
    assert calls["saved"][0][2] == "ep-keep", calls["saved"]
    assert calls["cleaned"] == [("ep-keep", "global")], calls["cleaned"]
    assert calls["deleted"] == [("ep-drop", "global")], calls["deleted"]

    assert calls["updates"], "settings were never written"
    assert calls["updates"][0]["model_endpoints"] == saved

    print("  Save, cleanup and delete each ran over the right endpoints.")
    return True


def test_deleting_the_default_endpoint_clears_the_default():
    """Otherwise chat falls back to another model without saying it has."""
    print("Testing default clearing on delete...")

    persist, calls = _load_persistence_helper()
    calls["settings"]["default_model_selection"] = {
        "endpoint_id": "ep-gone",
        "model_id": "gpt-4o",
        "provider": "aoai",
    }

    existing = [
        {
            "id": "ep-gone",
            "enabled": True,
            "provider": "aoai",
            "models": [{"id": "gpt-4o", "enabled": True}],
        }
    ]
    persist([], existing)

    written = calls["updates"][0]
    assert "default_model_selection" in written, written
    assert written["default_model_selection"] == {
        "endpoint_id": "",
        "model_id": "",
        "provider": "",
    }, written

    print("  A dangling default is cleared when its endpoint goes.")
    return True


def test_an_unaffected_default_is_left_alone():
    """Rewriting an unchanged value on every save would churn the settings document."""
    print("Testing that a valid default is not rewritten...")

    persist, calls = _load_persistence_helper()
    calls["settings"]["default_model_selection"] = {
        "endpoint_id": "ep-1",
        "model_id": "gpt-4o",
        "provider": "aoai",
    }

    endpoints = [
        {
            "id": "ep-1",
            "enabled": True,
            "provider": "aoai",
            "models": [{"id": "gpt-4o", "enabled": True}],
        }
    ]
    persist(endpoints, endpoints)

    written = calls["updates"][0]
    assert "default_model_selection" not in written, written

    print("  An unchanged default is not rewritten.")
    return True


def test_classic_form_shares_the_selection_rule():
    """Two copies of this rule would drift, which is what the shared helper prevents."""
    print("Testing classic form uses the shared helper...")

    classic = (APP_DIR / "route_frontend_admin_settings.py").read_text(encoding="utf-8")
    assert "resolve_default_model_selection(" in classic, (
        "The classic admin form should resolve the default model selection through "
        "the shared helper so the two interfaces cannot disagree"
    )

    print("  Classic form resolves through the shared helper.")
    return True


if __name__ == "__main__":
    tests = [
        test_crud_routes_exist_and_are_admin_gated,
        test_endpoint_reads_are_sanitized,
        test_writes_go_through_the_key_vault_persistence_helper,
        test_default_model_selection_is_revalidated,
        test_persistence_revalidates_the_default_selection,
        test_persistence_runs_all_three_key_vault_passes,
        test_deleting_the_default_endpoint_clears_the_default,
        test_an_unaffected_default_is_left_alone,
        test_classic_form_shares_the_selection_rule,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAIL: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
