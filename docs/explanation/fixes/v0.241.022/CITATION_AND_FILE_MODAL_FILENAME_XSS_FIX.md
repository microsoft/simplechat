# CITATION_AND_FILE_MODAL_FILENAME_XSS_FIX.md

# Citation And File Modal Filename XSS Fix

Fixed in version: **0.241.018**

## Issue Description

Chat citation and uploaded-file popups built their modal header markup with attacker-controlled filenames on first render. The follow-up update path already used `textContent`, but the initial `innerHTML` assignment still allowed stored filename payloads to break into executable HTML.

## Root Cause Analysis

- `chat-citations.js` interpolated `fileName` directly inside the initial citation modal `<h5>` element.
- `chat-input-actions.js` interpolated `filename` directly inside the initial uploaded-file modal `<h5>` element.
- Both modals only switched to `textContent` on later renders, leaving the first open vulnerable.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-citations.js`
- `application/single_app/static/js/chat/chat-input-actions.js`
- `functional_tests/test_stored_xss_chat_modal_filename_fix.py`
- `ui_tests/test_chat_modal_filename_escaping.py`
- `application/single_app/config.py`

### Code Changes Summary

- Replaced first-render filename interpolation in the citation modal shell with an empty title element.
- Replaced first-render filename interpolation in the uploaded-file modal shell with an empty title element.
- Set both modal titles after creation with `textContent` so attacker-controlled filenames stay inert on the initial display as well as subsequent displays.
- Added functional and Playwright regression coverage for both modal title flows.

### Testing Approach

- Functional regression coverage verifies the first-render modal HTML no longer contains inline filename interpolation and that both flows use `textContent` for title updates.
- UI regression coverage loads the chat page, calls the affected modal functions with malicious filenames, and confirms the payloads render as text with no injected DOM nodes or script execution.

## Impact Analysis

- Normal citation and uploaded-file modal titles continue to render the same user-visible text.
- The fix only changes how the modal title is populated; modal behavior and download actions are otherwise unchanged.

## Validation

### Before

- Opening a citation or uploaded-file popup for the first time could inject a malicious filename into modal header HTML.

### After

- Both modal shells are static on first render.
- Both modal titles populate through `textContent`, keeping malicious filenames inert on every open.