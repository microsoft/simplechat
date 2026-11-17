#!/usr/bin/env python3
# test_v2_admin_parity.py
"""
Functional test for the V2 admin links, the Control Center refresh strip, Duplicate on global
agents and actions, and File Sync sources managed for another workspace.
Version: 0.261.445
Implemented in: 0.261.445

V2 Admin Settings and the V2 Control Center used to send an administrator to the classic page for
things V2 drew itself, and lacked four classic operations: refreshing the Control Center's stored
figures, duplicating a global agent or action, searching for a user, group or public workspace to
manage File Sync sources for, and a diagnostics switch that was still marked as classic-only after
V2 learned to draw what it reveals.

This test runs the browser-side checks in ``test_v2_admin_parity_logic.ts``, then pins what those
checks cannot see: that every section a link targets is one V2 draws (or is named as classic-only),
that the shipped Latest Features catalogue lands entirely inside V2 under the real resolver, that no
V2 code builds a classic admin address by hand, that the refresh strip calls the routes and reads
the fields the server provides under the capability the server checks, that Duplicate seeds the
draft keys the editors read, and that the File Sync target manager calls routes the server declares
for every kind of workspace, behind an administrator-only route for the options it needs.
"""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import APP_ROOT, import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least

REPO_ROOT = APP_ROOT.parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
LOGIC_TS = Path(__file__).resolve().parent / "test_v2_admin_parity_logic.ts"
SHORTCUT_PROBE_TS = Path(__file__).resolve().parent / "test_support" / "admin_shortcut_targets_probe.ts"

fields_module = import_app_module("admin_settings_fields")

# Navigation sections V2 has nothing to draw, with the reason. A link to one opens the classic tab.
CLASSIC_ONLY_SECTIONS = {
    "standard-citations-section": (
        "An informational card that states how citations behave. It has no setting, so V2 has "
        "nothing to draw and a link to it opens the classic Chat tab."
    ),
}


def read(path):
    return (V2_SRC / path).read_text(encoding="utf-8")


def toolchain_present():
    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return False
    return True


def run_bundled(entry, name, args=()):
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
            ["node", str(bundle), *[str(arg) for arg in args]],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()


def nav_section_ids():
    return {section["id"] for group in ADMIN_NAV for tab in group["tabs"] for section in tab["sections"]}


def test_the_typescript_logic_checks_pass():
    """Link routing, refresh wording, copies without credentials and the File Sync adapter."""
    print("Testing the admin parity logic (TypeScript)...")

    assert_app_version_at_least("0.261.445")
    if not toolchain_present():
        return
    assert LOGIC_TS.exists(), "The TypeScript logic checks are missing"

    result = run_bundled(LOGIC_TS, "admin-parity-check")
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 20, f"Expected at least 20 checks, {passed} ran:\n{result.stdout}"
    assert "FAIL" not in result.stdout + result.stderr
    print(f"  ok  {passed} TypeScript logic checks passed")


def test_the_dai_diagnostics_switch_is_no_longer_marked_classic_only():
    """V2 draws the diagnostics controls, so the switch's link stays inside V2."""
    print("\nTesting the Document Access Index diagnostics link...")

    schema = fields_module.get_admin_settings_fields()
    related = [
        field["related_section"]
        for fields in schema.values()
        for field in fields
        if field.get("key") == "enable_dai_debug" and field.get("related_section")
    ]
    assert related, "enable_dai_debug no longer links to the section its diagnostics appear in"
    assert related[0]["section_id"] == "document-access-index-section"
    assert "classic_only" not in related[0], (
        "enable_dai_debug is still marked classic-only, which sends the administrator to the "
        "classic page for diagnostics V2 draws"
    )

    # The claim behind removing the flag: the V2 panel draws the manual controls.
    panel = read("components/admin/DocumentAccessIndexPanel.tsx")
    for control in ("Run one backfill batch", "Reset checkpoint"):
        assert control in panel, f"The V2 DAI panel no longer draws {control!r}"
    print("  The switch links within V2 and the panel draws the diagnostics controls.")


def test_every_section_a_link_targets_is_drawn_by_v2_or_is_named_as_classic_only():
    """A link into a section V2 never draws would land on nothing, or on the classic page."""
    print("\nTesting the targets of related-section and prerequisite links...")

    schema = fields_module.get_admin_settings_fields()
    nav_ids = nav_section_ids()
    undrawn = {section_id for section_id in nav_ids if not schema.get(section_id)}
    assert undrawn == set(CLASSIC_ONLY_SECTIONS), (
        "The navigation sections V2 has no fields for changed. A new classic-only card needs a "
        f"documented reason here; a card V2 now draws must be removed.\n  undrawn: {sorted(undrawn)}"
        f"\n  documented: {sorted(CLASSIC_ONLY_SECTIONS)}"
    )

    targets = []
    for section_id, fields in schema.items():
        for field in fields:
            related = field.get("related_section")
            if related:
                targets.append((section_id, field.get("key"), related["section_id"]))
            requires = field.get("requires")
            for requirement in [requires] if isinstance(requires, dict) else (requires or []):
                if requirement.get("target_section"):
                    targets.append((section_id, field.get("key"), requirement["target_section"]))
    assert targets, "No link targets were found; the schema extraction likely broke."
    for section_id, key, target in targets:
        assert target in nav_ids, f"{section_id}.{key} links to {target}, which the navigation does not name"
    print(f"  {len(targets)} link(s) all lead to a navigation section; "
          f"{len(CLASSIC_ONLY_SECTIONS)} section(s) are classic-only by design.")


def test_the_latest_feature_aliases_name_sections_v2_draws():
    """An announcement that names a classic element lands on the V2 section that holds it."""
    print("\nTesting the Latest Features element aliases...")

    schema = fields_module.get_admin_settings_fields()
    source = read("lib/latestFeatures.ts")
    block = re.search(r"CLASSIC_ELEMENT_SECTIONS[^=]*=\s*\{(.*?)\};", source, re.S)
    assert block, "CLASSIC_ELEMENT_SECTIONS was not found in lib/latestFeatures.ts"
    aliases = dict(re.findall(r"'([^']+)':\s*'([^']+)'", block.group(1)))
    assert aliases, "The alias map is empty"
    nav_ids = nav_section_ids()
    for element, section_id in aliases.items():
        assert section_id in nav_ids and schema.get(section_id), (
            f"{element} is aliased to {section_id}, which V2 does not draw"
        )
    print(f"  {len(aliases)} classic element(s) are aliased to sections V2 draws.")


def test_every_latest_feature_admin_shortcut_lands_in_v2():
    """Run the real resolver over the shipped catalogue: nothing falls back to the classic page."""
    print("\nTesting where the shipped Latest Features admin shortcuts land...")

    if not toolchain_present():
        return
    schema = fields_module.get_admin_settings_fields()
    latest = import_app_module("functions_support_latest_features")
    payload = latest.build_latest_features_payload(
        {},
        resolve_endpoint_url=lambda endpoint: f"/x/{endpoint}",
        resolve_static_url=lambda path: f"/static/{path}",
        version="0.261.445",
    )
    actions = [
        {"admin_tab": action.get("admin_tab"), "admin_section": action.get("admin_section")}
        for catalogue in ("admin", "user")
        for group in payload[catalogue]
        for feature in group["features"]
        for action in feature["actions"]
        if action["kind"] == "admin"
    ]
    assert actions, "The catalogue has no admin shortcuts; the payload extraction likely broke."

    rendered = sorted(
        {section["id"] for group in ADMIN_NAV for tab in group["tabs"] for section in tab["sections"]
         if schema.get(section["id"])}
        | {tab["id"] for group in ADMIN_NAV for tab in group["tabs"] if tab.get("render")}
    )
    nav = json.loads(json.dumps(ADMIN_NAV))
    input_file = V2_DIR / "node_modules" / ".cache-admin-shortcuts.json"
    try:
        input_file.write_text(json.dumps({"nav": nav, "rendered": rendered, "actions": actions}), encoding="utf-8")
        result = run_bundled(SHORTCUT_PROBE_TS, "admin-shortcuts", [input_file])
    finally:
        if input_file.exists():
            input_file.unlink()
    assert result.returncode == 0, result.stderr
    targets = json.loads(result.stdout)
    assert len(targets) == len(actions)

    classic = [
        (action, target) for action, target in zip(actions, targets) if target.get("kind") != "section"
    ]
    assert not classic, (
        "These shortcuts would open the classic admin page although V2 draws the tab; add a V2 "
        f"section or an alias in lib/latestFeatures.ts:\n  {classic}"
    )
    print(f"  All {len(actions)} admin shortcut(s) land in a V2 section.")


def test_v2_source_builds_classic_admin_urls_in_one_place():
    """The classic page reads its fragment as a tab id, so hand-built addresses go wrong."""
    print("\nTesting that classic admin addresses are built by lib/adminOperations.ts only...")

    offenders = []
    for path in sorted(V2_SRC.rglob("*.ts*")):
        relative = path.relative_to(V2_SRC).as_posix()
        if relative in {"lib/adminOperations.ts"} or relative.startswith("lib/generated/"):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"/admin/settings#|/admin_settings", text):
            offenders.append(relative)
    assert not offenders, (
        "These files build a classic Admin Settings address themselves. Use safeClassicAdminTabHref "
        f"(lib/adminOperations.ts), which names the tab the classic page expects:\n  {offenders}"
    )
    helper = read("lib/adminOperations.ts")
    assert "`/admin/settings#${encodeURIComponent(tabId)}`" in helper
    # A classic address from V2 carries the escape pair, or the redirect to V2 would bounce it back.
    assert "return withClassicEscape(`/admin/settings#${encodeURIComponent(tabId)}`);" in helper
    assert "import { withClassicEscape } from './classicLinks';" in helper
    print("  Every classic admin address comes from safeClassicAdminTabHref, with the escape pair.")


def route_functions(source, route_rule):
    """The route functions whose decorators declare ``route_rule``."""
    tree = ast.parse(source)
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(f"'{route_rule}'" in ast.unparse(decorator) for decorator in node.decorator_list)
    ]


def test_the_control_center_refresh_strip_matches_the_routes_it_calls():
    """Same routes, same fields, same capability as the server."""
    print("\nTesting the Control Center refresh strip against the server contract...")

    source = (APP_ROOT / "route_backend_control_center.py").read_text(encoding="utf-8")
    client = read("lib/controlCenterRefresh.ts")
    expected = {
        "/api/admin/control-center/refresh": (
            "CONTROL_CENTER_REFRESH_ENDPOINT", "POST",
            {"refreshed_users", "failed_users", "refreshed_groups", "failed_groups", "success"},
        ),
        "/api/admin/control-center/refresh-status": (
            "CONTROL_CENTER_REFRESH_STATUS_ENDPOINT", "GET",
            {"last_refresh", "auto_refresh_enabled", "auto_refresh_time", "auto_refresh_timezone",
             "auto_refresh_next_run_utc"},
        ),
    }
    for rule, (constant, method, keys) in expected.items():
        assert f"{constant} = '{rule}'" in client, f"{constant} does not name {rule}"
        functions = route_functions(source, rule)
        assert len(functions) == 1, f"{rule} is not declared exactly once"
        function = functions[0]
        decorators = [ast.unparse(decorator) for decorator in function.decorator_list]
        assert any(f"methods=['{method}']" in decorator for decorator in decorators if "route(" in decorator)
        assert "control_center_required('admin')" in decorators, f"{rule} is not behind admin access"
        literals = {node.value for node in ast.walk(function) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        missing = keys - literals
        assert not missing, f"{rule} no longer provides {sorted(missing)}, which the strip reads"

    # The decorator's 'admin' level is the can_manage_users capability, which is what draws the strip.
    auth = (APP_ROOT / "functions_authentication.py").read_text(encoding="utf-8")
    assert re.search(r"elif access_level == 'admin':\s*permitted = capabilities\['can_manage_users'\]", auth)
    page = read("pages/ControlCenterPage.tsx")
    assert "Boolean(capabilities?.can_manage_users)" in page
    assert re.search(r"canRefresh \? <RefreshDataStrip", page)
    assert "SectionPlaceholder" not in page, "The unreachable placeholder branch came back"
    print("  The strip calls both routes, reads their fields and follows the admin capability.")


def test_duplicate_seeds_the_draft_keys_the_new_record_editors_read():
    """A copy reaches the editor only if it is stored under the key the editor looks up."""
    print("\nTesting that Duplicate seeds the editors' new-record draft keys...")

    agent_page = read("pages/workspace/AgentEditorPage.tsx")
    action_page = read("pages/workspace/ActionEditorPage.tsx")
    drafts = read("lib/workspaceEditorDrafts.ts")
    assert (
        "useWorkspaceEditorDraft<AgentConfiguration>('agents', `${scope}:${resourceId}`, newAgentDraft, adapter.draftScope)"
        in agent_page
    )
    assert (
        "useWorkspaceEditorDraft<ActionConfiguration>('actions', JSON.stringify([scope, resourceId, returnTo]), "
        "createActionDraft, adapter.draftScope)" in action_page
    )
    for page in (agent_page, action_page):
        assert "get('scope') === 'global' ? 'global' : 'personal'" in page
    seed = drafts[drafts.index("export function seedDuplicateEditorDraft"):]
    assert "'personal:new'" in seed and "JSON.stringify(['personal', 'new', null])" in seed

    # The lists open the plain /new route: no ?scope= and no returnTo, which the keys above assume.
    agents = read("components/admin/GlobalAgentsManager.tsx")
    actions = read("components/admin/GlobalActionsManager.tsx")
    assert "navigate(`${GLOBAL_AGENTS_BASE_PATH}/new`)" in agents
    assert "navigate(`${GLOBAL_ACTIONS_BASE_PATH}/new`)" in actions
    for manager, helper in ((agents, "duplicateAgentDraft"), (actions, "duplicateActionDraft")):
        assert helper in manager and "seedDuplicateEditorDraft" in manager and "fetchEditor(" in manager
    print("  Both lists seed the keys the agent and action editors read.")


def test_the_file_sync_target_manager_calls_routes_the_server_declares():
    """Every request the administrator adapter can send has a route, in all three scopes."""
    print("\nTesting the File Sync target manager against the administrator routes...")

    source = (APP_ROOT / "route_backend_file_sync.py").read_text(encoding="utf-8")
    declared = {
        (method.strip().strip("'\""), rule)
        for rule, methods in re.findall(r"@bp\.route\('([^']+)', methods=\[([^\]]+)\]\)", source)
        for method in methods.split(",")
    }

    def assert_declared(method, rule):
        assert (method, rule) in declared, f"{method} {rule} is not a File Sync route"

    for base in (
        "/api/admin/file-sync/personal/<target_user_id>",
        "/api/admin/file-sync/group/<group_id>",
        "/api/admin/file-sync/public/<public_workspace_id>",
    ):
        assert_declared("GET", f"{base}/sources")
        assert_declared("POST", f"{base}/sources")
        assert_declared("POST", f"{base}/sources/test-connection")
        assert_declared("PATCH", f"{base}/sources/<source_id>")
        assert_declared("DELETE", f"{base}/sources/<source_id>")
        assert_declared("POST", f"{base}/sources/<source_id>/test-connection")
        assert_declared("POST", f"{base}/sources/<source_id>/sync")
        assert_declared("GET", f"{base}/sources/<source_id>/runs")
    assert_declared("POST", "/api/admin/file-sync/<scope_type>/<scope_id>/sources/browse")
    assert_declared("POST", "/api/admin/file-sync/<scope_type>/<scope_id>/sources/<source_id>/browse")
    for search in ("users", "groups", "public-workspaces"):
        assert_declared("GET", f"/api/admin/file-sync/{search}/search")
    identities = (APP_ROOT / "route_backend_workspace_identities.py").read_text(encoding="utf-8")
    assert "@bp.route('/api/admin/workspace-identities/<scope_type>/<scope_id>/identities', methods=['GET'])" in identities

    # The one route the manager needed that did not exist: the editor options for a target.
    rule = "/api/admin/file-sync/<scope_type>/<scope_id>/source-options"
    functions = route_functions(source, rule)
    assert len(functions) == 1, f"{rule} is not declared exactly once"
    decorators = [ast.unparse(decorator) for decorator in functions[0].decorator_list]
    assert decorators == [
        f"bp.route('{rule}', methods=['GET'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "admin_required",
        "enabled_required('enable_file_sync')",
    ]
    body = ast.unparse(functions[0])
    assert "_require_admin_target_context(scope_type, scope_id)" in body
    assert "build_file_sync_source_options(scope_type, target_scope_id, get_settings())" in body

    # The client names the same search routes, the options route and the identity routes.
    client = read("lib/adminFileSyncTargets.ts")
    for search in ("users", "groups", "public-workspaces"):
        assert f"'/api/admin/file-sync/{search}/search'" in client
    assert "`${base}/source-options`" in client
    assert "`/api/admin/workspace-identities/${target.scope}/${encodeURIComponent(targetId)}/identities`" in client
    print("  All requests have a route in every scope; the options route is admin-only.")


def test_the_file_sync_card_declares_and_renders_the_target_manager():
    """A component the schema names and the page draws, behind File Sync being on."""
    print("\nTesting that the File Sync card carries the target manager...")

    schema = fields_module.get_admin_settings_fields()
    managers = [
        field for field in schema["file-sync-section"]
        if field.get("type") == "component" and field.get("component") == "file-sync-target-manager"
    ]
    assert len(managers) == 1
    assert managers[0]["depends_on"] == {"key": "enable_file_sync", "equals": True}
    page = read("pages/AdminSettingsPage.tsx")
    assert "case 'file-sync-target-manager':" in page
    # The server decides from the saved switches, so the pickers read the saved values.
    for key in (
        "enable_file_sync", "enable_redis_cache", "enable_file_sync_personal",
        "enable_file_sync_group", "enable_file_sync_public",
    ):
        assert f"readSwitch('{key}', false)" in page
    print("  The schema declares it, depends on File Sync, and the page reads the saved switches.")


if __name__ == "__main__":
    tests = [
        test_the_typescript_logic_checks_pass,
        test_the_dai_diagnostics_switch_is_no_longer_marked_classic_only,
        test_every_section_a_link_targets_is_drawn_by_v2_or_is_named_as_classic_only,
        test_the_latest_feature_aliases_name_sections_v2_draws,
        test_every_latest_feature_admin_shortcut_lands_in_v2,
        test_v2_source_builds_classic_admin_urls_in_one_place,
        test_the_control_center_refresh_strip_matches_the_routes_it_calls,
        test_duplicate_seeds_the_draft_keys_the_new_record_editors_read,
        test_the_file_sync_target_manager_calls_routes_the_server_declares,
        test_the_file_sync_card_declares_and_renders_the_target_manager,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
