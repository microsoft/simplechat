# test_v2_public_workspace_status_compatibility.py
"""
UI regressions for public workspace status compatibility.
Version: 0.261.372
Implemented in: 0.261.355
V2 availability independent of classic preferences in: 0.261.372

The production directory and composer run with real backend-produced status rows
and scope resolution. Azure Playwright uses synthetic HTTP, not live application
data, credentials, model calls, or changes to the federal acceptance harness.
"""

from copy import deepcopy
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import session
from playwright.sync_api import expect

# Reuse the isolated backend modules and shared browser fixtures when run directly.
ROOT = Path(__file__).resolve().parents[1]
for location in (ROOT, ROOT / "functional_tests", ROOT / "ui_tests" / "fixtures"):
    sys.path.insert(0, str(location))

from test_support.public_directory_harness import (  # noqa: E402
    public_directory_environment,
    public_workspace_document,
)
from ui_tests.fixtures.public_directory import PublicDirectoryFixture, directory_record  # noqa: E402
from ui_tests.fixtures.public_documents import chat_list  # noqa: E402
from ui_tests.test_v2_chat_context_selection import (  # noqa: E402,F401
    connect_options, context_page, mount_workflow, open_picker,
)


pytestmark = pytest.mark.ui
READER = "outsider-1"
LEGACY = "legacy-library"
NEW = "new-library"
HIDDEN = "hidden-library"


@pytest.fixture
def status_directory_ui(page, monkeypatch):
    ui = PublicDirectoryFixture(page)
    ui.directory_workspaces.clear()
    documents = {}
    for identifier, status in [
        (LEGACY, "active"), (HIDDEN, "active"), ("locked", "locked"),
        ("uploads-off", "upload_disabled"), ("inactive", "inactive"),
        ("null", None), ("empty", ""), ("future", "future-status"),
    ]:
        document = public_workspace_document(identifier, f"Library {identifier}")
        document["status"] = status
        if identifier == LEGACY:
            del document["status"]
        documents[identifier] = document

    with public_directory_environment() as backend:
        with backend.app.test_request_context():
            session["user"] = {
                "oid": "owner-1", "name": "Olive Owner",
                "preferred_username": "olive.owner@example.test",
            }
            created = backend.modules.public_workspaces.create_public_workspace(
                "Library newly created", "A newly created public library",
            )
        created["id"] = NEW
        documents[NEW] = created
        backend.reset()
        for document in documents.values():
            backend.seed_document(document)
        backend.as_user(READER)
        response = backend.directory()
        if response.status_code != 200:
            raise AssertionError("The real directory could not produce the browser fixture")
        api_rows = {row["id"]: row for row in response.get_json()["workspaces"]}
        project = backend.modules.directory.build_public_directory_row

    for document in documents.values():
        ui.directory_workspaces[document["id"]] = directory_record(document["id"], document["name"])
    ui.seed_visibility({HIDDEN: False, "unrelated-library": True})

    def project_response(record):
        if record["membership"] == "none":
            return deepcopy(api_rows[record["id"]])
        document = deepcopy(documents[record["id"]])
        document["pendingDocumentManagers"] = [{"userId": READER}]
        return project(document, READER)

    monkeypatch.setattr(ui, "_project", project_response)
    yield ui
    ui.assert_clean()


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900), ("dark", 1440, 900),
    ("light", 390, 844), ("dark", 390, 844),
])
def test_legacy_and_new_workspaces_keep_membership_actions_without_curation(
    status_directory_ui, theme, width, height,
):
    ui = status_directory_ui
    before = deepcopy(ui.preferences["publicDirectorySettings"])
    ui.open("/public/directory", theme=theme, width=width, height=height)
    for identifier in (LEGACY, NEW):
        name = ui.directory_workspaces[identifier]["name"]
        expect(ui.page.get_by_role("button", name=f"Open {name}", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("checkbox", name=re.compile("in public chat"))).to_have_count(0)
    ui.page.reload(wait_until="networkidle")

    name = ui.directory_workspaces[LEGACY]["name"]
    request = ui.page.get_by_role("button", name=f"Ask to manage documents in {name}", exact=True)
    request.focus()
    request.press("Enter")
    cancel = ui.page.get_by_role("button", name=f"Cancel request for {name}", exact=True)
    expect(cancel).to_be_visible()
    cancel.click()
    expect(ui.page.get_by_role("button", name=f"Ask to manage documents in {name}", exact=True)).to_be_visible()
    assert ui.preferences["publicDirectorySettings"] == before
    assert not [entry for entry in ui.requests
                if entry.path == "/api/user/settings" and entry.method == "POST"]
    ui.assert_no_overflow()


def test_explicit_status_restrictions_and_untouched_visibility_are_preserved(status_directory_ui):
    ui = status_directory_ui
    before = deepcopy(ui.preferences["publicDirectorySettings"])
    ui.open("/public/directory")
    for identifier in ("inactive", "null", "empty", "future"):
        name = ui.directory_workspaces[identifier]["name"]
        target = ui.page.get_by_role("listitem").filter(has_text=name)
        expect(target.get_by_text("Not available for chat right now.", exact=True)).to_be_visible()
    for identifier in (LEGACY, NEW, HIDDEN, "locked", "uploads-off"):
        name = ui.directory_workspaces[identifier]["name"]
        target = ui.page.get_by_role("listitem").filter(has_text=name)
        expect(target.get_by_text("Not available for chat right now.", exact=True)).to_have_count(0)
    ui.page.reload(wait_until="networkidle")
    assert ui.preferences["publicDirectorySettings"] == before
    assert not [entry for entry in ui.requests
                if entry.path == "/api/user/settings" and entry.method == "POST"]


@pytest.mark.parametrize("legacy_map", [
    {}, {"public-1": True}, {"public-1": True, HIDDEN: False},
    {"public-1": True, HIDDEN: True},
])
def test_current_context_picker_discovers_all_eligible_public_sources(context_page, legacy_map):
    page, _api = context_page
    workspaces = [
        public_workspace_document("public-1", "Visible library"),
        public_workspace_document(HIDDEN, "Hidden library"),
    ]
    del workspaces[0]["status"]
    preferences = {"settings": {"publicDirectorySettings": deepcopy(legacy_map)}}
    with public_directory_environment() as backend:
        public = backend.modules.public_workspaces
        public.get_all_public_workspaces = lambda: workspaces
        backend.modules.settings.get_user_settings = lambda _user_id: deepcopy(preferences)
        resolve = public.resolve_public_chat_workspace_ids
        settings = dict(backend.settings)

    source_queries = []
    sources = [
        {"id": "visible-guide", "title": "Visible guide", "file_name": "visible-guide.md",
         "public_workspace_id": "public-1", "status": "completed"},
        {"id": "hidden-guide", "title": "Hidden guide", "file_name": "hidden-guide.md",
         "public_workspace_id": HIDDEN, "status": "completed"},
    ]

    def public_sources(route):
        query = parse_qs(urlsplit(route.request.url).query)
        source_queries.append(query)
        assert route.request.headers.get("x-simplechat-ui") == "v2"
        # The synthetic HTTP boundary models V2 all-available policy independently of
        # aggregate mode. Use the real eligibility resolver to retain status restrictions.
        workspace_ids = resolve(READER, "all", settings=settings)
        search = query.get("search", [""])[0].casefold()
        documents = [document for document in sources
                     if document["public_workspace_id"] in workspace_ids
                     and search in document["file_name"].casefold()]
        route.fulfill(json=chat_list(documents))

    page.route("**/api/public_workspace_documents?**", public_sources)
    mount_workflow(page)
    open_picker(page)
    expect(page.get_by_label("Search in", exact=True)).to_have_value("")
    search = page.get_by_role("searchbox", name="Search documents", exact=True)
    search.fill("hidden-guide.md")
    hidden = page.get_by_role("button", name=re.compile("^Hidden guide"))
    expect(hidden).to_be_visible()
    assert source_queries and all("public_workspace_selection" not in query for query in source_queries)
    hidden.click()
    expect(hidden).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.get_by_role("button", name="Remove Hidden guide", exact=True)).to_be_visible()
    page.get_by_role("textbox", name="Message", exact=True).fill("#Hidden")
    expect(page.get_by_role("option", name=re.compile("^Hidden guide"))).to_be_visible()
    page.get_by_role("textbox", name="Message", exact=True).press("Escape")
    open_picker(page)
    search = page.get_by_role("searchbox", name="Search documents", exact=True)
    search.fill("visible-guide.md")
    candidate = page.get_by_role("button", name=re.compile("^Visible guide"))
    expect(candidate).to_be_visible()
    candidate.click()
    expect(candidate).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.get_by_role("button", name="Remove Visible guide", exact=True)).to_be_visible()
    assert preferences["settings"]["publicDirectorySettings"] == legacy_map
