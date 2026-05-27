# test_tts_speech_speed_prosody_rate.py
#!/usr/bin/env python3
"""
Functional test for TTS speech speed prosody rate formatting.
Version: 0.241.102
Implemented in: 0.241.102

This test ensures that chat text-to-speech speed multipliers are translated
to Azure Speech SSML relative prosody rates without flattening faster speeds.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "application", "single_app"))

from route_backend_tts import (  # noqa: E402
    _format_tts_prosody_rate,
    _normalize_tts_speed,
)


def test_faster_speeds_use_relative_increase_percentages():
    """Validate 1.1x through 2.0x do not collapse into invalid absolute percentages."""
    assert _format_tts_prosody_rate(1.1) == "+10.00%"
    assert _format_tts_prosody_rate(1.5) == "+50.00%"
    assert _format_tts_prosody_rate(2.0) == "+100.00%"


def test_slower_speeds_use_relative_decrease_percentages():
    """Validate speeds below normal are sent as negative relative percentages."""
    assert _format_tts_prosody_rate(0.9) == "-10.00%"
    assert _format_tts_prosody_rate(0.5) == "-50.00%"


def test_normal_speed_keeps_default_rate():
    """Validate normal speed maps to Azure's default prosody rate."""
    assert _format_tts_prosody_rate(1.0) == "default"


def test_speed_normalization_clamps_to_supported_range():
    """Validate out-of-range speeds are clamped to Azure Speech's supported range."""
    assert _normalize_tts_speed(0.1) == 0.5
    assert _normalize_tts_speed(3.0) == 2.0


def test_invalid_speed_raises_value_error():
    """Validate invalid speed payloads are rejected as client parameter errors."""
    try:
        _normalize_tts_speed("fast")
    except ValueError as ex:
        assert "speed must be a number" in str(ex)
    else:
        raise AssertionError("Invalid speed did not raise ValueError")


if __name__ == "__main__":
    tests = [
        test_faster_speeds_use_relative_increase_percentages,
        test_slower_speeds_use_relative_decrease_percentages,
        test_normal_speed_keeps_default_rate,
        test_speed_normalization_clamps_to_supported_range,
        test_invalid_speed_raises_value_error,
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