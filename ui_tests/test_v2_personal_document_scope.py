# test_v2_personal_document_scope.py
"""
Protect personal document behavior while the shared explorer gains group scope.

Version: 0.261.128
Implemented in: 0.261.128

The real SPA runs against closed synthetic personal APIs. A saved active group
must not retarget personal reads, filtering, selection, or metadata writes.
"""

import copy
import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import (
    OWNER_ID, WorkspaceAuthoringFixture, connect_options,  # noqa: F401
)


pytestmark = pytest.mark.ui


class PersonalDocumentFixture(WorkspaceAuthoringFixture):
    def __init__(self, page):
        super().__init__(page)
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
        if entry.path == "/api/documents" and entry.method == "GET":
            assert "group_id" not in entry.query and "group_ids" not in entry.query
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
                "total_count": len(rows), "file_downloads_enabled": False,
            })
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
