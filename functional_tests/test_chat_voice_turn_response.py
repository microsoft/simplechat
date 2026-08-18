#!/usr/bin/env python3
# test_chat_voice_turn_response.py
"""
Functional test for microphone-originated chat response playback.
Version: 0.250.203
Implemented in: 0.250.203

This test ensures a transcribed microphone turn retains voice modality through
chat submission and plays the completed assistant response without duplicating
the user's normal text-to-speech autoplay behavior.
"""

from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_JS_ROOT = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat"
CHAT_SPEECH_INPUT_JS = CHAT_JS_ROOT / "chat-speech-input.js"
CHAT_MESSAGES_JS = CHAT_JS_ROOT / "chat-messages.js"
CHAT_COLLABORATION_JS = CHAT_JS_ROOT / "chat-collaboration.js"


def read_text(path: Path) -> str:
    """Read a repository file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_microphone_auto_send_preserves_voice_modality():
    """Verify transcription auto-send explicitly identifies a voice turn."""
    speech_input_content = read_text(CHAT_SPEECH_INPUT_JS)

    assert_app_version_at_least("0.250.203")
    assert "sendMessage({" in speech_input_content
    assert "inputModality: 'voice'" in speech_input_content
    assert "responseModality: 'voice'" in speech_input_content
    assert "sendBtn.click();" not in speech_input_content


def test_chat_request_and_completion_preserve_voice_response_contract():
    """Verify voice modality reaches the request and terminal TTS callback."""
    messages_content = read_text(CHAT_MESSAGES_JS)

    required_snippets = [
        "export async function sendMessage(turnOptions = {})",
        "actuallySendMessage(combinedMessage, turnOptions);",
        'messageData.input_modality = inputModality;',
        'messageData.response_modality = responseModality;',
        'function buildVoiceResponseCompletionHandler(responseModality) {',
        'if (isTTSAutoplayEnabled()) {',
        'void playTTS(messageId, responseText);',
        'onDone: onVoiceResponseDone,',
        'sendBtn.addEventListener("click", () => sendMessage());',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in messages_content]
    assert not missing, f"Missing voice-turn response contract snippets: {missing}"


def test_collaboration_forwards_initiating_browser_completion_handler():
    """Verify shared AI streams retain voice playback only in the sender tab."""
    collaboration_content = read_text(CHAT_COLLABORATION_JS)

    assert "pendingContext = null, streamOptions = {})" in collaboration_content
    assert "onDone: streamOptions.onDone || null," in collaboration_content


if __name__ == "__main__":
    test_microphone_auto_send_preserves_voice_modality()
    test_chat_request_and_completion_preserve_voice_response_contract()
    test_collaboration_forwards_initiating_browser_completion_handler()
    print("PASS: microphone-originated assistant responses retain voice playback")
