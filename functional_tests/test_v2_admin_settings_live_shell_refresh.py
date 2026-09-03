#!/usr/bin/env python3
"""
Functional test for the V2 interface refreshing its shell after an admin save.

Version: 0.261.046
Implemented in: 0.261.046

An administrator enabled the classification banner in the V2 admin settings, saved, and
nothing happened. The banner only appeared after reloading the browser.

The banner was never missing. `/api/v2/bootstrap` is fetched exactly once, from a mount
effect in App.tsx, and `AdminSettingsPage.save()` merged the PATCH response into its own
local state only -- the bootstrap store was never told anything had changed. Every value
the shell draws itself from went stale on save, not just the banner: the sidebar logo and
application title, `hide_app_title`, the feature flags the chat surface branches on, the
AI notice and the admin navigation.

The fix re-reads bootstrap after a successful write. It cannot reuse `load()`, which sets
`loading` and `error` -- App.tsx replaces the entire interface with the boot screen while
`loading` is set and with the boot error when `error` is, so a background refetch driven
through `load()` would tear down the page being edited and discard the unsaved draft.

This test ensures the refresh exists, that it stays silent, that it cannot apply a stale
payload, and that both write paths on the admin page call it.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


IMPLEMENTED_IN_VERSION = "0.261.046"


def _read(path):
    return path.read_text(encoding="utf-8")


def _strip_comments(source):
    """Drop comments so an assertion reads the code rather than the prose beside it."""
    without_blocks = re.sub(r"/\*(.|\n)*?\*/", "", source)
    return re.sub(r"//[^\n]*", "", without_blocks)


def _refresh_action():
    """The body of the store's refresh action."""
    source = _read(V2_SRC / "stores" / "bootstrapStore.ts")
    action = re.search(r"    refresh: async \(\) => \{(.|\n)*?\n    \},", source)
    assert action, (
        "bootstrapStore must expose a refresh action. Bootstrap is fetched once at "
        "startup, so without one an administrator's saved change is invisible until the "
        "browser is reloaded"
    )
    return action.group(0)


def test_the_store_can_reread_bootstrap():
    """The payload the shell draws from has to be re-readable after it changes."""
    print("Testing the bootstrap refresh action...")

    source = _read(V2_SRC / "stores" / "bootstrapStore.ts")

    assert "refresh: () => Promise<void>;" in source, (
        "The refresh action must be declared on BootstrapState, or nothing outside the "
        "store can call it"
    )

    body = _refresh_action()
    assert "await fetchBootstrap()" in body, (
        "The refresh must re-read /api/v2/bootstrap. The server decides whether the "
        "classification banner exists at all -- it is emitted only when enabled and "
        "non-empty -- and applies its colour defaults, so the browser cannot re-derive it"
    )
    assert "set({ data })" in body, "The refresh must apply the payload it fetched"

    print("Bootstrap refresh action test passed!")
    return True


def test_the_refresh_never_drives_the_boot_screen():
    """A background refetch must not take down the page the reader is working on."""
    print("Testing that the refresh stays silent...")

    body = _strip_comments(_refresh_action())

    assert "loading" not in body, (
        "The refresh must not set `loading`. App.tsx renders BootScreen instead of the "
        "whole interface while it is set, so the admin page would be torn down mid-edit "
        "and the unsaved draft lost"
    )
    assert "error" not in body and "authExpired" not in body, (
        "The refresh must not set `error` or `authExpired`. App.tsx renders BootError "
        "instead of the whole interface when `error` is set, so a failed background "
        "refetch would replace a page whose save had just succeeded"
    )

    # The failure has to be swallowed deliberately rather than left to reject unhandled.
    assert "} catch {" in body, (
        "A failed refresh is advisory: the write it follows already succeeded, so a "
        "briefly stale shell is cosmetic and the next full load corrects it"
    )

    # load() is what the boot sequence uses and it must keep its reporting.
    load = re.search(r"    load: async \(\) => \{(.|\n)*?\n    \},", _read(
        V2_SRC / "stores" / "bootstrapStore.ts"
    ))
    assert load and "loading: true" in load.group(0), (
        "load() must still report progress; the silent behaviour belongs to refresh() "
        "alone, because a first load has nothing on screen to preserve"
    )

    print("Silent refresh test passed!")
    return True


def test_a_slow_refresh_cannot_overwrite_a_newer_one():
    """Two saves in a row race, and the older response must not win."""
    print("Testing the refresh sequence guard...")

    source = _read(V2_SRC / "stores" / "bootstrapStore.ts")
    body = _refresh_action()

    assert "let refreshSequence = 0;" in source, (
        "Concurrent refreshes need ordering; nothing guarantees responses arrive in the "
        "order their requests left"
    )
    assert "const sequence = ++refreshSequence;" in body, (
        "Each refresh must claim a sequence number before it starts"
    )
    assert "if (sequence === refreshSequence) {" in body, (
        "A refresh must apply its payload only while it is still the newest, or two "
        "quick saves can leave the interface showing the state from before the second"
    )

    # The claim has to happen before the request, or every refresh looks like the newest.
    assert body.index("const sequence") < body.index("await fetchBootstrap()"), (
        "The sequence must be claimed before awaiting, not after"
    )

    print("Refresh sequence guard test passed!")
    return True


def test_the_admin_page_refreshes_the_shell_after_writing():
    """Both admin write paths persist immediately, so both must refresh."""
    print("Testing the admin settings save and upload...")

    source = _read(V2_SRC / "pages" / "AdminSettingsPage.tsx")

    assert "const refreshBootstrap = useBootstrapStore((state) => state.refresh);" in source, (
        "The admin page must hold the refresh action to be able to call it"
    )

    save = re.search(r"    const save = useCallback\(async \(\) => \{(.|\n)*?\n    \}, \[[^\]]*\]\);", source)
    assert save, "AdminSettingsPage should define a save callback"
    save_body = save.group(0)

    assert "void refreshBootstrap();" in save_body, (
        "A successful save must re-read bootstrap. The settings edited here are the same "
        "ones the shell draws itself from, and it holds the payload from page load"
    )
    assert "refreshBootstrap]" in save_body, (
        "refreshBootstrap must be a dependency of the save callback"
    )

    # The refresh belongs to the success path; a rejected save changed nothing to re-read.
    assert save_body.index("void refreshBootstrap();") < save_body.index("} catch ("), (
        "The refresh must sit on the success path, not after the catch: a rejected save "
        "leaves the settings document untouched"
    )

    upload = re.search(
        r"    const onBrandingUploaded = useCallback\((.|\n)*?\n    \);", source
    )
    assert upload, "AdminSettingsPage should define a branding upload callback"
    assert "void refreshBootstrap();" in upload.group(0), (
        "A branding image upload writes to the settings document immediately rather than "
        "waiting for Save, so the rail would keep drawing the previous logo -- and its "
        "URL is version-stamped, so only a refetch busts the cache"
    )

    print("Admin settings save and upload test passed!")
    return True


def test_the_banner_is_read_from_the_refreshed_payload():
    """The refresh only fixes the banner if the banner still reads from the store."""
    print("Testing the classification banner source...")

    shell = _read(V2_SRC / "components" / "layout" / "AppShell.tsx")

    assert (
        "useBootstrapStore((state) => state.data?.branding?.classification_banner)" in shell
    ), (
        "The banner must read from the bootstrap store, which is what the refresh "
        "updates. Reading it from anywhere else would put it back out of reach of a save"
    )
    assert "if (!banner?.enabled || !banner.text) {" in shell, (
        "The banner must disappear again when it is turned off or blanked, which is the "
        "same refresh working in reverse"
    )

    print("Classification banner source test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The change is present from the version that introduced it onwards."""
    print("Testing application version...")
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_the_store_can_reread_bootstrap,
        test_the_refresh_never_drives_the_boot_screen,
        test_a_slow_refresh_cannot_overwrite_a_newer_one,
        test_the_admin_page_refreshes_the_shell_after_writing,
        test_the_banner_is_read_from_the_refreshed_payload,
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
