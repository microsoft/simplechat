# test_v2_admin_governance_settings.py
"""
Browser coverage for the V2 Admin Settings governance group and its tie-ins.
Version: 0.261.273
Implemented in: 0.261.273

Exercise the built application, the real field schema, and in-memory governance
APIs. Check that the governance group replaces the fallback switch, that feature and
delegated item policies save through the governance API rather than the Save bar,
that unsaved policy edits cannot be discarded by navigating away or closing a dialog
mid-save, that the MCP destination builder refuses patterns that can never match,
and that the tie-ins on the Agents & Actions, Inbound MCP, and AI Connections
settings reach the same editor. No live settings or policies are touched.
"""

import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

# Fixtures stay under ui_tests; the import also registers Azure connect_options.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_governance import GovernanceSettingsFixture  # noqa: E402
from v2_admin_settings import connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

GOVERNANCE_REGIONS = (
    "Governance Feature Toggles",
    "Feature Policies",
    "Delegated Item Policies",
    "MCP Action Destination Governance",
    "Inbound MCP Source Governance",
)


@pytest.fixture
def governance_ui(page):
    fixture = GovernanceSettingsFixture(page)
    yield fixture
    fixture.assert_clean()


def _open_group(page, label):
    page.get_by_role("button", name=label, exact=True).click()


def _region(page, name):
    return page.get_by_role("region", name=name, exact=True)


def _add_principal(scope, list_title, search_label, term, entry_name):
    """Search a principal list and add one entry to it."""
    principal_list = scope.get_by_role("group", name=list_title, exact=True)
    principal_list.get_by_role("button", name=re.compile(r"^Find (people|groups)$")).click()
    principal_list.get_by_role("searchbox", name=search_label).fill(term)
    principal_list.get_by_role("button", name=f"Add {entry_name}", exact=True).click()
    expect(principal_list.get_by_role("list", name=list_title, exact=True)).to_contain_text(entry_name)


def _set_toggle(scope, label, checked):
    toggle = scope.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))
    if toggle.is_checked() != checked:
        scope.get_by_text(label, exact=True).click()
    expect(toggle).to_be_checked(checked=checked)


def test_governance_group_replaces_the_fallback_switch(governance_ui):
    governance_ui.open()
    page = governance_ui.page
    _open_group(page, "Governance")

    for name in GOVERNANCE_REGIONS:
        expect(_region(page, name)).to_be_visible()
    expect(page.get_by_text("Mcp destination governance", exact=True)).to_have_count(0)
    expect(page.get_by_text("Enforce MCP Destination Allowlist", exact=True)).to_be_visible()

    toggles = _region(page, "Governance Feature Toggles")
    expect(toggles.get_by_role("checkbox", name=re.compile("^Govern Group Agents"))).to_be_checked()
    # Kept while its feature is off, with the reason and a way to the feature.
    expect(toggles).to_contain_text("Govern Group Agents is kept")
    toggles.get_by_role("button", name="Configure Allow Group Agents", exact=True).click()
    expect(page.locator("#agent-toggles-card-title")).to_be_focused()
    expect(_region(page, "Workspace Agent Permissions")).to_be_visible()
    expect(_region(page, "Governance Feature Toggles")).to_have_count(0)

    # The feature links back to the governance that applies to it.
    permissions = _region(page, "Workspace Agent Permissions")
    expect(permissions.get_by_role("group", name="Related governance").filter(
        has_text="Govern Personal Agents"
    )).to_contain_text("On")
    permissions.get_by_role("button", name="Review Govern Group Agents", exact=True).click()
    expect(page.locator("#governance-feature-toggles-section-title")).to_be_focused()

    _region(page, "Governance Feature Toggles").get_by_role(
        "button", name="How a request is checked"
    ).click()
    expect(_region(page, "Governance Feature Toggles")).to_contain_text("Block lists")
    governance_ui.capture("governance-overview", folder="v2_admin_governance")
    assert governance_ui.patches == []


def test_feature_policy_restricts_an_audience_without_the_save_bar(governance_ui):
    governance_ui.open()
    page = governance_ui.page
    _open_group(page, "Governance")
    policies = _region(page, "Feature Policies")

    personal_agents = policies.locator('[data-feature-policy="governance_user_agents"]')
    expect(personal_agents).to_contain_text("Enforced")
    group_agents = policies.locator('[data-feature-policy="governance_group_agents"]')
    expect(group_agents).to_contain_text("Waiting for Allow Group Agents")

    personal_agents.get_by_role("button", name="Edit the Personal Agents policy").click()
    editor = page.get_by_role("group", name="Edit the Personal Agents policy")
    _set_toggle(editor, "Allow everyone", False)
    expect(editor.get_by_role("status").filter(has_text="Nobody passes this policy")).to_be_visible()
    _add_principal(editor, "Allowed people", "Search people by name or email", "Ada", "Ada Lovelace")
    _add_principal(
        editor, "Blocked groups", "Search group or public workspaces by name or ID",
        "research", "Research Library",
    )
    expect(editor.get_by_role("list", name="Blocked groups")).to_contain_text("Public")
    editor.get_by_role("button", name="Save policy", exact=True).click()

    expect(editor).to_have_count(0)
    expect(personal_agents).to_contain_text("Allows 1 person")
    expect(personal_agents).to_contain_text("Blocks 1 group")
    assert governance_ui.feature_writes == [{
        "feature_key": "governance_user_agents",
        "allow_all": False,
        "allowed_users": ["u-ada"],
        "allowed_groups": [],
        "denied_users": [],
        "denied_groups": ["pw-research"],
    }]
    assert governance_ui.patches == [], "A feature policy must not wait for the Save bar."

    # An unsaved prerequisite change is shown as what happens after saving.
    _open_group(page, "Agents & Actions")
    _set_toggle(_region(page, "Workspace Agent Permissions"), "Allow Group Agents", True)
    _open_group(page, "Governance")
    expect(group_agents).to_contain_text("Enforced after you save")
    page.get_by_role("button", name="Discard", exact=True).click()
    expect(group_agents).not_to_contain_text("after you save")


def test_unsaved_feature_policy_edit_locks_navigation(governance_ui):
    governance_ui.open()
    page = governance_ui.page
    _open_group(page, "Governance")
    group_agents = _region(page, "Feature Policies").locator('[data-feature-policy="governance_group_agents"]')
    edit = group_agents.get_by_role("button", name="Edit the Group Agents policy")
    edit.click()
    editor = page.get_by_role("group", name="Edit the Group Agents policy")
    search = page.get_by_role("searchbox", name="Search settings")
    # An editor with nothing changed has nothing to lose.
    expect(search).to_be_enabled()

    _set_toggle(editor, "Allow everyone", False)
    expect(editor).to_contain_text("Settings categories and search are locked")
    expect(page.get_by_role("button", name="Agents & Actions", exact=True)).to_be_disabled()
    expect(search).to_be_disabled()
    expect(edit).to_be_disabled()

    # Its feature is in another category, so going there is refused rather than
    # discarding the edit.
    group_agents.get_by_role("button", name="Go to setting").click()
    expect(page.get_by_text(re.compile("Save or discard the feature policy you are editing"))).to_be_visible()
    expect(_region(page, "Workspace Agent Permissions")).to_have_count(0)
    expect(editor.get_by_role("checkbox", name=re.compile("^Allow everyone"))).not_to_be_checked()

    editor.get_by_role("button", name="Discard changes", exact=True).click()
    expect(editor).to_have_count(0)
    expect(search).to_be_enabled()
    group_agents.get_by_role("button", name="Go to setting").click()
    expect(page.locator("#agent-toggles-card-title")).to_be_focused()
    assert governance_ui.feature_writes == []


def test_item_policy_create_inverse_duplicate_and_delete(governance_ui):
    governance_ui.open()
    page = governance_ui.page
    _open_group(page, "Governance")
    section = _region(page, "Delegated Item Policies")
    expect(section).to_contain_text("No delegated item policies yet")

    section.get_by_role("button", name="New policy", exact=True).click()
    dialog = page.get_by_role("dialog", name="New delegated item policy")
    dialog.get_by_label("Applies to", exact=True).select_option("global_agent")
    dialog.get_by_role("combobox", name="Item").select_option("agent-research")
    _set_toggle(dialog, "Allow everyone", False)
    _add_principal(dialog, "Allowed people", "Search people by name or email", "grace", "Grace Hopper")
    dialog.get_by_role("button", name="Create policy", exact=True).click()
    expect(dialog).to_have_count(0)

    created = governance_ui.item_writes[-1]
    assert created["entity_type"] == "global_agent" and created["item_id"] == "agent-research"
    assert created["policy_name"] == "Research Assistant Global Agent Policy"
    assert created["allow_all"] is False and created["allowed_users"] == ["u-grace"]
    expect(section.get_by_role("list", name="Delegated item policies")).to_contain_text(
        "Research Assistant Global Agent Policy"
    )

    section.get_by_role(
        "button", name="Inverse of Research Assistant Global Agent Policy: swap allowed and blocked"
    ).click()
    inverse = page.get_by_role("dialog", name="New delegated item policy")
    expect(inverse.get_by_label("Policy name", exact=True)).to_have_value("Research Assistant Global Agent Policy (inverse)")
    expect(inverse.get_by_role("checkbox", name=re.compile("^Allow everyone"))).to_be_checked()
    expect(inverse.get_by_role("list", name="Blocked people")).to_contain_text("Grace Hopper")
    inverse.get_by_role("button", name="Create policy", exact=True).click()
    expect(inverse).to_have_count(0)
    written = governance_ui.item_writes[-1]
    assert written["allow_all"] is True and written["denied_users"] == ["u-grace"]
    assert written["policy_id"] == "", "An inverse is a new policy, not an edit."
    pagination = section.get_by_role("status").filter(has_text="Showing")
    expect(pagination).to_contain_text("of 2")
    inverse_id = next(
        policy["policy_id"] for policy in governance_ui.item_policies
        if policy["policy_name"].endswith("(inverse)")
    )

    section.get_by_role("button", name="Duplicate Research Assistant Global Agent Policy", exact=True).click()
    duplicate = page.get_by_role("dialog", name="New delegated item policy")
    expect(duplicate.get_by_label("Policy name", exact=True)).to_have_value("Research Assistant Global Agent Policy (copy)")
    page.keyboard.press("Escape")
    expect(duplicate).to_have_count(0)
    assert len(governance_ui.item_writes) == 2

    section.get_by_role(
        "button", name="Delete Research Assistant Global Agent Policy (inverse)", exact=True
    ).click()
    section.get_by_role("button", name="Confirm delete").click()
    expect(pagination).to_contain_text("of 1")
    assert governance_ui.item_deletes == [
        {"entity_type": "global_agent", "item_id": "agent-research", "policy_id": inverse_id}
    ]
    assert governance_ui.patches == []


def test_mcp_destination_builder_refuses_patterns_that_cannot_match(governance_ui):
    governance_ui.open()
    page = governance_ui.page
    _open_group(page, "Governance")
    section = _region(page, "MCP Action Destination Governance")
    expect(section.get_by_role("status").filter(has_text="saved but not enforced")).to_be_visible()
    expect(section).to_contain_text("The deployment environment adds no destination restrictions")

    section.get_by_role("button", name="New group destination policy", exact=True).click()
    dialog = page.get_by_role("dialog", name="New delegated item policy")
    expect(dialog.get_by_label("Applies to", exact=True)).to_have_value("mcp_group_destination")
    # Nothing is reported before anything is entered.
    expect(dialog.get_by_role("alert")).to_have_count(0)
    dialog.get_by_role("button", name="Create policy", exact=True).click()
    expect(dialog.get_by_role("alert")).to_have_text("Choose a preconfigured server.")

    kind = dialog.get_by_label("What this policy allows", exact=True)
    kind.select_option("host")
    dialog.get_by_role("textbox", name="Host pattern").fill("mcp.contoso.com:8443")
    expect(dialog.get_by_role("alert")).to_contain_text("A host pattern is a host name only")
    dialog.get_by_role("button", name="Create policy", exact=True).click()
    expect(dialog.get_by_text(re.compile("A host pattern is a host name only"))).to_have_count(1)
    assert governance_ui.item_writes == []

    kind.select_option("transport")
    dialog.get_by_role("combobox", name="Transport").select_option("streamable_http")
    dialog.get_by_role("checkbox", name=re.compile("^Only for one group")).check()
    dialog.get_by_role("searchbox", name="Search groups for this destination policy").fill("oper")
    dialog.get_by_role("list", name="Matching groups").get_by_role(
        "button", name=re.compile("^Operations")
    ).click()
    expect(dialog).to_contain_text("Applies to Operations")
    expect(dialog.get_by_text("group:g-ops::transport:streamable_http", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Create policy", exact=True).click()
    expect(dialog).to_have_count(0)

    written = governance_ui.item_writes[-1]
    assert written["entity_type"] == "mcp_group_destination"
    assert written["item_id"] == "group:g-ops::transport:streamable_http"
    assert written["allow_all"] is True
    expect(section.get_by_role("list", name="MCP destination policies")).to_contain_text(
        "group:g-ops::transport:streamable_http"
    )

    # With a policy in place, turning the allowlist on clears the not-enforced notice.
    _set_toggle(section, "Enforce MCP Destination Allowlist", True)
    expect(section.get_by_role("status").filter(has_text="saved but not enforced")).to_have_count(0)
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    assert governance_ui.patches == [{"enable_mcp_destination_governance": True}]


def test_inbound_shortcut_creates_a_source_policy_and_links_to_governance(governance_ui):
    governance_ui.open()
    page = governance_ui.page
    _open_group(page, "Agents & Actions")
    inbound = _region(page, "Inbound MCP")
    expect(inbound.get_by_role("status").filter(
        has_text="No source policy yet, so inbound MCP returns no tools to anyone."
    )).to_be_visible()

    inbound.get_by_role("button", name="Create a policy for any source", exact=True).click()
    dialog = page.get_by_role("dialog", name="New delegated item policy")
    expect(dialog.get_by_label("Applies to", exact=True)).to_be_disabled()
    expect(dialog.get_by_role("combobox", name="Source")).to_have_value("*")
    # Restricted by default: nobody is allowed until someone is named.
    expect(dialog.get_by_role("checkbox", name=re.compile("^Allow everyone"))).not_to_be_checked()
    _add_principal(dialog, "Allowed groups", "Search group or public workspaces by name or ID", "pilot", "Personal Agents Pilot")
    dialog.get_by_role("button", name="Create policy", exact=True).click()
    expect(dialog).to_have_count(0)
    assert governance_ui.item_writes[-1]["entity_type"] == "inbound_mcp_source"
    assert governance_ui.item_writes[-1]["item_id"] == "*"
    assert governance_ui.item_writes[-1]["allowed_groups"] == ["g-pilot"]
    expect(inbound.get_by_role("status").filter(
        has_text="1 source policy decides who receives tools."
    )).to_be_visible()

    inbound.get_by_role("button", name="Review in Governance").click()
    expect(page.locator("#governance-inbound-mcp-section-title")).to_be_focused()
    expect(_region(page, "Inbound MCP Source Governance").get_by_role(
        "list", name="Inbound MCP source policies"
    )).to_contain_text("Inbound MCP all source access")


def test_ai_connection_access_dialog_creates_a_policy_and_returns(governance_ui):
    governance_ui.open()
    page = governance_ui.page
    _open_group(page, "AI Models")
    _region(page, "AI Connections").get_by_role(
        "button", name="Manage access to East US OpenAI", exact=True
    ).click()
    access = page.get_by_role("dialog", name="Access to East US OpenAI")
    expect(access).to_contain_text("No policy narrows this connection")

    access.get_by_role("button", name="New access policy", exact=True).click()
    expect(access).to_have_count(0)
    editor = page.get_by_role("dialog", name="New delegated item policy")
    expect(editor.get_by_role("combobox", name="Item")).to_have_value("conn-east")
    _set_toggle(editor, "Allow everyone", False)
    _add_principal(editor, "Allowed groups", "Search group or public workspaces by name or ID", "oper", "Operations")
    governance_ui.hold_item_writes = True
    editor.get_by_role("button", name="Create policy", exact=True).click()
    expect(editor.get_by_role("button", name="Saving…", exact=True)).to_be_visible()
    # A save in flight keeps its dialog open, so its outcome is never lost.
    page.keyboard.press("Escape")
    expect(editor).to_be_visible()
    governance_ui.release_item_writes()

    # Then the editor hands back to the list it was opened from, which stays open.
    access = page.get_by_role("dialog", name="Access to East US OpenAI")
    expect(access.get_by_role("list", name="Access policies for East US OpenAI")).to_contain_text(
        "East US OpenAI Global Endpoint Policy"
    )
    written = governance_ui.item_writes[-1]
    assert (written["entity_type"], written["item_id"], written["allowed_groups"]) == (
        "global_endpoint", "conn-east", ["g-ops"],
    )

    # Escape on an editor opened from the list goes back to the list, not off the page.
    access.get_by_role("button", name="Duplicate East US OpenAI Global Endpoint Policy", exact=True).click()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="Access to East US OpenAI")).to_be_visible()
    page.get_by_role("dialog", name="Access to East US OpenAI").get_by_role(
        "button", name="Close", exact=True
    ).last.click()
    expect(page.get_by_role("dialog")).to_have_count(0)


@pytest.mark.parametrize("theme,width", [("dark", 390), ("light", 1440)])
def test_governance_cards_fit_narrow_and_dark_layouts(governance_ui, theme, width):
    governance_ui.open(theme=theme, width=width)
    page = governance_ui.page
    if width >= 1024:
        _open_group(page, "Governance")
    else:
        page.get_by_label("Settings category").select_option(label="Governance")
    for name in GOVERNANCE_REGIONS:
        region = _region(page, name)
        expect(region).to_be_visible()
        overflow = region.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"{name} overflows by {overflow}px at {width}px"

    _region(page, "MCP Action Destination Governance").get_by_role(
        "button", name="New personal destination policy", exact=True
    ).click()
    dialog = page.get_by_role("dialog", name="New delegated item policy")
    expect(dialog).to_be_visible()
    body = dialog.locator("div.overflow-y-auto").first
    overflow = body.evaluate("element => element.scrollWidth - element.clientWidth")
    assert overflow <= 1, f"The policy editor overflows by {overflow}px at {width}px"
    panel = body.evaluate("element => element.parentElement.getBoundingClientRect().width")
    assert panel <= width, f"The policy editor is {panel}px wide in a {width}px viewport"
    governance_ui.capture(f"editor-{theme}-{width}", folder="v2_admin_governance")
