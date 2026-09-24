# Chat Upload File Access Error Fix

Fixed in version: **0.261.032**

## Issue

Dragging a file into chat could report only `Failed to fetch` when the browser
could not read the file. This commonly affected cloud-synced documents that
were open in another application or were not fully available on the device.
Because the browser failed while preparing the request body, the upload never
reached SimpleChat and no corresponding server log entry was created.

## Root Cause

The chat uploader passed the selected `File` directly to `fetch()`. Browser
file-access failures surfaced as a generic network `TypeError`, which did not
identify the document or explain how the user could resolve the problem.

## Technical Details

The shared chat upload path now performs a minimal file-read check before
starting the request. If that check fails, the toast identifies the filename
and asks the user to close it in other applications or make it available
offline. A later browser transport failure also explains the possible file
lock, cloud availability, and network causes instead of displaying only the
opaque browser error.

The change applies consistently to files selected with the paperclip, pasted
from the clipboard, or dropped into the chat input.

## Validation

The existing chat upload Playwright workflow now simulates an unreadable
dropped file and verifies that the actionable toast appears without an upload
request. Functional coverage also checks that the shared uploader retains the
file-read guard and recovery guidance.

The application version in `application/single_app/config.py` was updated to
`0.261.032` for this fix.