# Outlook MSG File Ingestion

Implemented in version: **0.242.063**
Fixed/Implemented in version: **0.242.063**
Related Config Update: `application/single_app/config.py` -> `VERSION = "0.242.063"`

## Overview
SimpleChat now accepts Outlook `.msg` files for personal workspace, group workspace, public workspace, external public workspace, and chat uploads. Uploaded messages are parsed into searchable plain text and indexed through the existing document processing pipeline.

## Purpose
Teams often store decisions, approvals, and incident context as Outlook message files. Supporting `.msg` uploads lets users add those messages to workspace knowledge and chat task-document flows without converting them to another format first.

## Dependencies
- Existing `olefile` dependency for Outlook compound document parsing.
- Shared workspace upload routes and `allowed_file()` validation.
- Chat upload personal and group workspace handoff.
- Existing AI Search chunking and embedding pipeline.

## Technical Specifications
- `.msg` is represented by `EMAIL_EXTENSIONS` in `application/single_app/config.py` and merged into `get_allowed_extensions()`.
- `extract_outlook_msg_text()` reads standard Outlook MAPI streams for subject, sender, recipients, message id, plain body, and HTML body fallback.
- HTML message bodies are converted to plain text with BeautifulSoup after script and style removal. Message HTML is not marked trusted or rendered directly.
- `process_msg()` chunks extracted text with the `msg` chunk-size default and saves chunks through the existing embedding and AI Search flow.
- Chat upload support includes `.msg` in workspace-backed uploads and in the direct chat extraction fallback used when workspace upload is unavailable.

## Usage Instructions
1. Open a personal workspace, group workspace, public workspace, or chat with file uploads enabled.
2. Upload an Outlook `.msg` file through the existing drag-and-drop area or file picker.
3. Wait for document processing to complete.
4. Search, summarize, analyze, or compare the uploaded message as a normal workspace document or chat-uploaded task document.

## Testing and Validation
- Functional coverage: `functional_tests/test_msg_file_upload_support.py`.
- UI coverage: `ui_tests/test_chat_file_upload_access_control.py` verifies chat upload controls advertise `.msg` support when enabled.
- Validation includes route decorator preservation, central allowlist coverage, processor dispatch, and XSS-safe HTML-to-text extraction boundaries.

## Known Limitations
- Embedded attachments inside `.msg` files are not recursively extracted in this release. Upload attachment files separately when they also need to be indexed.