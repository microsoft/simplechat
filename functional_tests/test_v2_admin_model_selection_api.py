#!/usr/bin/env python3
# test_v2_admin_model_selection_api.py
"""
Functional test for the V2 admin embedding and image deployment selection API.
Version: 0.261.082
Implemented in: 0.261.082

``embedding_model`` and ``image_gen_model`` are stored as
``{"selected": [...], "all": [...]}`` -- the deployments discovery last returned, plus
the one in use. That is a dict, and ``normalize_admin_settings_updates`` coerces declared
values by scalar type and passes undeclared keys through untouched, so neither route the
settings PATCH offers is safe for them: one would mangle the shape, the other would store
whatever arrived.

They are therefore declared as ``component`` fields, which puts them in
``NON_PATCHABLE_TYPES`` and makes the PATCH refuse them, and given their own routes. The
rule those routes exist to enforce is that the selection names a deployment that is
actually in the catalog. Accepting one that is not produces an admin page that looks
correctly configured while every embedding or image call fails with a deployment-not-found
error, which reads like an outage rather than a settings mistake.

Discovery is deliberately *not* reimplemented here: ``/api/models/embedding`` and
``/api/models/image`` already exist, are already admin-gated, and are what the classic
page calls.
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
MODELS_ROUTES_FILE = APP_DIR / "route_backend_models.py"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

EXPECTED_ROUTES = {
    ("/api/v2/admin/model-selection/<kind>", "GET"): "v2_admin_get_model_selection",
    ("/api/v2/admin/model-selection/<kind>", "PUT"): "v2_admin_set_model_selection",
}

REQUIRED_DECORATORS = {"swagger_route", "login_required", "admin_required"}

# The catalogs, the section that owns each one, and the component that renders it.
EXPECTED_CATALOGS = {
    "embedding_model": ("embeddings-config", "embedding-model-selection"),
    "image_gen_model": ("image-config", "image-model-selection"),
}

# The discovery routes reused rather than reimplemented, and the guard each must keep.
REUSED_DISCOVERY_ROUTES = {
    "/api/models/embedding": "get_embedding_models",
    "/api/models/image": "get_image_models",
}

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


def _load_catalog_normalizer():
    """Exec ``normalize_model_catalog`` out of ``route_backend_v2.py``.

    The route module builds Azure clients transitively and cannot be imported in a test.
    The normalizer is ordinary Python over lists and dicts, so lifting its source runs
    the real rule rather than a copy of it.
    """
    tree = _parse(ROUTES_FILE)
    wanted = {"normalize_model_catalog", "_normalize_model_deployment"}

    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    found = {node.name for node in selected}
    missing = wanted - found
    assert not missing, (
        "These catalog helpers were not found in route_backend_v2.py, so this test "
        f"cannot exercise the real rule: {', '.join(sorted(missing))}"
    )

    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROUTES_FILE), "exec"), namespace)
    return namespace["normalize_model_catalog"]


normalize_model_catalog = _load_catalog_normalizer()


def deployments():
    return [
        {"deploymentName": "text-embedding-3-large", "modelName": "text-embedding-3-large"},
        {"deploymentName": "ada-002", "modelName": "text-embedding-ada-002"},
    ]


def test_routes_exist_and_are_admin_gated():
    """These routes read and write stored endpoint configuration."""
    print("Testing model selection route declarations...")

    assert_app_version_at_least("0.261.082")

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

    print("  Both routes are declared and admin-gated.")
    return True


def test_the_read_route_does_not_write():
    """Opening the admin page must not mutate stored configuration."""
    print("\nTesting that the read route is read-only...")

    functions = _find_functions(_parse(ROUTES_FILE))
    source = ast.dump(functions["v2_admin_get_model_selection"])

    assert "update_settings" not in source, (
        "v2_admin_get_model_selection writes settings. A read that also writes turns "
        "opening the page into a change, and hides what the stored value was."
    )

    # And it must not call Azure. The list is a cache precisely so that opening Admin
    # Settings does not depend on Resource Manager being reachable.
    for forbidden in ("build_cognitive_services_client", "deployments"):
        assert forbidden not in source, (
            f"v2_admin_get_model_selection references {forbidden}; discovery belongs on "
            "the existing /api/models routes, run on demand."
        )

    print("  The read returns stored state and nothing else.")
    return True


def test_discovery_is_reused_rather_than_reimplemented():
    """Two answers to 'what is deployed here' would eventually disagree."""
    print("\nTesting discovery reuse...")

    functions = _find_functions(_parse(MODELS_ROUTES_FILE))

    declared = {}
    for name, node in functions.items():
        for path, method in _route_declarations(node):
            if method == "GET":
                declared[path] = name

    for path, expected_name in REUSED_DISCOVERY_ROUTES.items():
        assert declared.get(path) == expected_name, (
            f"{path} is no longer served by {expected_name}; the V2 picker calls it "
            f"directly, so a rename breaks the Fetch button. Found: {declared.get(path)}"
        )
        decorators = set(_decorator_names(functions[expected_name]))
        assert "admin_required" in decorators, (
            f"{expected_name} exposes deployment names and must stay admin-gated"
        )

    # The V2 library must point at exactly those paths.
    library = (V2_SRC / "lib" / "modelSelection.ts").read_text(encoding="utf-8")
    for path in REUSED_DISCOVERY_ROUTES:
        assert f"'{path}'" in library, f"modelSelection.ts does not call {path}"

    print("  Both discovery routes are reused and admin-gated.")
    return True


def test_catalogs_are_components_so_the_patch_refuses_them():
    """A dict through the settings PATCH would be stored unexamined."""
    print("\nTesting the catalog field declarations...")

    declared_sections = {}
    for section_id, field in fields_module.iter_fields():
        key = field.get("key")
        if key:
            declared_sections[key] = (section_id, field)

    problems = []
    for key, (expected_section, expected_component) in EXPECTED_CATALOGS.items():
        entry = declared_sections.get(key)
        if entry is None:
            problems.append(f"{key}: not declared at all")
            continue
        section_id, field = entry
        if section_id != expected_section:
            problems.append(
                f"{key}: declared under {section_id!r}, expected {expected_section!r}"
            )
        if field.get("type") != "component":
            problems.append(f"{key}: declared as {field.get('type')!r}, expected 'component'")
        if field.get("component") != expected_component:
            problems.append(
                f"{key}: renders {field.get('component')!r}, expected {expected_component!r}"
            )

    assert not problems, (
        "These catalogs are not declared as components, so the settings PATCH would "
        "accept them:\n  " + "\n  ".join(problems)
    )

    assert "component" in fields_module.NON_PATCHABLE_TYPES, (
        "Components are no longer refused by the PATCH, so declaring these as "
        "components no longer protects them."
    )

    # And the refusal has to be real, not merely implied by the type list.
    _normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
        {"embedding_model": {"selected": [], "all": []}}, {}
    )
    assert "embedding_model" in errors, (
        f"The settings PATCH accepted a catalog dict: {errors}"
    )

    print("  Both catalogs are components and the PATCH refuses them.")
    return True


def test_the_sections_exist_in_navigation():
    """A schema section with no navigation entry never renders."""
    print("\nTesting the owning navigation sections...")

    section_ids = {
        section["id"]
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
    }

    for _key, (section_id, _component) in EXPECTED_CATALOGS.items():
        assert section_id in section_ids, (
            f"{section_id} is not a navigation section, so nothing declared in it renders"
        )

    print("  Both sections exist in ADMIN_NAV.")
    return True


def test_a_selection_must_be_in_the_catalog():
    """A deployment that is not deployed fails at call time, not at save time."""
    print("\nTesting selection validation...")

    catalog, error = normalize_model_catalog(
        {"models": deployments(), "selected": {"deploymentName": "gone"}}, []
    )
    assert catalog is None, catalog
    assert "gone" in error, error

    catalog, error = normalize_model_catalog(
        {"models": deployments(), "selected": {"deploymentName": "ada-002"}}, []
    )
    assert error is None, error
    assert catalog["selected"] == [
        {"deploymentName": "ada-002", "modelName": "text-embedding-ada-002"}
    ], catalog
    # Single-select: the rest of the application reads selected[0] and nothing else.
    assert len(catalog["selected"]) == 1, catalog

    print("  A selection outside the catalog is refused.")
    return True


def test_an_omitted_list_keeps_the_stored_one():
    """Choosing from an already-loaded list must not erase the list."""
    print("\nTesting the omitted-list case...")

    stored = deployments()
    catalog, error = normalize_model_catalog(
        {"selected": {"deploymentName": "ada-002"}}, stored
    )

    assert error is None, error
    assert catalog["all"] == stored, catalog
    assert catalog["selected"][0]["deploymentName"] == "ada-002", catalog

    print("  An omitted list falls back to what is stored.")
    return True


def test_clearing_and_malformed_input():
    """Null clears; anything unusable is refused rather than half-stored."""
    print("\nTesting clears and malformed payloads...")

    catalog, error = normalize_model_catalog(
        {"models": deployments(), "selected": None}, []
    )
    assert error is None, error
    assert catalog["selected"] == [], catalog
    assert len(catalog["all"]) == 2, catalog

    for payload, why in (
        ("not-a-dict", "a non-object payload"),
        ({"models": "not-a-list"}, "a non-list model list"),
        ({"models": ["not-a-dict"]}, "a non-object model"),
        ({"models": [{"modelName": "no-deployment"}]}, "a model with no deployment name"),
        ({"models": [], "selected": "not-a-dict"}, "a non-object selection"),
        ({"models": [], "selected": {"modelName": "x"}}, "a selection with no deployment"),
    ):
        catalog, error = normalize_model_catalog(payload, [])
        assert catalog is None and error, f"{why} was accepted"

    # A duplicated deployment name is collapsed: the name is the whole identity, so two
    # rows carrying it would be two ways to choose one thing.
    catalog, error = normalize_model_catalog(
        {
            "models": [
                {"deploymentName": "ada-002"},
                {"deploymentName": "ada-002", "modelName": "again"},
            ]
        },
        [],
    )
    assert error is None, error
    assert len(catalog["all"]) == 1, catalog

    print("  Clears work and malformed payloads are refused.")
    return True


if __name__ == "__main__":
    tests = [
        test_routes_exist_and_are_admin_gated,
        test_the_read_route_does_not_write,
        test_discovery_is_reused_rather_than_reimplemented,
        test_catalogs_are_components_so_the_patch_refuses_them,
        test_the_sections_exist_in_navigation,
        test_a_selection_must_be_in_the_catalog,
        test_an_omitted_list_keeps_the_stored_one,
        test_clearing_and_malformed_input,
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
