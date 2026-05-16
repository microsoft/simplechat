# Chat Document Picker Width Fix

Fixed/Implemented in version: **0.241.030**

## Issue Description

The chat Document dropdown used a short field width in Search and Analyze mode on larger canvases, while Compare showed the desired full-width picker.

Users expected Search, Analyze, and Compare to share the same spacious desktop picker layout without losing the stacked full-width mobile behavior.

## Root Cause Analysis

The comparison modal had dedicated CSS that forced picker fields, dropdowns, and selects to `width: 100%`.

The normal Search and Analyze picker row did not share those rules, so the Document field could sit at its minimum width instead of growing across the remaining toolbar row. The dropdown sizing JavaScript then matched that smaller field width.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_document_picker_full_width.py`, `functional_tests/test_chat_prompt_desktop_toolbar_position.py`, `ui_tests/test_chat_document_action_selector_labels.py`, `ui_tests/test_chat_prompt_desktop_toolbar_position.py`

Code changes summary:

- Added shared full-width dropdown and form-select rules for chat search panel fields.
- Gave the wide Document field a larger flexible basis and removed its desktop maximum width cap.
- Kept the existing mobile rules that make all document picker fields stack at full width.
- Added functional coverage for the CSS and template contract.
- Extended the Playwright document action test to verify Search, Analyze, and Compare all stretch the Document picker across the desktop row.

Impact analysis:

- Search, Analyze, and Compare now use consistent full-width Document picker behavior on larger screens.
- Mobile remains a single-column, full-width picker layout.
- The dropdown menu continues to size from the field container through existing picker JavaScript.

## Validation

Test coverage: `functional_tests/test_chat_document_picker_full_width.py`, `ui_tests/test_chat_document_action_selector_labels.py`

Test results:

- `functional_tests/test_chat_document_picker_full_width.py`: validates the static template and CSS contract for the full-width document picker.
- `ui_tests/test_chat_document_action_selector_labels.py`: validates rendered desktop picker widths for Search, Analyze, and Compare; skips when authenticated UI test settings are not configured.

Before/after comparison:

- Before: Search and Analyze could render a narrow Document dropdown while Compare appeared full width.
- After: All three document actions share the full-width desktop Document picker and retain the mobile stacked layout.

Related config.py version update: `VERSION = "0.241.030"`