# test_v2_public_tags.py
"""
Production-SPA coverage for the native V2 public workspace Tags section.
Version: 0.261.445
Implemented in: 0.261.445

Public Tags used to hand off to classic: the public context closed the section and the page showed a
classic card. It is native now -- the same vocabulary editor the group workspace uses, run against the
immutable `/api/public-workspaces/<id>/documents/tags` routes. The context's own `manage_tags` operation
decides who may change the vocabulary (an owner, admin or document manager of an active workspace);
every other viewer browses it read-only, and an inactive or unrecognized workspace closes the section
with the server's reason.

Only HTTP responses are scripted, by the management fixture (`ui_tests/fixtures/public_document_management.py`,
whose receipts are the real routes' and are held to them by test_public_document_fixture_parity.py).
Components, stores, navigation and validation run in the production SPA. It pins the section as a rail
and overview entry with no classic label, the vocabulary with its counts, the read-only states and their
explanation, a create that normalizes the name, a recolour that waits for an explicit save, an encoded
rename, a merge and a delete that touch only current documents, a partial result that keeps the old
vocabulary, a vocabulary conflict and a refusal that keep the draft, the chat button's gating, the
unsaved-draft guard, the administrator's workspace label in the wording, every request staying on the
workspace's own tag routes, and both themes at both breakpoints.
"""

import copy
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.public_document_management import (
    DOCUMENT_OPERATION_FAILED_ERROR, TAG_REVISION_CHANGED_ERROR, VOCABULARY_CONFLICT_CODE,
    VOCABULARY_CONFLICT_MESSAGE, batch_error, connect_options, operation_path,  # noqa: F401
    public_management_ui, tag_created, tag_result, tag_vocabulary_refusal,
)
from ui_tests.fixtures.public_workspace import PUBLIC_INACTIVE_REASON, PUBLIC_STATUS_UNKNOWN_REASON
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui
SCREENSHOTS = Path(os.environ.get(
    "SIMPLECHAT_UI_SCREENSHOTS", str(Path(__file__).parent / "artifacts" / "public-tags"),
))

WORKSPACE = "pub-a"
TAGS_PATH = f"/api/public-workspaces/{WORKSPACE}/documents/tags"
INTRO = (
    "Vocabulary changes affect only the current version of this public workspace's documents. "
    "Earlier versions keep their tags."
)
READ_ONLY_NOTE = (
    "Tag management is not available with this workspace's current permissions. "
    "You can still browse its vocabulary."
)
LAYOUTS = [
    pytest.param("light", 1440, 900, "dl", id="desktop-light"),
    pytest.param("dark", 1440, 900, "dd", id="desktop-dark"),
    pytest.param("light", 390, 844, "ml", id="mobile-light"),
    pytest.param("dark", 390, 844, "md", id="mobile-dark"),
]


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------

def response_for(method, path):
    return lambda response: response.request.method == method and urlsplit(response.url).path == path


def perform(ui, reply, action):
    with ui.page.expect_response(response_for(reply.method, reply.path)) as pending:
        action()
    response = pending.value
    assert response.status == reply.status
    response.finished()
    return response


def open_tags(ui, **options):
    ui.open(f"/public/{WORKSPACE}/tags", **options)
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(any_row(ui, "finance")).to_be_visible()


def any_row(ui, name):
    """A tag's row, whether or not the viewer may change it."""
    return ui.page.get_by_role("listitem").filter(has=ui.page.get_by_text(name, exact=True))


def tag_row(ui, name):
    """A tag's row for a viewer who can change it: only those rows carry a colour control."""
    return ui.page.get_by_role("listitem").filter(
        has=ui.page.get_by_label(f"Colour for {name}", exact=True),
    )


def begin_rename(ui, name, new_name):
    item = tag_row(ui, name)
    item.get_by_role("button", name=name, exact=True).click()
    item.get_by_role("textbox", name=f"Rename {name}", exact=True).fill(new_name)
    return item


def changed_record(ui, identifier, **changes):
    return {**copy.deepcopy(ui.record(identifier, WORKSPACE)), **copy.deepcopy(changes)}


def tag_reads(ui):
    return [entry for entry in ui.requests if entry.method == "GET" and entry.path == TAGS_PATH]


def documents_link(ui):
    """The link in the line that says where tags are applied, not the rail's or the overview's."""
    return ui.page.locator("p", has_text="Apply tags from").get_by_role("link", name="Documents", exact=True)


def assert_read_only(ui):
    expect(ui.page.get_by_text(READ_ONLY_NOTE, exact=True)).to_be_visible()
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Create", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name=re.compile(r"^Delete tag "))).to_have_count(0)
    expect(ui.page.get_by_label(re.compile(r"^Colour for "))).to_have_count(0)
    # A tag's name is a rename button only for a viewer who can change it.
    expect(ui.page.get_by_role("button", name="finance", exact=True)).to_have_count(0)
    expect(any_row(ui, "finance")).to_be_visible()
    assert not ui.operation_requests


def assert_native_tag_traffic(ui):
    """Everything the section sent went to this workspace's own tag family; nothing reached classic or
    another scope."""
    for entry in ui.operation_requests:
        assert entry.path == TAGS_PATH or entry.path.startswith(f"{TAGS_PATH}/"), entry
    for entry in ui.requests:
        assert not entry.path.startswith(("/api/documents", "/api/group_documents", "/api/public_workspace_documents")), entry
        assert "/tags" not in entry.path or entry.path.startswith(f"/api/public-workspaces/{WORKSPACE}/"), entry
    assert not ui.classic_visits


# --------------------------------------------------------------------------
# A native section, not a classic card.
# --------------------------------------------------------------------------

def test_tags_is_a_native_section_that_lists_the_vocabulary_with_counts(public_management_ui):
    ui = public_management_ui
    open_tags(ui)
    expect(ui.page.get_by_text(INTRO, exact=True)).to_be_visible()
    expect(any_row(ui, "team")).to_contain_text("2 documents")
    expect(any_row(ui, "finance")).to_contain_text("1 document")
    expect(any_row(ui, "legacy/review")).to_contain_text("1 document")
    expect(any_row(ui, "review")).to_contain_text("0 documents")
    main = ui.page.get_by_role("main")
    expect(main.get_by_text("classic", exact=False)).to_have_count(0)
    expect(main.get_by_role("button", name=re.compile("classic", re.IGNORECASE))).to_have_count(0)
    assert len(tag_reads(ui)) == 1 and not ui.operation_requests
    assert_native_tag_traffic(ui)
    ui.assert_clean()


def test_the_rail_and_overview_open_tags_natively(public_management_ui):
    ui = public_management_ui
    ui.open(f"/public/{WORKSPACE}")
    expect(ui.page.get_by_text("About this workspace", exact=True)).to_be_visible()
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    link = nav.get_by_role("link", name="Tags", exact=True)
    expect(link).to_have_count(1)
    # The overview card for Tags is a live link like Documents', carrying no classic label.
    expect(ui.page.get_by_role("main").get_by_text("Classic", exact=True)).to_have_count(0)
    link.click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/tags")
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    assert not ui.classic_visits


def test_a_stray_segment_on_tags_opens_the_section(public_management_ui):
    ui = public_management_ui
    ui.open(f"/public/{WORKSPACE}/tags/stray-tag")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/tags")
    expect(ui.page.get_by_role("heading", name="Tags", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Opening the requested view...", exact=True)).to_have_count(0)
    assert not ui.classic_visits


def test_the_documents_link_stays_in_this_workspace(public_management_ui):
    ui = public_management_ui
    open_tags(ui)
    expect(documents_link(ui)).to_have_attribute("href", f"/v2/public/{WORKSPACE}/documents")


# --------------------------------------------------------------------------
# Who may change the vocabulary.
# --------------------------------------------------------------------------

def test_a_reader_browses_the_vocabulary_but_changes_nothing(public_management_ui):
    ui = public_management_ui
    ui.set_policy(role="User")
    open_tags(ui)
    assert_read_only(ui)
    expect(any_row(ui, "team")).to_contain_text("2 documents")
    expect(ui.page.get_by_role("button", name="Chat with documents tagged team", exact=True)).to_be_enabled()
    ui.assert_clean()


@pytest.mark.parametrize("role", ["Owner", "Admin", "DocumentManager"])
@pytest.mark.parametrize("status", ["locked", "upload_disabled"])
def test_a_manager_of_a_locked_or_upload_disabled_workspace_browses_tags_read_only(public_management_ui, role, status):
    """The server grants manage_tags only while the workspace is active, so the page offers no control
    in a locked or upload-disabled workspace and says why none is there."""
    ui = public_management_ui
    ui.set_policy(role=role, status=status)
    open_tags(ui)
    assert_read_only(ui)
    ui.assert_clean()


@pytest.mark.parametrize("status,reason", [
    ("inactive", PUBLIC_INACTIVE_REASON), ("frozen", PUBLIC_STATUS_UNKNOWN_REASON),
])
def test_an_inactive_or_unknown_workspace_closes_tags_with_the_servers_reason(public_management_ui, status, reason):
    ui = public_management_ui
    ui.set_policy(role="Owner", status=status)
    ui.open(f"/public/{WORKSPACE}/tags")
    expect(ui.page.get_by_text("Tags is not available", exact=True)).to_be_visible()
    expect(ui.page.get_by_text(reason, exact=True)).to_be_visible()
    assert not tag_reads(ui), "A closed section must not read the vocabulary."
    assert not ui.classic_visits


def test_a_workspace_without_a_documents_permission_is_told_so_not_sent_to_classic(public_management_ui):
    ui = public_management_ui
    ui.workspaces[WORKSPACE]["document_permissions"]["can_view"] = False
    ui.open(f"/public/{WORKSPACE}/tags")
    expect(ui.page.get_by_text("Tags are not available", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("You do not have access to this public workspace's documents.", exact=True)).to_be_visible()
    assert not tag_reads(ui) and not ui.classic_visits


# --------------------------------------------------------------------------
# Changing the vocabulary.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["Owner", "Admin", "DocumentManager"])
def test_a_manager_creates_a_tag_with_a_normalized_name_and_the_chosen_colour(public_management_ui, role):
    ui = public_management_ui
    ui.set_policy(role=role)
    original_documents = copy.deepcopy(ui.documents)
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("  Urgent  ")
    ui.page.get_by_role("button", name="Use colour #8b5cf6", exact=True).click()
    vocabulary = {**ui.vocabulary[WORKSPACE], "urgent": "#8b5cf6"}
    created = ui.queue_operation(
        "POST", "tags", body={"tag_name": "urgent", "color": "#8b5cf6"},
        response=tag_created("urgent", "#8b5cf6"), status=201, vocabulary=vocabulary,
    )
    perform(ui, created, ui.page.get_by_role("button", name="Create", exact=True).click)
    expect(tag_row(ui, "urgent")).to_contain_text("0 documents")
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_value("")
    expect(ui.page.get_by_role("status").filter(
        has_text="confirmed for this public workspace's current documents.")).to_be_visible()
    assert ui.documents == original_documents and len(ui.operation_requests) == 1
    assert_native_tag_traffic(ui)


def test_a_recolour_waits_for_an_explicit_save(public_management_ui):
    ui = public_management_ui
    original_documents = copy.deepcopy(ui.documents)
    open_tags(ui)
    colour = ui.page.get_by_label("Colour for finance", exact=True)
    colour.evaluate("""(input, value) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value);
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
    }""", "#ef4444")
    expect(tag_row(ui, "finance").get_by_role("button", name="Save colour", exact=True)).to_be_enabled()
    assert not ui.operation_requests, "Picking a colour sends nothing until it is saved."
    recoloured = ui.queue_operation(
        "PATCH", "tags/finance", body={"color": "#ef4444"},
        response=tag_result("update", tag={"name": "finance", "color": "#ef4444"}),
        vocabulary={**ui.vocabulary[WORKSPACE], "finance": "#ef4444"},
    )
    perform(ui, recoloured, tag_row(ui, "finance").get_by_role("button", name="Save colour", exact=True).click)
    expect(colour).to_have_value("#ef4444")
    assert ui.documents == original_documents and len(ui.operation_requests) == 1


def test_an_encoded_rename_a_merge_and_a_delete_change_only_current_documents(public_management_ui):
    ui = public_management_ui
    history = copy.deepcopy(ui.versions[(WORKSPACE, "same-document")][1])
    other_workspace = copy.deepcopy(ui.documents["pub-b"])
    open_tags(ui)
    item = begin_rename(ui, "legacy/review", "Archive")
    renamed_notes = changed_record(ui, "notes-document", tags=["team", "archive"])
    vocabulary = {name: colour for name, colour in ui.vocabulary[WORKSPACE].items() if name != "legacy/review"}
    vocabulary["archive"] = "#8b5cf6"
    rename = ui.queue_operation(
        "PATCH", f"tags/{quote('legacy/review', safe='')}", body={"new_name": "archive"},
        response=tag_result(
            "rename", tag={"name": "archive", "color": "#8b5cf6"},
            success=[{"document_id": "notes-document", "tags": renamed_notes["tags"]}],
        ),
        records=[renamed_notes], vocabulary=vocabulary,
    )
    perform(ui, rename, item.get_by_role("button", name="Save", exact=True).click)
    expect(tag_row(ui, "archive")).to_contain_text("1 document")
    expect(ui.page.get_by_label("Colour for legacy/review", exact=True)).to_have_count(0)

    item = begin_rename(ui, "archive", "team")
    expect(ui.page.get_by_text("A tag with that name exists. Saving merges the two.", exact=True)).to_be_visible()
    expect(item.get_by_role("button", name="Merge", exact=True)).to_be_enabled()
    merged_notes = changed_record(ui, "notes-document", tags=["team"])
    vocabulary.pop("archive")
    merge = ui.queue_operation(
        "PATCH", "tags/archive", body={"new_name": "team"},
        response=tag_result(
            "rename", tag={"name": "team", "color": vocabulary["team"]},
            success=[{"document_id": "notes-document", "tags": ["team"]}],
        ),
        records=[merged_notes], vocabulary=vocabulary,
    )
    perform(ui, merge, item.get_by_role("button", name="Merge", exact=True).click)
    expect(ui.page.get_by_label("Colour for archive", exact=True)).to_have_count(0)
    expect(tag_row(ui, "team")).to_contain_text("2 documents")

    ui.page.get_by_role("button", name="Delete tag team", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Delete tag", exact=True)
    expect(dialog).to_contain_text('Remove "team" from Research library? Documents themselves are kept.')
    expect(dialog).to_contain_text("Only current documents are changed. Earlier versions are not rewritten.")
    vocabulary.pop("team")
    updated = [
        changed_record(ui, "same-document", tags=["finance"]),
        changed_record(ui, "notes-document", tags=[]),
    ]
    deleted = ui.queue_operation(
        "DELETE", "tags/team",
        response=tag_result("delete", success=[
            {"document_id": record["id"], "tags": record["tags"]} for record in updated
        ]),
        records=updated, vocabulary=vocabulary,
    )
    perform(ui, deleted, dialog.get_by_role("button", name="Delete tag", exact=True).click)
    expect(dialog).to_have_count(0)
    expect(ui.page.get_by_label("Colour for team", exact=True)).to_have_count(0)
    # An earlier version and another workspace's documents are never rewritten.
    assert ui.versions[(WORKSPACE, "same-document")][1] == history
    assert ui.documents["pub-b"] == other_workspace
    assert len(ui.operation_requests) == 3
    assert_native_tag_traffic(ui)
    documents_link(ui).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/documents")
    expect(ui.page.get_by_role("button", name="Details for Field notes", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("row").filter(
        has=ui.page.get_by_role("button", name="Details for Field notes", exact=True),
    ).get_by_text("team", exact=True)).to_have_count(0)


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_a_partial_result_keeps_the_old_vocabulary_and_names_the_failed_document(public_management_ui, operation):
    ui = public_management_ui
    ui.record("notes-document", WORKSPACE)["tags"].append("finance")
    original_history = copy.deepcopy(ui.versions[(WORKSPACE, "same-document")][1])
    open_tags(ui)
    target_tags = ["budget", "team"] if operation == "rename" else ["team"]
    vocabulary = copy.deepcopy(ui.vocabulary[WORKSPACE])
    if operation == "rename":
        vocabulary["budget"] = vocabulary["finance"]
        item = begin_rename(ui, "finance", "budget")
        submit = item.get_by_role("button", name="Save", exact=True)
    else:
        ui.page.get_by_role("button", name="Delete tag finance", exact=True).click()
        submit = ui.page.get_by_role("dialog", name="Delete tag", exact=True).get_by_role(
            "button", name="Delete tag", exact=True,
        )
    partial = ui.queue_operation(
        "PATCH" if operation == "rename" else "DELETE", "tags/finance",
        body={"new_name": "budget"} if operation == "rename" else None, status=207,
        response=tag_result(
            operation,
            tag={"name": "budget", "color": vocabulary["finance"]} if operation == "rename" else None,
            success=[{"document_id": "same-document", "tags": target_tags}],
            errors=[batch_error("notes-document", TAG_REVISION_CHANGED_ERROR)],
        ),
        records=[changed_record(ui, "same-document", tags=target_tags)], vocabulary=vocabulary,
    )
    perform(ui, partial, submit.click)
    expect(ui.page.get_by_role("alert").filter(has_text=TAG_REVISION_CHANGED_ERROR)).to_be_visible()
    # The old tag stays in the vocabulary, and the document the server could not update still carries it.
    expect(tag_row(ui, "finance")).to_contain_text("1 document")
    if operation == "rename":
        expect(tag_row(ui, "budget")).to_contain_text("1 document")
    assert "finance" in ui.vocabulary[WORKSPACE]
    assert "finance" in ui.record("notes-document", WORKSPACE)["tags"]
    assert ui.versions[(WORKSPACE, "same-document")][1] == original_history
    assert len(ui.operation_requests) == 1


def test_a_vocabulary_conflict_shows_the_servers_sentence_and_keeps_the_draft(public_management_ui):
    ui = public_management_ui
    original = copy.deepcopy(ui.vocabulary[WORKSPACE])
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("urgent")
    reply = ui.queue_operation(
        "POST", "tags", body={"tag_name": "urgent", "color": "#3b82f6"},
        response=tag_vocabulary_refusal(), status=409,
    )
    perform(ui, reply, ui.page.get_by_role("button", name="Create", exact=True).click)
    expect(ui.page.get_by_role("alert").filter(has_text=VOCABULARY_CONFLICT_MESSAGE)).to_be_visible()
    expect(ui.page.get_by_text(VOCABULARY_CONFLICT_CODE)).to_have_count(0)
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_value("urgent")
    expect(ui.page.get_by_role("button", name="Create", exact=True)).to_be_enabled()
    assert ui.vocabulary[WORKSPACE] == original and len(ui.operation_requests) == 1


def test_a_refused_create_keeps_the_draft_and_shows_the_servers_words(public_management_ui):
    ui = public_management_ui
    original = copy.deepcopy(ui.vocabulary[WORKSPACE])
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("urgent")
    reply = ui.queue_operation(
        "POST", "tags", body={"tag_name": "urgent", "color": "#3b82f6"},
        response={"error": DOCUMENT_OPERATION_FAILED_ERROR}, status=500,
    )
    perform(ui, reply, ui.page.get_by_role("button", name="Create", exact=True).click)
    expect(ui.page.get_by_role("alert").filter(has_text=DOCUMENT_OPERATION_FAILED_ERROR)).to_be_visible()
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_value("urgent")
    expect(ui.page.get_by_label("Colour for urgent", exact=True)).to_have_count(0)
    assert ui.vocabulary[WORKSPACE] == original


def test_a_tag_change_the_workspace_no_longer_offers_is_held_before_it_is_sent(public_management_ui):
    """The page re-reads the permitted operations through the context: once the workspace is locked,
    a stale tab cannot send a vocabulary write the server would refuse, and the draft is kept."""
    ui = public_management_ui
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("urgent")
    ui.set_policy(role="DocumentManager", status="locked")
    with ui.page.expect_response(lambda response: response.url.endswith(f"/api/v2/workspaces/public/{WORKSPACE}")):
        ui.page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(ui.page.get_by_text(READ_ONLY_NOTE, exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Create", exact=True)).to_be_disabled()
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_value("urgent")
    assert not ui.operation_requests


# --------------------------------------------------------------------------
# Chat, drafts and wording.
# --------------------------------------------------------------------------

def test_chat_with_a_tag_needs_documents_and_the_chat_permission(public_management_ui):
    ui = public_management_ui
    open_tags(ui)
    expect(ui.page.get_by_role("button", name="Chat with documents tagged team", exact=True)).to_be_enabled()
    # A tag no document carries has nothing to chat with.
    expect(ui.page.get_by_role("button", name="Chat with documents tagged review", exact=True)).to_be_disabled()
    ui.workspaces[WORKSPACE]["document_permissions"]["can_chat"] = False
    open_tags(ui)
    expect(ui.page.get_by_role("button", name="Chat with documents tagged team", exact=True)).to_be_disabled()


def test_an_unsaved_tag_draft_is_guarded_when_leaving(public_management_ui):
    ui = public_management_ui
    open_tags(ui)
    ui.page.get_by_label("New tag", exact=True).fill("half-typed")
    documents_link(ui).click()
    leave = ui.page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)
    expect(leave).to_be_visible()
    leave.get_by_role("button", name="Keep editing", exact=True).click()
    expect(ui.page.get_by_label("New tag", exact=True)).to_have_value("half-typed")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/tags")
    ui.page.get_by_role("button", name="Cancel new tag", exact=True).click()
    documents_link(ui).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/{WORKSPACE}/documents")
    assert not ui.operation_requests


def test_a_custom_workspace_label_words_the_section(public_management_ui):
    ui = public_management_ui
    original = ui._bootstrap

    def labelled():
        payload = original()
        payload["settings"]["public_workspace_labels"] = {
            "is_custom": True, "max_length": 32, "singular": "Knowledge Hub", "plural": "Knowledge Hubs",
            "lower_singular": "knowledge hub", "lower_plural": "knowledge hubs", "short": "Hub",
        }
        return payload

    ui._bootstrap = labelled
    open_tags(ui)
    expect(ui.page.get_by_text(
        "Vocabulary changes affect only the current version of this knowledge hub's documents. "
        "Earlier versions keep their tags.", exact=True)).to_be_visible()
    ui.page.get_by_label("New tag", exact=True).fill("urgent")
    created = ui.queue_operation(
        "POST", "tags", body={"tag_name": "urgent", "color": "#3b82f6"},
        response=tag_created("urgent", "#3b82f6"), status=201,
        vocabulary={**ui.vocabulary[WORKSPACE], "urgent": "#3b82f6"},
    )
    perform(ui, created, ui.page.get_by_role("button", name="Create", exact=True).click)
    expect(ui.page.get_by_role("status").filter(
        has_text="confirmed for this knowledge hub's current documents.")).to_be_visible()


@pytest.mark.parametrize("theme,width,height,label", LAYOUTS)
def test_tags_layout_fits_both_themes_at_both_breakpoints(public_management_ui, theme, width, height, label):
    ui = public_management_ui
    open_tags(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_label("New tag", exact=True)).to_be_visible()
    expect(tag_row(ui, "finance")).to_be_visible()
    expect(ui.page.locator("html")).to_have_css("color-scheme", theme)
    ui.assert_no_overflow()
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    ui.page.screenshot(path=str(SCREENSHOTS / f"{label}-tags.png"), full_page=True)
    ui.page.get_by_role("button", name="Delete tag finance", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Delete tag", exact=True)
    expect(dialog).to_be_visible()
    box = dialog.locator(".glass-modal").bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
    ui.assert_no_overflow()
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert not ui.operation_requests
