# test_v2_public_journeys.py
"""M11 public end-to-end journeys: the role x status x File-Sync matrix, mid-session
transitions, Settings activation and the classic handoff, driven through the real SPA.

Version: 0.261.188
Implemented in: 0.261.185
The classic handoff follows the Documents header's renamed Classic tools button: 0.261.188
A locked overview entry is outlined, never faded, and its text stays readable: 0.261.188
The overview describes what a public workspace offers, and its Manage group who manages it: 0.261.188

These journeys are the public twin of test_v2_group_journeys.py. They ride one composite
public store (public_journeys_ui) across the whole public surface in one session and assert
that what the rail, the header and the overview render matches the pinned public context
exactly, for every role and status the server can return, and that a manager reaches the
connection sections only when File Sync is on for the workspace.

The matrix reads its expected sections and states from public_context(...) -- the same builder
test_public_context_fixture_parity holds to build_public_workspace_context -- rather than from a
second hand-written table, so a new public section (M10C's settings, activity and statistics)
flows into the matrix the moment it is added to the context and PUBLIC_WORKSPACE_SECTION_IDS.
Its rail label must then be added to PUBLIC_SECTION_LABELS below.

Coverage of M11 contract sec 2.3 (public role x status x feature):
    role x status matrix (rail + header + overview) . test_jp_rail_matches_the_pinned_context_matrix
    the File-Sync feature axis ...................... test_jp_file_sync_gates_the_connection_sections
    a reader's locked connection sections .......... test_jp_overview_lists_locked_connections_with_their_reason
    locked entries outlined, readable (2.4) ........ test_jp_locked_overview_entries_stay_readable
    the overview's public wording (2.4) ............ test_jp_overview_describes_what_a_public_workspace_offers
    status revoked mid-session (2.2) ............... test_jp_status_locked_then_barred_mid_session
    access revoked mid-session, 403 (2.2) ......... test_jp_access_revoked_mid_session_is_surfaced
    Settings activation refresh (2.2) ............. test_jp_settings_activation_makes_the_surface_available
    classic handoff round trip .................... test_jp_classic_handoff_carries_the_public_workspace
    the picker reaches another workspace .......... test_jp_picker_moves_between_public_workspaces
"""

import copy
import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.public_journeys import public_journeys_ui  # noqa: F401
from ui_tests.fixtures.public_workspace import (
    PUBLIC_CONNECTIONS_MANAGER_REASON, PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON,
    PUBLIC_IDENTITIES_UNAVAILABLE_REASON, PUBLIC_INACTIVE_REASON, PUBLIC_STATUS_UNKNOWN_REASON,
)
from ui_tests.fixtures.workspace_authoring import ORIGIN


pytestmark = pytest.mark.ui


# The rail label for each public section id, mirrored from pages/workspace/sections.tsx via
# WORKSPACE_SECTIONS_BY_ID -- the same strings test_v2_group_journeys.py pins -- so the matrix can
# name the link the SPA renders. The public context parity pin guards the underlying ids, and the
# public rail is PUBLIC_WORKSPACE_SECTION_IDS (documents, tags, sync, prompts, identities) plus the
# Manage group's Members.
PUBLIC_SECTION_LABELS = {
    "documents": "Documents", "tags": "Tags", "sync": "File sources",
    "prompts": "Prompts", "identities": "Identities", "members": "Members",
    "settings": "Settings", "activity": "Activity", "statistics": "Statistics",
}

# The header's friendly status strings, mirrored from lib/publicWorkspaceLabels PUBLIC_STATUS_LABELS.
# The public header carries only a Status pill -- no Role pill, unlike the group header -- so a raw
# "locked" would leak here if these drifted.
PUBLIC_STATUS_LABELS = {
    "active": "Active", "locked": "Locked - read only",
    "upload_disabled": "Uploads disabled", "inactive": "Inactive",
    "unknown": "Status unavailable",
}


def rail_enabled(context, sectionId):
    """Whether the public rail shows a section, exactly as the public navigation availability decides.

    The public rail reads each section's own `enabled` with no native-delegation swap: the public
    surface has no Call-agent-tools escape hatch, so a section is a live link only when its context
    entry is enabled.
    """
    return bool(context["sections"][sectionId]["enabled"])


def section(page, label):
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role(
        "link", name=label, exact=True).click()


def refocus(ui):
    # The App refreshes its bootstrap on focus and the public page revalidates its context on the
    # same event; this is how a status change, a revocation or a Settings activation another actor
    # made server-side reaches an already-open public page.
    ui.page.evaluate("window.dispatchEvent(new Event('focus'))")


def setactive_writes(ui):
    return [entry for entry in ui.writes if entry.path == "/api/public_workspaces/setActive"]


# --- J-P10: the role x status x File-Sync matrix -------------------------------------------------

# raw status sent to the fixture, and the status the server coerces it to. An unrecognized status
# (here "frozen") becomes "unknown", exactly as build_public_workspace_context does.
_STATUSES = [("active", "active"), ("locked", "locked"),
             ("upload_disabled", "upload_disabled"), ("inactive", "inactive"), ("frozen", "unknown")]
_ROLES = ["Owner", "Admin", "DocumentManager", "User"]

_MATRIX = [
    pytest.param(role, raw, coerced, 1440, 900, id=f"{role}-{coerced}-desktop")
    for role in _ROLES for raw, coerced in _STATUSES
] + [
    # Contract sec 2: run one role at 390x844, across a viewable and a non-viewable status.
    pytest.param("Owner", raw, coerced, 390, 844, id=f"Owner-{coerced}-mobile")
    for raw, coerced in (("active", "active"), ("frozen", "unknown"))
]


@pytest.mark.parametrize("role,rawStatus,status,width,height", _MATRIX)
def test_jp_rail_matches_the_pinned_context_matrix(public_journeys_ui, role, rawStatus, status, width, height):
    ui = public_journeys_ui
    ui.set_matrix("pub-a", role=role, status=rawStatus)
    context = copy.deepcopy(ui.workspaces["pub-a"])
    assert context["role"] == role and context["status"] == status
    ui.open("/public/pub-a", width=width, height=height)
    # The public header names the status exactly as the pinned context does, and never a role -- the
    # public surface publishes to everyone, so it withholds the viewer's own role.
    expect(ui.page.get_by_text(f"Status: {PUBLIC_STATUS_LABELS[status]}", exact=True)).to_be_visible()
    expect(ui.page.get_by_text("Role:", exact=False)).to_have_count(0)
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    # Every rail section is present or absent exactly as the context says; a disabled section is
    # never a live link, so nothing offers a control the context withholds.
    for sectionId, label in PUBLIC_SECTION_LABELS.items():
        expected = 1 if rail_enabled(context, sectionId) else 0
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_count(expected)
    if status in ("inactive", "unknown"):
        # A status that bars viewing leaves nothing in the rail; the overview carries the reason.
        reason = PUBLIC_INACTIVE_REASON if status == "inactive" else PUBLIC_STATUS_UNKNOWN_REASON
        expect(ui.page.get_by_text(reason, exact=False).first).to_be_visible()


def test_jp_file_sync_gates_the_connection_sections(public_journeys_ui):
    ui = public_journeys_ui
    # File Sync is the sole gate on Identities and File sources, and both are manager-only. A manager
    # of an active workspace reaches them only when File Sync is on for the workspace.
    ui.set_matrix("pub-a", role="Owner", status="active", file_sync=True)
    context = copy.deepcopy(ui.workspaces["pub-a"])
    assert rail_enabled(context, "identities") and rail_enabled(context, "sync")
    ui.open("/public/pub-a")
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    expect(nav.get_by_role("link", name="Identities", exact=True)).to_have_count(1)
    expect(nav.get_by_role("link", name="File sources", exact=True)).to_have_count(1)
    # Turn File Sync off for the same manager: both sections vanish from the rail, and the overview
    # explains that they require File Sync rather than implying the role is at fault.
    ui.set_matrix("pub-a", role="Owner", status="active", file_sync=False)
    refocus(ui)
    expect(nav.get_by_role("link", name="Identities", exact=True)).to_have_count(0)
    expect(nav.get_by_role("link", name="File sources", exact=True)).to_have_count(0)
    identities = ui.page.get_by_label("Identities (unavailable)", exact=True)
    expect(identities).to_contain_text(PUBLIC_IDENTITIES_UNAVAILABLE_REASON)
    expect(ui.page.get_by_label("File sources (unavailable)", exact=True)).to_contain_text(
        PUBLIC_FILE_SOURCES_UNAVAILABLE_REASON)


def test_jp_overview_lists_locked_connections_with_their_reason(public_journeys_ui):
    ui = public_journeys_ui
    # An ordinary reader on an active workspace: Documents and Prompts are available, the connection
    # sections are locked with the manager-only reason (never the File-Sync reason, which is a
    # manager's message). The overview must list both, so it matches the rail.
    ui.set_matrix("pub-a", role="User", status="active", file_sync=True)
    context = copy.deepcopy(ui.workspaces["pub-a"])
    ui.open("/public/pub-a")
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    for sectionId in ("identities", "sync"):
        assert not rail_enabled(context, sectionId)
        label = PUBLIC_SECTION_LABELS[sectionId]
        expect(nav.get_by_role("link", name=label, exact=True)).to_have_count(0)
        locked = ui.page.get_by_label(f"{label} (unavailable)", exact=True)
        expect(locked).to_be_visible()
        expect(locked).to_contain_text(PUBLIC_CONNECTIONS_MANAGER_REASON)
    assert rail_enabled(context, "documents")
    expect(ui.page.get_by_label("Documents (unavailable)", exact=True)).to_have_count(0)


# The contrast of each text line in an unavailable overview entry against what it's drawn on. The line's
# colour comes from its computed style, blended toward the background by every ancestor's opacity (the
# fading that caused 2.8:1); the background is the ancestors' colours composited on the theme's backdrop
# base. The backdrop's faint radial tints are left out, which changes no verdict here.
UNAVAILABLE_ENTRY_CONTRAST = """(entry) => {
    const parse = (value) => {
        const text = String(value).trim();
        if (text.startsWith('#')) {
            const hex = text.slice(1);
            const full = hex.length === 3 ? hex.split('').map((digit) => digit + digit).join('') : hex;
            return { r: parseInt(full.slice(0, 2), 16), g: parseInt(full.slice(2, 4), 16), b: parseInt(full.slice(4, 6), 16), a: 1 };
        }
        const parts = (text.match(/[\\d.]+/g) || []).map(Number);
        return { r: parts[0] ?? 0, g: parts[1] ?? 0, b: parts[2] ?? 0, a: parts[3] ?? 1 };
    };
    const over = (top, bottom, alpha) => ({
        r: top.r * alpha + bottom.r * (1 - alpha), g: top.g * alpha + bottom.g * (1 - alpha),
        b: top.b * alpha + bottom.b * (1 - alpha), a: 1,
    });
    const channel = (value) => {
        const unit = value / 255;
        return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
    };
    const luminance = (colour) => 0.2126 * channel(colour.r) + 0.7152 * channel(colour.g) + 0.0722 * channel(colour.b);
    const base = parse(getComputedStyle(document.documentElement).getPropertyValue('--backdrop-base'));
    return [...entry.querySelectorAll('p')].filter((line) => line.textContent.trim()).map((line) => {
        const chain = [];
        for (let node = line; node; node = node.parentElement) chain.unshift(node);
        let background = base;
        let opacity = 1;
        for (const node of chain) {
            const style = getComputedStyle(node);
            opacity *= Number(style.opacity);
            const colour = parse(style.backgroundColor);
            background = over(colour, background, colour.a);
        }
        const colour = parse(getComputedStyle(line).color);
        const text = over(colour, background, colour.a * opacity);
        const [lighter, darker] = [luminance(text), luminance(background)].sort((a, b) => b - a);
        return { text: line.textContent.trim(), opacity, ratio: (lighter + 0.05) / (darker + 0.05) };
    });
}"""


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_jp_locked_overview_entries_stay_readable(public_journeys_ui, theme):
    """A locked overview entry reads as locked through its dashed outline, its lock and its reason, never by
    fading: in neither theme is it faded, and in dark every line of it reaches 4.5:1 (faded, its reason
    fell to 2.8:1) (M11)."""
    ui = public_journeys_ui
    ui.set_matrix("pub-a", role="User", status="active", file_sync=True)
    ui.open("/public/pub-a", theme=theme)
    for sectionId in ("identities", "sync"):
        label = PUBLIC_SECTION_LABELS[sectionId]
        entry = ui.page.get_by_label(f"{label} (unavailable)", exact=True)
        expect(entry).to_be_visible()
        lines = entry.evaluate(UNAVAILABLE_ENTRY_CONTRAST)
        assert len(lines) == 3, lines
        assert all(line["opacity"] == 1 for line in lines), f"The {label} entry is faded: {lines}"
        if theme == "dark":
            low = [line for line in lines if line["ratio"] < 4.5]
            assert not low, f"The {label} entry has text below 4.5:1 in dark: {low}"


PUBLIC_OVERVIEW_DESCRIPTION = (
    "Published documents and prompts for this public workspace, and how it's connected and run. "
    "A locked section shows why it's unavailable to you."
)
PUBLIC_MANAGE_BLURB = "Who manages this workspace, and how it is run."


def test_jp_overview_describes_what_a_public_workspace_offers(public_journeys_ui):
    """The overview says what a public workspace holds, with no word of Classic sections it no longer has,
    and its Manage group describes the people who manage it, not a group's members (M11)."""
    ui = public_journeys_ui
    ui.set_matrix("pub-a", role="User", status="active", file_sync=True)
    ui.open("/public/pub-a")
    main = ui.page.get_by_role("main")
    expect(main.get_by_text(PUBLIC_OVERVIEW_DESCRIPTION, exact=True)).to_be_visible()
    expect(main.get_by_text(re.compile("Classic"))).to_have_count(0)
    manage = main.locator("section").filter(has=ui.page.get_by_role("heading", name="Manage", exact=True))
    expect(manage.get_by_text(PUBLIC_MANAGE_BLURB, exact=True)).to_be_visible()
    expect(main.get_by_text(re.compile("this group"))).to_have_count(0)


# --- J-P: mid-session transitions ----------------------------------------------------------------

def test_jp_status_locked_then_barred_mid_session(public_journeys_ui):
    ui = public_journeys_ui
    # A reader opens an active workspace and reaches Documents.
    ui.set_matrix("pub-a", role="User", status="active")
    ui.open("/public/pub-a/documents")
    nav = ui.page.get_by_role("navigation", name="Workspace sections", exact=True)
    expect(nav.get_by_role("link", name="Documents", exact=True)).to_have_count(1)
    # An administrator locks the workspace: reads stay, but the header flips to the locked status and
    # the rail keeps only the still-viewable sections.
    ui.set_matrix("pub-a", role="User", status="locked")
    refocus(ui)
    expect(ui.page.get_by_text("Status: Locked - read only", exact=True)).to_be_visible()
    expect(nav.get_by_role("link", name="Documents", exact=True)).to_have_count(1)
    # The workspace is then made inactive: viewing is barred, the rail clears, and the overview
    # carries the administrator-only reason -- no section is left offering a control.
    ui.set_matrix("pub-a", role="User", status="inactive")
    refocus(ui)
    expect(ui.page.get_by_text("Status: Inactive", exact=True)).to_be_visible()
    expect(nav.get_by_role("link", name="Documents", exact=True)).to_have_count(0)
    expect(ui.page.get_by_text(PUBLIC_INACTIVE_REASON, exact=False).first).to_be_visible()


def test_jp_access_revoked_mid_session_is_surfaced(public_journeys_ui):
    ui = public_journeys_ui
    ui.set_matrix("pub-a", role="User", status="active")
    ui.open("/public/pub-a")
    expect(ui.page.get_by_text("Status: Active", exact=True)).to_be_visible()
    # Access is revoked server-side: the next context revalidation returns 403, and the page surfaces
    # a refresh notice rather than silently keeping the stale surface or leaking another scope.
    ui.denied_workspaces.add("pub-a")
    refocus(ui)
    expect(ui.page.get_by_role("status").filter(has_text="Refreshing")).to_have_count(0)
    expect(ui.page.get_by_role("alert")).to_be_visible()


# --- J-P: Settings activation and the classic handoff --------------------------------------------

def test_jp_settings_activation_makes_the_surface_available(public_journeys_ui):
    ui = public_journeys_ui
    # Public workspaces are disabled deployment-wide: the surface is unavailable, and it must not
    # degrade into a personal or group experience -- it simply says the feature is off.
    ui.public_enabled = False
    ui.open("/public")
    expect(ui.page.get_by_text("Public Workspaces are not enabled", exact=True)).to_be_visible()
    # An administrator enables the feature in Settings: a refocus re-bootstraps and the chooser
    # becomes available without a reload.
    ui.public_enabled = True
    refocus(ui)
    expect(ui.page.get_by_text("Public Workspaces are not enabled", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("combobox", name="Public Workspace", exact=True)).to_be_visible()


def test_jp_classic_handoff_carries_the_public_workspace(public_journeys_ui):
    ui = public_journeys_ui
    ui.open("/public/pub-a/documents")
    # The Documents header's hand-off is "Classic tools", named for the legacy document upgrade (M11 2.4).
    ui.page.get_by_role("button", name="Open classic tools to upgrade legacy public workspace documents", exact=True).click()
    expect(ui.page).to_have_url(f"{ORIGIN}/public_workspaces")
    assert ("/public_workspaces", "pub-a") in ui.classic_visits


def test_jp_picker_moves_between_public_workspaces(public_journeys_ui):
    ui = public_journeys_ui
    ui.set_matrix("pub-a", role="Owner", status="active")
    ui.set_matrix("pub-b", role="User", status="active")
    ui.open("/public/pub-a/documents")
    # Selecting another workspace navigates by its explicit id and records the courtesy activation;
    # the reads that follow target the id in the path, never a leaked active selection.
    ui.page.get_by_role("combobox", name="Public Workspace", exact=True).select_option("pub-b")
    expect(ui.page).to_have_url(f"{ORIGIN}/v2/public/pub-b/documents")
    assert setactive_writes(ui) and setactive_writes(ui)[-1].body == {"workspaceId": "pub-b"}
    assert ui.active_workspace == "pub-b"
