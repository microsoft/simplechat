# V2 Chat Upload Extraction and Image Card Parity Fix

Fixed in version: **0.261.210**

Related issue: [#1583](https://github.com/microsoft/simplechat/issues/1583)

## Issue Description

Three problems made it hard to see what SimpleChat knew about an image uploaded into a V2
conversation.

- **File content not found.** Opening an uploaded image, or any other file uploaded into a
  conversation with the personal workspace enabled, showed "File content not found". The
  classic interface showed the extracted text and the AI vision analysis.
- **Cited images showed only the picture.** A citation of an image opened the image, with no
  sign of the text the assistant was given or the image's description.
- **The upload card did not match a generated image.** The uploaded image filled the whole
  message column, with the picture letterboxed in a grey box. Its actions were always visible
  and could not show sources, while a generated image in the same thread was drawn at its own
  size with its actions revealed on hover.

## Root Cause

A chat upload is stored as a workspace document and processed by the normal ingestion
pipeline. The chat message only records `workspace_document_id` and
`file_content_source: "workspace"`. It has no `file_content`.

`/api/get_file_content` only combined `file_content` from the message rows, or read the blob
for a screened document. Every unscreened workspace-backed upload therefore fell through to its
empty-content 404. The document's indexed chunks and its stored `vision_analysis` were never
read.

The V2 image citation viewer rendered only `/api/enhanced_citations/image`. It never requested
the cited passage.

`UploadedImageFileCard` was laid out as a full-width attachment card rather than the compact
card `ImageMessage` uses for generated images.

## Technical Details

### Files Modified

| File | Change |
| --- | --- |
| `application/single_app/functions_chat_upload_extraction.py` | New pure helpers that turn the linked document and its ordered chunks into the response: the indexed text, the stored vision analysis with error analyses dropped, the engine and its reason, and title, summary and keywords. Storage, scope and screening fields are never included. |
| `application/single_app/route_backend_documents.py` | For an unscreened, non-table upload linked to a workspace document, `get_file_content` reads the document's chunks with `get_ordered_document_chunks` in the document's own scope and returns the helper's payload. Screening errors keep their public wording, a missing document is a 404, and any other failure returns a fixed message. |
| `application/v2_ui/src/components/chat/ChatUploadExtraction.tsx` | New component that renders the extraction: the engine, the AI vision analysis (description, objects, visible text, contextual analysis), metadata, and the indexed text. It warns when nothing was indexed. |
| `application/v2_ui/src/components/chat/ChatFilePreview.tsx` | **Uploaded file** renders the extraction instead of a bare text block. |
| `application/v2_ui/src/components/chat/MessageInspector.tsx` | An uploaded file message gets **Sources**, which shows its extraction, and **Details**. |
| `application/v2_ui/src/components/chat/MessageList.tsx` | The uploaded image card is sized to the image like a generated image. Its actions row (Show sources, Message details, Open file preview, Use as reference, Edit) is revealed on hover or focus and stays visible while its panel is open. |
| `application/v2_ui/src/components/chat/MessageActions.tsx` | `IconButton` is exported so the upload card uses the same controls as other messages. |
| `application/v2_ui/src/components/chat/EnhancedCitationViewer.tsx`, `CitationChip.tsx` | The image viewer shows **What was extracted from this image**, the cited passage, beneath the image. |
| `application/v2_ui/src/lib/endpoints.ts` | Types for the new `workspace_document` details. |

### Response Shape

For a workspace-backed upload, `/api/get_file_content` returns:

```json
{
  "file_content": "indexed text, or the vision analysis when nothing was indexed",
  "filename": "lab.png",
  "is_table": false,
  "file_content_source": "workspace",
  "indexed_text_available": true,
  "workspace_document": {
    "document_id": "…",
    "title": "…",
    "status": "Processing complete - final metadata extracted",
    "percentage_complete": 100,
    "extraction_engine": "document_intelligence",
    "extraction_engine_reason": "…",
    "indexed_chunk_count": 1,
    "vision_analysis": {"model": "gpt-5.4", "description": "…", "objects": ["…"], "text": "", "analysis": "…"}
  }
}
```

`file_content` is always readable text, so the classic file popup, which renders only
`file_content`, also works for these uploads now. When there is nothing to show, the route
returns 404 with "This file is still being processed. Try again when it finishes." while
ingestion is running, or "No extracted content is available for this file yet." afterwards.

Tabular uploads and screened documents keep their existing paths.

## Testing

- `functional_tests/test_chat_upload_extraction_details.py`: response shaping, fallback to the
  stored vision analysis, processing and absent wording, the route helper's scope and error
  handling, and the position of the new branch before the empty-content 404.
- `ui_tests/test_v2_chat_image_uploads.py`: the card is sized to a 320×200 image, its actions
  appear only on hover, **Show sources** and **Uploaded file** show the vision analysis and
  indexed text, a processing file explains itself, and a cited image shows the extracted
  passage.
- Route policy tests in `functional_tests/route_tests/` pass unchanged. No route was added or
  moved.

## Validation

| Before | After |
| --- | --- |
| **Uploaded file** said "File content not found" for every workspace-backed upload. | It shows how the file was read, the AI vision analysis, and the indexed text. |
| A cited image showed only the picture. | The cited passage appears beneath the image. |
| The upload filled the message column, letterboxed, with its actions always visible. | The upload is drawn at the image's size, and its actions, including **Show sources**, appear on hover, as a generated image's do. |
