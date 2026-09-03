#!/usr/bin/env python3
"""
Functional test for conversation export in the V2 (React) interface.

Version: 0.261.038
Implemented in: 0.261.038

The V2 interface could export a single message as Word, PowerPoint or an email draft, but it
could not export a conversation at all — the classic interface's export wizard had no V2
equivalent. This covers the feature that closed that gap:

  - A stepped export wizard (review, format, packaging, intro summary, download) reachable from
    a conversation's own menu, from the rail's selection mode, and from the details dialog.
  - Multi-select in the conversation rail, so several conversations can go into one ZIP.
  - Browser-side rasterizing of the diagrams in the exported conversations, which is what stops
    the server having to launch headless Chromium per export.

No backend change was needed: the wizard drives ``POST /api/conversations/export`` and
``POST /api/conversations/export/visual-scan``, which already served the classic wizard. Much of
what is asserted here is therefore that the client keeps its half of that existing contract —
in particular that a summary model travels as all four identity fields, since sending fewer
makes the server silently resolve a different endpoint.

The behavioural half of this lives in ``test_v2_conversation_export_logic.ts``, run below.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.038"

EXPORT_LIB = V2_SRC / "lib" / "conversationExport.ts"
ENDPOINTS_TS = V2_SRC / "lib" / "endpoints.ts"
VISUALS_TS = V2_SRC / "lib" / "exportVisuals.ts"
RUNTIME_TS = V2_SRC / "lib" / "mermaidRuntime.ts"
RASTER_TS = V2_SRC / "lib" / "svgRaster.ts"
DIALOG_TSX = V2_SRC / "components" / "chat" / "ConversationExportDialog.tsx"
RAIL_TSX = V2_SRC / "components" / "chat" / "ConversationRail.tsx"
DETAILS_TSX = V2_SRC / "components" / "chat" / "ConversationDetails.tsx"
STORE_TS = V2_SRC / "stores" / "chatStore.ts"
EXPORT_ROUTE = APP_DIR / "route_backend_conversation_export.py"


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def test_version_is_at_least_the_implementing_release():
    """The feature must be present in the version the app reports."""
    print("Testing version...")
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_the_client_calls_the_existing_export_endpoints():
    """The wizard reuses the routes the classic wizard already drives."""
    print("Testing endpoint reuse...")

    endpoints = _read(ENDPOINTS_TS)
    visuals = _read(VISUALS_TS)
    routes = _read(EXPORT_ROUTE)

    assert "'/api/conversations/export'" in endpoints, (
        "the export must post to /api/conversations/export"
    )
    assert "'/api/conversations/export/visual-scan'" in visuals, (
        "diagram scanning must post to /api/conversations/export/visual-scan"
    )

    # Both must still exist server-side, so a rename cannot break the client silently.
    for route in ("/api/conversations/export", "/api/conversations/export/visual-scan"):
        assert f"@bp.route('{route}'" in routes, f"{route} is no longer registered"

    print("  ok  both existing export endpoints are used and still registered")


def test_the_request_matches_what_the_route_reads():
    """Every field the client sends is a field the route actually reads."""
    print("Testing request contract...")

    endpoints = _read(ENDPOINTS_TS)
    routes = _read(EXPORT_ROUTE)

    for field in (
        "conversation_ids",
        "format",
        "packaging",
        "include_summary_intro",
        "summary_model_deployment",
        "summary_model_endpoint_id",
        "summary_model_id",
        "summary_model_provider",
        "visual_assets",
    ):
        assert field in endpoints, f"the client never sends {field}"
        assert f"data.get('{field}'" in routes, f"the route does not read {field}"

    # The route rejects anything else, so the client's union types must not drift wider.
    assert "'json' | 'markdown' | 'pdf'" in endpoints, "formats must match the route's allowlist"
    assert "'single' | 'zip'" in endpoints, "packaging must match the route's allowlist"

    print("  ok  the request body matches the fields the route reads")


def test_the_summary_model_carries_its_whole_identity():
    """A deployment name alone resolves to a different endpoint, with no error."""
    print("Testing summary model identity...")

    source = _read(EXPORT_LIB)

    assert "modelIdentityForSelection" in source, (
        "the summary model must reuse the composer's own identity mapping rather than "
        "repeating it, or the two can resolve the same choice to different endpoints"
    )
    for field in (
        "summary_model_deployment",
        "summary_model_endpoint_id",
        "summary_model_id",
        "summary_model_provider",
    ):
        assert field in source, f"{field} must be part of the summary mapping"

    print("  ok  all four model identity fields are mapped")


def test_json_exports_do_not_rasterize():
    """A JSON export keeps its markdown fences, so drawing them would be wasted work."""
    print("Testing rasterizing is skipped for JSON...")

    assert "needsVisualAssets" in _read(EXPORT_LIB), "the decision must be explicit"
    assert "needsVisualAssets(format)" in _read(DIALOG_TSX), (
        "the dialog must consult it before rasterizing"
    )

    print("  ok  JSON exports skip the rasterizing step")


def test_diagram_rendering_goes_through_the_shared_runtime():
    """Export draws diagrams with the same hardened runtime the chat uses."""
    print("Testing diagram rendering path...")

    visuals = _read(VISUALS_TS)
    runtime = _read(RUNTIME_TS)

    assert "renderMermaidSvgForExport" in visuals, (
        "conversation export must render through the shared runtime, not its own mermaid setup"
    )
    assert "securityLevel: 'strict'" in runtime, (
        "the shared runtime must keep mermaid's strict security level"
    )
    assert "purify.sanitize(" in runtime, "the runtime must keep its DOMPurify boundary"

    # An export is read outside the application, so it must not inherit a dark theme.
    assert "MERMAID_EXPORT_PRESET" in runtime, "exports need their own rendering preset"

    print("  ok  export rendering reuses the hardened shared runtime")


def test_a_percentage_width_is_not_mistaken_for_a_size():
    """Mermaid emits width="100%", which parsed as a number squashes every export image."""
    print("Testing rasterizer sizing...")

    source = _read(RASTER_TS)

    assert "endsWith('%')" in source, (
        "a percentage width must report no size so the viewBox is used instead; parsing "
        "width=\"100%\" as 100 rasterizes a 1094x541 diagram into a 100px sliver"
    )

    print("  ok  percentage widths fall through to the viewBox")


def test_the_wizard_escapes_the_rails_containing_block():
    """A fixed-position dialog rendered inside the rail would be trapped in the sidebar."""
    print("Testing dialog placement...")

    dialog = _read(DIALOG_TSX)
    theme = _read(V2_SRC / "styles" / "theme.css")
    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")

    # The trap: `.glass` carries a backdrop-filter, and a non-`none` backdrop-filter makes an
    # element a containing block for fixed-position descendants. The rail sits inside one.
    assert "backdrop-filter" in theme, "the glass surfaces still use backdrop-filter"
    assert "'glass glass-edge" in sidebar, "the sidebar is still a glass surface"

    # So the dialog must not resolve its `inset-0` against the rail.
    assert "createPortal" in dialog, (
        "the export dialog must be portalled out of the rail; rendered in place its "
        "`fixed inset-0` resolves to the 280px sidebar rather than the viewport"
    )
    assert "document.body" in dialog, "the portal target must be the document body"

    print("  ok  the wizard is portalled out of the sidebar's containing block")


def test_the_conversation_cap_matches_the_conversation_route():
    """The conversation routes take a larger asset budget than the per-message ones."""
    print("Testing visual asset cap...")

    visuals = _read(VISUALS_TS)
    server_cap = _read(APP_DIR / "functions_export_visuals.py")

    assert "EXPORT_VISUAL_ASSET_MAX_COUNT = 60" in server_cap, (
        "the server budget changed; the client cap below must follow it"
    )
    assert "MAX_ASSETS_PER_CONVERSATION_EXPORT = 60" in visuals, (
        "a conversation export must rasterize up to the server's own 60, not the per-message "
        "20; capping lower fetches diagrams and then discards them, forcing the server to "
        "render them in headless Chromium instead"
    )
    assert "assets.length >= MAX_ASSETS_PER_CONVERSATION_EXPORT" in visuals, (
        "the conversation loop must use the conversation cap"
    )

    print("  ok  the client cap matches the conversation route's budget")


def test_the_rail_can_select_several_conversations():
    """Bulk export needs a selection mode, and it must survive rows being removed."""
    print("Testing rail multi-select...")

    store = _read(STORE_TS)
    rail = _read(RAIL_TSX)

    for action in (
        "selectionMode",
        "selectedConversationIds",
        "setSelectionMode",
        "toggleConversationSelected",
        "selectAllConversations",
        "clearConversationSelection",
    ):
        assert action in store, f"{action} must exist on the store"

    # Deleting or hiding a selected conversation must drop it from the selection, or the
    # export would name an id the user can no longer see.
    assert store.count("selectedConversationIds.filter(") >= 2, (
        "removing and hiding a conversation must both prune the selection"
    )

    assert 'type="checkbox"' in rail, "selection mode needs checkboxes"
    assert "ConversationExportDialog" in rail, "the rail must be able to open the wizard"

    print("  ok  the rail supports multi-select and keeps it consistent")


def test_every_entry_point_opens_the_wizard():
    """Export is reachable the same three ways the classic interface offers."""
    print("Testing entry points...")

    rail = _read(RAIL_TSX)
    details = _read(DETAILS_TSX)

    # From a single conversation's menu, which has nothing to review.
    assert "skipSelection: true" in rail, "the row menu must skip the review step"
    # From the selection toolbar, which does.
    assert "skipSelection: false" in rail, "a bulk export must review its selection"
    # And from the details dialog.
    assert "ConversationExportDialog" in details, (
        "the conversation details dialog must offer an export"
    )

    print("  ok  row menu, selection toolbar and details dialog all open the wizard")


def test_the_wizard_steps_match_the_classic_wizard():
    """The two interfaces should be describable by one set of instructions."""
    print("Testing wizard steps...")

    source = _read(EXPORT_LIB)

    for step in ("'select'", "'format'", "'packaging'", "'summary'", "'download'"):
        assert step in source, f"the {step} step is missing"

    print("  ok  all five steps are present")


def test_no_new_browser_dependency_was_introduced():
    """Everything the export needs is already vendored or already a dependency."""
    print("Testing browser dependencies...")

    package_json = _read(V2_DIR / "package.json")
    assert "mermaid" not in package_json, (
        "mermaid must stay a vendored runtime asset rather than an npm dependency"
    )

    for path in (EXPORT_LIB, ENDPOINTS_TS, VISUALS_TS, RUNTIME_TS, DIALOG_TSX, RAIL_TSX):
        source = _read(path)
        for marker in ("https://cdn", "http://cdn", "unpkg.com", "jsdelivr", "cdnjs"):
            assert marker not in source, f"{path.name} references a CDN ({marker})"

    print("  ok  no CDN reference and no new browser dependency")


def test_the_content_security_policy_is_unchanged():
    """Rasterizing needs a data: image source, which the policy already permits."""
    print("Testing Content-Security-Policy...")

    assert "img-src 'self' data: https: blob:;" in _read(APP_DIR / "config.py"), (
        "the policy must still allow the data: PNGs the rasterizer produces"
    )

    print("  ok  the existing policy already allows data: images")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    print("Testing TypeScript logic...")

    check = Path(__file__).with_suffix(".ts").with_name("test_v2_conversation_export_logic.ts")
    assert check.exists(), "the logic check file is missing"

    if not (V2_DIR / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    # The check file lives in functional_tests/, which has no node_modules of its own, so bare
    # imports are left for node to resolve at run time from where the bundle is written.
    bundle = V2_DIR / "node_modules" / ".cache-conversation-export-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(check),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # endpoints.ts reaches apiClient.ts, which reads Vite's `import.meta.env` at
                # module scope. Node has no such object, so it is defined away here; the
                # export logic under test never consults it.
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_client_calls_the_existing_export_endpoints,
    test_the_request_matches_what_the_route_reads,
    test_the_summary_model_carries_its_whole_identity,
    test_json_exports_do_not_rasterize,
    test_diagram_rendering_goes_through_the_shared_runtime,
    test_a_percentage_width_is_not_mistaken_for_a_size,
    test_the_wizard_escapes_the_rails_containing_block,
    test_the_conversation_cap_matches_the_conversation_route,
    test_the_rail_can_select_several_conversations,
    test_every_entry_point_opens_the_wizard,
    test_the_wizard_steps_match_the_classic_wizard,
    test_no_new_browser_dependency_was_introduced,
    test_the_content_security_policy_is_unchanged,
    test_the_typescript_logic_checks_pass,
]


def main():
    print("Testing V2 conversation export...\n")
    failed = []

    for test in TESTS:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failed.append(test.__name__)
            print(f"  FAIL  {test.__name__}: {exc}")
        print()

    passed = len(TESTS) - len(failed)
    print(f"{passed}/{len(TESTS)} tests passed")
    for name in failed:
        print(f"Failed: {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
