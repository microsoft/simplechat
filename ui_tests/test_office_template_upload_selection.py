# test_office_template_upload_selection.py
"""
UI regression for native Office template selection through the existing chat picker.
Version: 0.261.321
Implemented in: 0.261.321

Uses the production Jinja file control and production change/click handlers, with
an upload transport recorder rather than Azure ingestion. React's production upload
allowlist/validation functions are compiled with the existing local esbuild dependency.
The shared Azure Playwright fixture uses DefaultAzureCredential and
azure-mgmt-playwright when a service workspace is configured; otherwise the same
tests run against a local browser. Every browser runtime asset is served locally.
"""

from pathlib import Path
import subprocess

from jinja2 import Template
import pytest
from playwright.sync_api import expect

from fixtures.playwright_connection import connect_options  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"


@pytest.fixture
def template_picker(page):
    source = (APP / "templates" / "chats.html").read_text(encoding="utf-8")
    start = source.index('<input type="file" id="file-input"')
    end = source.index("{% endif %}", source.index('id="upload-btn"', start))
    controls = Template(source[start:end]).render(settings={"xsd_upload_available": False})
    actions = (APP / "static" / "js" / "chat" / "chat-input-actions.js").read_text(encoding="utf-8")
    start = actions.index("if (chooseFileBtn) {")
    end = actions.index("if (cancelFileSelection) {", start)
    handlers = """
const chooseFileBtn = document.getElementById('choose-file-btn');
const fileInputEl = document.getElementById('file-input');
const cancelFileSelection = document.getElementById('cancel-file-selection');
window.uploads = [];
function isChatFileUploadEnabled() { return window.uploadEnabled !== false; }
function showChatFileUploadDisabledToast() { document.getElementById('status').textContent = 'Uploads disabled'; }
function resetFileButton() { fileInputEl.value = ''; chooseFileBtn.querySelector('.file-btn-text').textContent = 'File'; }
function beginChatFileUpload(files) { window.uploads.push(...files.map(file => file.name)); }
""" + actions[start:end]
    html = (
        '<html lang="en"><head><link rel="stylesheet" href="/static/bootstrap.css"></head>'
        f'<body><main>{controls}<p id="status" role="status"></p></main>'
        '<script src="/static/picker.js"></script></body></html>'
    )

    def serve(route):
        path = route.request.url.split("simplechat.test")[-1]
        if path == "/static/bootstrap.css":
            route.fulfill(body=(APP / "static" / "css" / "bootstrap.min.css").read_text(encoding="utf-8"), content_type="text/css")
        elif path == "/static/picker.js":
            route.fulfill(body=handlers, content_type="application/javascript")
        else:
            route.fulfill(body=html, content_type="text/html")

    page.route("http://simplechat.test/**", serve)
    return page


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}])
@pytest.mark.parametrize("extension", ["dotx", "potx"])
def test_existing_file_picker_selects_office_templates(template_picker, viewport, extension):
    page = template_picker
    page.set_viewport_size(viewport)
    page.goto("http://simplechat.test/")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    accept = page.locator("#file-input").get_attribute("accept")
    assert f".{extension}" in accept.split(",")
    expect(page.locator("#file-input")).to_be_hidden()
    expect(page.locator("#choose-file-btn")).to_be_visible()
    with page.expect_file_chooser() as chooser:
        page.locator("#choose-file-btn").click()
    chooser.value.set_files({
        "name": f"reference.{extension}", "mimeType": "application/octet-stream", "buffer": b"native-template",
    })
    expect(page.locator(".file-btn-text")).to_have_text(f"reference.{extension}")
    selected = page.evaluate("window.uploads")
    assert selected == [f"reference.{extension}"] and not errors


@pytest.mark.ui
def test_disabled_uploads_keep_existing_recovery_message(template_picker):
    page = template_picker
    page.goto("http://simplechat.test/")
    page.evaluate("window.uploadEnabled = false")
    page.locator("#file-input").set_input_files({"name": "reference.dotx", "mimeType": "application/octet-stream", "buffer": b"template"})
    expect(page.locator("#status")).to_have_text("Uploads disabled")
    expect(page.locator(".file-btn-text")).to_have_text("File")
    selected = page.evaluate("window.uploads")
    assert selected == []


@pytest.mark.ui
def test_react_upload_validation_accepts_templates_but_not_active_formats(page):
    source = (ROOT / "application" / "v2_ui" / "src" / "lib" / "chatUploads.ts").read_text(encoding="utf-8")
    snippet = source[source.index("// The /upload route supports"):source.index("interface LocalPreviewEntry")]
    build = subprocess.run(
        ["node", "-e", (
            "const fs=require('fs'); const esbuild=require('./application/v2_ui/node_modules/esbuild');"
            "process.stdout.write(esbuild.transformSync(fs.readFileSync(0,'utf8'),"
            "{loader:'ts',format:'iife',globalName:'UploadRules'}).code)"
        )],
        input=snippet, text=True, capture_output=True, cwd=ROOT, check=True,
    ).stdout
    page.route("http://simplechat.test/**", lambda route: route.fulfill(
        content_type="application/javascript" if route.request.url.endswith(".js") else "text/html",
        body=build if route.request.url.endswith(".js") else '<html><body><script src="/static/upload-rules.js"></script></body></html>',
    ))
    page.goto("http://simplechat.test/")
    checks = page.evaluate("""() => ['dotx','potx','dotm','potm'].map(extension => ({
        extension,
        result: UploadRules.chatUploadValidationError(new File(['template'], `reference.${extension}`), true, 16)
    }))""")
    assert [entry["result"] for entry in checks[:2]] == [None, None]
    assert all(entry["result"] == "This file type is not supported for chat uploads." for entry in checks[2:])
