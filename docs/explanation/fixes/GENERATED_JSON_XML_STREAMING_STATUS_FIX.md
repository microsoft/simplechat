# Generated JSON and XML Streaming Status Fix

Fixed in version: **0.250.153**

Related issue: **microsoft/simplechat#1031**

## Issue Description

While an XML file was being generated, the assistant streamed contradictory prose claiming it could not attach a downloadable file, told the user to copy the XML manually, and rendered the large XML payload inline. Finalization later created the downloadable artifact correctly, but the interim experience made the real capability appear broken.

## Root Cause

The shared generated-file guidance recognized CSV, DOCX, and PDF but did not provide explicit JSON/XML publication guidance. Streaming Chat also forwarded every model token to the browser before the JSON/XML finalizer validated and uploaded the artifact.

## Technical Details

### Files Modified

- `application/single_app/functions_generated_file_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_generated_json_xml_exports.py`
- `docs/explanation/features/GENERATED_FILE_EXPORT_FRAMEWORK.md`

### Code Changes

- JSON guidance requires one complete valid JSON payload with no Markdown or publication commentary.
- XML guidance requires one complete well-formed XML document with no Markdown or publication commentary.
- Both guidance paths explicitly prohibit attachment limitation claims and manual copy/save instructions.
- Streaming Chat emits one truthful status line and accumulates JSON/XML payload chunks privately in both agent and direct-model paths.
- Non-streaming fallback content and appended content use the same private-stream gate.
- Successful artifact publication replaces private content with the concise artifact handoff and card.
- Failed publication leaves the accumulated model response available in the final event, preventing a stuck or false status.

## Validation

Functional coverage executes the status helper for XML, JSON, and non-target formats; verifies payload-only guidance; and checks all four streaming gates. The completed XML and JSON artifact card/modal workflows remain covered by authenticated browser validation from version **0.250.152**.

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.152** to **0.250.153** for this streaming-status fix.