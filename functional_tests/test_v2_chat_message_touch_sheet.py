#!/usr/bin/env python3
# test_v2_chat_message_touch_sheet.py
"""
Functional test for the V2 chat touch action sheet.
Version: 0.261.476
Implemented in: 0.261.476

This test ensures that pressing and holding a chat message on a touch screen opens the
message's actions in a bottom sheet, that the sheet reuses MessageActions rather than a copy
of it, that the hover-revealed action row is unchanged, and that the long press leaves mouse
input, scrolling, links, buttons and code alone.
"""

import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "application" / "v2_ui" / "src"


def read(relative):
    return (SOURCE / relative).read_text(encoding="utf-8")


def test_long_press_is_touch_only_and_cancellable():
    hook = read("lib/useLongPress.ts")
    assert hook.startswith("// useLongPress.ts")
    assert "event.pointerType !== 'touch'" in hook
    assert "LONG_PRESS_MS = 450" in hook
    assert "LONG_PRESS_MOVE_TOLERANCE_PX = 10" in hook
    assert "const onPointerCancel = useCallback(() => release(), [release]);" in hook
    for target in ("'a'", "'button'", "'pre'", "'code'", "'[role=\"dialog\"]'"):
        assert target in hook, target
    assert "target?.closest(LONG_PRESS_IGNORED_TARGETS)" in hook


def test_long_press_ignores_events_from_its_own_portal():
    hook = read("lib/useLongPress.ts")
    # The sheet is portaled but is a React child of the message, so its taps reach the hook.
    assert "function isOwnEvent(" in hook
    assert "event.currentTarget.contains(event.target)" in hook
    assert hook.count("isOwnEvent(event)") >= 4
    assert "LIFT_CLICK_WINDOW_MS" in hook
    assert "-webkit-touch-callout" in hook


def test_sheet_reuses_message_actions():
    list_source = read("components/chat/MessageList.tsx")
    assert "import { MessageActionSheet } from './MessageActionSheet';" in list_source
    assert "<MessageActions {...actionProps} />" in list_source
    assert "<MessageActions {...actionProps} onSheetDone={closeActionSheet} />" in list_source
    assert "<MessageActions message={message} onSheetDone={closeActionSheet} />" in list_source
    assert "useLongPress(() => setActionSheetOpen(true), !editing)" in list_source


def test_hover_row_is_unchanged():
    list_source = read("components/chat/MessageList.tsx")
    assert "'transition-opacity group-hover/message:opacity-100 focus-within:opacity-100'" in list_source
    assert "inspector || replayExpanded ? 'opacity-100' : 'opacity-0'" in list_source
    actions = read("components/chat/MessageActions.tsx")
    # The row keeps its clusters and its overflow menu behind the ellipsis.
    assert "const cluster = sheet ? 'contents' : 'flex items-center gap-0.5';" in actions
    assert "'mt-1 flex flex-wrap items-center gap-x-3 gap-y-1'" in actions
    assert "<IconButton label=\"More actions\" onClick={toggle}>" in actions
    assert "'glass-modal absolute right-0 z-50 w-52 rounded-xl p-1'" in actions


def test_sheet_layout_closes_after_an_action():
    actions = read("components/chat/MessageActions.tsx")
    assert "const SheetLayoutContext = createContext<(() => void) | null>(null);" in actions
    assert "<SheetLayoutContext.Provider value={onSheetDone ?? null}>" in actions
    assert re.search(r"onClick\(\);\s*closeSheet\(\);", actions)
    assert "if (!keepSheet) closeSheet?.();" in actions
    # Save as prompt keeps the sheet until its dialog closes.
    assert "}, false, true)}" in actions
    assert "if (hadPromptDraft.current && !promptDraft) onSheetDone?.();" in actions


def test_sheet_dismissal():
    sheet = read("components/chat/MessageActionSheet.tsx")
    assert sheet.startswith("// MessageActionSheet.tsx")
    assert "createPortal(" in sheet
    assert 'role="dialog"' in sheet
    assert 'aria-modal="true"' in sheet
    assert "event.key === 'Escape'" in sheet
    assert "SWIPE_CLOSE_PX = 80" in sheet
    assert "Date.now() - openedAt.current > LIFT_GRACE_MS" in sheet
    assert "env(safe-area-inset-bottom)" in sheet


def run_all():
    tests = [
        test_long_press_is_touch_only_and_cancellable,
        test_long_press_ignores_events_from_its_own_portal,
        test_sheet_reuses_message_actions,
        test_hover_row_is_unchanged,
        test_sheet_layout_closes_after_an_action,
        test_sheet_dismissal,
    ]
    print("Testing V2 chat touch action sheet...")
    try:
        for test in tests:
            test()
            print(f"  passed: {test.__name__}")
        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
