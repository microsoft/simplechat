# test_chat_message_email_chart_download.py
"""
UI test for per-message email visual PNG downloads.
Version: 0.241.143
Implemented in: 0.241.019

This test ensures that Open in Email downloads PNG visual payloads from the
backend email draft response before opening the mailto draft.
"""

import json
import re
from pathlib import Path

import pytest


playwright_sync_api = pytest.importorskip("playwright.sync_api")


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPORT_JS_PATH = ROOT_DIR / "application" / "single_app" / "static" / "js" / "chat" / "chat-message-export.js"
SAMPLE_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _load_email_export_script_for_page():
    """Load the real export script with module syntax adapted for an isolated page."""
    source = EXPORT_JS_PATH.read_text(encoding="utf-8")
    source = source.replace(
        'import { showToast } from "./chat-toast.js";',
        "const showToast = (...args) => window.__toastMessages.push(args);",
    )
    source = re.sub(r"^export\s+", "", source, flags=re.MULTILINE)
    source = source.replace(
        "window.location.href = mailtoUrl;",
        "window.__capturedMailtoUrl = mailtoUrl;",
    )
    source += "\nwindow.__messageExportModule = { openInEmail };\n"
    return source


@pytest.mark.ui
def test_open_in_email_downloads_chart_png_attachments(playwright):
    """Validate the browser workflow downloads chart PNGs before composing mailto."""
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()

    draft_payload = {
        "subject": "Chart draft",
        "body": "Chart image exported as message_chart_1_revenue.png",
        "attachments": [
            {
                "filename": "message:chart?.png",
                "content_type": "image/png",
                "data_uri": SAMPLE_PNG_DATA_URI,
            }
        ],
    }

    try:
        page.set_content(
            """
            <main>
                <div id="message">
                    <textarea id="copy-md-message-1">```simplechart\n{}\n```</textarea>
                    <div class="message-text">chart content</div>
                </div>
            </main>
            """
        )
        page.add_script_tag(
            content=f"""
            window.currentConversationId = 'conversation-1';
            window.__toastMessages = [];
            window.__fetchCalls = [];
            window.__downloadCaptures = [];
            window.__createdBlobs = [];
            window.__capturedMailtoUrl = '';

            const originalCreateElement = document.createElement.bind(document);
            document.createElement = (tagName, options) => {{
                const element = originalCreateElement(tagName, options);
                if (String(tagName).toLowerCase() === 'a') {{
                    element.click = () => {{
                        window.__downloadCaptures.push({{
                            download: element.download,
                            href: element.href,
                        }});
                    }};
                }}
                return element;
            }};

            URL.createObjectURL = (blob) => {{
                const url = `blob:test-${{window.__createdBlobs.length + 1}}`;
                window.__createdBlobs.push({{
                    url,
                    size: blob.size,
                    type: blob.type,
                }});
                return url;
            }};
            URL.revokeObjectURL = () => {{}};

            window.fetch = async (url, init = {{}}) => {{
                window.__fetchCalls.push({{
                    url: String(url),
                    method: String(init.method || 'GET'),
                    body: String(init.body || ''),
                }});
                return {{
                    ok: true,
                    status: 200,
                    json: async () => ({json.dumps(draft_payload)}),
                }};
            }};
            """
        )
        page.add_script_tag(content=_load_email_export_script_for_page())
        page.evaluate(
            """
            async () => {
                const message = document.getElementById('message');
                await window.__messageExportModule.openInEmail(message, 'message-1', 'assistant');
            }
            """
        )

        downloads = page.evaluate("() => window.__downloadCaptures")
        created_blobs = page.evaluate("() => window.__createdBlobs")
        toast_messages = page.evaluate("() => window.__toastMessages")
        fetch_calls = page.evaluate("() => window.__fetchCalls")
        mailto_url = page.evaluate("() => window.__capturedMailtoUrl")

        assert len(downloads) == 1, downloads
        assert downloads[0]["download"] == "message_chart_.png", downloads
        assert created_blobs == [
            {
                "url": "blob:test-1",
                "size": 68,
                "type": "image/png",
            }
        ], created_blobs

        assert fetch_calls[0]["url"] == "/api/message/export-email-draft", fetch_calls
        assert fetch_calls[0]["method"] == "POST", fetch_calls
        request_body = json.loads(fetch_calls[0]["body"])
        assert request_body == {
            "message_id": "message-1",
            "conversation_id": "conversation-1",
        }, request_body

        assert mailto_url.startswith("mailto:?subject=Chart%20draft&body="), mailto_url
        assert "message_chart_1_revenue.png" in mailto_url, mailto_url
        assert ["1 visual PNG file downloaded for the email draft.", "success"] in toast_messages, toast_messages
    finally:
        context.close()
        browser.close()
