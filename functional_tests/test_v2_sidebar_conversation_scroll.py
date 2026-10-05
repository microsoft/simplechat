#!/usr/bin/env python3
# test_v2_sidebar_conversation_scroll.py
"""
Functional test for the V2 chat rail scrolling as one panel, and the workflow alert notice
hanging from the bell.
Version: 0.261.235
Implemented in: 0.261.235

On the V2 chat page the rail used to keep its whole height for the navigation and the
administrator's link groups, and the conversation list scrolled in whatever was left. With a
couple of external links configured, a 720px-tall window showed two conversations (#1642).
The classic sidebar has scrolled as one panel since 0.250.002 (#1098).

This test ensures that:
  - on the chat page, with the rail expanded, one scroll region holds the navigation, the
    link groups and the conversation list, with New chat above it and the footer below it;
  - the region scrolls nowhere else, so the collapsed strip and other pages lay out as before;
  - the conversation list has no scroller of its own, its search is held to the top of the
    region, and a short search result cannot pull the held search box out from under the
    reader;
  - paging and the held-header marker watch the region rather than the viewport;
  - keyboard focus on a row is moved out from under the held header, so it is never hidden;
  - the workflow alert notice hangs from the bell rather than from My Workspace, which the
    region can now scroll out of view.

These are source-level assertions, the convention for the V2 rail, so they run without a
build. ui_tests/test_v2_sidebar_conversation_scroll.py drives the rendered rail.
"""

import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
SIDEBAR_TSX = V2_SRC / "components" / "layout" / "Sidebar.tsx"
RAIL_TSX = V2_SRC / "components" / "chat" / "ConversationRail.tsx"
BELL_TSX = V2_SRC / "components" / "layout" / "NotificationBell.tsx"
NOTICE_TSX = V2_SRC / "components" / "notifications" / "WorkflowAlertNotice.tsx"
NOTICE_CSS = V2_SRC / "components" / "notifications" / "WorkflowAlertNotice.css"


def _read(path):
    return path.read_text(encoding="utf-8")


def _sidebar_component():
    """The body of the exported Sidebar component, without its helper components."""
    match = re.search(r"export function Sidebar\((.|\n)*", _read(SIDEBAR_TSX))
    assert match, "Sidebar should export a Sidebar component"
    return match.group(0)


def _scroll_region(body):
    """The rail's scroll region, from its opening tag to the footer that follows it."""
    start = body.find("ref={railScrollRef}")
    footer = body.find('<div className="shrink-0 space-y-1 border-t border-edge p-3">')
    assert start != -1, "The rail must have a scroll region bound to railScrollRef"
    assert footer != -1, "The rail's footer could not be located"
    assert start < footer, "The scroll region must come before the footer"
    return start, footer, body[start:footer]


def test_the_chat_rail_scrolls_as_one_panel():
    """Navigation, link groups and conversations share one region between New chat and the footer."""
    print("Testing the rail's scroll region...")

    body = _sidebar_component()
    assert "const showConversations = onChatPage && !collapsed;" in body, (
        "The region scrolls exactly when the conversation list is drawn: the chat page, full rail"
    )
    assert "className={clsx('flex-1', showConversations && 'min-h-0 overflow-y-auto')}" in body, (
        "The region must fill the rail and scroll only while the conversation list is shown"
    )

    start, footer, region = _scroll_region(body)
    nav_list = region.find("{NAV_ITEMS.map((item) => (")
    extras = region.find("<NavExtras collapsed={collapsed} />")
    rail = region.find("{showConversations && <ConversationRail scrollRootRef={railScrollRef} />}")
    assert -1 not in (nav_list, extras, rail), (
        "The navigation list, the link groups and the conversation list must all be inside the region"
    )
    assert nav_list < extras < rail, "The region keeps the rail's order: navigation, groups, conversations"

    new_chat = body.find('title="Start a new chat"')
    assert new_chat != -1 and new_chat < start, (
        "New chat stays above the region, so the held search settles right under it"
    )
    assert body.find("onClick={toggleTheme}") > footer, "The theme toggle stays in the fixed footer"
    assert body.find("<UserMenu collapsed={collapsed} />") > footer, "The account menu stays in the fixed footer"

    # The pieces the region replaced must not linger and split the height again.
    assert "mt-4 min-h-0 flex-1 border-t border-edge pt-3" not in body, (
        "The list's own flexing wrapper must be gone; it is what squeezed the list"
    )
    assert "(!onChatPage || collapsed) && <div className=\"flex-1\" />" not in body, (
        "The region fills the leftover height itself, so the old spacer must be gone"
    )
    # New chat's spacing still follows the button (test_v2_new_chat_scoping.py).
    assert "clsx('space-y-0.5 px-3', onChatPage && 'mt-3')" in region

    print("Rail scroll region test passed!")
    return True


def test_the_conversation_list_has_no_scroller_of_its_own():
    """One scrollbar for the whole panel, with the search held at its top."""
    print("Testing the conversation list layout...")

    rail = _read(RAIL_TSX)
    assert "overflow-y-auto" not in rail, (
        "The list must scroll with the rail; a scroller of its own is what kept it two rows tall"
    )
    assert "flex h-full min-h-0 flex-col" not in rail, "The list no longer sizes itself to a flex slot"

    assert "'relative mt-4 border-t border-edge'" in rail, (
        "The section carries the divider the Sidebar's wrapper used to draw"
    )
    assert "'sticky top-0 z-10 px-3 pt-3 pb-2'" in rail, (
        "The search header must be held to the top of the rail's region, keeping the old top spacing"
    )
    assert "searchTerm && 'min-h-full'" in rail, (
        "While a search narrows the list, the section must keep the region's height, so a short "
        "result cannot shrink the scroll range and drag the search box out from under the reader"
    )

    print("Conversation list layout test passed!")
    return True


def test_the_held_header_is_marked_without_rerendering_the_list():
    """Solid backing and an edge only while held; at rest the rail looks as it did."""
    print("Testing the held-header marker...")

    rail = _read(RAIL_TSX)
    assert "data-stuck:bg-surface-solid" in rail, "Held, the header needs a solid backing"
    assert "data-stuck:shadow-[0_1px_0_var(--edge-strong)]" in rail, (
        "Held, the header needs an edge where the list starts; light --edge is a white highlight "
        "that would vanish on the solid backing"
    )
    assert "header.toggleAttribute('data-stuck', stuck);" in rail, (
        "The marker is written to the node: state would re-render every row at the threshold"
    )
    assert re.search(r"ref=\{stuckMarkerRef\}\s*aria-hidden=\"true\"", rail), (
        "The marker the observer watches is decorative and hidden from assistive technology"
    )

    print("Held-header marker test passed!")
    return True


def test_paging_and_the_marker_watch_the_rail_region():
    """Both observers measure against the region the list now scrolls in."""
    print("Testing the observers' root...")

    rail = _read(RAIL_TSX)
    assert "scrollRootRef: RefObject<HTMLElement>;" in rail, "The rail's region must be passed in"
    assert "{ root: scrollRootRef.current, rootMargin: '120px' }" in rail, (
        "Paging must watch the region, or the region's edge clips the look-ahead margin and the "
        "next page waits until the last row is already on screen"
    )
    assert "}, [hasMore, loadMore, scrollRootRef]);" in rail
    assert "const root = scrollRootRef.current;" in rail and "{ root }," in rail, (
        "The held-header marker must be measured against the region's top, not the viewport's"
    )

    print("Observer root test passed!")
    return True


def test_rows_keep_clear_of_the_held_header():
    """Keyboard focus is moved out from under the held search, never under it (WCAG 2.4.11)."""
    print("Testing focus clearance...")

    rail = _read(RAIL_TSX)
    assert '<ul className="space-y-0.5" onFocus={keepFocusClearOfHeader}>' in rail, (
        "Row controls reached from the keyboard must be kept clear of the held search: the "
        "browser only scrolls a focused control into view when it lies outside the region"
    )
    handler = re.search(r"const keepFocusClearOfHeader = \((.|\n)*?\n    \};", rail)
    assert handler, "keepFocusClearOfHeader should be defined in the rail"
    body = handler.group(0)
    assert "target.matches(':focus-visible')" in body, (
        "Only keyboard focus may move the list: scrolling a clicked row out from under the "
        "pointer before the release would swallow the click"
    )
    assert "header.getBoundingClientRect().bottom - target.getBoundingClientRect().top" in body
    assert "root.scrollTop -= covered + FOCUS_CLEARANCE_PX;" in body

    # Neither CSS mechanism does the job here, and one of them actively harms.
    assert "scroll-mt-" not in rail, (
        "Chromium ignores a control's scroll-margin when the control is already in the region"
    )
    _, _, region = _scroll_region(_sidebar_component())
    assert "scroll-pt" not in region and "scroll-padding" not in region, (
        "Region scroll padding also applies to the held search box, so focusing it would throw "
        "the list hundreds of pixels"
    )

    print("Focus clearance test passed!")
    return True


def test_the_workflow_alert_notice_hangs_from_the_bell():
    """My Workspace can scroll out of view now; the bell cannot."""
    print("Testing the alert notice anchor...")

    sidebar = _read(SIDEBAR_TSX)
    assert "WorkflowAlertCalloutSlot" not in sidebar, (
        "The notice must no longer hang from My Workspace, which the rail can scroll away"
    )
    assert "item.to === '/workspace' ? 'relative'" not in sidebar, (
        "My Workspace no longer anchors anything, so it needs no positioning context"
    )
    assert "!mobile && alertCalloutShown && 'z-40'" in sidebar, (
        "The rail must still lift itself above the page while the notice hangs past its edge"
    )
    assert '<NotificationBell collapsed className="mx-3 mb-1 justify-center" />' in sidebar, (
        "Collapsed, the bell's wrapper spans the strip's inner width so the notice flies out "
        "from the strip's edge, and the bell stays centred over the expand button"
    )

    bell = _read(BELL_TSX)
    assert "<div className={clsx('relative flex shrink-0', className)}>" in bell, (
        "The bell's wrapper is the notice's positioning anchor and takes the layout classes"
    )
    button = bell.find('data-notification-bell=""')
    slot = bell.find("<WorkflowAlertCalloutSlot collapsed={collapsed} />")
    panel = bell.find("<NotificationPanel ")
    assert -1 not in (button, slot, panel), "The bell must render the notice's slot"
    assert button < slot < panel, (
        "The notice must follow the bell in the tab order, the item it hangs from"
    )

    notice = _read(NOTICE_TSX)
    assert "'top-full left-[calc(50%_-_24px)] mt-2'" in notice, (
        "Expanded, the notice drops from the bell as the bell's panel does, notch under the bell"
    )
    assert "'top-[calc(50%_-_22px)] left-full ml-3 max-w-[calc(100vw_-_68px_-_1rem)]'" in notice, (
        "Collapsed or on a phone, it flies out from the strip's edge, notch level with the bell"
    )
    assert "My Workspace item" not in notice, "The notice's own description must match its anchor"

    # The slot's offsets line the notch up; they only hold while the notch stays where it is.
    css = _read(NOTICE_CSS)
    below = re.search(r"\[data-placement='below'\] > \.wf-alert-notch \{(.*?)\}", css, re.DOTALL)
    flyout = re.search(r"\[data-placement='flyout'\] > \.wf-alert-notch \{(.*?)\}", css, re.DOTALL)
    assert below and "left: 18px;" in below.group(1), "Below the bell, the notch sits 18px in"
    assert flyout and "top: 16px;" in flyout.group(1), "Beside the bell, the notch sits 16px down"
    assert re.search(r"\.wf-alert-notch \{[^}]*width: 12px;[^}]*height: 12px;", css, re.DOTALL), (
        "The notch is 12px square, which is what centres it 24px in and 22px down"
    )

    print("Alert notice anchor test passed!")
    return True


def test_version_is_at_least_the_implementation_version():
    """The application carries at least the version this behaviour arrived in."""
    print("Testing version...")
    assert_app_version_at_least(
        "0.261.235",
        reason="The V2 rail scroll region and the bell-anchored alert notice landed in 0.261.235.",
    )
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_the_chat_rail_scrolls_as_one_panel,
        test_the_conversation_list_has_no_scroller_of_its_own,
        test_the_held_header_is_marked_without_rerendering_the_list,
        test_paging_and_the_marker_watch_the_rail_region,
        test_rows_keep_clear_of_the_held_header,
        test_the_workflow_alert_notice_hangs_from_the_bell,
        test_version_is_at_least_the_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
