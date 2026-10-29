# Word Document Comment Extraction (`.docx`, `.docm`, `.doc`, `.dotx`)

**Implemented in version: 0.261.390**  
**Related config.py version: `0.261.390`**  
**Related issue: [#1850](https://github.com/microsoft/simplechat/issues/1850)**

## 1. Overview and Purpose

Microsoft Word documents frequently contain important review feedback, edge-case clarifications, and threaded Q&A stored as margin comments. Previously:

- **`.docx` files** processed via Azure Document Intelligence (`prebuilt-read`) only extracted main document text, tables, headers/footers, and footnotes, ignoring `word/comments.xml`.
- **`.docm` files** processed via `docx2txt` only read `word/header*.xml`, `word/document.xml`, and `word/footer*.xml`, ignoring `word/comments.xml`.
- **`.doc` files** (legacy Word 97–2003 OLE binary format) decoded the `PlcPcd` piece table as a flat stream without parsing the File Information Block (`FIB`) annotation subdocument (`ccpAtn`) or the comment author/reference tables (`GrpXstAtnOwners`, `PlcfandRef`, `PlcfandTxt`).

SimpleChat now extracts review comments locally from both OOXML Word packages (`.docx`, `.docm`, `.dotx`) and legacy binary OLE Word files (`.doc`) with zero additional Azure API calls, preserving comment authors, initials, dates, resolved states, threaded replies, and the anchored document text they reference.

---

## 2. Technical Specifications

### Architecture Overview

1. **OOXML Word Comment Extraction (`application/single_app/functions_office_media.py`)**:
   - `extract_docx_comments(file_path)` safely inspects OOXML ZIP archives using bounded streaming reads (`_read_zip_entry_bounded`) and `defusedxml.ElementTree.fromstring`.
   - `build_docx_comment_anchors_and_offsets(archive)` walks `word/document.xml` in reading order to capture:
     - The exact text enclosed between `<w:commentRangeStart w:id="..."/>` and `<w:commentRangeEnd w:id="..."/>`.
     - The reading-order `word_offset` (and `total_body_words`) where each comment range or `<w:commentReference>` appears.
   - `_parse_docx_comments_extended(archive)` parses `word/commentsExtended.xml` (`w15:commentEx`) to link reply comments (`paraIdParent`) to their parent comment thread and detect resolved status (`done="1"`).

2. **Legacy `.doc` Binary OLE Comment Extraction (`application/single_app/functions_content.py`)**:
   - `_parse_legacy_doc_fib(word_stream)` reads the Word 97–2003 File Information Block (`FibBase`, `FibRgW97`, `FibRgLw97`, `FibRgFcLcb97`) to locate the active table stream (`0Table` or `1Table`), subdocument CP counts (`ccpText`, `ccpFtn`, `ccpHdr`, `ccpMcr`, `ccpAtn`), and comment table pointers.
   - `_extract_legacy_doc_comments_from_streams(table_stream, fib, raw_full_text)` parses:
     - `GrpXstAtnOwners` for comment author names.
     - `PlcfandRef` (`ATRDPre10`) for main-document anchor CPs, user initials, author index, and bookmark tags.
     - `PlcfandTxt` for per-comment CP boundaries within the annotation subdocument (`ccpAtn`).
     - `PlcfbkfAtn` and `PlcfbklAtn` for bookmarked anchor text ranges in the body.
   - `extract_legacy_doc_text(file_path)` separates the annotation subdocument (`ccpAtn`) from the body text so raw comment text is never duplicated unmarked at the end of the body.

3. **Chunk Placement and Pipeline Integration (`application/single_app/functions_documents.py`, `route_frontend_chats.py`)**:
   - During workspace ingestion (`process_di_document` and `process_office_template`), `_build_word_comment_chunks()` builds formatted Markdown comment blocks with `word_offset` metadata and merges each comment thread into the chunk containing its anchored text via `_merge_embedded_images_into_chunks()` (with overflow chunk fallback when a chunk reaches the embedding character budget).
   - During direct text extraction (`extract_word_text()`, `.docm` processing, direct chat uploads in `route_frontend_chats.py`, and M365 extraction in `functions_m365_extraction.py`), extracted comments are formatted under a `### Document Comments` section.
   - Content screening (`current_extraction`) receives extracted comment blocks via `capture.add_supplement(..., kind="comment")`.

---

## 3. Usage Instructions

Word comment extraction runs automatically whenever `.docx`, `.docm`, `.doc`, or `.dotx` files are uploaded to Personal, Group, or Public workspaces, uploaded directly to a chat conversation, or read through Microsoft 365 file extraction.

Each extracted comment thread is formatted in Markdown alongside its chunk:

```markdown
### Document comment 1 of 2 by Alice Reviewer (AR) [2025-02-10T14:00:00Z] on "payment within 30 days"
Please extend the payment window to 60 days.
- Reply by Bob Author (BA) [2025-02-10T15:30:00Z]: Updated in section 4.2.
```

---

## 4. Testing and Validation

- **Functional Test**: `functional_tests/test_word_comment_extraction.py`
  - Validates OOXML `.docx` comment extraction, anchor text capture, reply threading (`commentsExtended.xml`), and resolved status.
  - Validates reading-order chunk placement into target document chunks without inventing duplicate page numbers.
  - Validates legacy `.doc` FIB (`FibRgLw97` / `FibRgFcLcb97`) comment extraction, author/initials decoding, bookmark anchor text, and clean separation of `ccpAtn` from body text.
- **Regression Test**: `functional_tests/test_legacy_doc_ole_extraction.py` and `functional_tests/test_figure_chunk_association.py`.
- **Related Architecture**: See [Document Accessibility, Structure, and Comment Extraction](DOCUMENT_ACCESSIBILITY_AND_STRUCTURE_EXTRACTION.md) for the full Mermaid dissection and storage routing diagrams across PDF, Word (`.docx`, `.docm`, `.dotx`, `.doc`), and PowerPoint (`.pptx`).
