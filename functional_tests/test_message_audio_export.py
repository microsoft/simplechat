# test_message_audio_export.py
#!/usr/bin/env python3
"""
Functional test for per-message MP3 audio export.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures user and assistant messages expose a text-to-speech-gated
audio export that downloads MP3 bytes using the active TTS voice and speed.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
EXPORT_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-message-export.js"
MESSAGES_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
TTS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-tts.js"
TTS_ROUTE_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_tts.py"


def read_text(path: Path) -> str:
    """Read a repository file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_audio_export_uses_existing_mp3_tts_contract():
    """Verify audio export reuses the authenticated MP3 synthesis endpoint."""
    tts_source = read_text(TTS_FILE)
    route_source = read_text(TTS_ROUTE_FILE)

    assert "export async function synthesizeSpeechBlob(text)" in tts_source
    assert "fetch('/api/chat/tts'" in tts_source
    assert "voice: ttsVoice" in tts_source
    assert "speed: ttsSpeed" in tts_source
    assert "return response.blob();" in tts_source
    assert "Audio48Khz192KBitRateMonoMp3" in route_source
    assert "mimetype='audio/mpeg'" in route_source
    assert "as_attachment=False" in route_source


def test_audio_export_downloads_visible_message_text():
    """Verify the browser downloads visible message text as a timestamped MP3."""
    export_source = read_text(EXPORT_FILE)

    assert "function getMessagePlainText(messageDiv)" in export_source
    assert "messageText.innerText || messageText.textContent" in export_source
    assert "export async function exportMessageAsAudio(messageDiv, messageId, role)" in export_source
    assert "window.appSettings?.enable_text_to_speech" in export_source
    assert "const { synthesizeSpeechBlob } = await import('./chat-tts.js');" in export_source
    assert "const audioBlob = await synthesizeSpeechBlob(content);" in export_source
    assert "message_audio_${filenameTimestamp()}.mp3" in export_source
    assert "downloadBlob(audioBlob, filename);" in export_source


def test_audio_export_menu_is_gated_for_user_and_assistant_messages():
    """Verify both message roles expose the action only under the TTS flag."""
    messages_source = read_text(MESSAGES_FILE)

    assert "actionName: 'exportMessageAsAudio'" in messages_source
    assert "selectors: ['.dropdown-export-audio-btn', '.inline-export-audio-btn']" in messages_source
    assert messages_source.count("const audioExportMenuItemHtml = window.appSettings?.enable_text_to_speech") == 2
    assert messages_source.count("dropdown-export-audio-btn") >= 3
    assert messages_source.count("${audioExportMenuItemHtml}") == 2
    assert 'data-default-label="Export to Audio"' in messages_source
    assert 'data-pending-label="Creating Audio File..."' in messages_source


def test_audio_export_version_is_current():
    """Verify the feature version is recorded in application configuration."""
    assert 'VERSION = "0.250.102"' in read_text(CONFIG_FILE)


if __name__ == "__main__":
    tests = [
        test_audio_export_uses_existing_mp3_tts_contract,
        test_audio_export_downloads_visible_message_text,
        test_audio_export_menu_is_gated_for_user_and_assistant_messages,
        test_audio_export_version_is_current,
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
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    raise SystemExit(0 if all(results) else 1)
