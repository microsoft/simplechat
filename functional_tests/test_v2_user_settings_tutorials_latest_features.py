#!/usr/bin/env python3
# test_v2_user_settings_tutorials_latest_features.py
"""
Functional test for V2 guided tours and the Latest Features shortcut.
Version: 0.261.281
Implemented in: 0.261.280
URL sink hardening updated in: 0.261.281

The V2 interface now has guided tours for chat and the workspace, with a master switch
shared with the classic tutorial buttons plus a per-tour choice, and a Latest Features
shortcut in the navigation rail that a user can hide until the next release. This file
pins the backend validation, the bootstrap navigation entry, the tour anchors, and the
pure resolution logic the rail and the Preferences page share.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
TOURS_TS = V2_SRC / "lib" / "tours.ts"
NAV_TS = V2_SRC / "lib" / "latestFeaturesNav.ts"
USERS_ROUTE = APP_DIR / "route_backend_users.py"
V2_ROUTE = APP_DIR / "route_backend_v2.py"
USER_SETTINGS_TS = V2_SRC / "lib" / "userSettings.ts"
PREFERENCES_TSX = V2_SRC / "components" / "settings" / "PreferencesTab.tsx"
GUIDANCE_TSX = V2_SRC / "components" / "settings" / "GuidanceCards.tsx"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def _tour_ids():
    return re.findall(r"^        id: '([a-z-]+)',", _read(TOURS_TS), flags=re.MULTILINE)


def test_version_is_at_least_the_implementing_release():
    print("Testing the application version...")
    assert_app_version_at_least("0.261.280")


def test_route_accepts_only_shipped_tours():
    print("Testing tutorial visibility validation...")
    route = _read(USERS_ROUTE)
    match = re.search(r"TUTORIAL_IDS = frozenset\(\{([^}]*)\}\)", route)
    assert match, "The route must declare the tutorials it accepts"
    route_ids = set(re.findall(r'"([a-z-]+)"', match.group(1)))
    assert route_ids == set(_tour_ids()), (
        f"The route accepts {sorted(route_ids)} but V2 ships {sorted(_tour_ids())}; a tour "
        "the route rejects could never be hidden"
    )
    assert "'tutorialVisibility'" in route, "tutorialVisibility must be a writable key"
    assert "tutorial_id not in TUTORIAL_IDS or not isinstance(visible, bool)" in route
    assert 'isinstance(settings_to_update["showTutorialButtons"], bool)' in route

    user_settings = _read(USER_SETTINGS_TS)
    for key in ("'tutorialVisibility'", "'latestFeaturesHiddenVersion'"):
        assert key in user_settings, f"{key} must be in WRITABLE_USER_SETTING_KEYS"


def test_every_tour_target_exists():
    print("Testing tour anchors...")
    targets = re.findall(r"target: '([a-z-]+)'", _read(TOURS_TS))
    assert targets, "Tours must declare their targets"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in V2_SRC.rglob("*.tsx")
    )
    for target in targets:
        assert f'data-tour="{target}"' in sources, (
            f"No element carries data-tour={target!r}, so that tour step would be skipped"
        )


def test_tours_are_launchable_and_configurable():
    print("Testing tour launchers and preferences...")
    chat_page = _read(V2_SRC / "pages" / "ChatPage.tsx")
    workspace_page = _read(V2_SRC / "pages" / "workspace" / "WorkspacePage.tsx")
    assert '<TourLauncher tourId="chat"' in chat_page
    assert '<TourLauncher tourId="workspace"' in workspace_page

    preferences = _read(PREFERENCES_TSX)
    guidance = _read(GUIDANCE_TSX)
    assert 'id="guidance"' in preferences, "Preferences must list the Help and guidance group"
    assert "<TutorialsCard" in preferences and "<LatestFeaturesCard" in preferences
    for needle in ("showTutorialButtons", "withTourVisibility", "requestTour", "latestFeaturesHiddenVersion"):
        assert needle in guidance, f"GuidanceCards must use {needle}"

    for path in (GUIDANCE_TSX, V2_SRC / "components" / "tour" / "GuidedTour.tsx"):
        assert "display:none" not in _read(path).replace(" ", "")

    # Navigation URLs crossing from API data into the browser have an explicit safe boundary.
    latest_link = _read(V2_SRC / "components" / "layout" / "LatestFeaturesLink.tsx")
    guided_tour = _read(V2_SRC / "components" / "tour" / "GuidedTour.tsx")
    message_list = _read(V2_SRC / "components" / "chat" / "MessageList.tsx")
    workspace_shell = _read(V2_SRC / "components" / "workspace" / "WorkspaceShell.tsx")
    assert 'href="/support/latest-features"' in latest_link
    assert "candidate.dataset.tour === step.target" in guided_tour
    assert "href={safeStreamAuthUrl}" in message_list
    assert "normalizeWorkspaceUrl(" in workspace_shell


def test_bootstrap_exposes_latest_features_nav():
    print("Testing the Latest Features navigation entry...")
    route = _read(V2_ROUTE)
    assert "def _build_latest_features_nav(" in route
    assert '"latest_features": _build_latest_features_nav(' in route
    for needle in ("enable_support_latest_features", "has_visible_support_latest_features", "hidden_by_development"):
        assert needle in route, f"The navigation entry must consider {needle}"
    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    assert "<LatestFeaturesLink" in sidebar


NODE_SCRIPT = r"""
import { resolveLatestFeaturesNav, describeLatestFeaturesNav } from './latestFeaturesNav.ts';
import { isTourEnabled, withTourVisibility } from './tours.ts';
const nav = { available: true, hidden_by_development: false };
const out = {
    unavailable: resolveLatestFeaturesNav({ available: false, hidden_by_development: false }, null, '1.0').status,
    development: resolveLatestFeaturesNav({ available: true, hidden_by_development: true }, null, '1.0').status,
    hidden: resolveLatestFeaturesNav(nav, ' 1.0 ', '1.0'),
    stale: resolveLatestFeaturesNav(nav, '0.9', '1.0'),
    staleText: describeLatestFeaturesNav(resolveLatestFeaturesNav(nav, '0.9', '1.0'), '1.0'),
    masterOff: isTourEnabled('chat', false, { chat: true }),
    missingShown: isTourEnabled('chat', true, {}),
    tourOff: isTourEnabled('chat', true, { chat: false }),
    merged: withTourVisibility({ chat: false, bogus: true, workspace: 'x' }, 'workspace', false),
    unknownIgnored: withTourVisibility({}, 'bogus', true),
};
console.log(JSON.stringify(out));
"""


def test_resolution_logic_runtime():
    print("Testing the shared resolution logic in Node...")
    node = shutil.which("node")
    if not node:
        print("Node is not installed; skipping the runtime check.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shutil.copy(NAV_TS, tmp_path / "latestFeaturesNav.ts")
        shutil.copy(TOURS_TS, tmp_path / "tours.ts")
        (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (tmp_path / "run.ts").write_text(NODE_SCRIPT, encoding="utf-8")
        result = subprocess.run(
            [node, "--experimental-strip-types", "--no-warnings", "run.ts"],
            cwd=tmp_path, capture_output=True, text=True, timeout=60,
        )
    if result.returncode != 0 and "strip-types" in result.stderr:
        print("This Node version cannot strip types; skipping the runtime check.")
        return
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["unavailable"] == "unavailable"
    assert out["development"] == "development"
    assert out["hidden"] == {"status": "hidden", "showInRail": False, "staleHiddenVersion": None}
    assert out["stale"] == {"status": "visible", "showInRail": True, "staleHiddenVersion": "0.9"}
    assert "0.9" in out["staleText"]
    assert out["masterOff"] is False, "The shared master switch must turn every tour off"
    assert out["missingShown"] is True, "A tour with no saved choice must be shown"
    assert out["tourOff"] is False
    assert out["merged"] == {"chat": False, "workspace": False}, "Unknown or non-boolean entries must be dropped"
    assert out["unknownIgnored"] == {}


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_route_accepts_only_shipped_tours,
        test_every_tour_target_exists,
        test_tours_are_launchable_and_configurable,
        test_bootstrap_exposes_latest_features_nav,
        test_resolution_logic_runtime,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAILED {test.__name__}: {exc}")
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
