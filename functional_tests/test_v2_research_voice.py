#!/usr/bin/env python3
"""
Functional test for V2 chat research, reasoning and voice controls.

Version: 0.261.009
Implemented in: 0.261.009

This test ensures the V2 composer sends the request fields the chat endpoint actually
reads, and that the reasoning effort control offers exactly the levels each model family
supports.

Two details are easy to get wrong and are asserted directly:

* Deep research is carried by TWO fields, source_review_enabled and deep_research_enabled.
  Sending only one silently disables half the behaviour.
* Reasoning support is per model family. Offering a level a model rejects produces a
  request the endpoint has to strip; hiding a level it supports removes a capability.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
LEGACY_CHAT_JS = APP_DIR / "static" / "js" / "chat"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def test_research_request_fields_match_the_backend():
    """Deep research and URL access send the fields the chat route reads."""
    print("Testing research request fields...")

    chats = _read(APP_DIR / "route_backend_chats.py")
    for field in ("source_review_enabled", "deep_research_enabled", "url_access_enabled"):
        assert field in chats, f"The chat route no longer reads {field!r}"

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    # Both deep-research fields must be sent together; the existing client does the same.
    assert "source_review_enabled: options.deepResearch" in store, (
        "Deep research must set source_review_enabled"
    )
    assert "deep_research_enabled: options.deepResearch" in store, (
        "Deep research must ALSO set deep_research_enabled; sending only one field "
        "silently disables query planning"
    )
    assert "url_access_enabled: options.urlAccess" in store, (
        "URL access must send url_access_enabled"
    )

    print("Research request field test passed!")
    return True


def test_research_controls_are_gated_on_their_settings():
    """Research controls appear only when their capability is enabled."""
    print("Testing research gating...")

    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")
    gating = _read(V2_SRC / "lib" / "composerGating.ts")

    # The capability checks live in the gating module; the composer consumes its result.
    assert "enable_source_review" in gating, (
        "Deep research must be gated on enable_source_review"
    )
    assert "gating.showDeepResearch" in composer, (
        "The composer must respect the resolved deep research gate"
    )
    assert "enable_url_access" in gating, (
        "URL access must be gated on enable_url_access"
    )
    assert "gating.showUrlAccess" in composer, (
        "The composer must respect the resolved URL access gate"
    )
    assert "features.enable_speech_to_text_input" in composer, (
        "Voice input must be gated on enable_speech_to_text_input"
    )

    # These are computed per user, so the bootstrap must resolve them rather than
    # forwarding the raw admin setting.
    bootstrap = _read(APP_DIR / "route_backend_v2.py")
    assert "is_source_review_enabled_for_user(" in bootstrap
    assert "is_url_access_enabled_for_user(" in bootstrap

    print("Research gating test passed!")
    return True


def test_reasoning_levels_match_the_existing_client():
    """Each model family offers exactly the levels chat-reasoning.js allows."""
    print("Testing reasoning level parity...")

    legacy = _read(LEGACY_CHAT_JS / "chat-reasoning.js")
    v2 = _read(V2_SRC / "lib" / "reasoning.ts")

    # Model families whose supported set differs; a mismatch here is a real capability bug.
    families = {
        "gpt-4o": ["none"],
        "gpt-5-pro": ["high"],
        "gpt-5.1": ["none", "minimal", "medium", "high"],
        "gpt-5": ["minimal", "low", "medium", "high"],
    }

    for family, expected in families.items():
        assert family in legacy, f"chat-reasoning.js no longer special-cases {family!r}"
        assert family in v2, f"The V2 reasoning map is missing {family!r}"

        # The expected set must appear verbatim in the V2 map.
        rendered = ", ".join(f"'{level}'" for level in expected)
        assert rendered in v2, (
            f"{family!r} should offer [{rendered}] in the V2 reasoning map"
        )

    # o-series is matched by pattern rather than a literal name in both implementations.
    assert re.search(r"\\bo\[0-9\]", v2) or "o[0-9]" in v2, (
        "The o-series pattern is missing from the V2 reasoning map"
    )

    print("Reasoning level parity test passed!")
    return True


def test_reasoning_control_is_hidden_when_unsupported():
    """The reasoning control is not shown for models that offer no choice."""
    print("Testing reasoning control visibility...")

    v2 = _read(V2_SRC / "lib" / "reasoning.ts")
    assert "export function supportsReasoning" in v2, (
        "A support check is needed so the control can be hidden for models like gpt-4o"
    )

    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")
    assert "reasoningLevels.length > 0" in composer, (
        "The reasoning control must be conditional on the model supporting it"
    )

    print("Reasoning visibility test passed!")
    return True


def test_voice_endpoints_and_payloads():
    """Voice input and output call the right endpoints with the right payloads."""
    print("Testing voice endpoints...")

    speech = _read(APP_DIR / "route_backend_speech.py")
    assert "/api/speech/transcribe-chat" in speech, "The transcription route is missing"
    assert "enable_speech_to_text_input" in speech, (
        "Transcription is gated on enable_speech_to_text_input"
    )

    tts = _read(APP_DIR / "route_backend_tts.py")
    assert '"/api/chat/tts"' in tts, "The speech synthesis route is missing"
    assert "enable_text_to_speech" in tts, (
        "Synthesis is gated on enable_text_to_speech"
    )

    voice = _read(V2_SRC / "lib" / "voice.ts")

    # The route reads the file from an 'audio' form field; anything else is ignored.
    assert "formData.append('audio'" in voice, (
        "The transcription upload must use the 'audio' form field"
    )
    # Azure Speech expects 16 kHz mono, and MediaRecorder rarely produces WAV directly.
    assert "16000" in voice, "Audio must be resampled to 16 kHz before upload"
    assert "encodeWav" in voice, (
        "The recording must be re-encoded as WAV; browsers typically capture WebM/Opus"
    )
    # Synthesis returns an audio stream rather than JSON.
    assert "response.blob()" in voice, (
        "Speech synthesis returns an audio stream, not JSON"
    )

    print("Voice endpoint test passed!")
    return True


def test_no_unwired_preview_controls_remain_in_the_composer():
    """Every composer control is now wired; none are left as visible stubs."""
    print("Testing for leftover stubs...")

    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")
    assert "NotWiredBadge" not in composer, (
        "The composer still renders a not-wired badge; these controls are implemented now"
    )
    assert "not wired up yet" not in composer, (
        "The composer still describes a control as unwired"
    )

    print("Leftover stub test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added these controls."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.009")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_research_request_fields_match_the_backend,
        test_research_controls_are_gated_on_their_settings,
        test_reasoning_levels_match_the_existing_client,
        test_reasoning_control_is_hidden_when_unsupported,
        test_voice_endpoints_and_payloads,
        test_no_unwired_preview_controls_remain_in_the_composer,
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
