# test_tts_voice_fallback.py
#!/usr/bin/env python3
"""
Functional test for TTS live voice fallback.
Version: 0.241.099
Implemented in: 0.241.099

This test ensures that unavailable saved TTS voices fall back to a supported
voice and that Azure unsupported-voice errors are detected for retry handling.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "application", "single_app"))

from route_backend_tts import (  # noqa: E402
    _get_backup_tts_voices,
    _is_unsupported_tts_voice_error,
    _select_supported_tts_voice,
)


def test_requested_voice_is_used_when_available():
    """Validate that a supported requested voice is preserved."""
    voices = [
        {"name": "en-US-AndrewMultilingualNeural", "locale": "en-US"},
        {"name": "en-US-AvaMultilingualNeural", "locale": "en-US"},
    ]

    selected_voice = _select_supported_tts_voice("en-US-AvaMultilingualNeural", voices)
    assert selected_voice == "en-US-AvaMultilingualNeural"


def test_unavailable_saved_dragon_voice_falls_back():
    """Validate that a stale DragonHD voice falls back to the preferred live voice."""
    voices = [
        {"name": "en-US-AndrewMultilingualNeural", "locale": "en-US"},
        {"name": "en-US-AvaMultilingualNeural", "locale": "en-US"},
    ]

    selected_voice = _select_supported_tts_voice("en-US-Ava:DragonHDLatestNeural", voices)
    assert selected_voice == "en-US-AndrewMultilingualNeural"


def test_excluded_rejected_voice_selects_next_available_voice():
    """Validate retry fallback skips the voice Azure already rejected."""
    voices = [
        {"name": "en-US-AndrewMultilingualNeural", "locale": "en-US"},
        {"name": "en-US-AvaMultilingualNeural", "locale": "en-US"},
    ]

    selected_voice = _select_supported_tts_voice(
        None,
        voices,
        excluded_voice_names={"en-US-AndrewMultilingualNeural"},
    )
    assert selected_voice == "en-US-AvaMultilingualNeural"


def test_unsupported_voice_error_detection():
    """Validate Azure unsupported-voice cancellation details trigger fallback retry."""
    error_details = (
        "Connection was closed by the remote host. Error code: 1007. "
        "Error details: Unsupported voice en-US-Ava:DragonHDLatestNeural."
    )

    assert _is_unsupported_tts_voice_error(error_details) is True


def test_backup_voices_use_broadly_available_neural_names():
    """Validate static backup voices avoid DragonHD-only names."""
    backup_voices = _get_backup_tts_voices()

    assert backup_voices[0]["name"] == "en-US-AndrewMultilingualNeural"
    assert all("DragonHD" not in voice["name"] for voice in backup_voices)


if __name__ == "__main__":
    tests = [
        test_requested_voice_is_used_when_available,
        test_unavailable_saved_dragon_voice_falls_back,
        test_excluded_rejected_voice_selects_next_available_voice,
        test_unsupported_voice_error_detection,
        test_backup_voices_use_broadly_available_neural_names,
    ]
    results = []

    for test in tests:
        print(f"\nTesting {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as ex:
            print(f"Test failed: {ex}")
            import traceback

            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)