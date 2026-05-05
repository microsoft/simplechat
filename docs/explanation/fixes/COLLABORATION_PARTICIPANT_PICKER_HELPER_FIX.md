# Collaboration Participant Picker Helper Fix (v0.241.010)

Fixed and implemented in version: **0.241.010**

## Issue Description

Clicking Add participants from the chat UI could throw a browser-side runtime error:

- `ReferenceError: isCollaborativeConversation is not defined`

The failure occurred before the participant picker modal opened, so eligible personal conversations could not be upgraded into collaborative conversations from the sidebar or details actions.

## Root Cause Analysis

The collaboration module had already standardized on `isCollaborationConversation(...)`, but the participant gating helpers still referenced the old helper name `isCollaborativeConversation(...)` in two paths:

- participant-flow eligibility checks
- collaborative message-post permission checks

Because the old helper no longer existed, the add-participants workflow failed immediately when the gate ran.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-collaboration.js`
- `ui_tests/test_chat_collaboration_ui_scaffolding.py`
- `application/single_app/config.py`

### Code Changes Summary

- Replaced stale `isCollaborativeConversation(...)` references with `isCollaborationConversation(...)`.
- Extended the chat collaboration UI regression to call `openParticipantPicker(...)` with a mocked eligible personal conversation and assert that the participant modal opens.

### Testing Approach

- Static editor diagnostics for the updated collaboration UI files
- Updated Playwright UI scaffolding regression for the add-participants entry path

## Validation

### Test Results

- The updated UI test module loads successfully and skips cleanly when authenticated Playwright storage state is not available in the environment.

### Before And After

- Before: clicking Add participants could fail immediately with a `ReferenceError`.
- After: the participant-flow eligibility check uses the defined collaboration helper and allows the modal path to proceed for eligible personal conversations.

### User Experience Improvements

- Sidebar and details-based participant adds no longer fail on helper-name drift.
- The personal-to-collaborative upgrade path is available again from the existing chat UI actions.