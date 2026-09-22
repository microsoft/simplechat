# test_v2_personal_document_scope.py
"""
Protect personal document behavior while the shared explorer gains group scope.

Version: 0.261.129
Implemented in: 0.261.128
Management baseline expanded in: 0.261.129

The real SPA runs against closed synthetic personal APIs. A saved active group
must not retarget personal reads, filtering, selection, or metadata writes.
"""

import copy
import re
from collections import Counter

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import (
    OWNER_ID, WorkspaceAuthoringFixture, connect_options,  # noqa: F401
)


pytestmark = pytest.mark.ui


class PersonalDocumentFixture(WorkspaceAuthoringFixture):
    def __init__(self, page):
        super().__init__(page)
        self.downloads_enabled = False
        self.confirm_delete = False
        self.failed_deletes = set()
        self.documents = {
            "personal-alpha": {
                "id": "personal-alpha", "document_id": "personal-alpha",
                "user_id": OWNER_ID, "owner_id": OWNER_ID,
                "title": "Personal Alpha", "file_name": "personal-alpha.txt",
                "file_type": "txt", "abstract": "Private alpha reference.",
                "authors": ["A. Author"], "keywords": ["alpha"],
                "tags": ["Finance"], "version": 1, "number_of_pages": 2,
                "file_size": 1024, "num_chunks": 2, "percentage_complete": 100,
                "status": "Complete", "shared_approval_status": "owner",
                "is_current_version": True, "revision_family_id": "family-alpha", "_ts": 2,
            },
            "personal-beta": {
                "id": "personal-beta", "document_id": "personal-beta",
                "user_id": OWNER_ID, "owner_id": OWNER_ID,
                "title": "Personal Beta", "file_name": "personal-beta.txt",
                "file_type": "txt", "abstract": "Private beta reference.",
                "tags": [], "version": 1, "number_of_pages": 1,
                "file_size": 2048, "percentage_complete": 100, "status": "Complete",
                "shared_approval_status": "owner", "is_current_version": True,
                "revision_family_id": "family-beta", "_ts": 1,
            },
        }
        self.extra_gets["/api/documents/facets"] = {
            "total": 2, "untagged": 1, "processing": 0, "errors": 0,
            "recent": 0, "shared_with_me": 0,
            "by_tag": {"Finance": 1}, "by_classification": {},
        }
        self.extra_gets["/api/documents/tags"] = {
            "tags": [{"name": "Finance", "count": 1, "color": "#0078d4"}],
        }

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["scope"]["active_group_id"] = "unrelated-active-group"
        payload["scope"]["groups"] = [{"id": "unrelated-active-group", "name": "Unrelated group"}]
        return payload

    def _dispatch(self, route, entry):
        if entry.path.startswith("/api/documents"):
            assert "group_id" not in entry.query and "group_ids" not in entry.query
        if entry.path == "/api/documents" and entry.method == "GET":
            rows = list(self.documents.values())
            term = entry.query.get("search", [""])[0].lower()
            if term:
                rows = [row for row in rows if term in f'{row["title"]} {row["file_name"]}'.lower()]
            tags = entry.query.get("tags", [""])[0].split(",")
            tags = [tag for tag in tags if tag]
            if tags:
                rows = [row for row in rows if all(tag in row["tags"] for tag in tags)]
            self._json(route, {
                "documents": rows, "page": 1, "page_size": 25,
                "total_count": len(rows), "file_downloads_enabled": self.downloads_enabled,
            })
        elif entry.path == "/api/documents/facets":
            self._json(route, {
                "total": len(self.documents),
                "untagged": sum(not row["tags"] for row in self.documents.values()),
                "processing": 0, "errors": 0, "recent": 0, "shared_with_me": 0,
                "by_tag": dict(Counter(tag for row in self.documents.values() for tag in row["tags"])),
                "by_classification": {},
            })
        elif entry.path == "/api/documents/tags" and entry.method == "GET":
            counts = Counter(tag for row in self.documents.values() for tag in row["tags"])
            self._json(route, {"tags": [
                {"name": name, "count": count, "color": "#0078d4"} for name, count in counts.items()
            ]})
        elif entry.path == "/api/documents/upload" and entry.method == "POST":
            filenames = re.findall(r'filename="([^"]+)"', str(entry.body))
            if not filenames:
                self._json(route, {"error": "Fixture expected a multipart file."}, 400)
                return
            identifiers = []
            for filename in filenames:
                identifier = f"uploaded-{len(self.documents)}"
                self.documents[identifier] = {
                    **copy.deepcopy(self.documents["personal-alpha"]),
                    "id": identifier, "document_id": identifier,
                    "title": filename, "file_name": filename, "tags": [],
                    "revision_family_id": identifier,
                }
                identifiers.append(identifier)
            self._json(route, {"document_ids": identifiers, "processed_filenames": filenames, "errors": []})
        elif entry.path == "/api/documents/bulk-tag" and entry.method == "POST":
            assert entry.body["action"] == "add_tags"
            success = []
            for identifier in entry.body["document_ids"]:
                target = self.documents[identifier]
                target["tags"] = list(dict.fromkeys([*target["tags"], *entry.body["tags"]]))
                success.append({"document_id": identifier, "tags": target["tags"]})
            self._json(route, {"success": success, "errors": []})
        elif entry.path == "/api/documents/bulk-delete" and entry.method == "POST":
            if self.confirm_delete and entry.body.get("file_sync_delete_action") != "keep_source":
                self._json(route, {
                    "deleted": [], "deleted_count": 0, "error_count": 1,
                    "errors": [{
                        "document_id": entry.body["document_ids"][0],
                        "needs_confirmation": True, "error": "file_sync_confirmation_required",
                        "message": "This file is managed by a file source.",
                    }],
                }, 207)
                return
            deleted = []
            errors = []
            for identifier in entry.body["document_ids"]:
                if identifier in self.failed_deletes:
                    errors.append({
                        "document_id": identifier, "error": "fixture_delete_failed",
                        "message": "Fixture retained this document.",
                    })
                    continue
                self.documents.pop(identifier)
                deleted.append({"document_id": identifier})
            self._json(route, {
                "deleted": deleted, "errors": errors,
                "deleted_count": len(deleted), "error_count": len(errors),
            }, 207 if errors else 200)
        elif entry.path == "/api/documents/personal-alpha/download" and entry.method == "GET":
            route.fulfill(
                body=b"personal source fixture", content_type="application/octet-stream",
                headers={"Content-Disposition": 'attachment; filename="personal-alpha.txt"'},
            )
        elif entry.path.startswith("/api/documents/") and entry.path.rsplit("/", 1)[-1] in self.documents:
            assert "group_id" not in entry.query and "group_ids" not in entry.query
            identifier = entry.path.rsplit("/", 1)[-1]
            if entry.method == "PATCH":
                self.documents[identifier].update(copy.deepcopy(entry.body))
            elif entry.method != "GET":
                self.unexpected_requests.append(f"{entry.method} {entry.path}")
                self._json(route, {"error": "Unexpected personal document mutation."}, 500)
                return
            self._json(route, self.documents[identifier])
        else:
            super()._dispatch(route, entry)


@pytest.fixture
def personal_documents(page):
    fixture = PersonalDocumentFixture(page)
    yield fixture
    fixture.assert_clean()


def test_personal_reads_and_controls_ignore_an_active_group(personal_documents):
    ui = personal_documents
    ui.open("/workspace/documents")
    expect(ui.page.get_by_role("button", name="Upload", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True)).to_be_visible()
    ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True).check()
    expect(ui.page.get_by_role("button", name="Tag", exact=True).first).to_be_enabled()
    expect(ui.page.get_by_role("button", name="Delete", exact=True).first).to_be_enabled()
    expect(ui.page.get_by_role("button", name="Edit", exact=True)).to_be_enabled()
    reads = [entry for entry in ui.requests if entry.path.startswith("/api/documents")]
    assert {entry.path for entry in reads} >= {
        "/api/documents", "/api/documents/tags", "/api/documents/facets",
    }
    assert all("group_id" not in entry.query and "group_ids" not in entry.query for entry in reads)
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/group_documents")]


def test_personal_search_and_tag_filters_still_use_personal_api(personal_documents):
    ui = personal_documents
    ui.open("/workspace/documents")
    search = ui.page.get_by_role("searchbox", name="Search documents. Press Enter to search immediately.", exact=True)
    search.fill("Beta")
    search.press("Enter")
    expect(ui.page.get_by_role("checkbox", name="Select Personal Beta", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True)).to_have_count(0)
    assert any(entry.query.get("search") == ["Beta"] for entry in ui.requests if entry.path == "/api/documents")
    search.press("Escape")
    expect(ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True)).to_be_visible()
    ui.page.get_by_role("button", name=re.compile(r"^Finance(?:\s+1)?$")).click()
    expect(ui.page.get_by_role("checkbox", name="Select Personal Beta", exact=True)).to_have_count(0)
    assert any(entry.query.get("tags") == ["Finance"] for entry in ui.requests if entry.path == "/api/documents")
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/group_documents")]


def test_personal_metadata_edit_keeps_its_endpoint_and_target(personal_documents):
    ui = personal_documents
    ui.open("/workspace/documents")
    ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True).check()
    ui.page.get_by_role("button", name="Edit", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit metadata", exact=True)
    dialog.get_by_label(re.compile(r"^Title")).fill("Updated personal title")
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_role("checkbox", name="Select Updated personal title", exact=True)).to_be_visible()
    writes = [entry for entry in ui.writes if entry.path.startswith("/api/documents")]
    assert len(writes) == 1
    assert writes[0].method == "PATCH"
    assert writes[0].path == "/api/documents/personal-alpha"
    assert writes[0].query == {}
    assert writes[0].body["title"] == "Updated personal title"
    assert ui.documents["personal-beta"]["title"] == "Personal Beta"


def test_personal_upload_remains_personal_with_an_active_group(personal_documents):
    ui = personal_documents
    ui.open("/workspace/documents")
    with ui.page.expect_file_chooser() as chooser:
        ui.page.get_by_role("button", name="Upload", exact=True).click()
    chooser.value.set_files({"name": "personal-upload.txt", "mimeType": "text/plain", "buffer": b"personal upload fixture"})
    expect(ui.page.get_by_role("checkbox", name="Select personal-upload.txt", exact=True)).to_be_visible()
    uploads = [entry for entry in ui.writes if entry.path.endswith("/upload")]
    assert len(uploads) == 1
    assert uploads[0].path == "/api/documents/upload"
    assert uploads[0].query == {}


def test_personal_tagging_does_not_use_group_operations(personal_documents):
    ui = personal_documents
    ui.open("/workspace/documents")
    ui.page.get_by_role("checkbox", name="Select Personal Beta", exact=True).check()
    ui.page.get_by_role("button", name="Tag", exact=True).first.click()
    dialog = ui.page.get_by_role("dialog", name="Tag Personal Beta", exact=True)
    dialog.get_by_role("checkbox", name=re.compile("^Finance")).check()
    dialog.get_by_role("button", name="Apply", exact=True).click()
    expect(dialog).to_have_count(0)
    target = ui.page.get_by_role("row").filter(
        has=ui.page.get_by_role("checkbox", name="Select Personal Beta", exact=True),
    )
    expect(target).to_contain_text("Finance")
    writes = [entry for entry in ui.writes if entry.path.endswith("/bulk-tag")]
    assert len(writes) == 1
    assert writes[0].path == "/api/documents/bulk-tag"
    assert writes[0].body == {"document_ids": ["personal-beta"], "action": "add_tags", "tags": ["Finance"]}


def test_personal_delete_preserves_explicit_version_and_sync_confirmation(personal_documents):
    ui = personal_documents
    ui.confirm_delete = True
    ui.open("/workspace/documents")
    ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True).check()
    ui.page.get_by_role("button", name="Delete", exact=True).first.click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    dialog.get_by_role("checkbox", name=re.compile("^Delete every version")).uncheck()
    dialog.get_by_role("button", name="Delete", exact=True).click()
    blocked = ui.page.get_by_role("dialog", name="Some documents need confirmation", exact=True)
    expect(blocked).to_be_visible()
    assert "personal-alpha" in ui.documents
    blocked.get_by_role("button", name="Delete anyway", exact=True).click()
    expect(ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("checkbox", name="Select Personal Beta", exact=True)).to_be_visible()
    writes = [entry for entry in ui.writes if entry.path.endswith("/bulk-delete")]
    assert len(writes) == 2
    assert all(entry.path == "/api/documents/bulk-delete" and entry.query == {} for entry in writes)
    assert all(entry.body["delete_mode"] == "current_only" for entry in writes)
    assert writes[0].body["file_sync_delete_action"] is None
    assert writes[1].body["file_sync_delete_action"] == "keep_source"


def test_personal_download_uses_the_personal_source_route(personal_documents):
    ui = personal_documents
    ui.downloads_enabled = True
    ui.open("/workspace/documents")
    ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True).check()
    with ui.page.expect_download() as download:
        ui.page.get_by_role("button", name="Download", exact=True).first.click()
    filename = download.value.suggested_filename
    assert filename == "personal-alpha.txt"
    requests = [entry for entry in ui.requests if entry.path.endswith("/download")]
    assert len(requests) == 1
    assert requests[0].path == "/api/documents/personal-alpha/download"
    assert requests[0].query == {}


def test_personal_failed_metadata_save_keeps_the_draft(personal_documents):
    ui = personal_documents
    ui.open("/workspace/documents")
    ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True).check()
    ui.page.get_by_role("button", name="Edit", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Edit metadata", exact=True)
    title = dialog.get_by_label(re.compile("^Title"))
    title.fill("Unsaved personal revision")
    ui.reject_next("PATCH", "/api/documents/personal-alpha", error="Fixture metadata conflict.", status=409)
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog.get_by_role("alert")).to_have_text("Fixture metadata conflict.")
    expect(dialog).to_be_visible()
    expect(title).to_have_value("Unsaved personal revision")
    assert ui.documents["personal-alpha"]["title"] == "Personal Alpha"
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/groups/")]


def test_personal_partial_delete_retains_the_failed_document(personal_documents):
    ui = personal_documents
    ui.failed_deletes.add("personal-beta")
    ui.open("/workspace/documents")
    ui.page.get_by_role("checkbox", name="Select all documents on this page", exact=True).check()
    ui.page.get_by_role("button", name="Delete", exact=True).first.click()
    dialog = ui.page.get_by_role("dialog", name="Delete documents", exact=True)
    dialog.get_by_role("button", name="Delete", exact=True).click()
    expect(ui.page.get_by_text("Fixture retained this document.", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("checkbox", name="Select Personal Alpha", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("checkbox", name="Select Personal Beta", exact=True)).to_be_visible()
    assert set(ui.documents) == {"personal-beta"}
    writes = [entry for entry in ui.writes if entry.path.endswith("/bulk-delete")]
    assert len(writes) == 1
    assert writes[0].path == "/api/documents/bulk-delete"
    assert set(writes[0].body["document_ids"]) == {"personal-alpha", "personal-beta"}
    assert writes[0].query == {}
