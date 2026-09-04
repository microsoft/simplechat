#!/usr/bin/env python3
# test_v2_admin_section_shell.py
"""
Functional test for the Admin Settings section shell and connection tests.
Version: 0.261.059
Implemented in: 0.261.059

Two things arrive together here, because neither is useful without the other.

The section shell replaces a flat run of controls with a header that carries the
capability toggle and a status, and a body of collapsible groups. Its judgement
calls live in ``adminSections.ts`` and are executed by the companion TypeScript
checks this file bundles and runs.

Connection tests give the V2 surface something it did not have: a way to find out
whether an endpoint and credential actually work before saving them. The
server-rendered page has always offered this, and without it configuring a
connection in V2 means saving blind and waiting for a user to hit the failure.

The Python checks here cover the parts that are structural rather than
behavioural: that both interfaces dispatch through one shared list of tests, that
the V2 route is guarded, and that the page really does route sections through the
shell rather than rendering them itself.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
PAGE_TSX = V2_DIR / "src" / "pages" / "AdminSettingsPage.tsx"
SECTION_TSX = V2_DIR / "src" / "components" / "admin" / "SettingsSection.tsx"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_admin_section_logic.ts"

# The tests the Knowledge group needs to be able to run from the V2 surface.
KNOWLEDGE_TEST_TYPES = (
    "web_search",
    "url_access_policy",
    "azure_ai_search",
    "azure_doc_intelligence",
    "content_understanding",
    "multimodal_vision",
)


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_both_interfaces_share_one_connection_test_dispatcher():
    """Two dispatchers would let one interface test things the other cannot."""
    print("Testing the shared connection-test dispatcher...")

    assert_app_version_at_least("0.261.059")

    settings_source = _read(APP_ROOT / "route_backend_settings.py")

    assert "def run_admin_settings_connection_test(" in settings_source, (
        "The connection tests should be dispatched by a shared module-level "
        "function so both admin interfaces reach the same set."
    )

    registry = re.search(
        r"ADMIN_SETTINGS_CONNECTION_TESTS = \{(.*?)\n\}", settings_source, re.DOTALL
    )
    assert registry, "Could not read ADMIN_SETTINGS_CONNECTION_TESTS"
    declared = set(re.findall(r"'([a-z_]+)':", registry.group(1)))

    missing = sorted(set(KNOWLEDGE_TEST_TYPES) - declared)
    assert not missing, (
        "The Knowledge group needs these connection tests, but the shared "
        f"dispatcher does not offer them: {missing}"
    )

    # The server-rendered route should now delegate rather than keep its own chain,
    # which is what stops the two lists from drifting apart again.
    assert "return run_admin_settings_connection_test(" in settings_source, (
        "/api/admin/settings/test_connection should delegate to the shared "
        "dispatcher rather than maintaining its own if/elif chain."
    )

    print(f"  {len(declared)} connection test(s) available to both interfaces.")
    return True


def test_the_v2_connection_test_route_is_admin_guarded():
    """This route reaches external services using stored credentials."""
    print("\nTesting the V2 connection-test route...")

    source = _read(APP_ROOT / "route_backend_v2.py")

    route = re.search(
        r'@bp\.route\("/api/v2/admin/settings/test-connection".*?\n    def '
        r"v2_admin_test_connection",
        source,
        re.DOTALL,
    )
    assert route, (
        "Expected a POST /api/v2/admin/settings/test-connection route in "
        "route_backend_v2.py."
    )

    decorators = route.group(0)
    for decorator in ("@swagger_route(", "@login_required", "@admin_required"):
        assert decorator in decorators, (
            f"The connection-test route is missing {decorator}. It runs "
            "administrator-configured requests using stored credentials, so it "
            "must not be reachable without the Admin role."
        )

    assert 'methods=["POST"]' in decorators, "The route should accept POST only."

    print("  The route is registered, documented and admin-guarded.")
    return True


def test_the_page_renders_sections_through_the_shell():
    """A section rendered inline would skip the status and disclosure rules."""
    print("\nTesting that the page uses the section shell...")

    page = _read(PAGE_TSX)

    assert "<SettingsSection" in page, (
        "AdminSettingsPage should render each section through SettingsSection, "
        "which is what applies the status chip and the group disclosure rules."
    )
    assert "forceExpanded={Boolean(query.trim())}" in page, (
        "A search match inside a collapsed group has to force that group open, "
        "otherwise filtering the page shows cards with nothing in them."
    )
    assert "case 'connection-test':" in page, (
        "The connection-test component needs a branch in the page's renderer or "
        "a declared test would render nothing."
    )

    print("  Sections render through the shell, with search expansion wired up.")
    return True


def test_the_shell_keeps_acknowledgements_on_the_capability_toggle():
    """The capability toggle moves to the header but must keep its gate."""
    print("\nTesting capability rendering in the shell...")

    section = _read(SECTION_TSX)
    page = _read(PAGE_TSX)

    assert "renderCapability" in section, (
        "The shell should render the capability toggle through a callback rather "
        "than drawing a raw Toggle, so acknowledgement modals keep working."
    )
    assert "renderCapability={renderField}" in page, (
        "The page should pass its own field renderer for the capability toggle, "
        "which is what routes it through onSwitchChange and its acknowledgement "
        "handling."
    )

    print("  The capability toggle still goes through the page's renderer.")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("\nTesting section shell logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-admin-section-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # adminFields reaches nothing Vite-specific, but the define keeps this
                # identical to the other logic-check runners.
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
    return True


if __name__ == "__main__":
    tests = [
        test_both_interfaces_share_one_connection_test_dispatcher,
        test_the_v2_connection_test_route_is_admin_guarded,
        test_the_page_renders_sections_through_the_shell,
        test_the_shell_keeps_acknowledgements_on_the_capability_toggle,
        test_the_typescript_logic_checks_pass,
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
