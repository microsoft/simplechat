#!/usr/bin/env python3
# test_chat_tts_autoplay_toggle.py
"""
Functional test for chat AI voice response autoplay toggle.
Version: 0.242.048
Implemented in: 0.242.048

This test ensures the chat AI voice response toggle enables text-to-speech
playback state as well as autoplay so new assistant messages can start reading
automatically even when older user settings have ttsEnabled saved as false.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_TTS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-tts.js"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"


def read_text(path: Path) -> str:
    """Read a repository file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_chat_tts_autoplay_toggle_enables_tts_state():
    """Verify chat auto voice response enables TTS playback state."""
    print("Testing chat TTS autoplay toggle state contract...")

    config_content = read_text(CONFIG_FILE)
    chat_tts_content = read_text(CHAT_TTS_JS)

    assert 'VERSION = "0.242.048"' in config_content
    assert "ttsEnabled = Boolean(settings.ttsEnabled || settings.ttsAutoplay);" in chat_tts_content
    assert "const previousTTSEnabled = ttsEnabled;" in chat_tts_content
    assert "if (ttsAutoplay) {\n        ttsEnabled = true;\n    }" in chat_tts_content
    assert "settingsUpdate.ttsEnabled = true;" in chat_tts_content
    assert "ttsEnabled = previousTTSEnabled;" in chat_tts_content

    print("PASS: chat TTS autoplay toggle enables playback state")


if __name__ == "__main__":
    test_chat_tts_autoplay_toggle_enables_tts_state()
