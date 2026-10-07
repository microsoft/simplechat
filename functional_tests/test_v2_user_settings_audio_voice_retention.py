#!/usr/bin/env python3
# test_v2_user_settings_audio_voice_retention.py
"""
Functional test for V2 User Settings voice, audio and retention parity.
Version: 0.261.278
Implemented in: 0.261.278

V2 Preferences now carries the classic profile page's completion sounds, spoken reply voice,
speed and auto-play, microphone permission status, and personal retention period, each with
the runtime behaviour behind it. The personal retention route also accepts 'default', which
the "Organization default" choice sends. This file pins those contracts.
"""

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
SETTINGS_DIR = V2_SRC / "components" / "settings"
PREFERENCES_TSX = SETTINGS_DIR / "PreferencesTab.tsx"
VOICE_CARDS_TSX = SETTINGS_DIR / "VoiceAudioCards.tsx"
RETENTION_CARD_TSX = SETTINGS_DIR / "RetentionCard.tsx"
COMPLETION_AUDIO_TS = V2_SRC / "lib" / "completionAudio.ts"
SPEECH_PLAYBACK_TS = V2_SRC / "lib" / "speechPlayback.ts"
VOICE_TS = V2_SRC / "lib" / "voice.ts"
RUNTIME_TS = V2_SRC / "lib" / "useNotificationRuntime.ts"
MESSAGE_ACTIONS_TSX = V2_SRC / "components" / "chat" / "MessageActions.tsx"
USER_SETTINGS_TS = V2_SRC / "lib" / "userSettings.ts"
USERS_ROUTE = APP_DIR / "route_backend_users.py"
RETENTION_ROUTE = APP_DIR / "route_backend_retention_policy.py"
CUE_DIR = APP_DIR / "static" / "audio" / "completion-cues"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_version_is_at_least_the_implementing_release():
    print("Testing the application version...")
    assert_app_version_at_least("0.261.278")
    return True


def test_cards_are_gated_by_their_capabilities():
    print("Testing the voice, audio and retention cards are gated...")
    preferences = _read(PREFERENCES_TSX)
    for flag, card in (
        ("enable_chat_completion_audio_cues", "<CompletionAudioCard"),
        ("enable_text_to_speech", "<SpokenRepliesCard"),
        ("enable_speech_to_text_input", "<MicrophoneCard"),
        ("enable_retention_policy_personal", "<RetentionCard"),
    ):
        guard = f"{{enabled('{flag}') && "
        assert guard in preferences, f"{card} is not gated by {flag}"
        assert preferences.index(guard) < preferences.index(card), f"{card} appears outside its guard"
    assert 'id="voice-audio"' in preferences
    assert 'id="memory-data"' in preferences
    # The old hard-coded voice list was replaced by the live voice catalogue.
    assert "TTS_VOICES" not in preferences
    return True


def test_preference_keys_are_writable_on_both_sides():
    print("Testing the preference keys can be saved...")
    client = _read(USER_SETTINGS_TS)
    server = _read(USERS_ROUTE)
    for key in (
        "chatCompletionAudioEnabled",
        "chatCompletionAudioMuted",
        "chatCompletionAudioSound",
        "chatCompletionAudioVolume",
        "ttsEnabled",
        "ttsVoice",
        "ttsSpeed",
        "ttsAutoplay",
    ):
        assert f"'{key}'" in client, f"{key} is not writable from V2"
        assert f"'{key}'" in server, f"{key} is not accepted by the settings route"
    return True


def test_completion_sounds_use_the_shared_catalogue():
    print("Testing completion sounds...")
    audio = _read(COMPLETION_AUDIO_TS)
    assert "/static/audio/completion-cues/" in audio
    sounds = {path.stem for path in CUE_DIR.glob("*.wav")}
    assert sounds, "No completion cue sounds found"
    for sound in sounds:
        assert f"'{sound}'" in audio, f"Sound {sound} is not offered in V2"
    cards = _read(VOICE_CARDS_TSX)
    assert "previewCompletionSound" in cards
    return True


def test_spoken_replies_send_speed_and_use_one_reader():
    print("Testing spoken replies...")
    voice = _read(VOICE_TS)
    assert "speed" in voice and "body.speed" in voice
    playback = _read(SPEECH_PLAYBACK_TS)
    assert "export async function speak(" in playback
    assert "export function stopSpeech(" in playback
    assert "createSpeechAutoplayListener" in playback
    actions = _read(MESSAGE_ACTIONS_TSX)
    assert "useSpeechState" in actions and "synthesizeSpeech" not in actions
    cards = _read(VOICE_CARDS_TSX)
    assert "/api/chat/tts/voices" in cards
    assert "ttsAutoplay: true, ttsEnabled: true" in cards.replace("\n", " ").replace("  ", " ")
    return True


def test_runtime_listens_for_finished_replies():
    print("Testing the reply listeners are wired...")
    runtime = _read(RUNTIME_TS)
    assert "subscribeCompletedReplies(createCompletionCueListener(" in runtime
    assert "subscribeCompletedReplies(createSpeechAutoplayListener(" in runtime
    assert "stopCues()" in runtime and "stopAutoplay()" in runtime
    return True


def test_microphone_status_does_not_prompt_on_load():
    print("Testing the microphone card...")
    cards = _read(VOICE_CARDS_TSX)
    mic = cards[cards.index("export function MicrophoneCard"):]
    assert "permissions" in mic and "'microphone'" in mic
    # getUserMedia is only reached from the button, never from an effect.
    effect_start = mic.find("useEffect(")
    effect_end = mic.find("});", effect_start)
    assert "getUserMedia" not in mic[effect_start:effect_end]
    assert "getUserMedia" in mic
    return True


def test_retention_card_saves_through_the_personal_route():
    print("Testing the retention card...")
    card = _read(RETENTION_CARD_TSX)
    assert "/api/retention-policy/user" in card
    assert "/api/retention-policy/defaults/personal" in card
    assert 'value="default"' in card
    for days in (1, 7, 30, 90, 365, 730):
        assert f"{days}," in card or f"{days}]" in card
    return True


def _personal_route_source():
    source = _read(RETENTION_ROUTE)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "update_user_retention_settings":
            return ast.get_source_segment(source, node)
    raise AssertionError("update_user_retention_settings not found")


def test_personal_retention_route_accepts_default():
    print("Testing the personal retention route accepts 'default'...")
    body = _personal_route_source()
    for kind, field in (("conv", "conversation_retention_days"), ("doc", "document_retention_days")):
        branch = f"elif {kind}_retention == 'default':"
        assert branch in body, f"{field} does not accept 'default'"
        after = body[body.index(branch):]
        assert f"retention_settings['{field}'] = 'default'" in after.split("else:")[0]
        # 'default' has to be handled before it reaches int().
        assert body.index(branch) < body.index("int(", body.index(f"{kind}_retention ="))
    return True


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_cards_are_gated_by_their_capabilities,
        test_preference_keys_are_writable_on_both_sides,
        test_completion_sounds_use_the_shared_catalogue,
        test_spoken_replies_send_speed_and_use_one_reader,
        test_runtime_listens_for_finished_replies,
        test_microphone_status_does_not_prompt_on_load,
        test_retention_card_saves_through_the_personal_route,
        test_personal_retention_route_accepts_default,
    ]
    results = []
    for test in tests:
        try:
            results.append(test() is not False)
        except AssertionError as error:
            print(f"FAILED {test.__name__}: {error}")
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
