# V2 Chat Message Touch Action Sheet

## Overview

In the V2 chat, each message's actions (Copy, Retry, feedback, sources, Fork, the overflow menu and so on) sit in a row that appears only when the pointer hovers over the message. A touch screen has no hover, so on a phone or tablet the row never shows and the actions are out of reach.

Pressing and holding a message on a touch screen now opens those actions in a bottom sheet. The hover row on desktop is unchanged and nothing new is shown on screen until a message is held.

- **Version:** 0.261.476
- **Dependencies:** React 18, `lucide-react`, the existing `MessageActions` component

## Technical Specifications

### Architecture

| Piece | Role |
|-------|------|
| `src/lib/useLongPress.ts` | Detects a touch press-and-hold and returns pointer handlers to spread onto an element |
| `src/components/chat/MessageActionSheet.tsx` | The bottom sheet: portal, backdrop, focus, Escape and swipe-down dismissal |
| `src/components/chat/MessageActions.tsx` | Gains an `onSheetDone` prop that lays the same actions out for the sheet |
| `src/components/chat/MessageList.tsx` | Wires the long press and sheet into `MessageBubbleInner` and `ImageMessage` |

### Long press

- Touch only (`pointerType === 'touch'`); mouse and pen keep hover and right-click.
- Fires after 450 ms. It is abandoned if the finger moves more than 10 px, the browser cancels the pointer to scroll, a second finger lands, or the finger lifts early.
- Presses that start on a link, button, form field, `summary`, `pre`/`code`, a dialog, or anything marked `data-no-long-press` keep their own behaviour, so code can still be selected and links copied.
- While a press is held the message cannot start a native text selection or the iOS callout. When the press fires it clears any selection and gives a short vibration where supported.
- The click some browsers send for the lift is swallowed for 400 ms; Android's context menu is suppressed for the press.
- Events that React bubbles up from the sheet's portal are ignored (`isOwnEvent`), so taps inside the sheet are never mistaken for the message's own.

### The sheet

`MessageList` builds one `actionProps` object and passes it to both the hover row and the sheet, so the two always offer the same entries with the same handlers.

With `onSheetDone` set, `MessageActions` provides a `SheetLayoutContext`:

- Each `IconButton` renders as a labelled tile in a four-column grid and closes the sheet after running.
- The overflow menu's entries are listed in place under the tiles instead of behind the ellipsis, with Delete in red. Exports close the sheet and report progress through their toast.
- **Save as prompt** keeps the sheet open under the prompt editor, and the sheet closes when the editor does.

The sheet closes on a backdrop tap (ignored for the first 600 ms so the opening press's lift does not close it), on Escape, or on a downward swipe of more than 80 px.

## Usage

No configuration. On a touch screen, press and hold a chat message or generated image for about half a second, then choose an action.

## Testing and Validation

- `functional_tests/test_v2_chat_message_touch_sheet.py` pins touch-only detection, the ignored targets, portal event isolation, reuse of `MessageActions`, the unchanged hover row, and sheet dismissal.
- Checked with the real `MessageList` and simulated touch input at phone size: tap, drag, mouse press and a press on a code block do not open the sheet; a long press does; the lift does not close it; choosing **Message details** opens the inspector and closes the sheet; a user message's sheet includes **Edit**.

### Limitations

- Uploaded-file cards are not covered; their Open and Use as reference buttons are already visible.
- Holding message text opens the sheet instead of starting a native text selection. Copy covers most uses, and text inside code blocks can still be selected.
