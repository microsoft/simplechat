# test_chat_message_audio_export.py
"""
UI test for per-message MP3 audio export.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures user and assistant message text is synthesized with the
active TTS voice and speed and downloaded as MP3 files in the browser.
"""

import json
import re
from pathlib import Path

import pytest


playwright_sync_api = pytest.importorskip("playwright.sync_api")

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-message-export.js"
TTS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-tts.js"


def load_tts_script():
    """Adapt the real TTS module for an isolated browser page."""
    source = TTS_FILE.read_text(encoding="utf-8")
    source = source.replace(
        "import { showToast } from './chat-toast.js';",
        "var showToast = (...args) => window.__toastMessages.push(args);",
    )
    source = re.sub(r"^export\s+", "", source, flags=re.MULTILINE)
    source += "\nwindow.__testTTSModule = { initializeTTS, synthesizeSpeechBlob };\n"
    return source


def load_export_script():
    """Adapt the real message export module for an isolated browser page."""
    source = EXPORT_FILE.read_text(encoding="utf-8")
    source = source.replace(
        'import { showToast } from "./chat-toast.js";',
        "var showToast = (...args) => window.__toastMessages.push(args);",
    )
    source = source.replace(
        "const { synthesizeSpeechBlob } = await import('./chat-tts.js');",
        "const { synthesizeSpeechBlob } = window.__testTTSModule;",
    )
    source = re.sub(r"^export\s+", "", source, flags=re.MULTILINE)
    source += "\nwindow.__testMessageExportModule = { exportMessageAsAudio };\n"
    return source


@pytest.mark.ui
def test_user_and_assistant_messages_download_audio_with_active_preferences():
    """Validate the complete browser synthesis and MP3 download workflow."""
    playwright = playwright_sync_api.sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()

    try:
        page.set_content(
            """
            <main>
                <article id="user-message">
                    <div class="message-text">User asks about quarterly results.</div>
                </article>
                <article id="assistant-message">
                    <textarea id="copy-md-assistant-1">**Hidden Markdown**</textarea>
                    <div class="message-text">
                        <strong>Quarterly results</strong> improved by 12%.
                    </div>
                </article>
            </main>
            """
        )
        page.add_script_tag(
            content=f"""
            window.appSettings = {{ enable_text_to_speech: true }};
            window.__toastMessages = [];
            window.__ttsRequests = [];
            window.__downloads = [];
            window.__createdBlobs = [];

            const originalCreateElement = document.createElement.bind(document);
            document.createElement = (tagName, options) => {{
                const element = originalCreateElement(tagName, options);
                if (String(tagName).toLowerCase() === 'a') {{
                    element.click = () => window.__downloads.push({{
                        filename: element.download,
                        href: element.href,
                    }});
                }}
                return element;
            }};

            URL.createObjectURL = (blob) => {{
                const url = `blob:audio-${{window.__createdBlobs.length + 1}}`;
                window.__createdBlobs.push({{
                    url,
                    size: blob.size,
                    type: blob.type,
                }});
                return url;
            }};
            URL.revokeObjectURL = () => {{}};

            window.fetch = async (url, init = {{}}) => {{
                if (String(url) === '/api/user/settings') {{
                    return new Response(
                        {json.dumps(json.dumps({"settings": {"ttsVoice": "en-US-AvaMultilingualNeural", "ttsSpeed": 1.25}}))},
                        {{ status: 200, headers: {{ 'Content-Type': 'application/json' }} }}
                    );
                }}

                window.__ttsRequests.push({{
                    url: String(url),
                    method: String(init.method || 'GET'),
                    body: JSON.parse(String(init.body || '{{}}')),
                }});
                return new Response(
                    new Uint8Array([73, 68, 51, 4]),
                    {{ status: 200, headers: {{ 'Content-Type': 'audio/mpeg' }} }}
                );
            }};
            """
        )
        page.add_script_tag(content=load_tts_script())
        page.add_script_tag(content=load_export_script())

        page.evaluate(
            """
            async () => {
                await window.__testTTSModule.initializeTTS();
                await window.__testMessageExportModule.exportMessageAsAudio(
                    document.getElementById('user-message'),
                    'user-1',
                    'user'
                );
                await window.__testMessageExportModule.exportMessageAsAudio(
                    document.getElementById('assistant-message'),
                    'assistant-1',
                    'assistant'
                );
            }
            """
        )

        requests = page.evaluate("() => window.__ttsRequests")
        downloads = page.evaluate("() => window.__downloads")
        created_blobs = page.evaluate("() => window.__createdBlobs")
        toast_messages = page.evaluate("() => window.__toastMessages")

        assert requests == [
            {
                "url": "/api/chat/tts",
                "method": "POST",
                "body": {
                    "text": "User asks about quarterly results.",
                    "voice": "en-US-AvaMultilingualNeural",
                    "speed": 1.25,
                },
            },
            {
                "url": "/api/chat/tts",
                "method": "POST",
                "body": {
                    "text": "Quarterly results improved by 12%.",
                    "voice": "en-US-AvaMultilingualNeural",
                    "speed": 1.25,
                },
            },
        ]
        assert len(downloads) == 2
        assert all(re.fullmatch(r"message_audio_\d{8}_\d{6}\.mp3", item["filename"]) for item in downloads)
        assert created_blobs == [
            {"url": "blob:audio-1", "size": 4, "type": "audio/mpeg"},
            {"url": "blob:audio-2", "size": 4, "type": "audio/mpeg"},
        ]
        assert toast_messages.count(["Message exported as audio.", "success"]) == 2
    finally:
        context.close()
        browser.close()
        playwright.stop()


@pytest.mark.ui
def test_audio_export_is_blocked_when_text_to_speech_is_disabled():
    """Validate direct calls cannot bypass the frontend feature flag."""
    playwright = playwright_sync_api.sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context()
    page = context.new_page()

    try:
        page.set_content('<article id="message"><div class="message-text">Do not synthesize.</div></article>')
        page.add_script_tag(
            content="""
            window.appSettings = { enable_text_to_speech: false };
            window.__toastMessages = [];
            window.__synthesisCalled = false;
            window.__testTTSModule = {
                synthesizeSpeechBlob: async () => {
                    window.__synthesisCalled = true;
                    return new Blob([], { type: 'audio/mpeg' });
                },
            };
            """
        )
        page.add_script_tag(content=load_export_script())
        page.evaluate(
            """
            async () => {
                await window.__testMessageExportModule.exportMessageAsAudio(
                    document.getElementById('message'),
                    'message-1',
                    'user'
                );
            }
            """
        )

        assert page.evaluate("() => window.__synthesisCalled") is False
        assert page.evaluate("() => window.__toastMessages") == [
            ["Text-to-speech is not enabled.", "warning"]
        ]
    finally:
        context.close()
        browser.close()
        playwright.stop()
