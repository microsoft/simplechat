# test_v2_public_directory_settings_keys.py
"""
Functional test for the V2 public directory user-settings keys.

Version: 0.261.175
Implemented in: 0.261.175

The V2 public directory reuses the classic interface's per-user visibility state so the two
read each other's writes. Three keys carry it:

  * ``publicDirectorySettings``    -- the ``{ workspaceId: boolean }`` view/hide map.
  * ``publicDirectorySavedLists``  -- named lists, ``{ listName: [id, ...] }``.
  * ``activePublicWorkspaceOid``   -- the active-workspace pointer.

``/api/user/settings`` validates against ``allowed_keys`` in route_backend_users.py and drops
anything outside it **without complaining** -- the POST still returns success and the value
simply never arrives. So a visibility choice written under an unlisted key would appear to
save and be gone on the next reload.

The active pointer is different: the route pops it and routes it to
``update_active_public_workspace_for_user()`` rather than storing it as a setting, so it must
NOT be declared writable by the V2 client (writing it through the settings store would make
the store believe a save had been lost, exactly the reason ``activeGroupOid`` is excluded).

This pin therefore holds:
  * the server still accepts all three keys (a regression guard -- the server needs no change);
  * V2 declares the two visibility keys writable and types all three shapes;
  * V2 keeps the active pointer OUT of its writable list;
  * the V2 shapes match the classic ones so classic and V2 read each other's writes.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

VISIBILITY_KEYS = ("publicDirectorySettings", "publicDirectorySavedLists")
ROUTED_SEPARATELY_KEY = "activePublicWorkspaceOid"
ALL_KEYS = VISIBILITY_KEYS + (ROUTED_SEPARATELY_KEY,)


def _read(path):
    return path.read_text(encoding="utf-8")


def _allowed_keys():
    """The whitelist the settings route validates against."""
    users = _read(APP_DIR / "route_backend_users.py")
    block = re.search(r"allowed_keys = \{(.*?)\}", users, re.DOTALL)
    assert block, "Could not find allowed_keys in route_backend_users.py"
    return set(re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", block.group(1)))


def _writable_keys():
    """The keys the V2 client may write, read from its literal list."""
    settings = _read(V2_SRC / "lib" / "userSettings.ts")
    block = re.search(
        r"export const WRITABLE_USER_SETTING_KEYS = \[(.*?)\] as const;", settings, re.DOTALL
    )
    assert block, "Could not find WRITABLE_USER_SETTING_KEYS in userSettings.ts"
    return [key for key in re.findall(r"'([^']+)'", block.group(1))]


def test_version_is_at_least_the_implementing_release():
    """Guard against silently shipping this pin under an older application."""
    print("Checking application version floor...")
    assert_app_version_at_least("0.261.170")
    print("  ok  version floor satisfied")
    return True


def test_server_still_accepts_all_three_keys():
    """The server needs no change; assert it still accepts all three (regression guard)."""
    print("Testing the server allowlist keeps the public directory keys...")

    allowed = _allowed_keys()
    missing = [key for key in ALL_KEYS if key not in allowed]
    assert not missing, (
        "These public directory keys must stay in allowed_keys, or the server silently "
        f"drops them: {missing}"
    )

    print(f"  ok  {', '.join(ALL_KEYS)} are accepted by the settings route")
    return True


def test_visibility_keys_are_declared_writable_by_v2():
    """A visibility choice written under an unlisted key is dropped silently."""
    print("Testing the V2 writable list declares the visibility keys...")

    writable = _writable_keys()
    allowed = _allowed_keys()

    for key in VISIBILITY_KEYS:
        assert key in writable, (
            f"{key} must be declared in WRITABLE_USER_SETTING_KEYS or V2 loses the write"
        )
        assert key in allowed, f"{key} must also be whitelisted server-side"

    print(f"  ok  {', '.join(VISIBILITY_KEYS)} are writable on both sides")
    return True


def test_active_pointer_is_not_written_through_the_settings_store():
    """The active pointer is routed separately, so it must not be a normal setting."""
    print("Testing the active pointer stays out of the V2 writable list...")

    writable = _writable_keys()
    assert ROUTED_SEPARATELY_KEY not in writable, (
        f"{ROUTED_SEPARATELY_KEY} is popped and routed to "
        "update_active_public_workspace_for_user(); writing it through the settings store "
        "would make the store believe a save was lost, the reason activeGroupOid is excluded"
    )

    settings = _read(V2_SRC / "lib" / "userSettings.ts")
    assert f"{ROUTED_SEPARATELY_KEY}?: string;" in settings, (
        f"{ROUTED_SEPARATELY_KEY} should still be typed in the UserSettings interface"
    )

    print(f"  ok  {ROUTED_SEPARATELY_KEY} is typed but not writable")
    return True


def test_v2_shapes_match_the_classic_ones():
    """Classic and V2 must agree on the shapes so they read each other's writes."""
    print("Testing the V2 shapes match the classic directory...")

    settings = _read(V2_SRC / "lib" / "userSettings.ts")
    assert "publicDirectorySettings?: Record<string, boolean>;" in settings, (
        "publicDirectorySettings is the classic { workspaceId: boolean } view/hide map"
    )
    assert "publicDirectorySavedLists?: Record<string, string[]>;" in settings, (
        "publicDirectorySavedLists is the classic { listName: [id, ...] } shape"
    )

    classic = _read(APP_DIR / "static" / "js" / "public" / "public_directory.js")
    # Classic writes a boolean into the settings map and an id array into a saved list.
    assert re.search(
        r"publicDirectorySettings\[\s*workspaceId\s*\]\s*=\s*isVisible", classic
    ), "Classic stores publicDirectorySettings[workspaceId] = <boolean>"
    assert re.search(
        r"publicDirectorySavedLists\[\s*listName\s*\]\s*=\s*visibleIds", classic
    ), "Classic stores publicDirectorySavedLists[listName] = <id array>"

    print("  ok  the V2 and classic shapes agree")
    return True


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_server_still_accepts_all_three_keys,
    test_visibility_keys_are_declared_writable_by_v2,
    test_active_pointer_is_not_written_through_the_settings_store,
    test_v2_shapes_match_the_classic_ones,
]


if __name__ == "__main__":
    results = []
    for test in TESTS:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {test.__name__} failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"\n📊 Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if passed == len(results) else 1)
