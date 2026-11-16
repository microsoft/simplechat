# test_v2_onenote_workspace_uploads.py
"""
Production-SPA browser coverage for React v2 OneNote workspace uploads.
Version: 0.261.142
Implemented in: 0.261.142

Use the existing closed-API SPA fixture and Azure Playwright connection support.
Only synthetic file bytes enter the browser; no application login, Azure writes,
or private notebooks are required. Native extraction is tested separately.
"""

import copy
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import (
    ORIGIN,
    OWNER_ID,
    connect_options,  # noqa: F401
    workspace_ui,  # noqa: F401
)
from ui_tests.test_workspace_supported_file_types_modal import _allowed_categories


pytestmark = pytest.mark.ui
LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]
READY_STATUS = "Processing complete - OneNote typed text only; images, handwriting, and attachments excluded"
MISSING_RUNTIME = (
    "Error: Processing failed: The OneNote extractor is unavailable. "
    "Install the native component or use the current application container."
)


@pytest.fixture
def onenote_ui(workspace_ui, monkeypatch):
    ui = workspace_ui
    bootstrap = ui._bootstrap()
    bootstrap["workspace_uploads"] = {"categories": _allowed_categories()}
    bootstrap["features"]["enable_chat_file_uploads"] = True
    bootstrap["settings"]["max_file_size_mb"] = 1
    state = {"bootstrap": bootstrap, "uploads": [], "documents": [], "status": READY_STATUS}
    monkeypatch.setattr(ui, "_bootstrap", lambda: copy.deepcopy(state["bootstrap"]))
    listing = {"documents": state["documents"], "total_count": 0, "file_downloads_enabled": False}
    ui.extra_gets["/api/documents"] = listing
    ui.extra_gets["/api/documents/tags"] = {"tags": []}
    ui.extra_gets["/api/documents/facets"] = {
        "total": 0, "untagged": 0, "processing": 0, "errors": 0,
        "recent": 0, "shared_with_me": 0, "by_tag": {},
    }

    def upload(route):
        request = route.request
        assert request.method == "POST"
        header = request.headers["content-type"]
        body = request.post_data_buffer
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {header}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body,
        )
        parts = list(message.iter_parts())
        names = [part.get_filename() for part in parts]
        fields = [part.get_param("name", header="content-disposition") for part in parts]
        assert fields == ["file"] * len(parts)
        assert names and all(names)
        state["uploads"].append(names)
        ids = []
        for name in names:
            identifier = f"onenote-{len(state['documents']) + 1}"
            record = {
                "id": identifier, "file_name": name, "title": name, "user_id": OWNER_ID,
                "file_type": f".{name.rsplit('.', 1)[-1].lower()}",
                "file_size": 128, "tags": [], "authors": [],
                "status": state["status"],
                "percentage_complete": 0 if state["status"].startswith("Error:") else 100,
                "number_of_pages": 1,
            }
            state["documents"].append(record)
            ui.extra_gets[f"/api/documents/{identifier}"] = record
            ids.append(identifier)
        listing["total_count"] = len(state["documents"])
        ui._json(route, {"document_ids": ids, "processed_filenames": names, "errors": []}, 202)

    ui.page.route(f"{ORIGIN}/api/documents/upload", upload)
    return ui, state


def submit_files(page, filenames, *, drop=False):
    if drop:
        transfer = page.evaluate_handle(
            """names => {
                const transfer = new DataTransfer();
                for (const name of names) {
                    transfer.items.add(new File(['synthetic file'], name, {type: 'application/onenote'}));
                }
                return transfer;
            }""",
            filenames,
        )
        try:
            page.get_by_role("region", name="Workspace documents", exact=True).dispatch_event(
                "drop", {"dataTransfer": transfer},
            )
        finally:
            transfer.dispose()
    else:
        page.get_by_label("Upload workspace documents", exact=True).set_input_files([
            {"name": name, "mimeType": "application/onenote", "buffer": b"synthetic file"}
            for name in filenames
        ])


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
@pytest.mark.parametrize("extension", [".one", ".ONEPKG"])
def test_picker_and_supported_types_accept_native_formats(onenote_ui, theme, width, height, extension):
    ui, state = onenote_ui
    ui.open("/workspace/documents", theme=theme, width=width, height=height)
    picker = ui.page.get_by_label("Upload workspace documents", exact=True)
    accepted = set(picker.get_attribute("accept").split(","))
    assert {".one", ".onepkg", ".pdf", ".docx", ".csv"} <= accepted
    assert {".onetoc2", ".exe", ".mp4"}.isdisjoint(accepted)
    summary = ui.page.locator("summary").filter(has_text="Supported file types")
    summary.focus()
    summary.press("Enter")
    expect(ui.page.get_by_text("OneNote (typed text and tables)", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(".one, .onepkg", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("OneNote (.one, .onepkg): typed text and tables only.", exact=False)).to_be_visible()
    ui.assert_no_overflow()
    if extension == ".one":
        artifacts = Path(__file__).resolve().parent / "artifacts"
        artifacts.mkdir(exist_ok=True)
        ui.page.screenshot(path=str(artifacts / f"onenote-v2-{theme}-{width}.png"))
    summary.press("Enter")
    expect(ui.page.get_by_text(".one, .onepkg", exact=True)).not_to_be_visible()

    filename = f"Native notes{extension}"
    submit_files(ui.page, [filename])
    row = ui.page.get_by_role("row").filter(has_text=filename)
    expect(row).to_be_visible()
    expect(row.get_by_text("Ready", exact=True)).to_be_visible()
    assert state["uploads"] == [[filename]]
    assert len(state["documents"]) == 1
    ui.assert_no_overflow()


@pytest.mark.parametrize("drop", [False, True], ids=["picker", "drop"])
def test_mixed_uploads_report_unsupported_files_without_losing_valid_notes(onenote_ui, drop):
    ui, state = onenote_ui
    ui.open("/workspace/documents")
    submit_files(ui.page, ["Notes.one", "Notebook.onepkg", "existing.txt", "blocked.exe"], drop=drop)
    expect(ui.page.get_by_text("Unsupported workspace file type: blocked.exe.", exact=False)).to_be_visible()
    expect(ui.page.get_by_role("row").filter(has_text="Notebook.onepkg")).to_be_visible()
    assert state["uploads"] == [["Notes.one", "Notebook.onepkg", "existing.txt"]]


def test_unsupported_and_oversized_notebooks_never_send_a_request(onenote_ui):
    ui, state = onenote_ui
    ui.open("/workspace/documents")
    submit_files(ui.page, ["notebook.onetoc2", "one", "file.one.exe"])
    expect(ui.page.get_by_text("Unsupported workspace file type:", exact=False)).to_be_visible()
    assert state["uploads"] == []
    ui.page.get_by_label("Upload workspace documents", exact=True).set_input_files({
        "name": "Too large.onepkg", "mimeType": "application/onenote", "buffer": b"x" * (1024 * 1024 + 1),
    })
    expect(ui.page.get_by_text("Too large.onepkg exceeds the 1 MB limit.", exact=True)).to_be_visible()
    assert state["uploads"] == []


def test_native_runtime_failure_is_visible_in_existing_document_status(onenote_ui):
    ui, state = onenote_ui
    state["status"] = MISSING_RUNTIME
    ui.open("/workspace/documents")
    submit_files(ui.page, ["Missing runtime.onepkg"])
    row = ui.page.get_by_role("row").filter(has_text="Missing runtime.onepkg")
    expect(row).to_be_visible()
    error = row.get_by_text("Error", exact=True)
    expect(error).to_be_visible()
    expect(error).to_have_attribute("title", MISSING_RUNTIME)
    expect(row.get_by_text("Ready", exact=True)).to_have_count(0)
    assert state["uploads"] == [["Missing runtime.onepkg"]]


def test_older_bootstrap_keeps_existing_server_validated_uploads(onenote_ui):
    ui, state = onenote_ui
    del state["bootstrap"]["workspace_uploads"]
    ui.open("/workspace/documents")
    picker = ui.page.get_by_label("Upload workspace documents", exact=True)
    accepted = picker.get_attribute("accept")
    assert accepted is None
    expect(ui.page.locator("summary").filter(has_text="Supported file types")).to_have_count(0)
    submit_files(ui.page, ["existing.txt"])
    expect(ui.page.get_by_role("row").filter(has_text="existing.txt")).to_be_visible()
    assert state["uploads"] == [["existing.txt"]]


@pytest.mark.parametrize("extension", [".one", ".onepkg"])
def test_chat_attachment_picker_does_not_expand(onenote_ui, extension):
    ui, state = onenote_ui
    ui.open("/chat")
    picker = ui.page.locator('input[type="file"]')
    expect(picker).to_have_count(1)
    accepted = set(picker.get_attribute("accept").split(","))
    assert {".one", ".onepkg"}.isdisjoint(accepted)
    picker.set_input_files({
        "name": f"Chat notes{extension}", "mimeType": "application/onenote", "buffer": b"synthetic file",
    })
    expect(ui.page.get_by_text("This file type is not supported for chat uploads.", exact=False)).to_be_visible()
    assert state["uploads"] == []
    assert not any(request.path in {"/upload", "/api/documents/upload"} for request in ui.writes)
