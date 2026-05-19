# Chat Follow-Up Prompt Actions Fix (v0.241.047)

Fixed/Implemented in version: **0.241.047**

## Header Information

### Issue Description

Assistant replies could ask useful closing questions such as "Do you want me to..." or "Would you like...", but the chat UI did not consistently turn those questions into follow-up prompt buttons.

### Root Cause Analysis

The follow-up action extractor only looked for a narrow set of trigger phrases and then only accepted bullet or numbered list lines. Direct question-style choices, including the pattern shown in recent Citi partnership responses, were left as plain text even when they were good next prompts.

### Version Implemented

`0.241.047`

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.047"`.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_follow_up_prompt_actions.py`
- `ui_tests/test_chat_follow_up_prompt_actions.py`

### Code Changes Summary

- Expanded follow-up detection to recognize direct closing questions such as "Do you want me to...", "Would you like...", "Would you prefer...", and "Should I...".
- Added support for a standard "Suggested follow-ups" section so system prompts or agent instructions can produce a predictable button-friendly format.
- Converted assistant-perspective wording like "give you" into user-ready prompt text like "give me" before staging the next prompt.
- Exposed the extractor through the chat module so browser tests can validate the real parser instead of manually creating mock buttons.

### Testing Approach

- Updated the functional test to verify the new question-style parser helpers are present.
- Updated the Playwright UI test to render an assistant message with direct closing questions, assert that two buttons appear, and verify clicking a button stages the user-ready prompt text.

### Impact Analysis

- Users can click direct follow-up choices instead of copying or retyping them.
- Existing bullet and numbered-list suggestions continue to render as before.
- No backend prompt or storage contract changes are required for the UI fix, though agents can now use a "Suggested follow-ups" section for more consistent results.

## Validation

### Before

- Button rendering depended on a narrow bullet-list pattern after phrases like "If you want".
- Direct questions such as "Do you want me to make this stricter...?" stayed as plain text.

### After

- Direct follow-up questions and explicit "Suggested follow-ups" sections are parsed into safe DOM-created buttons.
- Clicking a generated button stages the prompt with the existing cancelable send countdown behavior.

Related tests:

- `functional_tests/test_chat_follow_up_prompt_actions.py`
- `ui_tests/test_chat_follow_up_prompt_actions.py`