# Generated JSON and XML Completed Card Fix

Fixed in versions: **0.250.152-0.250.153**

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

Version **0.250.153** also fixes the in-progress state. The model receives payload-only guidance that explicitly prohibits claiming files cannot be attached or instructing users to copy/save the payload manually. Streaming Chat emits one truthful server-authored generation status while accumulating XML/JSON privately. Successful publication replaces that status with the artifact card; failed publication returns the accumulated response as a fallback.

## Validation

Functional coverage verifies JSON/XML parsing, file-export metadata, bounded previews, and renderer hooks. Authenticated browser validation confirmed that a completed XML card showed only `Download XML`, `View XML`, and `Add to Workspace`; XML containing a literal `script` element remained inert text in the modal.

## Related Version Update

`application/single_app/config.py` was incremented through **0.250.153** for completed JSON/XML artifact normalization and truthful private payload streaming.