# Generated JSON and XML Completed Card Fix

Fixed in version: **0.250.152**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Foreground-generated XML and JSON files used a generic analysis artifact card. The assistant payload remained visible inline, XML or JSON preview text appeared directly in the card, and the actions offered Download and Add to Workspace without the same format-specific View action used by completed durable tabular files.

## Root Cause

Foreground generated-file metadata used the `analysis` capability, while concise completed structured cards recognized only durable `tabular` artifacts. The renderer therefore treated XML and JSON as analysis previews instead of completed file exports.

## Technical Details

### Files Modified

- `application/single_app/functions_generated_file_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_generated_json_xml_exports.py`
- `ui_tests/test_chat_generated_tabular_output_card.py`

### Code Changes

- Foreground JSON/XML artifacts use the `file_export` capability.
- Completed file-export metadata suppresses redundant assistant prose and preserves bounded preview rows, columns, or text lines.
- Completed CSV, JSON, and XML cards share the concise filename/action presentation.
- View buttons are labeled `View CSV`, `View JSON`, or `View XML` and include a format-specific accessible name.
- XML and JSON are rendered only inside the bounded preview modal using inert text or safe table cells.

## Validation

Functional coverage verifies JSON/XML parsing, file-export metadata, bounded previews, and renderer hooks. Authenticated browser validation confirmed that a completed XML card showed only `Download XML`, `View XML`, and `Add to Workspace`; XML containing a literal `script` element remained inert text in the modal.

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.151** to **0.250.152** for this completed JSON/XML artifact normalization.