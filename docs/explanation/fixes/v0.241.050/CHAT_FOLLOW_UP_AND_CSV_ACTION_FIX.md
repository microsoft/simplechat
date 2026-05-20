# Chat Follow-Up and CSV Action Fix (v0.241.050)

Fixed/Implemented in version: **0.241.050**

## Header Information

### Issue Description

Assistant follow-up suggestions could render twice: once as visible assistant text and again as prompt buttons. Some natural export phrases, such as requesting a shorter slide deck or asking to turn a table into CSV, also did not consistently trigger the expected quick actions or generated CSV artifact.

### Root Cause Analysis

The chat renderer appended follow-up prompt buttons after the assistant message body but left the original trailing suggestion section in the sanitized Markdown output. Inline export actions also required a narrower set of creation verbs, and CSV/table artifact detection used duplicated marker lists that missed common phrasing such as "turn that into a csv" and "create a table".

### Version Implemented

`0.241.050`

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.050"`.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/functions_assistant_table_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_follow_up_prompt_actions.py`
- `functional_tests/test_assistant_table_csv_artifact.py`
- `ui_tests/test_chat_follow_up_prompt_actions.py`
- `ui_tests/test_chat_inline_export_action_buttons.py`

### Code Changes Summary

- Capped assistant follow-up prompt buttons at three suggestions with a shared constant.
- Stripped the trailing recognized follow-up suggestion section from rendered assistant Markdown when follow-up buttons are created.
- Broadened inline export intent detection to handle natural deck and presentation wording such as "provide a 5-slide executive deck" and "turn this into a presentation".
- Expanded CSV/table request markers to include common conversion language such as "turn that into a csv", "convert this to csv", and "create a table".
- Reused the assistant table CSV marker list in the tabular generated output detector so CSV/table request handling stays consistent.

### Testing Approach

- Updated source-level functional coverage for follow-up rendering hooks, the three-button cap, duplicate source stripping, and deck export wording.
- Updated assistant table CSV artifact coverage for natural CSV/table request phrases.
- Updated Playwright UI tests for capped follow-up buttons without duplicate visible source text and deck wording export actions.

### Impact Analysis

- Users see up to three concise follow-up buttons without the same suggestion text repeated in the assistant response.
- Follow-up prompts that mention a slide deck are more likely to produce the existing PowerPoint quick action on the next assistant response.
- Natural CSV/table conversion requests create downloadable CSV artifacts whenever the assistant response or tabular workflow can supply parseable table data.

## Validation

### Before

- Assistant suggestions could appear as both list text and buttons.
- "Please provide a shorter 5-slide executive deck" did not satisfy the inline export verb gate.
- "turn that into a csv" and "create a table" were not recognized by all CSV/table artifact paths.

### After

- Recognized trailing follow-up sections render as buttons only, capped at three.
- Natural presentation/deck wording is included in inline export intent detection.
- CSV/table request markers are shared and include the common conversion phrases.

Related tests:

- `functional_tests/test_chat_follow_up_prompt_actions.py`
- `functional_tests/test_assistant_table_csv_artifact.py`
- `ui_tests/test_chat_follow_up_prompt_actions.py`
- `ui_tests/test_chat_inline_export_action_buttons.py`