# Document Intelligence PDF and Image Extraction Mode

## Overview

SimpleChat admins can choose how Azure Document Intelligence processes PDF and image uploads from the Search & Extract admin settings. The setting supports explicit **Read**, explicit **Layout**, and **Auto** mode.

Implemented in version: **0.241.158**
Enhanced in version: **0.241.163**

## Purpose

The setting lets administrators balance extraction speed against richer document understanding:

- **Read** keeps the previous behavior and focuses on faster OCR text extraction.
- **Layout** captures richer document structure for PDFs and images, including tables, layout structure, forms, and checked or unchecked selection marks. Layout can add parsing latency compared with Read and has a 6X increase for every 1000 pages when selected.
- **Auto** samples the configured number of first PDF pages with Layout. If the sample shows table structure or selection marks, the full PDF is extracted with Layout. Otherwise, SimpleChat finishes extraction with Read. Images use Layout in Auto mode because they are single-page inputs and benefit from spatial structure detection.

## Technical Specifications

- Setting key: `document_intelligence_pdf_image_extraction_mode`
- Allowed values: `read`, `layout`, `auto`
- Default value: `read`
- Auto sample-page key: `document_intelligence_auto_sample_pages`
- Auto sample-page default: `3`
- Document metadata key: `document_intelligence_extraction_mode`
- Requested mode metadata key: `document_intelligence_extraction_mode_requested`
- Auto reason metadata key: `document_intelligence_auto_reason`
- Applies to PDF and image uploads handled through Azure Document Intelligence.
- Layout extraction requests Markdown output so table and selection mark structure can be preserved in page content for search and chat retrieval.
- New PDF and image uploads store the original source blob even when enhanced citations are disabled. This makes later PDF Read/Layout reprocessing possible without requiring enhanced citations.

## File Structure

- `application/single_app/functions_settings.py`: default value and normalization helpers.
- `application/single_app/templates/admin_settings.html`: Search & Extract admin selector.
- `application/single_app/static/js/admin/admin_settings.js`: connection test payload and admin change hook.
- `application/single_app/route_backend_settings.py`: mode-aware Document Intelligence connection test.
- `application/single_app/functions_content.py`: mode-aware Azure Document Intelligence extraction.
- `application/single_app/functions_documents.py`: PDF/image metadata update and ingestion call.
- `application/single_app/route_backend_documents.py`: personal PDF extraction reprocess API.
- `application/single_app/route_backend_group_documents.py`: group PDF extraction reprocess API.
- `application/single_app/route_backend_public_documents.py`: public workspace PDF extraction reprocess API.
- `application/single_app/static/js/workspace/workspace-documents.js`: personal workspace extraction badges and reprocess actions.
- `application/single_app/static/js/workspace/workspace-tags.js`: personal folder extraction badges and reprocess actions.
- `application/single_app/templates/group_workspaces.html`: group workspace extraction badges and reprocess actions.
- `application/single_app/static/js/public/public_workspace.js`: public workspace extraction badges and reprocess actions.

## Usage

1. Open Admin Settings.
2. Go to Search & Extract.
3. In Document Intelligence, choose **Read**, **Layout**, or **Auto** for PDF and image extraction.
4. If choosing Auto, set how many first PDF pages to sample.
5. Save settings.

New PDF and image uploads record both the requested extraction mode and the resolved Read/Layout mode in document metadata. Existing documents with missing extraction metadata are treated as **Read** in workspace file info.

Workspace users with document management permission can reprocess stored PDFs from the document ellipsis menu or the multi-select **Reprocess** dropdown. Reprocess choices are **Read** and **Layout**. Older PDFs that do not have a stored source blob must be re-uploaded before they can be reprocessed.

## Testing and Validation

Functional coverage is provided by `functional_tests/test_document_intelligence_pdf_image_extraction_mode.py` and `functional_tests/test_document_intelligence_auto_reprocess_contract.py`.

UI contract coverage is provided by `ui_tests/test_document_intelligence_extraction_ui_contract.py`.

Config version updated in `application/single_app/config.py` to `0.241.163`.