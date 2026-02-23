# CITATION_IMPROVEMENTS.md

**Feature**: Citation Improvements
**Version**: v0.238.024
**Dependencies**: Enhanced Citations System, chat-citations.js

## Overview and Purpose

This release includes several improvements to the citation system in the chat interface. These changes fix parsing bugs with page range references, extend the document dropdown width for better readability, and improve error handling throughout the citation rendering pipeline. Citation links are now more robust with support for both inline source references and hybrid citation buttons.

## Key Features

- **Citation Parsing Bug Fix**: Fixed edge cases where page range references (e.g., "Pages: 1-5") failed to generate correct links when not all pages had explicit reference IDs
- **Extended Document Dropdown Width**: Widened the document selection dropdown for improved readability of long filenames
- **Improved Error Handling**: Graceful JSON parsing with explicit error messages in citation processing
- **Robust Citation Links**: Support for both inline citation links and hybrid citation buttons
- **Metadata Citations**: New metadata citation type for viewing extracted metadata (OCR text, vision analysis, detected objects)

## Technical Specifications

### Citation Parsing Fix

**Problem**: When AI responses contained page range citations like "Pages: 1-5", the citation parser would fail to generate links for pages that did not have explicit reference IDs in the bracketed citation section of the response. This left some page links non-functional.

**Solution**: Added auto-fill logic using `getDocPrefix()` which extracts the document ID prefix from known reference patterns and constructs missing page references. For example, if `[doc_abc_1]` exists for page 1, the system infers `doc_abc_2`, `doc_abc_3`, etc. for pages 2-5.

**Affected function**: `parseCitations()` in `chat-citations.js`

### Citation Types

The citation system supports multiple citation types:

| Type | Description | Display |
|------|-------------|---------|
| **Hybrid Citations** | Document source references with file name and page number | Page link that opens PDF/image/video/audio viewer |
| **Web Citations** | URL references from web search results | Clickable title link opening in new tab |
| **Agent Citations** | Tool execution details from Semantic Kernel agents | Expandable section with function args and results |
| **Metadata Citations** | Extracted metadata from document processing | Expandable section with OCR text, vision analysis, detected objects |

### Enhanced Citation Modal

Citations that reference documents open specialized viewers based on file type:

| File Type | Extensions | Viewer |
|-----------|------------|--------|
| PDF | `.pdf` | Iframe PDF viewer with page navigation |
| Images | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`, `.heif` | Image viewer |
| Video | `.mp4`, `.mov`, `.avi`, `.mkv`, `.flv`, `.webm`, `.wmv` | Video player with timestamp seeking |
| Audio | `.mp3`, `.wav`, `.ogg`, `.aac`, `.flac`, `.m4a` | Audio player with timestamp seeking |
| Other | All other extensions | Text citation fallback |

Video and audio citations support timestamp navigation using HH:MM:SS and MM:SS format parsing.

### Document Dropdown Width

The document selection dropdown in the chat interface was widened to accommodate long filenames. The dropdown width now dynamically adapts to the parent container width, preventing filename truncation.

## File Structure

| File | Purpose |
|------|---------|
| `static/js/chat/chat-citations.js` | Core citation parsing, link generation, and rendering |
| `static/js/chat/chat-enhanced-citations.js` | Enhanced citation modal for PDF/image/video/audio viewing |
| `static/js/chat/chat-documents.js` | `getDocumentMetadata()` for metadata citations; dropdown width updates |

## Commits

| Commit | Description |
|--------|-------------|
| `de3a523` | Fixed citation bug — page range parsing and auto-fill logic |
| `dc746a4` | Extended document dropdown width for readability |
| `b256a07` | Updated chat-documents.js with dropdown improvements |

## Testing and Validation

- **Page range citations**: Verify citations with "Pages: 1-5" generate clickable links for all pages, including those without explicit bracket references
- **Single page citations**: Verify standard single-page citations continue to work correctly
- **Missing references**: Verify graceful fallback when page references cannot be auto-filled
- **Dropdown width**: Verify long filenames are fully visible in the document dropdown
- **File type detection**: Verify citations route to the correct viewer (PDF, image, video, audio, text)
- **Timestamp seeking**: Verify video and audio citations navigate to the correct timestamp
- **Metadata citations**: Verify extracted metadata (OCR, vision, objects) displays correctly in expandable sections
- **Error handling**: Verify malformed citation strings are handled gracefully without breaking the chat interface
