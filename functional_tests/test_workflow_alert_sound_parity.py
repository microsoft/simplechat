#!/usr/bin/env python3
# test_workflow_alert_sound_parity.py
"""
Functional test for the workflow alert sound contract shared by classic and V2.
Version: 0.261.234
Implemented in: 0.261.234

Classic pages and the V2 frame take turns sounding through one Web Lock, share the per-device
"Play alert sounds" switch and the browser-wide "sounded once" record, and announce
acknowledgments on one BroadcastChannel. This test ensures both sides still use the same names,
timings, limits and tones, since a mismatch would silently let two tabs sound at once, chime twice
for one alert, or keep sounding after another tab acknowledged it.
"""

import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CLASSIC_SOUND = ROOT_DIR / "application" / "single_app" / "static" / "js" / "workflow-alert-sound.js"
CLASSIC_NOTIFICATIONS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "notifications.js"
V2_LIB = ROOT_DIR / "application" / "v2_ui" / "src" / "lib"
V2_SOUND = V2_LIB / "workflowAlertSound.ts"
V2_DEVICE_PREFERENCES = V2_LIB / "workflowAlertDevicePreferences.ts"
V2_ACTIONS = V2_LIB / "workflowAlertActions.ts"
V2_STORE = ROOT_DIR / "application" / "v2_ui" / "src" / "stores" / "workflowAlertStore.ts"
AUDIO_DIR = ROOT_DIR / "application" / "single_app" / "static" / "audio" / "workflow-alerts"
TONES = ("alarm.wav", "urgent.wav", "chime.wav")


def read(path):
    return path.read_text(encoding="utf-8")


def string_constant(source, name):
    match = re.search(rf"\b{re.escape(name)}\s*=\s*'([^']+)'", source)
    assert match, f"{name} is not declared as a string constant"
    return match.group(1)


def numeric_constant(source, name):
    """A constant written as a product of whole numbers, such as 25 * 3_600_000."""
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([\d_\s*]+);", source)
    assert match, f"{name} is not declared as a whole-number constant"
    value = 1
    for factor in match.group(1).split("*"):
        value *= int(factor.strip().replace("_", ""))
    return value


def test_both_sides_share_the_lock_storage_and_timing():
    """Classic and V2 name the same lock, keys and limits."""
    classic = read(CLASSIC_SOUND)
    v2 = read(V2_SOUND)
    v2_preferences = read(V2_DEVICE_PREFERENCES)

    assert string_constant(classic, "lockName") == string_constant(v2, "LOCK_NAME") == "simplechat.workflowAlertSound"
    assert (
        string_constant(classic, "soundedOnceStorageKey")
        == string_constant(v2, "SOUNDED_ONCE_KEY")
        == "simplechat.workflowAlerts.soundedOnce"
    )
    assert (
        string_constant(classic, "playSoundsStorageKey")
        == string_constant(v2_preferences, "WORKFLOW_ALERT_PLAY_SOUNDS_KEY")
        == "simplechat.workflowAlerts.playSounds"
    )
    assert numeric_constant(classic, "soundedOnceTtlMs") == numeric_constant(v2, "SOUNDED_ONCE_TTL_MS") == 25 * 3_600_000
    assert numeric_constant(classic, "soundedOnceMax") == numeric_constant(v2, "SOUNDED_ONCE_MAX") == 500
    assert (
        numeric_constant(classic, "WORKFLOW_ALERT_SOUND_REPEAT_MS")
        == numeric_constant(v2, "WORKFLOW_ALERT_SOUND_REPEAT_MS")
        == 5_000
    )


def test_both_sides_announce_acknowledgments_on_one_channel():
    """Every BroadcastChannel either side opens for alerts is the same one."""
    channel = "simplechat.workflowAlerts"
    assert f"new BroadcastChannel('{channel}')" in read(CLASSIC_NOTIFICATIONS)
    assert f"new BroadcastChannel('{channel}')" in read(V2_STORE)
    assert string_constant(read(V2_ACTIONS), "BROADCAST_CHANNEL") == channel


def test_both_sides_play_the_same_bundled_tones():
    """Each tone either side plays is a bundled file, and both use all three."""
    for path in (CLASSIC_SOUND, V2_SOUND):
        played = set(re.findall(r"'/static/audio/workflow-alerts/([a-z]+\.wav)'", read(path)))
        assert played == set(TONES), f"{path.name} plays {sorted(played)}"
    for tone in TONES:
        assert (AUDIO_DIR / tone).is_file(), f"{tone} is missing"


def main():
    tests = [
        test_both_sides_share_the_lock_storage_and_timing,
        test_both_sides_announce_acknowledgments_on_one_channel,
        test_both_sides_play_the_same_bundled_tones,
    ]
    for test in tests:
        test()
        print(f"Passed: {test.__name__}")
    return True


if __name__ == "__main__":
    try:
        success = main()
    except Exception as error:
        print(f"Failed: {error}")
        raise
    sys.exit(0 if success else 1)
