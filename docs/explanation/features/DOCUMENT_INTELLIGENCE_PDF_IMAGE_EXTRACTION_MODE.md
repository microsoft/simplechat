# Document Intelligence PDF and Image Extraction Mode

## Overview

SimpleChat admins can choose how Azure Document Intelligence processes PDF and image uploads from the Search & Extract admin settings.

Implemented in version: **0.241.158**

## Purpose

The setting lets administrators balance extraction speed against richer document understanding:

- **Read** keeps the previous behavior and focuses on faster OCR text extraction.
- **Layout** captures richer document structure for PDFs and images, including tables, layout structure, and checked or unchecked selection marks. Layout can add parsing latency compared with Read.

## Technical Specifications

- Setting key: `document_intelligence_pdf_image_extraction_mode`
- Allowed values: `read`, `layout`
- Default value: `read`
- Document metadata key: `document_intelligence_extraction_mode`
- Applies to PDF and image uploads handled through Azure Document Intelligence.
- Layout extraction requests Markdown output so table and selection mark structure can be preserved in page content for search and chat retrieval.

## File Structure

- `application/single_app/functions_settings.py`: default value and normalization helpers.
- `application/single_app/templates/admin_settings.html`: Search & Extract admin selector.
- `application/single_app/static/js/admin/admin_settings.js`: connection test payload and admin change hook.
- `application/single_app/route_backend_settings.py`: mode-aware Document Intelligence connection test.
- `application/single_app/functions_content.py`: mode-aware Azure Document Intelligence extraction.
- `application/single_app/functions_documents.py`: PDF/image metadata update and ingestion call.

## Usage

1. Open Admin Settings.
2. Go to Search & Extract.
3. In Document Intelligence, choose **Read** or **Layout** for PDF and image extraction.
4. Save settings.

New PDF and image uploads record the selected extraction mode in document metadata. Existing documents keep the metadata they already have unless reprocessed.

## Testing and Validation

Functional coverage is provided by `functional_tests/test_document_intelligence_pdf_image_extraction_mode.py`.

Config version updated in `application/single_app/config.py` to `0.241.158`.