# test_v2_legacy_document_upgrade.py
"""
Functional test for the V2 "update older documents" notice in the Documents explorer.
Version: 0.261.448
Implemented in: 0.261.448

Classic offers an "Update older documents" alert for personal and group documents. V2 detected
none of it: personal had no notice, and group and public sent the user to a "Classic tools"
button. The explorer now reads the flag every document list sets and offers the update itself.

These checks pin that the client and the server agree, because a drift between them shows only as
an update that never appears or never works:

- the three list producers write the one flag the explorer reads, and the V2 client does not read
  the classic public list's differently named one;
- the client calls the upgrade route each scope registers, with the route names taken from the
  server's own route source, and a group or public workspace never uses the classic route that
  acts on the saved active workspace;
- the explicit routes authorize as a metadata edit, and the client offers the update to exactly
  the roles and workspace statuses the server's own management hint lists that operation for;
- the "Classic tools" buttons and the props that fed them are gone;
- the TypeScript logic (flag, routes, receipts, the notice) passes against a stubbed fetch.
"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_legacy_document_upgrade_logic.ts"
FEATURE_DOC = REPO_ROOT / "docs" / "explanation" / "features" / "V2_LEGACY_DOCUMENT_UPGRADE.md"

PERSONAL_ROUTE_FILE = APP_ROOT / "route_backend_documents.py"
GROUP_ROUTE_FILE = APP_ROOT / "route_backend_group_documents.py"
PUBLIC_ROUTE_FILE = APP_ROOT / "route_backend_public_document_management.py"
GROUP_LIST_FILE = APP_ROOT / "functions_group_document_reads.py"
PUBLIC_LIST_FILE = APP_ROOT / "functions_public_document_reads.py"
CLASSIC_PUBLIC_LIST_FILE = APP_ROOT / "route_backend_public_documents.py"

UPGRADE_ROUTES = {
    "personal": (PERSONAL_ROUTE_FILE, "api_upgrade_legacy_user_documents"),
    "group": (GROUP_ROUTE_FILE, "api_scoped_group_documents_upgrade_legacy"),
    "public": (PUBLIC_ROUTE_FILE, "api_scoped_public_documents_upgrade_legacy"),
}
LIST_FLAG = "needs_legacy_update_check"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _function(path, name):
    tree = ast.parse(_read(path))
    function = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name), None,
    )
    assert function is not None, f"{path.name} no longer defines {name}"
    return function


def _decorators(function):
    names = []
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.append(target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "?"))
    return names


def _route_rule(path, name):
    """The (rule, methods) the route function is registered with."""
    function = _function(path, name)
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call) and getattr(decorator.func, "attr", "") == "route":
            rule = ast.literal_eval(decorator.args[0])
            methods = next((ast.literal_eval(keyword.value) for keyword in decorator.keywords if keyword.arg == "methods"), ["GET"])
            return rule, methods
    raise AssertionError(f"{name} is not registered with a route decorator")


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.448")


def test_every_list_producer_writes_the_flag_the_explorer_reads():
    """Personal, group and public lists all carry one boolean, and the V2 client reads that one."""
    for path in (PERSONAL_ROUTE_FILE, GROUP_LIST_FILE, PUBLIC_LIST_FILE):
        assert f'"{LIST_FLAG}"' in _read(path), f"{path.name} no longer writes {LIST_FLAG}"

    types = _read(V2_SRC / "lib" / "types.ts")
    assert f"{LIST_FLAG}?: boolean" in types, "DocumentListResponse no longer declares the legacy flag"
    upgrade = _read(V2_SRC / "lib" / "documentLegacyUpgrade.ts")
    assert f"response?.{LIST_FLAG} === true" in upgrade, "The notice must follow the server's boolean"

    # The classic public list names its flag differently and has no notice of its own. The V2 list
    # does not use that route, so a reader of the wrong name would show the notice for nobody.
    classic_public = _read(CLASSIC_PUBLIC_LIST_FILE)
    assert re.search(r"'needs_legacy_update'\s*:", classic_public), "The classic public flag was renamed; re-check the V2 client"
    assert not re.search(r"needs_legacy_update(?!_check)", upgrade), "The V2 client must not read the classic public flag"
    for reader in ("createGroupDocumentReader", "createPublicDocumentReader"):
        assert reader in _read(V2_SRC / "lib" / "documentReadAdapter.ts")
    print("  ok  the three lists write the flag the explorer reads")


def test_the_client_calls_the_routes_the_server_registers():
    """Route names come from the server's route source, so a renamed route fails here."""
    expected = {}
    for scope, (path, name) in UPGRADE_ROUTES.items():
        rule, methods = _route_rule(path, name)
        assert methods == ["POST"], f"{name} must be a POST, not {methods}"
        expected[scope] = re.sub(r"<[^>]+>", lambda match: {"<group_id>": "group-a", "<workspace_id>": "public-a"}[match.group(0)], rule)
    assert expected == {
        "personal": "/api/documents/upgrade_legacy",
        "group": "/api/groups/group-a/documents/upgrade_legacy",
        "public": "/api/public-workspaces/public-a/documents/upgrade_legacy",
    }, expected

    client = _read(V2_SRC / "lib" / "documentLegacyUpgrade.ts")
    for fragment in ("/api/groups/${encodeURIComponent(", "/api/public-workspaces/${encodeURIComponent(",
                     "/documents/upgrade_legacy", "'/api/documents/upgrade_legacy'"):
        assert fragment in client, f"documentLegacyUpgrade.ts no longer builds {fragment}"
    # A V2 workspace page never relies on the saved active workspace, which the classic routes use.
    for classic in ("/api/group_documents/upgrade_legacy", "/api/public_documents/upgrade_legacy",
                    "/external/public_documents/upgrade_legacy"):
        assert classic not in client and classic not in _read(V2_SRC / "lib" / "documentOperations.ts"), (
            f"The V2 client must not call the classic active-workspace route {classic}"
        )
    print("  ok  the client builds the routes the server registers")


def test_the_explicit_routes_never_use_the_saved_active_workspace():
    """Both name their workspace in the path and authorize as a metadata edit."""
    for scope, expected_enabled in (("group", "enable_group_workspaces"), ("public", "enable_public_workspaces")):
        path, name = UPGRADE_ROUTES[scope]
        function = _function(path, name)
        decorators = _decorators(function)
        assert decorators[:4] == ["route", "swagger_route", "login_required", "user_required"], decorators
        assert "enabled_required" in decorators
        flag = next(
            ast.literal_eval(decorator.args[0]) for decorator in function.decorator_list
            if isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "") == "enabled_required"
        )
        assert flag == expected_enabled, f"{name} is gated on {flag}, not {expected_enabled}"
        source = ast.get_source_segment(_read(path), function)
        assert '"edit_metadata"' in source, f"{name} must authorize as a metadata edit"
        for forbidden in ("require_active_group", "require_active_public_workspace", "get_user_settings",
                          "activeGroupOid", "activePublicWorkspaceOid", "request.args.get", "request.get_json"):
            assert forbidden not in source, f"{name} must take its workspace from the path, not {forbidden}"
        assert "request.get_data()" in source, f"{name} must refuse a request body"
    print("  ok  the explicit routes take their workspace from the path and authorize as a metadata edit")


def test_the_update_is_offered_to_exactly_the_viewers_the_server_lets_edit_metadata():
    """The client gates on `edit_metadata` in the management hint; derive who has it from the policy."""
    client = _read(V2_SRC / "lib" / "documentLegacyUpgrade.ts")
    assert "LEGACY_UPGRADE_OPERATION: DocumentOperation = 'edit_metadata'" in client

    group_policy = import_app_module("functions_group_document_policy")
    public_policy = import_app_module("functions_public_document_policy")
    cases = (
        (group_policy.group_document_management_operations, {"enable_group_workspaces": True}, group_policy.GROUP_DOCUMENT_MANAGER_ROLES),
        (public_policy.public_document_management_operations, {"enable_public_workspaces": True}, public_policy.PUBLIC_DOCUMENT_MANAGER_ROLES),
    )
    for operations_for, settings, manager_roles in cases:
        for role in ("Owner", "Admin", "DocumentManager", "User", None):
            for status in ("active", "locked", "upload_disabled", "inactive", "unknown"):
                offered = "edit_metadata" in operations_for({"status": status}, role, settings, download_enabled=True)
                assert offered == (role in manager_roles and status == "active"), (
                    f"{operations_for.__name__}: role {role!r} in a {status} workspace offers edit_metadata={offered}"
                )
    print("  ok  only a manager of an active workspace is offered the update")


def test_the_classic_tools_buttons_are_gone():
    """Group and public Documents no longer hand the user to classic for this job."""
    section = _read(V2_SRC / "pages" / "workspace" / "DocumentsSection.tsx")
    for stale in ("onOpenClassic", "Classic tools", "classic tools", "ArrowUpRight"):
        assert stale not in section, f"DocumentsSection.tsx still carries {stale!r}"
    for page, element in (("GroupWorkspacePage.tsx", "GroupDocumentsSection"), ("PublicWorkspacePage.tsx", "PublicDocumentsSection")):
        source = _read(V2_SRC / "pages" / page)
        start = source.index(f"<{element}")
        usage = source[start:source.index("/>", start)]
        assert "onOpenClassic" not in usage, f"{page} still passes onOpenClassic to {element}"
        assert "Open classic tools" not in source
    explorer = _read(V2_SRC / "components" / "documents" / "DocumentExplorer.tsx")
    for wired in ("legacyUpdateNeeded(response)", "LegacyUpgradeBanner", "adapter.upgradeLegacy()",
                  "operations.canUpgradeLegacy", "refreshAll()"):
        assert wired in explorer, f"The explorer no longer wires {wired}"
    print("  ok  the Classic tools buttons are gone and the explorer owns the update")


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("\nTesting the legacy upgrade logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return

    assert LOGIC_CHECK_TS.exists(), "The TypeScript legacy upgrade checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where node can
    # resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-legacy-document-upgrade-check.mjs"
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
            shell=(sys.platform == "win32"), env={**os.environ},
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript legacy upgrade checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 19 and "FAIL" not in result.stdout, f"Only {passed} legacy upgrade checks ran; the runner likely broke."
    print(f"  ok  {passed} TypeScript legacy upgrade checks passed")


def test_the_feature_is_documented():
    doc = _read(FEATURE_DOC)
    assert "0.261.448" in doc and "upgrade_legacy" in doc


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_every_list_producer_writes_the_flag_the_explorer_reads,
        test_the_client_calls_the_routes_the_server_registers,
        test_the_explicit_routes_never_use_the_saved_active_workspace,
        test_the_update_is_offered_to_exactly_the_viewers_the_server_lets_edit_metadata,
        test_the_classic_tools_buttons_are_gone,
        test_the_typescript_logic_checks_pass,
        test_the_feature_is_documented,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures += 1
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
    print(f"\nResults: {len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
