#!/usr/bin/env python3
# test_v2_admin_default_model_api.py
"""
Functional test for the V2 admin default chat model API.
Version: 0.261.061
Implemented in: 0.261.061

``default_model_selection`` is a reference -- a connection id plus a model id -- not a
value. That makes it the one Admin Settings key the JSON PATCH cannot carry safely:
``normalize_admin_settings_updates`` passes undeclared keys through unexamined, so a
dangling reference would be stored exactly as sent and only surface later, as chat
quietly answering from a different model.

These checks pin the replacement:

  1. The key is declared as a ``component``, which is what makes the settings PATCH
     refuse it instead of storing an unchecked dict.
  2. It has its own read and write routes, both admin-gated.
  3. The read does not write, so opening the page cannot mutate stored configuration.
  4. The write stores only what ``resolve_default_model_selection`` returned, and
     refuses a reference that does not resolve rather than storing or silently
     emptying it.
"""

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
ROUTES_FILE = APP_DIR / "route_backend_v2.py"
SETTINGS_FILE = APP_DIR / "functions_settings.py"

SECTION_ID = "gpt-config"

EXPECTED_ROUTES = {
    ("/api/v2/admin/default-model", "GET"): "v2_admin_get_default_model",
    ("/api/v2/admin/default-model", "PUT"): "v2_admin_set_default_model",
}

REQUIRED_DECORATORS = ("swagger_route", "login_required", "admin_required")

# The rules the ported decision procedure below depends on. If the route stops doing
# any of these, the assertions about its behaviour no longer describe it.
WRITE_ROUTE_INVARIANTS = (
    ("normalizes the requested selection", "normalize_default_model_selection(candidate)"),
    ("treats an empty reference as a deliberate clear", 'not requested["endpoint_id"] and not requested["model_id"]'),
    ("refuses a selection while chat is on the classic endpoint", "not clearing and not multi_endpoint_enabled"),
    ("resolves against the stored connections", "resolve_default_model_selection("),
    ("refuses a reference that did not resolve", 'not clearing and not resolved["endpoint_id"]'),
    ("checks that the settings write succeeded", "if not update_settings("),
)

fields_module = import_app_module("admin_settings_fields")


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
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _called_names(node):
    """Return the names of every function called inside a function body."""
    called = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            called.add(target.id)
        elif isinstance(target, ast.Attribute):
            called.add(target.attr)
    return called


def _load_selection_helpers():
    """Exec the pure default-model helpers out of ``functions_settings.py``.

    ``functions_settings`` builds Azure clients at import time and the shared test stub
    replaces the whole module, so the real functions cannot simply be imported. They are
    pure, so lifting their source keeps the test honest about which implementation it is
    checking. ``resolve_default_model_selection`` delegates to a generic resolver, so
    whichever helpers exist are collected rather than a fixed list being demanded.
    """
    tree = _parse(SETTINGS_FILE)
    wanted_functions = {
        "normalize_default_model_selection",
        "resolve_default_model_selection",
        "resolve_model_selection",
    }
    wanted_constants = {"EMPTY_DEFAULT_MODEL_SELECTION", "EMPTY_MODEL_SELECTION"}

    selected = []
    found_functions = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            selected.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & wanted_constants:
                selected.append(node)

    required = {"normalize_default_model_selection", "resolve_default_model_selection"}
    missing = required - found_functions
    assert not missing, (
        "These default-model helpers were not found in functions_settings.py, so this "
        f"test cannot exercise the real rule: {', '.join(sorted(missing))}"
    )

    namespace = {}
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(SETTINGS_FILE), "exec"),
        namespace,
    )
    return namespace


HELPERS = _load_selection_helpers()


def endpoints_fixture():
    """Two connections: one usable, one disabled, plus a disabled model."""
    return [
        {
            "id": "conn-live",
            "name": "Primary",
            "provider": "aoai",
            "enabled": True,
            "models": [
                {"id": "gpt-4o", "deploymentName": "gpt-4o", "enabled": True},
                {"id": "retired", "deploymentName": "retired", "enabled": False},
            ],
        },
        {
            "id": "conn-off",
            "name": "Secondary",
            "provider": "aifoundry",
            "enabled": False,
            "models": [{"id": "phi-4", "deploymentName": "phi-4", "enabled": True}],
        },
    ]


def decide(selection, endpoints, multi_endpoint_enabled):
    """Port of ``v2_admin_set_default_model``: what a write does with a selection.

    Returns ``(status, stored_or_error)``. ``stored`` is what reaches
    ``update_settings``; on a refusal nothing is stored at all.
    """
    requested = HELPERS["normalize_default_model_selection"](selection)
    clearing = not requested["endpoint_id"] and not requested["model_id"]

    if not clearing and not multi_endpoint_enabled:
        return 400, "classic-endpoint"

    resolved, reason = HELPERS["resolve_default_model_selection"](
        requested, endpoints, multi_endpoint_enabled=multi_endpoint_enabled
    )

    if not clearing and not resolved["endpoint_id"]:
        return 400, reason or "incomplete"

    return 200, resolved


def test_the_key_is_declared_so_the_settings_patch_refuses_it():
    """An undeclared key would be written into settings exactly as sent."""
    print("Testing that the settings PATCH refuses the default model...")

    assert_app_version_at_least("0.261.061")

    field = fields_module.get_field_definition("default_model_selection")
    assert field is not None, (
        "default_model_selection is not declared in admin_settings_fields.py. Without a "
        "declaration the settings PATCH passes it through unexamined, which is how a "
        "dangling reference gets stored."
    )
    assert field["type"] == "component", (
        f"default_model_selection is declared as {field['type']!r}. It must be "
        "'component' so NON_PATCHABLE_TYPES refuses it on the settings PATCH."
    )

    _normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"default_model_selection": {"endpoint_id": "anything", "model_id": "anything"}}
    )
    assert "default_model_selection" in errors, (
        "The settings PATCH accepted a raw default_model_selection. It must be rejected "
        f"so it can only be written through its own validating route. Got: {errors}"
    )

    print("  Declared as a component, and the settings PATCH refuses it.")
    return True


def test_the_chat_section_declares_its_components():
    """An undeclared section falls back to the enable_* scan and shows only switches."""
    print("\nTesting the Chat section declaration...")

    section_ids = {
        section["id"]
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
    }
    assert SECTION_ID in section_ids, (
        f"ADMIN_NAV no longer defines a {SECTION_ID!r} section, so the schema entry "
        "would render nowhere."
    )

    fields = fields_module.get_admin_settings_fields().get(SECTION_ID)
    assert fields, f"No fields are declared for the {SECTION_ID!r} section."

    components = [
        field.get("component") for field in fields if field.get("type") == "component"
    ]
    for expected in ("chat-mode-notice", "chat-default-model"):
        assert expected in components, (
            f"The {SECTION_ID!r} section does not declare the {expected!r} component. "
            f"Declared: {components}"
        )

    print(f"  {SECTION_ID} declares {len(fields)} field(s), including both components.")
    return True


def test_routes_exist_and_are_admin_gated():
    """A missing admin guard would let any signed-in user repoint chat's default."""
    print("\nTesting default model route declarations...")

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

        decorators = _decorator_names(functions[expected_name])
        for required in REQUIRED_DECORATORS:
            assert required in decorators, (
                f"{expected_name} is missing @{required}. Got: {decorators}"
            )

    print(f"  Both route(s) declared and carrying {len(REQUIRED_DECORATORS)} guard(s).")
    return True


def test_the_read_route_does_not_write():
    """Re-resolving on read is a report, not a repair; writing there hides the cause."""
    print("\nTesting that reading the default model does not store anything...")

    functions = _find_functions(_parse(ROUTES_FILE))
    reader = functions["v2_admin_get_default_model"]
    called = _called_names(reader)

    assert "update_settings" not in called, (
        "v2_admin_get_default_model calls update_settings. Loading the admin page would "
        "then rewrite stored configuration, which erases the evidence of why a default "
        "stopped resolving."
    )
    assert "resolve_default_model_selection" in called, (
        "v2_admin_get_default_model must resolve the stored selection before returning "
        "it, otherwise the UI shows a reference that no longer means anything."
    )

    print("  The read route resolves for display and writes nothing.")
    return True


def test_the_write_route_stores_only_the_resolved_value():
    """Storing the request's own dict is exactly the failure the route exists to stop."""
    print("\nTesting what the write route hands to update_settings...")

    functions = _find_functions(_parse(ROUTES_FILE))
    writer = functions["v2_admin_set_default_model"]

    resolved_names = set()
    for node in ast.walk(writer):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "resolve_default_model_selection"
        ):
            for target in node.targets:
                if isinstance(target, ast.Tuple):
                    resolved_names.update(
                        element.id
                        for element in target.elts
                        if isinstance(element, ast.Name)
                    )
                elif isinstance(target, ast.Name):
                    resolved_names.add(target.id)

    assert resolved_names, (
        "v2_admin_set_default_model does not bind the result of "
        "resolve_default_model_selection, so it cannot be storing a validated value."
    )

    stored_values = []
    for node in ast.walk(writer):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "update_settings"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            for key, value in zip(node.args[0].keys, node.args[0].values):
                if isinstance(key, ast.Constant) and key.value == "default_model_selection":
                    stored_values.append(value)

    assert stored_values, (
        "v2_admin_set_default_model never writes default_model_selection."
    )
    for value in stored_values:
        assert isinstance(value, ast.Name) and value.id in resolved_names, (
            "default_model_selection is written from something other than the resolved "
            f"selection: {ast.dump(value)[:120]}"
        )

    source = ast.get_source_segment(ROUTES_FILE.read_text(encoding="utf-8"), writer) or ""
    missing = [
        description
        for description, fragment in WRITE_ROUTE_INVARIANTS
        if fragment not in source
    ]
    assert not missing, (
        "The write route no longer works the way this test models it, so the behaviour "
        "assertions below are no longer meaningful. Re-read the route and update "
        "decide() to match:\n  " + "\n  ".join(missing)
    )

    print("  Only the resolved selection is stored, and every guard is present.")
    return True


def test_a_reference_that_does_not_resolve_is_refused():
    """Storing or silently emptying it both read as 'no default' afterwards."""
    print("\nTesting refusals for references that do not resolve...")

    endpoints = endpoints_fixture()

    cases = {
        "missing connection": {"endpoint_id": "conn-gone", "model_id": "gpt-4o"},
        "disabled connection": {"endpoint_id": "conn-off", "model_id": "phi-4"},
        "missing model": {"endpoint_id": "conn-live", "model_id": "gpt-9"},
        "disabled model": {"endpoint_id": "conn-live", "model_id": "retired"},
        "connection without a model": {"endpoint_id": "conn-live", "model_id": ""},
        "model without a connection": {"endpoint_id": "", "model_id": "gpt-4o"},
    }

    for description, selection in cases.items():
        status, detail = decide(selection, endpoints, multi_endpoint_enabled=True)
        assert status == 400, (
            f"A {description} was accepted and stored as {detail!r}. It must be refused "
            "so the administrator is told what went missing."
        )
        assert isinstance(detail, str) and detail, (
            f"A {description} was refused without a message."
        )

    print(f"  All {len(cases)} unresolvable reference(s) are refused.")
    return True


def test_a_resolvable_reference_is_stored_with_its_provider():
    """The provider is taken from the connection, not from whatever the browser sent."""
    print("\nTesting an accepted selection...")

    status, stored = decide(
        {"endpoint_id": "conn-live", "model_id": "gpt-4o", "provider": "WRONG"},
        endpoints_fixture(),
        multi_endpoint_enabled=True,
    )

    assert status == 200, f"A valid selection was refused: {stored!r}"
    assert stored == {
        "endpoint_id": "conn-live",
        "model_id": "gpt-4o",
        "provider": "aoai",
    }, stored

    print("  The stored selection carries the connection's own provider.")
    return True


def test_clearing_is_allowed_in_either_mode():
    """Choosing 'no default' must work even when nothing else could be chosen."""
    print("\nTesting that the default can be cleared...")

    for multi_endpoint_enabled in (True, False):
        status, stored = decide(
            {"endpoint_id": "", "model_id": "", "provider": ""},
            endpoints_fixture(),
            multi_endpoint_enabled=multi_endpoint_enabled,
        )
        assert status == 200, f"Clearing was refused: {stored!r}"
        assert stored == {"endpoint_id": "", "model_id": "", "provider": ""}, stored

    print("  Clearing succeeds whether or not connections are in force.")
    return True


def test_a_selection_is_refused_while_chat_uses_the_classic_endpoint():
    """Resolving would empty it silently, which looks identical to never setting it."""
    print("\nTesting a selection made while connections are off...")

    status, detail = decide(
        {"endpoint_id": "conn-live", "model_id": "gpt-4o"},
        endpoints_fixture(),
        multi_endpoint_enabled=False,
    )

    assert status == 400, (
        f"A default was accepted while chat runs on the classic single endpoint: {detail!r}. "
        "It would be cleared on the next write, so accepting it reports a save that did "
        "not survive."
    )

    print("  Refused, rather than accepted and quietly emptied.")
    return True


if __name__ == "__main__":
    tests = [
        test_the_key_is_declared_so_the_settings_patch_refuses_it,
        test_the_chat_section_declares_its_components,
        test_routes_exist_and_are_admin_gated,
        test_the_read_route_does_not_write,
        test_the_write_route_stores_only_the_resolved_value,
        test_a_reference_that_does_not_resolve_is_refused,
        test_a_resolvable_reference_is_stored_with_its_provider,
        test_clearing_is_allowed_in_either_mode,
        test_a_selection_is_refused_while_chat_uses_the_classic_endpoint,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
