# Tabular Popup Download Fix

Fixed/Implemented in version: **0.239.124**

## Issue Description

Downloading a workbook from the chat tabular preview popup could fail with a generic browser download error, while the app showed no JavaScript error and the backend logged no application error.

## Root Cause Analysis

The popup used a plain anchor-based download control for a session-protected endpoint.

That meant the browser handled the request outside the app's normal error flow, so failures surfaced only as a generic download error and bypassed the UI's toast/error handling.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-enhanced-citations.js`
- `application/single_app/config.py`
- `functional_tests/test_tabular_popup_download_fix.py`

### Code Changes Summary

- Replaced the tabular popup download anchor with a controlled button-driven download flow.
- Added an authenticated `fetch()` request for the tabular download endpoint using same-origin credentials.
- Added blob-based client download handling and explicit toast/error reporting when the request fails.
- Updated `config.py` to version `0.239.124` for this fix.

### Testing Approach

- Added a functional regression test that inspects the chat enhanced citations JavaScript for the fetch-to-blob download flow.
- Added coverage to verify the popup no longer uses the old blank-target anchor download path.

## Validation

### Before

- The tabular popup download used a browser-managed anchor request.
- When the download failed, the user saw a generic browser download error without an app-level error message.

### After

- The tabular popup download is handled explicitly in JavaScript with `fetch()` and blob download logic.
- Failures now route through the app's error handling and can surface a toast message instead of failing silently.

### User Experience Improvement

Users can download tabular files from the chat preview popup through a controlled download path that is more reliable and easier to troubleshoot when something goes wrong.