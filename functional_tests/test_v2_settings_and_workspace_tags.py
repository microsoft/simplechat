#!/usr/bin/env python3
"""
Functional test for the V2 personal settings page and conversation workspace tags.

Version: 0.261.023
Implemented in: 0.261.020

Two things are pinned here.

**Settings keys must be whitelisted.** `/api/user/settings` validates against `allowed_keys`
in route_backend_users.py and drops anything outside it **without complaining** -- the POST
still returns success and the value simply never arrives. A client writing an unlisted key
therefore appears to work and silently loses the preference on every reload. That is the
same failure mode as the model-identity and document-scope defects fixed earlier in the V2
work, where the client sent a field the server never acted on.

**Workspace tags need no server change.** The conversation feed returns the whole
conversation document -- `_strip_internal_feed_fields` removes only `_feed_source` -- and
`chat_type` and `context` are stored on that document. The badge is therefore derivable from
what the list already has. If the feed ever starts projecting a subset of fields, the tags
would silently disappear, so the test asserts the feed still passes the document through.
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


def test_every_key_the_client_writes_is_whitelisted():
    """An unlisted key is dropped silently, so this must never regress."""
    print("Testing settings key whitelist...")

    allowed = _allowed_keys()
    writable = _writable_keys()

    assert writable, "The V2 client should declare the settings keys it writes"

    missing = [key for key in writable if key not in allowed]
    assert not missing, (
        "These keys are written by the V2 client but are not in allowed_keys, so the "
        f"server will accept the request and discard them: {missing}"
    )

    print(f"All {len(writable)} client-written keys are whitelisted!")
    return True


def test_the_workspace_tag_setting_exists_on_both_sides():
    """The new preference has to be declared by the client and accepted by the route."""
    print("Testing the workspace tag setting...")

    assert "showConversationWorkspaceTags" in _allowed_keys(), (
        "showConversationWorkspaceTags must be added to allowed_keys or the toggle will "
        "appear to save and then reset on reload"
    )
    assert "showConversationWorkspaceTags" in _writable_keys(), (
        "The client must declare the key it writes so the whitelist check covers it"
    )

    rail = _read(V2_SRC / "components" / "chat" / "ConversationRail.tsx")
    assert "showConversationWorkspaceTags" in rail, (
        "The conversation list must respect the setting"
    )
    # Absent means on: the information is useful and was previously missing entirely.
    assert "!== false" in rail, (
        "The tag should default to shown when the preference has never been set"
    )

    preferences = _read(V2_SRC / "components" / "settings" / "PreferencesTab.tsx")
    assert "showConversationWorkspaceTags" in preferences, (
        "The setting needs a control on the preferences tab"
    )

    print("Workspace tag setting test passed!")
    return True


def test_tags_are_derived_from_the_feed_without_extra_requests():
    """The list must not fetch metadata per row to label a conversation."""
    print("Testing tag derivation...")

    feed = _read(APP_DIR / "functions_conversation_feed.py")
    strip = re.search(r"def _strip_internal_feed_fields\((.|\n)*?\n\n", feed).group(0)
    popped = re.findall(r"public_item\.pop\('([^']+)'", strip)
    assert popped == ["_feed_source"], (
        "The feed no longer passes the whole conversation document through -- it now "
        f"removes {popped}. Workspace tags read chat_type and context from the feed, so "
        "they would silently disappear."
    )

    metadata = _read(APP_DIR / "functions_conversation_metadata.py")
    assert "conversation_item['chat_type']" in metadata, (
        "chat_type is expected to live on the conversation document"
    )
    assert "conversation_item['context']" in metadata, (
        "context is expected to live on the conversation document"
    )

    # The badge helper must accept a feed conversation, not only the metadata payload.
    badges = _read(V2_SRC / "lib" / "conversationBadges.ts")
    assert "export type BadgeSource" in badges, (
        "The badge helper needs to accept both the metadata payload and a feed conversation"
    )
    assert "Conversation, ConversationMetadata" in badges or "ConversationMetadata | Conversation" in badges

    rail = _read(V2_SRC / "components" / "chat" / "ConversationRail.tsx")
    assert "workspaceBadge(conversation)" in rail, (
        "The tag must be derived from the conversation the list already holds"
    )
    assert "fetchMessageMetadata" not in rail and "loadMetadata" not in rail, (
        "The list must not fetch metadata per row; that would be one request per "
        "conversation on every page of the feed"
    )

    print("Tag derivation test passed!")
    return True


def test_settings_saves_are_debounced_and_recoverable():
    """A dropped save must not leave a control showing a value that was never stored."""
    print("Testing settings save behaviour...")

    store = _read(V2_SRC / "stores" / "userSettingsStore.ts")

    assert "SAVE_DEBOUNCE_MS" in store, (
        "Saves must be debounced, or dragging a slider issues one request per frame"
    )
    assert "pending = { ...pending, ...partial }" in store, (
        "Pending keys must be merged into one request; separate requests would race"
    )
    assert "rollback" in store, (
        "A failed save must revert the control, otherwise the user sees a value the "
        "server never stored and has no way to find out"
    )
    assert re.search(r"catch \(error\)(.|\n)*?\.\.\.previous", store), (
        "The rollback must be applied in the failure branch"
    )

    print("Settings save behaviour test passed!")
    return True


def test_gated_tabs_are_hidden_rather_than_empty():
    """A tab whose capability is off can only render an error, so it must not appear."""
    print("Testing settings tab gating...")

    tabs = _read(V2_SRC / "components" / "settings" / "tabs.tsx")
    for flag in (
        "enable_group_workspaces",
        "enable_public_workspaces",
        "enable_user_feedback",
        "enable_content_safety",
    ):
        assert flag in tabs, f"The tab registry should gate on {flag}"

    page = _read(V2_SRC / "pages" / "SettingsPage.tsx")
    assert re.search(r"SETTINGS_TABS\.filter\((.|\n)*?features\[tab\.feature\] === true", page), (
        "Tabs must be filtered by their capability flag before rendering"
    )

    print("Settings tab gating test passed!")
    return True


def test_only_settings_this_interface_honours_are_offered():
    """A control that changes nothing here is worse than its absence.

    Several classic preferences drive V1-only surfaces — the tutorial buttons on its pages,
    its sidebar hide-control style. Offering them in V2 would either do nothing visible or
    silently change the other interface, so the preferences tab covers the ones V2 acts on
    and leaves the rest to the classic page.
    """
    print("Testing preference honouring...")

    preferences = _read(V2_SRC / "components" / "settings" / "PreferencesTab.tsx")

    # Each offered setting is wired to something.
    app = _read(V2_SRC / "App.tsx")
    assert "dataset.fontSize" in app, (
        "Text size must be applied at startup, not only while the control is on screen"
    )
    theme_css = _read(V2_SRC / "styles" / "theme.css")
    for size in ("xs", "s", "m", "l", "xl"):
        assert f"html[data-font-size='{size}']" in theme_css, (
            f"The {size!r} text scale has no rule, so choosing it would do nothing"
        )

    actions = _read(V2_SRC / "components" / "chat" / "MessageActions.tsx")
    assert "settings.ttsVoice" in actions, (
        "The chosen voice must reach the speech call, or the picker does nothing"
    )

    # Settings V2 does not act on are deliberately not offered.
    for absent in ("sidebarToggleStyle", "showTutorialButtons"):
        assert absent not in preferences, (
            f"{absent!r} drives a classic-interface surface with no V2 equivalent; offering "
            "it here would change the other interface with no visible effect in this one"
        )

    print("Preference honouring test passed!")
    return True


def test_the_text_scale_matches_the_classic_interface():
    """A size chosen in one interface has to mean the same in the other."""
    print("Testing text scale parity...")

    classic = _read(APP_DIR / "static" / "css" / "styles.css")
    v2 = _read(V2_SRC / "styles" / "theme.css")

    for size, percent in (("xs", "75%"), ("s", "87.5%"), ("m", "100%"), ("l", "150%"), ("xl", "200%")):
        assert re.search(
            rf'html\[data-font-size="{size}"\]\s*\{{\s*font-size:\s*{re.escape(percent)}',
            classic,
        ), f"The classic scale for {size!r} is no longer {percent}; V2's copy has drifted"
        assert re.search(
            rf"html\[data-font-size='{size}'\]\s*\{{\s*font-size:\s*{re.escape(percent)}",
            v2,
        ), f"V2's scale for {size!r} does not match the classic interface"

    print("Text scale parity test passed!")
    return True


def test_shell_preferences_persist_per_user():
    """Theme, rail and chat width follow the user rather than the browser."""
    print("Testing shell preference persistence...")

    ui = _read(V2_SRC / "stores" / "uiStore.ts")

    # Theme deliberately shares the classic key so the two interfaces agree.
    assert "darkModeEnabled: theme === 'dark'" in ui, (
        "The theme should be stored under the key the classic interface already uses, so "
        "choosing dark in one place applies to both"
    )
    assert "darkModeEnabled" in _allowed_keys(), "darkModeEnabled must be whitelisted"

    # Rail and width are namespaced, because the classic equivalents mean something else.
    for key in ("v2RailCollapsed", "v2ChatWidth"):
        assert key in ui, f"{key} should be written when its control changes"
        assert key in _allowed_keys(), f"{key} must be whitelisted or it is silently dropped"
        assert key in _writable_keys(), f"{key} must be declared by the client"

    for classic_key in ("dockedSidebarHidden", "chatLayout"):
        assert classic_key not in ui, (
            f"{classic_key} describes the classic interface's own layout; writing it from "
            "here would rearrange that interface as a side effect"
        )

    # localStorage stays as the first-paint cache, or the theme flashes on every load.
    assert "localStorage.setItem" in ui, (
        "The local cache must be kept: the settings request has not resolved during the "
        "first render, so hydrating only from the server flashes the wrong theme"
    )
    assert "export function hydrateUiPreferences" in ui, (
        "The server's values need to be adopted once they arrive"
    )

    app = _read(V2_SRC / "App.tsx")
    assert "hydrateUiPreferences" in app, "Hydration must run after the settings load"

    print("Shell preference persistence test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added this."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.020")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_every_key_the_client_writes_is_whitelisted,
        test_the_workspace_tag_setting_exists_on_both_sides,
        test_tags_are_derived_from_the_feed_without_extra_requests,
        test_settings_saves_are_debounced_and_recoverable,
        test_gated_tabs_are_hidden_rather_than_empty,
        test_only_settings_this_interface_honours_are_offered,
        test_the_text_scale_matches_the_classic_interface,
        test_shell_preferences_persist_per_user,
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
