#!/usr/bin/env python3
# test_v2_global_identities.py
"""
Functional test for Global Identities in V2 Admin Settings.
Version: 0.261.445
Implemented in: 0.261.445

The Global Identities section used to be a read-only list that sent an administrator to the classic
admin page to add, edit or delete one. It is now the same identities workbench the workspaces use,
bound to the admin routes that name the global scope. This test runs the browser-side checks in
``test_v2_global_identities_logic.ts`` (URLs, bodies, refusals, scope validation, the gates, and that
the personal, group and public scopes did not change), then pins what those checks cannot see:
that the adapter names routes the server declares, that every one of them is administrator-only,
that the editor offers the authentication methods and capabilities the classic pane offers, that the
section composes the workbench and no longer says "classic only", and that the schema and the page
still draw it.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import APP_ROOT, import_app_module
from test_support.versioning import assert_app_version_at_least

REPO_ROOT = APP_ROOT.parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
LOGIC_TS = Path(__file__).resolve().parent / "test_v2_global_identities_logic.ts"
GLOBAL_BASE = "/api/admin/workspace-identities/global/identities"

fields_module = import_app_module("admin_settings_fields")


def read(path):
    return (V2_SRC / path).read_text(encoding="utf-8")


def toolchain_present():
    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return False
    return True


def run_bundled(entry, name):
    """Bundle a TypeScript entry with esbuild beside the real node_modules, and run it under node."""
    bundle = V2_DIR / "node_modules" / f".cache-{name}.mjs"
    try:
        subprocess.run(
            [
                "npx", "esbuild", str(entry), "--bundle", "--platform=node", "--format=esm",
                "--packages=external", "--define:import.meta.env={}", f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        return subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()


def declared_global_routes():
    """Every global identity route the server declares: (method, rule) -> its decorator names."""
    source = (APP_ROOT / "route_backend_workspace_identities.py").read_text(encoding="utf-8")
    routes = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
        for decorator in decorators:
            match = re.fullmatch(r"bp\.route\('([^']+)', methods=\['([A-Z]+)'\]\)", decorator)
            if match and match.group(1).startswith(GLOBAL_BASE):
                routes[(match.group(2), match.group(1))] = decorators
    return routes


def test_the_typescript_logic_checks_pass():
    """URLs, bodies, refusals, scope validation, the gates, and the other scopes unchanged."""
    print("Testing the global identities logic (TypeScript)...")

    assert_app_version_at_least("0.261.445")
    if not toolchain_present():
        return
    assert LOGIC_TS.exists(), "The TypeScript logic checks are missing"

    result = run_bundled(LOGIC_TS, "global-identities-check")
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 12, f"Expected at least 12 checks, {passed} ran:\n{result.stdout}"
    assert "FAIL" not in result.stdout + result.stderr
    print(f"  ok  {passed} TypeScript logic checks passed")


def test_the_adapter_calls_routes_the_server_declares_and_every_one_is_administrator_only():
    """The surface is the gate, so the server's admin check has to be on every route it calls."""
    print("\nTesting the global adapter against the declared routes...")

    routes = declared_global_routes()
    expected = {
        ("GET", GLOBAL_BASE), ("POST", GLOBAL_BASE),
        ("PATCH", f"{GLOBAL_BASE}/<identity_id>"), ("DELETE", f"{GLOBAL_BASE}/<identity_id>"),
    }
    assert set(routes) == expected, f"The global identity routes changed: {sorted(routes)}"
    for key, decorators in routes.items():
        assert "swagger_route(security=get_auth_security())" in decorators, key
        assert "login_required" in decorators and "admin_required" in decorators, (
            f"{key} is not administrator-only, but the V2 section offers every operation on that basis"
        )
        assert "user_required" not in decorators, key

    workbench = read("lib/identityWorkbench.ts")
    assert f"const GLOBAL_IDENTITIES_URL = '{GLOBAL_BASE}';" in workbench
    assert "`${GLOBAL_IDENTITIES_URL}/${encodeURIComponent(requireWorkspaceId(identityId))}`" in workbench
    print("  The four routes exist, each behind login and admin checks.")


def test_the_editor_offers_what_the_classic_pane_offers():
    """The classic pane is the behaviour reference: same capabilities, same default, same methods."""
    print("\nTesting the editor options against the classic Global Identities pane...")

    pane = (APP_ROOT / "templates" / "admin" / "_panes" / "workspace-identities.html").read_text(encoding="utf-8")

    def option(name):
        match = re.search(rf'data-{name}="([^"]*)"', pane)
        assert match, f"The classic pane no longer sets data-{name}"
        return [value for value in match.group(1).split(",") if value]

    assert re.search(r'data-identity-api-base="/api/admin/workspace-identities/global"', pane)
    capabilities = option("capability-options")
    classic_methods = option("auth-type-options")
    assert option("default-capability") == ["action"]

    fields = read("lib/identityFields.ts")
    group_capabilities = re.search(r"GROUP_IDENTITY_CAPABILITIES = \[([^\]]*)\]", fields)
    assert group_capabilities
    assert re.findall(r"'([a-z_]+)'", group_capabilities.group(1)) == capabilities
    assert "capabilities: ['action']" in fields, "a new draft starts on the classic default capability"

    workbench = read("lib/identityWorkbench.ts")
    methods = re.search(r"GLOBAL_IDENTITY_AUTH_TYPES: readonly string\[\] = \[([^\]]*)\]", workbench)
    assert methods
    assert re.findall(r"'([a-z_]+)'", methods.group(1)) == classic_methods, (
        "The global editor must offer the authentication methods the classic pane lists, in its order"
    )
    assert "anonymous" not in classic_methods
    print(f"  capabilities {capabilities}, methods {classic_methods}")


def test_the_section_composes_the_workbench_and_no_longer_says_classic_only():
    """The read-only list, its paragraph and its link to the classic tab are gone."""
    print("\nTesting the Global Identities component...")

    component = read("components/admin/GlobalIdentitiesList.tsx")
    assert "IdentityWorkbenchSection" in component and "GLOBAL_IDENTITY_WORKBENCH" in component
    assert 'presentation="admin"' in component and "leadText={help}" in component
    for stale in (
        "Adding, editing and deleting an identity is done on",
        "classic admin settings page",
        "safeClassicAdminTabHref",
        "large amount of work",
        "Read-only",
        "api.get<IdentitiesResponse>",
    ):
        assert stale not in component, f"GlobalIdentitiesList still carries: {stale}"

    page = read("pages/AdminSettingsPage.tsx")
    assert "case 'global-identities-list':" in page
    assert "<GlobalIdentitiesList key={key} help={field.help} />" in page

    schema = fields_module.get_admin_settings_fields()["workspace-identities-section"]
    assert [field.get("component") for field in schema] == ["global-identities-list"]
    assert schema[0]["help"], "The card's help text is what the section shows beside New identity"
    print("  The component composes the workbench; the page and the schema still draw it.")


def test_the_workspace_presentation_is_the_default():
    """The workspaces keep their heading and wording unless a host asks for the administrator's."""
    print("\nTesting that the identities section defaults to the workspace presentation...")

    section = read("components/identities/IdentityWorkbenchSection.tsx")
    assert "presentation = 'workspace'" in section
    assert "authTypeOptions={adapter.authTypes}" in section
    for binding in ("pages/workspace/IdentitiesSection.tsx", "pages/workspace/GroupIdentitiesSection.tsx"):
        assert "presentation" not in read(binding), f"{binding} must keep the default presentation"
    print("  Personal, group and public bind the section without a presentation.")


if __name__ == "__main__":
    tests = [
        test_the_typescript_logic_checks_pass,
        test_the_adapter_calls_routes_the_server_declares_and_every_one_is_administrator_only,
        test_the_editor_offers_what_the_classic_pane_offers,
        test_the_section_composes_the_workbench_and_no_longer_says_classic_only,
        test_the_workspace_presentation_is_the_default,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - report every failure, then exit non-zero
            failures += 1
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
    print(f"\nResults: {len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
