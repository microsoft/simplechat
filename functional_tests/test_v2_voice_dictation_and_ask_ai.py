#!/usr/bin/env python3
# test_v2_voice_dictation_and_ask_ai.py
"""
Functional test for V2 voice dictation speedup, progressive segmentation, and Ask AI voice input.
Version: 0.261.386
Implemented in: 0.261.386

This test ensures that:
1. /api/speech/transcribe-chat uses Azure Speech Fast Transcription API on the configured
   endpoint when available and automatically falls back to Speech SDK continuous recognition.
2. V2 VoiceInput and ComposerEditor render live waveform bars, inline "Listening…" and
   "Finishing…" status indicators (without technical chunk counters), cancel rollback, and
   one-click retry on failure.
3. AssistThread integrates VoiceInput so all V2 Ask AI panels (Agent, Action, Workflow,
   Orchestration Plan, Diagram, Chart, Image, and Pending Action editors) support voice dictation.
4. The Node logic suite (test_v2_voice_dictation_logic.mjs) passes against voice.ts.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_version_at_least_implemented():
    """Verify VERSION in config.py is at least 0.261.386."""
    print("Testing version is at least 0.261.386...")
    assert_app_version_at_least("0.261.386")
    print("Version test passed!")
    return True


def test_backend_fast_transcription_with_sdk_fallback():
    """Verify /api/speech/transcribe-chat uses Fast Transcription API first and falls back to Speech SDK."""
    print("Testing backend speech transcription Fast API and SDK fallback...")
    speech_route = _read(APP_DIR / "route_backend_speech.py")

    assert "_transcribe_audio_with_fast_api" in speech_route, (
        "route_backend_speech.py must use _transcribe_audio_with_fast_api for fast transcription"
    )
    assert "_transcribe_wav_with_speech_sdk" in speech_route, (
        "route_backend_speech.py must retain Speech SDK fallback for sovereign clouds or unsupported regions"
    )
    assert "AZURE_ENVIRONMENT not in (\"usgovernment\", \"custom\")" in speech_route, (
        "Fast Transcription API must be gated on non-sovereign cloud environment"
    )
    assert "'error': str(e)" not in speech_route, (
        "route_backend_speech.py must not leak raw exception strings to the client"
    )

    # Execute the _transcribe_chat_wav helper in isolation with stubbed dependencies.
    namespace = {
        "AZURE_ENVIRONMENT": "public",
        "log_event": lambda *_args, **_kwargs: None,
    }
    fast_calls = []
    sdk_calls = []

    def fake_fast_api(audio_path, filename, content_type, settings, endpoint, locale):
        fast_calls.append((audio_path, filename, content_type, endpoint, locale))
        return ["Compare Q3 renewal clauses", "and highlight indemnity caps."]

    def fake_sdk(audio_path, settings, endpoint, locale):
        sdk_calls.append((audio_path, endpoint, locale))
        return ["Fallback SDK transcript."]

    namespace["_transcribe_audio_with_fast_api"] = fake_fast_api
    namespace["_transcribe_wav_with_speech_sdk"] = fake_sdk

    start = speech_route.index("def _transcribe_chat_wav(")
    end = speech_route.index("def register_route_backend_speech(")
    exec(speech_route[start:end], namespace)  # noqa: S102
    transcribe_chat_wav = namespace["_transcribe_chat_wav"]

    # 1. Commercial cloud happy path uses Fast Transcription API and does not invoke SDK.
    phrases = transcribe_chat_wav(
        "temp.wav",
        {"speech_service_authentication_type": "managed_identity"},
        "https://westus.api.cognitive.microsoft.com/",
        "en-US",
    )
    assert phrases == ["Compare Q3 renewal clauses", "and highlight indemnity caps."]
    assert len(fast_calls) == 1
    assert fast_calls[0][3] == "https://westus.api.cognitive.microsoft.com"
    assert len(sdk_calls) == 0

    # 2. If Fast Transcription API raises (e.g., unsupported region), it falls back to Speech SDK.
    def failing_fast_api(*_args, **_kwargs):
        raise RuntimeError("Fast transcription endpoint unavailable")

    namespace["_transcribe_audio_with_fast_api"] = failing_fast_api
    fallback_phrases = transcribe_chat_wav(
        "temp.wav",
        {},
        "https://westus.api.cognitive.microsoft.com/",
        "en-US",
    )
    assert fallback_phrases == ["Fallback SDK transcript."]
    assert len(sdk_calls) == 1

    # 3. Sovereign cloud (usgovernment) goes directly to Speech SDK.
    namespace["AZURE_ENVIRONMENT"] = "usgovernment"
    gov_phrases = transcribe_chat_wav(
        "temp.wav",
        {},
        "https://virginia.api.cognitive.microsoft.us/",
        "en-US",
    )
    assert gov_phrases == ["Fallback SDK transcript."]
    assert len(sdk_calls) == 2

    print("Backend Fast Transcription + SDK fallback test passed!")
    return True


def test_v2_voice_input_and_composer_ux_contract():
    """Verify VoiceInput, ComposerEditor, Composer, and AssistThread implement the progressive UX."""
    print("Testing V2 VoiceInput, ComposerEditor, Composer, and AssistThread contracts...")
    voice_input = _read(V2_SRC / "components" / "chat" / "VoiceInput.tsx")
    composer_editor = _read(V2_SRC / "components" / "chat" / "ComposerEditor.tsx")
    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")
    assist_thread = _read(V2_SRC / "components" / "chat" / "AssistThread.tsx")

    # VoiceInput must provide live waveform bars, Finishing… state, cancel rollback, and Retry pill.
    assert 'data-testid="voice-input-waveform"' in voice_input
    assert 'data-testid="voice-input-finishing"' in voice_input
    assert "Finishing…" in voice_input
    assert 'data-testid="voice-input-error-pill"' in voice_input
    assert "Last clip failed" in voice_input
    assert "Retry" in voice_input
    assert "shouldFlushSpeechSegment(" in voice_input
    assert "pcmChunksToWav(" in voice_input

    # Ensure no user-facing "chunk" label appears in VoiceInput or ComposerEditor.
    assert "chunks transcribed" not in voice_input.lower()
    assert "chunk " not in composer_editor.lower()

    # ComposerEditor must render inline Listening… and Finishing… status when voiceStatus is active.
    assert 'data-testid="voice-dictation-status"' in composer_editor
    assert "Listening…" in composer_editor
    assert "Finishing…" in composer_editor

    # Composer and AssistThread must both wire VoiceInput with progressive append and cancel rollback.
    for name, source in (("Composer.tsx", composer), ("AssistThread.tsx", assist_thread)):
        assert "<VoiceInput" in source, f"{name} must render VoiceInput"
        assert "appendDictatedText(" in source, f"{name} must use appendDictatedText"
        assert "revertDictatedSegments(" in source, f"{name} must roll back cancelled dictation"
        assert "voiceStatus={voiceStatus}" in source, f"{name} must pass voiceStatus to ComposerEditor"

    print("V2 VoiceInput, Composer, and AssistThread UX contract test passed!")
    return True


def test_node_voice_dictation_logic_suite():
    """Run the Node TypeScript logic tests in test_v2_voice_dictation_logic.mjs."""
    print("Running Node test_v2_voice_dictation_logic.mjs...")
    script = Path(__file__).with_name("test_v2_voice_dictation_logic.mjs")
    result = subprocess.run(
        ["node", str(script)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError(f"test_v2_voice_dictation_logic.mjs failed with exit code {result.returncode}")
    print(result.stdout.strip())
    return True


if __name__ == "__main__":
    tests = [
        test_version_at_least_implemented,
        test_backend_fast_transcription_with_sdk_fallback,
        test_v2_voice_input_and_composer_ux_contract,
        test_node_voice_dictation_logic_suite,
    ]
    results = []
    for test_fn in tests:
        print(f"\nRunning {test_fn.__name__}...")
        try:
            results.append(bool(test_fn()))
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
