# Document Intelligence PDF and Image Extraction Mode

## Overview

SimpleChat admins can choose how Azure Document Intelligence processes PDF and image uploads from the Search & Extract admin settings. The UI presents **Standard**, **Enhanced**, and **Auto** extraction modes. Standard maps to Azure Document Intelligence Read, and Enhanced maps to Azure Document Intelligence Layout.

Implemented in version: **0.241.158**
Enhanced in version: **0.241.163**
UI terminology updated in version: **0.241.166**
Extraction action terminology updated in version: **0.241.167**

## Purpose

The setting lets administrators balance extraction speed against richer document understanding:

- **Standard** keeps the previous Read behavior and focuses on faster OCR text extraction.
- **Enhanced** uses Layout to capture richer document structure for PDFs and images, including tables, layout structure, forms, and checked or unchecked selection marks. Enhanced can add parsing latency compared with Standard and has a 6X increase for every 1000 pages when selected.
- **Auto** samples the configured number of first PDF pages with Enhanced extraction. If the sample shows table structure or selection marks, the full PDF is extracted with Enhanced. Otherwise, SimpleChat finishes extraction with Standard. Images use Enhanced in Auto mode because they are single-page inputs and benefit from spatial structure detection.

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
- Enhanced/Layout extraction requests Markdown output so table and selection mark structure can be preserved in page content for search and chat retrieval.
- New PDF and image uploads store the original source blob even when enhanced citations are disabled. This makes later PDF extraction changes possible without requiring enhanced citations.

## File Structure

- `application/single_app/functions_settings.py`: default value and normalization helpers.
- `application/single_app/templates/admin_settings.html`: Search & Extract admin selector.
- `application/single_app/static/js/admin/admin_settings.js`: connection test payload and admin change hook.
- `application/single_app/route_backend_settings.py`: mode-aware Document Intelligence connection test.
- `application/single_app/functions_content.py`: mode-aware Azure Document Intelligence extraction.
- `application/single_app/functions_documents.py`: PDF/image metadata update and ingestion call.
- `application/single_app/route_backend_documents.py`: personal PDF extraction change API.
- `application/single_app/route_backend_group_documents.py`: group PDF extraction change API.
- `application/single_app/route_backend_public_documents.py`: public workspace PDF extraction change API.
- `application/single_app/static/js/workspace/workspace-documents.js`: personal workspace extraction badges and Change Extraction actions.
- `application/single_app/static/js/workspace/workspace-tags.js`: personal folder extraction badges and Change Extraction actions.
- `application/single_app/templates/group_workspaces.html`: group workspace extraction badges and Change Extraction actions.
- `application/single_app/static/js/public/public_workspace.js`: public workspace extraction badges and Change Extraction actions.

## Usage

1. Open Admin Settings.
2. Go to Search & Extract.
3. In Document Intelligence, choose **Standard**, **Enhanced**, or **Auto** for PDF and image extraction.
4. If choosing Auto, set how many first PDF pages to sample.
5. Save settings.

New PDF and image uploads record both the requested extraction mode and the resolved Standard/Enhanced mode in document metadata. Existing documents with missing extraction metadata are treated as **Standard** in workspace file info.

Workspace users with document management permission can use **Change Extraction** from the document ellipsis menu or the multi-select toolbar. Single-document actions only show the opposite extraction mode: Standard documents offer **Change to Enhanced**, and Enhanced documents offer **Change to Standard**. The menu item tooltip explains when the target mode is useful. Older PDFs that do not have a stored source blob must be re-uploaded before extraction can be changed.

## Testing and Validation

Functional coverage is provided by `functional_tests/test_document_intelligence_pdf_image_extraction_mode.py` and `functional_tests/test_document_intelligence_auto_reprocess_contract.py`.

UI contract coverage is provided by `ui_tests/test_document_intelligence_extraction_ui_contract.py`.

Config version updated in `application/single_app/config.py` to `0.241.167`.