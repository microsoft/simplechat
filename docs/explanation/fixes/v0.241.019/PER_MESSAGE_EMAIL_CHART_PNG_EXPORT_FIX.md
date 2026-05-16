# Per-Message Email Chart PNG Export Fix

Fixed/Implemented in version: **0.241.019**

## Issue Description

Per-message "Open in Email" drafts did not use the existing inline chart export path. Messages containing SimpleChat chart blocks could leave the email workflow with text placeholders or raw chart markdown instead of chart PNG output, even though Word and PowerPoint exports already rendered those charts as images.

## Root Cause Analysis

The Word and PowerPoint export paths called `replace_inline_chart_blocks_with_export_html()` before rendering documents. The email draft path rendered markdown directly into plain text for `mailto:`, so it skipped the server-side chart-to-PNG conversion helper.

Because `mailto:` cannot attach files automatically, the email workflow also needed a separate attachment payload and frontend download step for the generated PNGs.

## Technical Details

### Files Modified

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-message-export.js`
- `application/single_app/config.py`
- `functional_tests/test_per_message_export.py`
- `ui_tests/test_chat_message_email_chart_download.py`
- `docs/explanation/features/v0.241.001/MESSAGE_EXPORT.md`

### Code Changes Summary

- Reused the existing inline chart export helper in `_message_to_email_draft_payload()` before plain-text email rendering.
- Extracted converted chart images into an `attachments` payload with PNG data URIs, filenames, captions, and content types.
- Replaced chart image positions in the mailto body with filename references, avoiding raw `simplechart` markdown and oversized base64 text in the email body.
- Updated the frontend email action to download chart PNG files before opening the user's default mail client.
- Bumped the application version to `0.241.019`.

### Testing Approach

- Extended `functional_tests/test_per_message_export.py` with a regression check that injects a converted inline chart and verifies the email draft payload includes a PNG attachment.
- Updated frontend source assertions to confirm the email workflow consumes draft attachments.
- Added a Playwright UI regression that stubs the email draft response and verifies the browser downloads the PNG payload before composing the mailto draft.

## Validation

### Before

- Open in Email skipped the chart-to-PNG conversion used by Word and PowerPoint exports.
- Chart blocks could remain as text-only content in the email draft flow.

### After

- Open in Email converts inline chart blocks to PNG data through the shared export helper.
- The generated mailto body references chart PNG filenames where charts appear.
- The frontend downloads chart PNG files before opening the email draft so users can attach them.

### User Experience Improvement

Users opening a chart-bearing chat message in email now receive the chart PNG files alongside the prefilled draft, matching the image-export behavior of Word and PowerPoint as closely as `mailto:` allows.
