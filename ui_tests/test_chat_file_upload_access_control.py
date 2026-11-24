# test_chat_file_upload_access_control.py
"""
UI test for chat file upload access control.

Version: 0.261.483
Implemented in: 0.241.110; expanded in: 0.242.063

This test ensures the chat toolbar renders the file upload controls only when
the current user's effective chat upload setting allows new uploads and exposes
that same setting to browser-side upload guards. It also verifies the browser
file picker advertises Outlook MSG and Visio VSDX upload support.
"""

import ast
import os
from pathlib import Path

import pytest
from jinja2 import Template


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.ui
@pytest.mark.parametrize("audio,video,xsd_available", [(False, False, False), (True, False, True), (False, True, False), (True, True, True)])
def test_chat_picker_matches_workspace_formats(audio, video, xsd_available):
    """Validate the rendered chat picker uses the complete enabled format list."""
    from playwright.sync_api import sync_playwright

    config_tree = ast.parse((REPO_ROOT / "application" / "single_app" / "config.py").read_text(encoding="utf-8"))
    names = {
        "BASE_ALLOWED_EXTENSIONS", "DOCUMENT_EXTENSIONS", "IMAGE_EXTENSIONS",
        "TABULAR_EXTENSIONS", "SCHEMA_EXTENSIONS", "VISIO_EXTENSIONS",
        "EMAIL_EXTENSIONS", "AUDIO_EXTENSIONS", "VIDEO_EXTENSIONS",
        "ONENOTE_EXTENSIONS",
    }
    definitions = [
        node for node in config_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
        or isinstance(node, ast.FunctionDef) and node.name == "get_allowed_extensions"
    ]
    namespace = {}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "config.py", "exec"), namespace)
    extensions = namespace["get_allowed_extensions"](enable_audio=audio, enable_video=video)
    if not xsd_available:
        extensions -= namespace["SCHEMA_EXTENSIONS"]
    template = (REPO_ROOT / "application" / "single_app" / "templates" / "chats.html").read_text(encoding="utf-8")
    input_markup = next(line for line in template.splitlines() if 'id="file-input"' in line)
    button_markup = next(line for line in template.splitlines() if 'id="choose-file-btn"' in line)
    markup = Template(input_markup + button_markup + "</button>").render(
        chat_upload_extensions=sorted(extensions),
        chat_group_upload_extensions=sorted(extensions),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(markup)
            picker = page.locator("#file-input")
            accepted = set((picker.get_attribute("accept") or "").split(","))
            assert accepted == {f".{extension}" for extension in extensions}
            assert set(picker.get_attribute("data-group-accept").split(",")) == accepted
            assert {".vsdx", ".ppt", ".xls", ".heic"} <= accepted
            assert (".wav" in accepted) == audio
            assert (".mp4" in accepted) == video
            assert (".xsd" in accepted) == xsd_available
            assert "vsdx" in page.locator("#choose-file-btn").get_attribute("title").lower()
            picker.set_input_files(str(REPO_ROOT / "artifacts" / "architecture.vsdx"))
            assert picker.evaluate("(input) => input.files[0].name") == "architecture.vsdx"
        finally:
            browser.close()


@pytest.mark.ui
def test_chat_file_upload_toolbar_matches_effective_setting():
    """Validate the chat file upload button follows the server-rendered effective setting."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
            expect(page.locator("#user-input")).to_be_visible()

            upload_enabled = page.evaluate("() => window.appSettings?.enable_chat_file_uploads === true")
            upload_button = page.locator("#choose-file-btn")
            upload_input = page.locator("#file-input")

            if upload_enabled:
                expect(upload_button).to_be_visible()
                expect(upload_input).to_have_count(1)
                accept_value = upload_input.get_attribute("accept") or ""
                upload_title = upload_button.get_attribute("title") or ""
                assert ".msg" in {item.strip() for item in accept_value.split(",")}
                assert "msg" in upload_title.lower()
                assert ".vsdx" in {item.strip() for item in accept_value.split(",")}
                assert "vsdx" in upload_title.lower()
            else:
                expect(upload_button).to_have_count(0)
                expect(upload_input).to_have_count(0)
        finally:
            context.close()
            browser.close()