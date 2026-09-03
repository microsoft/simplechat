#!/usr/bin/env python3
"""
Functional test for the V2 personal workspace sections and the routes behind them.

Version: 0.261.039
Implemented in: 0.261.039

The V2 workspace is assembled from eight independent capabilities, and two kinds of mistake
here are invisible at runtime.

The first is a field name. Every one of these routes wraps its collection in a differently
named key -- `prompts`, `identities`, `sources`, `runs`, `workflows`, `endpoints` -- and two
of them return a bare array instead. A client reading the wrong key still gets a successful
response; the section simply renders empty, which is indistinguishable from having nothing
in it.

The second is gating. Whether a section is available combines plain settings, app-role
checks and governance policy, and the classic interface computes that in Jinja where the SPA
cannot see it. If the two ever disagree, one interface shows a section whose endpoints
refuse every request. That is why both now read the same helper, and why this test pins the
gates the helper is required to cover.
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


def test_collection_keys_match_between_routes_and_client():
    """Each route's collection key, and the client reading that exact key."""
    print("Testing workspace collection key contracts...")

    client = _read(V2_SRC / "lib" / "workspaceApi.ts")

    # (route file, the literal the route returns, the key the client must ask for)
    contracts = [
        ("route_backend_prompts.py", '"prompts"', "'prompts'"),
        ("route_backend_workspace_identities.py", '"identities"', "'identities'"),
        ("route_backend_file_sync.py", '"sources"', "'sources'"),
        ("route_backend_file_sync.py", '"runs"', "'runs'"),
        ("route_backend_workflows.py", "'workflows'", "'workflows'"),
        ("route_backend_models.py", '"endpoints"', "'endpoints'"),
    ]

    for route_file, server_key, client_key in contracts:
        source = _read(APP_DIR / route_file)
        assert server_key in source, f"{route_file} no longer returns {server_key}"
        assert client_key in client, (
            f"workspaceApi.ts must read {client_key}; without it the section renders "
            f"empty even though the request succeeded"
        )

    print("Collection key contract test passed!")
    return True


def test_per_item_routes_exist_for_agents_actions_and_endpoints():
    """The three collections that previously had no per-item write path."""
    print("Testing per-item route registration...")

    expectations = [
        ("route_backend_agents.py", "/api/user/agents/<agent_id>", ["GET", "PATCH", "DELETE"]),
        ("route_backend_plugins.py", "/api/user/plugins/<action_id>", ["GET", "PATCH", "DELETE"]),
        (
            "route_backend_models.py",
            "/api/user/model-endpoints/<endpoint_id>",
            ["GET", "PATCH", "DELETE"],
        ),
    ]

    for route_file, path, methods in expectations:
        source = _read(APP_DIR / route_file)
        for method in methods:
            pattern = re.escape(path) + r"['\"],\s*methods=\[['\"]" + method + r"['\"]\]"
            assert re.search(pattern, source), (
                f"{route_file} is missing {method} {path}. Without it the client has to "
                f"round-trip the whole collection to change one row."
            )

    print("Per-item route registration test passed!")
    return True


def test_client_never_posts_a_whole_collection():
    """The deprecated bulk form must not creep back into the V2 client."""
    print("Testing that the client uses per-item writes...")

    client = _read(V2_SRC / "lib" / "workspaceApi.ts")

    # A bare array body to either of these is the whole-collection replace: any row the
    # client did not know about is deleted, and a stale copy reverts another tab's edit.
    for collection in ("/api/user/agents", "/api/user/plugins"):
        bulk = re.search(
            re.escape(f"api.post<") + r"[^>]*>\(\s*'" + re.escape(collection) + r"',\s*\[",
            client,
        )
        assert not bulk, f"workspaceApi.ts posts an array to {collection}"

    assert "endpoints: [" not in client, (
        "workspaceApi.ts must not send the whole endpoints list; the copies it holds have "
        "their secrets stripped, so posting them back blanks the stored credentials"
    )

    # And the per-item calls it should be making instead.
    for expected in (
        "api.patch<WorkspaceAgent>(`/api/user/agents/",
        "api.delete<{ success?: boolean }>(`/api/user/agents/",
        "api.delete<{ success?: boolean }>(`/api/user/plugins/",
        "/api/user/model-endpoints/",
    ):
        assert expected in client, f"workspaceApi.ts should call {expected}"

    print("Per-item write test passed!")
    return True


def test_bootstrap_reports_workspace_sections():
    """The SPA cannot derive these from `features`, so bootstrap must send them."""
    print("Testing bootstrap workspace block...")

    bootstrap = _read(APP_DIR / "route_backend_v2.py")

    assert '"workspace": workspace' in bootstrap, (
        "The bootstrap payload no longer carries a workspace block"
    )
    assert "build_workspace_section_availability" in bootstrap, (
        "Bootstrap must use the shared helper rather than recomputing the gates"
    )

    # _build_feature_flags forwards only `enable_*` booleans, so these four never reach the
    # SPA through `features` and the workspace block is the only route they have.
    flags = _read(APP_DIR / "functions_workspace_sections.py")
    for key in (
        "per_user_semantic_kernel",
        "allow_user_agents",
        "allow_user_plugins",
        "allow_user_custom_endpoints",
    ):
        assert key in flags, f"The section helper no longer consults {key}"
        assert not key.startswith("enable_"), (
            f"{key} would reach the SPA through features if it were an enable_ key; this "
            f"assertion exists to catch a rename that makes the workspace block redundant"
        )

    client = _read(V2_SRC / "lib" / "workspaceSections.ts")
    assert "availability?.sections" in client, (
        "The client must read the server's per-section verdicts"
    )

    print("Bootstrap workspace block test passed!")
    return True


def test_gating_is_shared_between_the_two_interfaces():
    """One helper, used by both, so a capability cannot be gated differently in each."""
    print("Testing gating parity...")

    helper = _read(APP_DIR / "functions_workspace_sections.py")
    classic = _read(APP_DIR / "route_frontend_workspace.py")

    assert "build_workspace_section_availability" in classic, (
        "The classic workspace route must read the shared helper"
    )
    assert "is_file_sync_enabled_for_user" not in classic, (
        "The classic route recomputes file sync availability; that is the drift the shared "
        "helper exists to prevent"
    )

    # Every gate the classic template branches on has to be represented in the helper.
    for gate in (
        "enable_semantic_kernel",
        "per_user_semantic_kernel",
        "allow_user_agents",
        "allow_user_plugins",
        "allow_user_custom_endpoints",
        "enable_multi_model_endpoints",
        "is_file_sync_enabled_for_user",
        "is_user_workflows_enabled_for_user",
        "governance_user_agents",
        "governance_user_actions",
        "governance_user_endpoints",
    ):
        assert gate in helper, f"The section helper no longer accounts for {gate}"

    # Identities are available when either of the two things that consume them is.
    assert "file_sync_enabled or semantic_kernel_enabled" in helper, (
        "Identities exist to serve file sync and actions, and the classic template gates "
        "them on `file_sync_enabled or settings.enable_semantic_kernel`"
    )

    print("Gating parity test passed!")
    return True


def test_section_ids_agree_between_server_and_client():
    """A section the client renders but the server never reports is permanently hidden."""
    print("Testing section id agreement...")

    helper = _read(APP_DIR / "functions_workspace_sections.py")
    server_ids = set(
        re.findall(r'"(\w+)": "(?:knowledge|automation|connections)"', helper)
    )
    assert server_ids, "Could not read the server's section groups"

    registry = _read(V2_SRC / "pages" / "workspace" / "sections.tsx")
    client_ids = set(re.findall(r"^\s{8}id: '([a-z_]+)',", registry, re.MULTILINE))
    assert client_ids, "Could not read the client's section registry"

    assert client_ids == server_ids, (
        f"The section registries disagree. Only on the client: "
        f"{sorted(client_ids - server_ids)}. Only on the server: "
        f"{sorted(server_ids - client_ids)}. A client-only section can never be enabled, "
        f"and a server-only one is never rendered."
    )

    print("Section id agreement test passed!")
    return True


def test_every_registered_section_has_a_component():
    """A section in the registry with no component would crash the page on selection."""
    print("Testing section registry...")

    workspace_dir = V2_SRC / "pages" / "workspace"
    registry = _read(workspace_dir / "sections.tsx")

    components = re.findall(r"<(\w+Section)\b", registry)
    assert len(set(components)) == 8, (
        f"Expected eight section components, found {sorted(set(components))}"
    )

    sources = list(workspace_dir.glob("*.tsx"))
    for component in set(components):
        assert f"import {{ {component} }}" in registry, f"{component} is not imported"
        assert any(f"export function {component}" in _read(path) for path in sources), (
            f"No component named {component} exists"
        )

    # Each section needs the sentence the overview shows for it, which is the only
    # explanation a user gets for a section their administrator has switched off.
    blurbs = re.findall(r"blurb: '([^']+)'", registry)
    assert len(blurbs) == 8, f"Every section needs a blurb; found {len(blurbs)}"
    assert len(set(blurbs)) == 8, "Section blurbs must be distinct, not boilerplate"

    print("Section registry test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added this."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.039")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_collection_keys_match_between_routes_and_client,
        test_per_item_routes_exist_for_agents_actions_and_endpoints,
        test_client_never_posts_a_whole_collection,
        test_bootstrap_reports_workspace_sections,
        test_gating_is_shared_between_the_two_interfaces,
        test_section_ids_agree_between_server_and_client,
        test_every_registered_section_has_a_component,
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
