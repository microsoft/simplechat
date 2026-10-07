#!/usr/bin/env python3
"""
Functional test for the V2 settings tabs and the routes behind them.

Version: 0.261.294
Implemented in: 0.261.022
Groups and Public workspaces rows open their workspace page: 0.261.294

Each tab reads a different set of endpoints, and every field name and query parameter here
was taken from the route rather than inferred. The point of pinning them is that a rename on
the server is otherwise invisible: the request still succeeds, the response simply has
nothing the client recognises, and the tab renders empty.

The set-active flow gets particular attention. `activeGroupOid` looks like an ordinary
setting, and writing it to /api/user/settings does work -- but the route pops it, handles it
separately, and never returns it from a later GET, so a client treating it as a setting sees
what looks like a lost save. The dedicated setActive routes report *why* they refused, which
is the difference between "you are not a member of that group" and silence.

Each Groups and Public workspaces row also offers Open, which goes to that workspace's V2 page
by id. Like the directories' Open it only navigates: activation is left to the page it lands on.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def test_workspace_lists_match_their_routes():
    """The group and public lists differ in wording, and both spellings must be right."""
    print("Testing workspace list contracts...")

    groups = _read(APP_DIR / "route_backend_groups.py")
    public = _read(APP_DIR / "route_backend_public_workspaces.py")
    client = _read(V2_SRC / "lib" / "workspaces.ts")

    # The two responses use different array names; mixing them up yields an empty list.
    assert '"groups": mapped_results' in groups, "The groups route no longer returns `groups`"
    assert '"workspaces": mapped' in public, (
        "The public workspaces route no longer returns `workspaces`"
    )
    # Both kinds read their list through one validated reader, `readPage(response, key, ...)`,
    # so check each kind names its own array, and only its own.
    assert "const items = response[key];" in client, "The shared reader no longer reads the named array"
    group_kind = client[client.index("export const GROUP_WORKSPACES"):client.index("export const PUBLIC_WORKSPACES")]
    public_kind = client[client.index("export const PUBLIC_WORKSPACES"):]
    assert "readPage(response, 'groups'," in group_kind and "'workspaces'" not in group_kind, (
        "The client must read `groups` for group workspaces"
    )
    assert "readPage(response, 'workspaces'," in public_kind and "'groups'" not in public_kind, (
        "The client must read `workspaces` for public workspaces"
    )

    # Paging and search are server-side on both. The two files differ in quote style, so
    # match on the argument name rather than the literal.
    for name, source in (("groups", groups), ("public workspaces", public)):
        for param in ("page", "page_size"):
            assert re.search(rf"request\.args\.get\(['\"]{param}['\"]", source), (
                f"The {name} route no longer reads {param!r} from the query string"
            )
    assert "page_size" in client and "search" in client, (
        "Paging and search are server-side, so the client must send them"
    )

    # Fields the rows render.
    for field in ('"userRole"', '"isActive"', '"status"'):
        assert field in groups, f"The groups route no longer returns {field}"

    print("Workspace list contract test passed!")
    return True


def test_set_active_uses_the_dedicated_routes():
    """Not /api/user/settings, which pops the key and never gives it back."""
    print("Testing set-active flow...")

    groups = _read(APP_DIR / "route_backend_groups.py")
    public = _read(APP_DIR / "route_backend_public_workspaces.py")
    client = _read(V2_SRC / "lib" / "workspaces.ts")

    assert '"/api/groups/setActive", methods=["PATCH"]' in groups
    assert '"/api/public_workspaces/setActive", methods=["PATCH"]' in public

    # The body key differs between them.
    assert 'data.get("groupId")' in groups, "The groups route reads groupId"
    assert 'data.get("workspaceId")' in public, "The public route reads workspaceId"
    assert "{ groupId: id }" in client, "The client must send groupId for a group"
    assert "{ workspaceId: id }" in client, (
        "The client must send workspaceId for a public workspace"
    )

    # The refusals are meaningful and worth surfacing.
    assert '"You are not a member of this group"' in groups, (
        "The 403 message is what tells a user why a switch was refused"
    )
    assert '"Group not found"' in groups

    # And the settings store must not try to carry these itself.
    settings = _read(V2_SRC / "lib" / "userSettings.ts")
    for key in ("activeGroupOid", "activePublicWorkspaceOid"):
        assert f"'{key}'" not in settings.split("WRITABLE_USER_SETTING_KEYS")[1].split("]")[0], (
            f"{key} must not be written as an ordinary setting: the route pops it and it "
            "never comes back from a GET, so the store would think the save was lost"
        )

    print("Set-active flow test passed!")
    return True


def test_rows_open_their_workspace_without_activating():
    """Open goes to the workspace's V2 page by id; the page it lands on owns any activation."""
    print("Testing the Open action on settings rows...")

    client = _read(V2_SRC / "lib" / "workspaces.ts")
    tab = _read(V2_SRC / "components" / "settings" / "WorkspaceListTab.tsx")
    app = _read(V2_SRC / "App.tsx")
    checker = _read(REPO_ROOT / "scripts" / "check_xss_sinks.py")

    # Each kind owns its path, built with the same builders the workspace pages navigate with.
    assert "openPath: (id: string) => string;" in client, "WorkspaceKind must declare openPath"
    group_kind = client[client.index("export const GROUP_WORKSPACES"):client.index("export const PUBLIC_WORKSPACES")]
    public_kind = client[client.index("export const PUBLIC_WORKSPACES"):]
    assert "openPath: (id) => groupWorkspacePath(id)," in group_kind, (
        "A group row must open its group page"
    )
    assert "openPath: (id) => publicWorkspacePath(id)," in public_kind, (
        "A public workspace row must open its public workspace page"
    )

    # Navigation is an XSS sink, so the builders must stay on the checker's reviewed list.
    builders = re.search(r"TS_SAME_ORIGIN_URL_BUILDERS = frozenset\(\{(.*?)\}\)", checker, re.S)
    assert builders, "Could not find the reviewed same-origin URL builders"
    for builder in ("groupWorkspacePath", "publicWorkspacePath"):
        assert f"'{builder}'" in builders.group(1), (
            f"{builder} must stay a reviewed same-origin URL builder; Open navigates with it"
        )

    # The paths are real routes rather than the catch-all, which would send the user home.
    assert '<Route path="/groups/:groupId" element={<GroupWorkspacePage />} />' in app
    assert '<Route path="/public/:workspaceId" element={<PublicWorkspacePage />} />' in app

    # Open only navigates. A group page activates the group it shows and a public page does not,
    # exactly as the directories' Open leaves it, so the tab must not activate on its own.
    handler = re.search(
        r"const openWorkspace = \(workspace: WorkspaceSummary\) => \{(.*?)\n    \};", tab, re.S
    )
    assert handler, "Could not find the Open handler"
    body = handler.group(1)
    assert "kind.openPath(workspace.id)" in body and "navigate(path)" in body, (
        "Open must navigate to the kind's path for the row"
    )
    for activation in ("setActive", "activate(", "reconcile(", "refreshRequired"):
        assert activation not in body, f"Open must not activate from the settings tab ({activation})"
    assert "setActionError(" in body, "An id the path builder refuses must be reported, not thrown"

    assert "onClick={() => openWorkspace(workspace)}" in tab
    assert "aria-label={`Open ${workspace.name || 'Untitled'}`}" in tab, (
        "Open must be named for its workspace, as the directories' Open is"
    )
    # Open waits for an in-flight Set active or reconcile like Set active does, so two
    # activations can never race.
    assert tab.count("disabled={activating !== null || needsReconciliation}") == 2, (
        "Open and Set active must share the same busy gating"
    )

    assert_app_version_at_least("0.261.294")
    print("Settings Open action test passed!")
    return True


def test_feedback_and_violations_read_the_right_fields():
    """Both tabs are paginated, filtered and exported server-side."""
    print("Testing feedback and violations contracts...")

    feedback = _read(APP_DIR / "route_backend_feedback.py")
    safety = _read(APP_DIR / "route_backend_safety.py")

    assert '"feedback": paginated_items' in feedback, (
        "The feedback route no longer returns `feedback`"
    )
    assert '"logs": paginated_items' in safety, "The safety route no longer returns `logs`"

    feedback_client = _read(V2_SRC / "components" / "settings" / "FeedbackTab.tsx")
    safety_client = _read(V2_SRC / "components" / "settings" / "ViolationsTab.tsx")

    assert "listResponse?.feedback" in feedback_client
    assert "logsResponse?.logs" in safety_client

    # Filters are query parameters applied in the query, not client-side.
    assert "request.args.get('page'" in safety
    for param in ("type", "ack"):
        assert f"'{param}'" in feedback or f'"{param}"' in feedback
    assert "search.set('type'" in feedback_client and "search.set('ack'" in feedback_client
    assert "search.set('status'" in safety_client and "search.set('action'" in safety_client

    # A violation is read-only except the user's own notes: the PATCH body carries that
    # field and nothing else, since status, action and admin notes are an administrator's.
    assert "'/api/safety/logs/my/<string:log_id>', methods=['PATCH']" in safety, (
        "The notes route moved; the client targets PATCH on this path"
    )
    patch_body = re.search(
        r"api\.patch\(\s*`/api/safety/logs/my/\$\{[^}]+\}`,\s*\{([^}]*)\}", safety_client
    )
    assert patch_body, "Could not find the violation notes PATCH in the client"
    sent = {field.strip().rstrip(',') for field in patch_body.group(1).split('\n') if field.strip()}
    assert sent == {"user_notes: draft,".rstrip(',')} or sent == {"user_notes: draft"}, (
        f"The notes PATCH must send only user_notes; it sends {sent}. Status, action and "
        "admin notes are an administrator's to set and would be rejected."
    )

    print("Feedback and violations contract test passed!")
    return True


def test_stats_uses_an_allowed_window_and_local_charts():
    """The window is an enum, and the charts are drawn from vendored bytes."""
    print("Testing stats contract...")

    windows = _read(APP_DIR / "functions_stats_windows.py")
    match = re.search(r"ALLOWED_STATS_WINDOW_DAYS = \(([^)]*)\)", windows)
    assert match, "Could not find the allowed stats windows"
    allowed = {value.strip() for value in match.group(1).split(",") if value.strip()}

    stats_lib = _read(V2_SRC / "lib" / "userStats.ts")
    offered = set(re.findall(r"\{ days: (\d+),", stats_lib))
    assert offered <= allowed, (
        f"The stats tab offers windows the route rejects: {offered - allowed}. "
        "An unrecognised value silently falls back to the default."
    )
    assert offered, "The stats tab should offer at least one window"

    client = _read(V2_SRC / "components" / "settings" / "StatsTab.tsx")

    # Response field names.
    profile = _read(APP_DIR / "route_frontend_profile.py")
    for field in ('"logins"', '"conversations"', '"documents"', '"tokens"'):
        assert field in profile, f"The activity-trends response no longer has {field}"
    assert '"creates"' in profile and '"uploads"' in profile, (
        "Conversations and documents are nested by action"
    )
    assert "data?.conversations?.creates" in client
    assert "data?.documents?.uploads" in client

    # Charts are drawn from the copy of Chart.js committed to this repository and served
    # from the app's own origin, loaded through the shared runtime rather than a second
    # loader of its own. Nothing is fetched from the public Internet.
    runtime = _read(V2_SRC / "lib" / "chartRuntime.ts")
    assert "VENDOR_PATHS.chartJs" in runtime, (
        "chartRuntime.ts must load Chart.js from the vendored path"
    )
    chart_component = _read(V2_SRC / "components" / "settings" / "StatsChart.tsx")
    assert "loadChartRuntime" in chart_component, (
        "The stats charts must use the shared vendored Chart.js loader"
    )
    for source in (client, chart_component, runtime):
        assert "cdn" not in source.lower(), "Browser assets must be served locally"
        assert "http://" not in source and "https://" not in source, (
            "The stats charts must not reference an absolute URL"
        )

    # Vendoring is the point: a charting package pulled from npm would be bundled into the
    # entry chunk and downloaded by every user, including the ones who never open this tab.
    package_json = _read(REPO_ROOT / "application" / "v2_ui" / "package.json")
    for charting in ("chart.js", "recharts", "d3", "apexcharts"):
        assert charting not in package_json, (
            f"{charting} was added as an npm dependency; Chart.js is vendored under "
            "public/vendor/ and loaded on demand so it never enters the main bundle"
        )

    print("Stats contract test passed!")
    return True


def test_every_registered_tab_has_a_component():
    """A tab in the registry with no component would crash the page on selection."""
    print("Testing tab registry...")

    tabs = _read(V2_SRC / "components" / "settings" / "tabs.tsx")
    # Only the registry entries, not the ComponentType annotation on the interface.
    registered = re.findall(r"Component: (\w+Tab)\b", tabs)
    assert len(registered) == 6, f"Expected six tabs, found {len(registered)}: {registered}"

    settings_dir = V2_SRC / "components" / "settings"
    for component in registered:
        assert f"import {{ {component} }}" in tabs, f"{component} is not imported"
        matches = list(settings_dir.glob("*.tsx"))
        assert any(f"export function {component}" in _read(path) for path in matches), (
            f"No component named {component} exists"
        )

    print("Tab registry test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added this."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.022")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_workspace_lists_match_their_routes,
        test_set_active_uses_the_dedicated_routes,
        test_rows_open_their_workspace_without_activating,
        test_feedback_and_violations_read_the_right_fields,
        test_stats_uses_an_allowed_window_and_local_charts,
        test_every_registered_tab_has_a_component,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
