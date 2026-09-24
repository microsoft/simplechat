# test_v2_group_endpoints.py
"""
Production-SPA coverage for the native scope-aware V2 group model endpoints section.
Version: 0.261.143
Implemented in: 0.261.143

Exercises the real Endpoints section -- the admin ModelConnectionsManager driven by a
scope-aware group adapter, not a fork -- and its editor dialog against closed synthetic HTTP.
The fixture serves only the immutable `/api/groups/<id>/model-endpoints` CRUD family and the
group `/api/groups/<id>/models/{fetch,test-model}` routes, and never a tenant-admin
`/api/v2/admin/*` route or a personal `/api/user/*` read, so a group scope that reached an
admin surface would fail the run rather than be answered. A manager creates through the group
route with no `expected_revision`, edits with a conditional write that keeps the stored API key
masked, toggles enablement with a partial conditional write, deletes with an
`expected_revision`-only body, and keeps the draft open on a stale-revision 409 with a reload
offer or on an unrelated group-write 409 for a plain retry; an inline `endpoint_actions` gate
hides enable, edit and delete per endpoint beside an editable positive control; a delete
refused because the endpoint is still referenced names what uses it; the server's reviewed
credential message renders verbatim; the admin-only test-connection and network-policy
surfaces are absent in group scope; and a member sees a read-only list with no write
affordance and no admin read.
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN  # noqa: F401
from ui_tests.fixtures.group_endpoints import (  # noqa: F401
    GroupEndpointsFixture, group_endpoints_ui,
    EDITABLE_ENDPOINT_ID, WITHHELD_ENDPOINT_ID, FOUNDRY_ENDPOINT_ID, IN_USE_ENDPOINT_ID,
    DISCOVERY_ENDPOINT_ID,
    EDITABLE_ENDPOINT_NAME, WITHHELD_ENDPOINT_NAME, FOUNDRY_ENDPOINT_NAME, IN_USE_ENDPOINT_NAME,
    DISCOVERY_ENDPOINT_NAME,
)
from ui_tests.fixtures.group_workspace import (  # noqa: F401
    ENDPOINT_STORED_CREDENTIAL_SUPPLIED,
)


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]


def open_endpoints(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/endpoints", **options)


def open_manager(ui, group="group-a", **options):
    open_endpoints(ui, group, **options)
    expect(ui.page.get_by_role("heading", name="Endpoints", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Add connection", exact=True)).to_be_visible()


def row(ui, name):
    return ui.page.get_by_role("listitem").filter(has_text=name)


def endpoints_get(ui, group="group-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/groups/{group}/model-endpoints" and entry.method == "GET"
    ]


def last_write(ui, path, method):
    matches = [entry for entry in ui.writes if entry.path == path and entry.method == method]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w.method, w.path) for w in ui.writes]}"
    return matches[-1]


def assert_no_admin_or_personal_reads(ui):
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/v2/admin/")], (
        "A group endpoints section must not reach any tenant-admin route."
    )
    # The CatalogProfilePicker's read-only /api/models/catalog stays in group scope; the admin
    # discovery and single-model test routes are what a group page must never reach.
    admin_model_routes = {
        "/api/models/fetch", "/api/models/test-model",
        "/api/models/test-capability", "/api/models/foundry/agents",
    }
    assert not [entry for entry in ui.requests if entry.path in admin_model_routes], (
        "A group endpoints section must not reach the admin model discovery or test routes."
    )
    assert not [
        entry for entry in ui.requests
        if entry.path.startswith("/api/user/") and entry.path != "/api/user/settings"
    ], "A group endpoints section must not read any personal /api/user resource."


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_group_endpoint_layout(group_endpoints_ui, theme, width, height):
    """The manager section matches the shell in both themes and both breakpoints."""
    ui = group_endpoints_ui
    open_endpoints(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("heading", name="Endpoints", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("button", name="Add connection", exact=True)).to_be_enabled()
    expect(row(ui, EDITABLE_ENDPOINT_NAME)).to_be_visible()
    # The native section renders, not the classic hand-off panel.
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


def test_group_endpoints_read_from_the_group_route_only(group_endpoints_ui):
    """Every list is a group read with no query; no admin or personal request is ever made."""
    ui = group_endpoints_ui
    open_manager(ui)
    expect(row(ui, EDITABLE_ENDPOINT_NAME)).to_be_visible()
    assert endpoints_get(ui), "The section must load from the group model-endpoints route."
    assert all(not entry.query for entry in endpoints_get(ui)), (
        "The model-endpoints list route takes no query parameters."
    )
    assert_no_admin_or_personal_reads(ui)


def test_malformed_list_is_a_hard_error_not_empty(group_endpoints_ui):
    """A malformed list envelope is a hard load error, never rendered as an empty collection."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    ui.malformed_endpoint_list = True
    open_endpoints(ui)
    expect(page.get_by_role("heading", name="Endpoints", exact=True)).to_be_visible()
    expect(page.get_by_text(
        "The model endpoint list was malformed. Refresh and try again.", exact=True)).to_be_visible()
    expect(row(ui, EDITABLE_ENDPOINT_NAME)).to_have_count(0)
    assert_no_admin_or_personal_reads(ui)


def test_admin_surfaces_are_absent_in_group_scope(group_endpoints_ui):
    """The admin-only test-connection and network-policy surfaces do not render in group scope."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    # The tenant network-policy editor is admin-only.
    expect(page.get_by_text("Custom endpoint network policy", exact=True)).to_have_count(0)
    row(ui, EDITABLE_ENDPOINT_NAME).get_by_role("button", name=f"Edit {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    # The connection-level test is admin-only; a group manager still discovers models.
    expect(dialog.get_by_role("button", name="Test connection", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Discover models", exact=True)).to_be_visible()


def test_inline_endpoint_actions_gate_writes(group_endpoints_ui):
    """The editable endpoint shows enable, edit and delete; the withheld endpoint shows none."""
    ui = group_endpoints_ui
    open_manager(ui)
    editable = row(ui, EDITABLE_ENDPOINT_NAME)
    expect(editable.get_by_role("button", name=f"Disable {EDITABLE_ENDPOINT_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Edit {EDITABLE_ENDPOINT_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Delete {EDITABLE_ENDPOINT_NAME}", exact=True)).to_be_visible()

    withheld = row(ui, WITHHELD_ENDPOINT_NAME)
    expect(withheld.get_by_role("button", name=f"Disable {WITHHELD_ENDPOINT_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Edit {WITHHELD_ENDPOINT_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Delete {WITHHELD_ENDPOINT_NAME}", exact=True)).to_have_count(0)
    # The withheld row is still readable through a View control.
    expect(withheld.get_by_role("button", name=f"View {WITHHELD_ENDPOINT_NAME}", exact=True)).to_be_visible()


def test_group_manager_creates_an_endpoint(group_endpoints_ui):
    """A manager authors a new endpoint through the group route with no expected_revision."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    page.get_by_role("button", name="Add connection", exact=True).click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("button", name="Create connection", exact=True)).to_be_visible()
    dialog.get_by_label("Name", exact=True).fill("Warehouse chat connection")
    dialog.get_by_label("Endpoint URL", exact=True).fill("https://warehouse.openai.azure.com")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/groups/group-a/model-endpoints"
    ) as response:
        dialog.get_by_role("button", name="Create connection", exact=True).click()
    assert response.value.status == 201
    write = last_write(ui, "/api/groups/group-a/model-endpoints", "POST")
    assert write.body["name"] == "Warehouse chat connection"
    assert "expected_revision" not in write.body
    created = next(r for r in ui.native_endpoints["group-a"] if r["name"] == "Warehouse chat connection")
    assert created["id"].startswith("group-a-endpoint-created-")
    expect(row(ui, "Warehouse chat connection")).to_be_visible()


def test_group_manager_edits_with_a_conditional_write(group_endpoints_ui):
    """Editing an endpoint sends expected_revision and the changed field, and updates the stored row."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    revision = ui._endpoint_revision("group-a", EDITABLE_ENDPOINT_ID)
    open_manager(ui)
    row(ui, EDITABLE_ENDPOINT_NAME).get_by_role("button", name=f"Edit {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    dialog = page.get_by_role("dialog")
    name = dialog.get_by_label("Name", exact=True)
    expect(name).to_have_value(EDITABLE_ENDPOINT_NAME)
    name.fill("Research chat connection (rotated)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        dialog.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}", "PATCH")
    assert write.body["expected_revision"] == revision
    assert write.body["name"] == "Research chat connection (rotated)"
    assert ui.record_endpoint("group-a", EDITABLE_ENDPOINT_ID)["name"] == "Research chat connection (rotated)"


def test_edit_preserves_the_stored_api_key(group_endpoints_ui):
    """Editing an endpoint without supplying a new key keeps the stored credential server-side."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    row(ui, EDITABLE_ENDPOINT_NAME).get_by_role("button", name=f"Edit {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Research chat connection (kept key)")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        dialog.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}", "PATCH")
    # A blank key means "keep the stored value"; no plaintext api_key rides the request.
    assert not str((write.body.get("auth") or {}).get("api_key") or "")
    assert ui.record_endpoint("group-a", EDITABLE_ENDPOINT_ID)["has_api_key"] is True


def test_enable_toggle_sends_a_partial_conditional_write(group_endpoints_ui):
    """Toggling enablement sends only enabled plus expected_revision, and flips the row state."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        row(ui, EDITABLE_ENDPOINT_NAME).get_by_role(
            "button", name=f"Disable {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}", "PATCH")
    assert set(write.body) == {"enabled", "expected_revision"}
    assert write.body["enabled"] is False
    assert ui.record_endpoint("group-a", EDITABLE_ENDPOINT_ID)["enabled"] is False


def test_group_manager_deletes_an_endpoint(group_endpoints_ui):
    """Deleting an endpoint confirms, calls DELETE with only the version marker, and removes the row."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    row(ui, EDITABLE_ENDPOINT_NAME).get_by_role("button", name=f"Delete {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    expect(page.get_by_role("heading", name="Delete this connection?", exact=True)).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        page.get_by_role("button", name="Delete", exact=True).click()
    assert response.value.ok
    write = last_write(ui, f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}", "DELETE")
    assert set(write.body) == {"expected_revision"}
    expect(row(ui, EDITABLE_ENDPOINT_NAME)).to_have_count(0)
    assert ui.record_endpoint("group-a", EDITABLE_ENDPOINT_ID) is None


def test_endpoint_conflict_keeps_draft_and_offers_reload(group_endpoints_ui):
    """A stale revision keeps the editor and its draft and offers to reload the saved endpoint."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    row(ui, EDITABLE_ENDPOINT_NAME).get_by_role("button", name=f"Edit {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Draft in flight")
    ui.touch_endpoint("group-a", EDITABLE_ENDPOINT_ID)
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        dialog.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Draft in flight")
    expect(dialog.get_by_role("button", name="Reload latest", exact=True)).to_be_visible()
    expect(dialog.get_by_text(re.compile("Reload it before saving"))).to_be_visible()


def test_group_write_conflict_keeps_draft_for_a_plain_retry(group_endpoints_ui):
    """An unrelated group-write 409 keeps the draft with no reload; a plain retry then succeeds."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    ui.endpoint_write_conflicts.add("group-a")
    open_manager(ui)
    row(ui, EDITABLE_ENDPOINT_NAME).get_by_role("button", name=f"Edit {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Retry after group write")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        dialog.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 409
    # The endpoint's own revision is still valid, so no reload is offered -- a plain retry is enough.
    expect(dialog.get_by_role("button", name="Reload latest", exact=True)).to_have_count(0)
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Retry after group write")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        dialog.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.ok
    assert ui.record_endpoint("group-a", EDITABLE_ENDPOINT_ID)["name"] == "Retry after group write"


def test_delete_in_use_names_the_references(group_endpoints_ui):
    """A delete refused because the endpoint is still referenced names what uses it; nothing is removed."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    row(ui, IN_USE_ENDPOINT_NAME).get_by_role("button", name=f"Delete {IN_USE_ENDPOINT_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{IN_USE_ENDPOINT_ID}"
    ) as response:
        page.get_by_role("button", name="Delete", exact=True).click()
    assert response.value.status == 409
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="This connection is still in use", exact=True)).to_be_visible()
    expect(dialog.get_by_text("Group assistant", exact=False)).to_be_visible()
    expect(row(ui, IN_USE_ENDPOINT_NAME)).to_be_visible()
    assert ui.record_endpoint("group-a", IN_USE_ENDPOINT_ID) is not None


def test_reviewed_credential_message_renders_verbatim(group_endpoints_ui):
    """The server's reviewed credential message renders verbatim, and the draft is kept."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    ui.next_endpoint_write_error = ENDPOINT_STORED_CREDENTIAL_SUPPLIED
    open_manager(ui)
    row(ui, EDITABLE_ENDPOINT_NAME).get_by_role("button", name=f"Edit {EDITABLE_ENDPOINT_NAME}", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name", exact=True).fill("Credential refused draft")
    with page.expect_response(
        lambda response: response.request.method == "PATCH"
        and urlsplit(response.url).path == f"/api/groups/group-a/model-endpoints/{EDITABLE_ENDPOINT_ID}"
    ) as response:
        dialog.get_by_role("button", name="Save changes", exact=True).click()
    assert response.value.status == 400
    expect(dialog.get_by_text(ENDPOINT_STORED_CREDENTIAL_SUPPLIED, exact=True)).to_be_visible()
    expect(dialog.get_by_label("Name", exact=True)).to_have_value("Credential refused draft")


def test_group_discovery_uses_the_group_route(group_endpoints_ui):
    """Model discovery in the editor posts to the group /models/fetch route, never the admin one."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_manager(ui)
    row(ui, DISCOVERY_ENDPOINT_NAME).get_by_role(
        "button", name=f"Edit {DISCOVERY_ENDPOINT_NAME}", exact=True).click()
    dialog = page.get_by_role("dialog")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/groups/group-a/models/fetch"
    ) as response:
        dialog.get_by_role("button", name="Discover models", exact=True).click()
    assert response.value.ok
    assert_no_admin_or_personal_reads(ui)


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_member_sees_a_read_only_list(group_endpoints_ui, theme, width, height):
    """A member's endpoints section renders the collection read-only, with no write affordance."""
    ui, page = group_endpoints_ui, group_endpoints_ui.page
    open_endpoints(ui, group="group-b", theme=theme, width=width, height=height)
    expect(page.get_by_role("heading", name="Endpoints", exact=True)).to_be_visible()
    expect(row(ui, "Shared team connection")).to_be_visible()
    # No create control and no per-row write affordance: the member reads, never writes.
    expect(page.get_by_role("button", name="Add connection", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Disable Shared team connection", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Edit Shared team connection", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Delete Shared team connection", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="View Shared team connection", exact=True)).to_be_visible()
    assert endpoints_get(ui, group="group-b"), "The member's read-only section still lists from the group route."
    assert_no_admin_or_personal_reads(ui)
    ui.assert_no_overflow()
