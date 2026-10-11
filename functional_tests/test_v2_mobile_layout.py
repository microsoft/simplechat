# test_v2_mobile_layout.py
"""
Functional contracts for the shared V2 responsive layout.
Version: 0.261.325
Implemented in: 0.261.323

Pins shared components, preference isolation, local assets, and responsive
document presentation. Geometry and interactions are covered by the mobile UI tests.
"""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "application" / "v2_ui" / "src"


def read(relative):
    return (SOURCE / relative).read_text(encoding="utf-8")


def test_navigation_does_not_reserve_closed_mobile_rail_space():
    shell = read("components/layout/AppShell.tsx")
    assert "w-[68px]" not in shell
    assert "(!mobile || mobileNavOpen)" in shell
    assert "MobileNavigationContext.Provider" in shell
    assert "mobile && mobileNavOpen" in shell
    assert ".inert =" in shell
    for file_name in ("components/layout/PageHeader.tsx", "pages/ChatPage.tsx"):
        assert "<MobileNavigation" in read(file_name)


def test_mobile_disclosure_does_not_write_desktop_preferences():
    controls = read("components/layout/MobileNavigation.tsx")
    assert "setMobileNavOpen" in controls
    assert "toggleRail" not in controls
    assert "useUserSettingsStore" not in controls
    state = read("stores/uiStore.ts")
    assert "setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen })" in state
    workspace = read("components/workspace/WorkspaceShell.tsx")
    assert "const collapsed = !mobile && railCollapsed" in workspace
    assert "groupWorkspaceSections(navigableSections(sections))" in workspace


def test_mobile_documents_reuse_rows_without_persisting_column_changes():
    table = read("components/documents/DocumentTable.tsx")
    assert "mobile ? column.id === 'name' : columns.includes(column.id)" in table
    assert "DocumentStatusBadge" in table
    assert "ClassificationBadge" in table
    assert "blockedReason" in table
    assert "updatePrefs" not in table
    assert "max-md:break-words" in table
    composer = read("components/chat/Composer.tsx")
    assert 'aria-controls="composer-secondary-tools"' in composer
    assert "composer-primary-actions" in composer
    assert "effectiveApprovalMode" in composer


def test_viewport_support_preserves_zoom_and_local_assets():
    index = (ROOT / "application" / "v2_ui" / "index.html").read_text(encoding="utf-8")
    assert "viewport-fit=cover" in index
    assert "user-scalable=no" not in index
    assert "maximum-scale" not in index
    css = read("styles/theme.css")
    assert "100dvh" in css
    assert "safe-area-inset-bottom" in css
    assert "min-height: 44px" in css


def test_headers_count_explicit_actions_and_keep_mobile_overlays_out_of_flow():
    header = read("components/layout/PageHeader.tsx")
    assert "shrink-0 flex-wrap" not in header
    assert "md:flex-wrap" in header
    assert "actions?: HeaderActionItems" in header
    assert 'role="status"' in header
    actions = read("components/layout/HeaderActions.tsx")
    assert "visible.length > 2" in actions
    assert "visible.slice(0, 1)" in actions
    assert "action.disabled || action.loading" in actions
    assert "aria-label={action.label}" in actions
    overlay = read("components/ui/ActionPopover.tsx")
    assert "createPortal" in overlay
    assert "document.body" in overlay
    assert "pointerdown" in overlay
    assert "focusin" in overlay
    assert "onClose(true)" in overlay
    chat = read("pages/ChatPage.tsx")
    assert "anchorRef={actionsTrigger}" in chat
    assert "(!mobile || actionsOpen)" in chat
    css = read("styles/theme.css")
    assert not re.search(r"\.(?:page|chat)-header-actions\s*\{[^}]*flex-basis:\s*100%", css)
    workspace = read("pages/workspace/WorkspacePage.tsx")
    assert "actions={[tour.action]}" in workspace
    assert "{tour.dialog}" in workspace


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
