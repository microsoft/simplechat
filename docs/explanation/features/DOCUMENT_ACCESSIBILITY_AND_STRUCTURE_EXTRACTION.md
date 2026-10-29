# Document Accessibility, Structure, and Comment Extraction (`PDF`, `Word`, `PowerPoint`)

**Implemented in version: 0.261.391** (formatting, style inventory, and programmatic access added in **0.261.392**)  
**Related config.py version: `0.261.392`**

## 1. Overview and Purpose

Supporting document accessibility review (WCAG 2.1 AA, Section 508, and PDF/UA) requires more than text and visual layout extraction. While **Azure AI Document Intelligence** and **Azure AI Content Understanding** excel at reading visual page surfaces and generating AI descriptions of figures, relying on visual extraction alone can mask accessibility defects:

- An **untagged PDF** (missing `/StructTreeRoot` and `/MarkInfo/Marked`) is still OCR'd into clean Markdown headings and tables by Document Intelligence or Content Understanding, making an inaccessible PDF appear structured.
- A **figure missing native alt text** (`/Alt` in PDF or `wp:docPr/@descr` in Office) still receives an AI-generated visual summary from Content Understanding, hiding the fact that the document itself lacks native alternative text.
- Neither cloud extraction service returns PDF tag hierarchies (`/StructTreeRoot`), `/Artifact` markers, `/Lang`, `/ViewerPreferences/DisplayDocTitle`, `/AcroForm` field `/TU` tooltips, PDF review annotations (`/Annots`), or native Office accessibility properties (`adec:decorative`, `w:tblHeader`, pseudo-headings, floating object overlap, hidden text, and explicit color contrast).

SimpleChat combines visual content extraction (Document Intelligence / Content Understanding) with an in-process native file-format parser (`application/single_app/functions_accessibility.py`) using already-installed Python libraries (`pypdf`, `PyMuPDF`/`fitz`, `defusedxml`, `olefile`) and stores the results across **Azure AI Search chunks** and the **parent Cosmos DB document record**.

---

## 2. Architecture and Storage Routing (Mermaid Diagrams)

### End-to-End File Dissection & Storage Routing

```mermaid
flowchart TB
    subgraph Inputs["1. Uploaded Document Types"]
        PDF["PDF (.pdf)"]
        WORD_OOXML["Word OOXML (.docx, .docm, .dotx)"]
        WORD_LEGACY["Word Legacy (.doc)"]
        PPTX["PowerPoint (.pptx)"]
    end

    subgraph Extractors["2. Extraction Engines (Content + Native File Parsers)"]
        direction TB
        CU_DI["Azure Content Understanding / Document Intelligence\n• Page Markdown text & visual layout\n• AI figure descriptions & OCR\n• Table visual grids"]
        PDF_PARSER["PDF Native Parser (pypdf + PyMuPDF)\n• Catalog: /MarkInfo (Tagged), /Lang, /ViewerPreferences\n• Info & XMP: /Title, /Author, /Subject, /Keywords\n• /StructTreeRoot: Full Tag Tree + Reading Order + /Pg map\n• /AcroForm: Form fields & /TU tooltips\n• Page Content Streams: /Artifact markers\n• Page /Annots: Sticky notes, highlights, free-text comments"]
        OOXML_PARSER["Office OOXML Native Parser (defusedxml + python-docx/pptx)\n• docProps/core.xml + styles.xml: Title, Author, Subject, Keywords, w:lang\n• Heading hierarchy (w:outlineLvl) vs. Pseudo-headings (bold/size Normal)\n• Lists (w:numPr vs manual bullets)\n• Tables (w:tblHeader repeat row, w:gridSpan/w:vMerge merged cells)\n• Shapes/Images (wp:docPr @descr/@title Alt Text, adec:decorative='1')\n• Layout & Cues (wp:anchor floating/overlap, w:vanish hidden text, w:color/w:shd contrast)\n• Comments (word/comments.xml + commentsExtended.xml + word_offset anchors;\n  ppt/comments/comment*.xml + modernComment*.xml)"]
        OLE_PARSER["Legacy .doc OLE Parser (olefile + MS-DOC FIB)\n• SummaryInformation & DocumentSummaryInformation\n• FIB Comment Streams (PlcfandRef, PlcfandTxt, anchor_text, word_offset)\n• Paragraph/Heading/Table heuristics"]
    end

    subgraph Storage["3. Where Each Extracted Part Is Stored"]
        direction LR
        subgraph Cosmos["Parent Cosmos DB Document Record\n(user_documents / group_documents / public_documents)"]
            COSMOS_CORE["Core Document Fields\n• id, file_name, version, num_chunks\n• title, authors, abstract (subject), keywords, language\n• word_comment_count, pdf_comment_count, pptx_comment_count"]
            COSMOS_A11Y["accessibility_metadata (JSON Object)\n• Document Flags: is_tagged, suspects, has_struct_tree,\n  language, title, display_doc_title, has_bookmarks, page_tabs_order\n• Full Inventories: heading_outline, figures_summary (native alt/decorative),\n  tables_summary (TH/tblHeader, scope, merged cells), forms_summary (/TU tooltips),\n  links_summary (tooltips/generic text), artifacts_summary, formatting_and_layout\n• Semantic Tag / Structure Tree (with page/section mapping)\n• Detected Accessibility Issues (code, severity, message)"]
        end

        subgraph AISearch["Azure AI Search Chunks\n(user / group / public index — 1..N chunks per page/section)"]
            CHUNK_TEXT["chunk_text (Per-Page / Per-Slide / Per-Section)\n1. Page / Section Extracted Content (Markdown text & tables)\n2. Inline Embedded Images Block (### Embedded image X of Y)\n   + AI Visual Description (CU/DI)\n   + Native Alt Text (@descr / /Alt), Decorative Flag & Placement\n3. Inline Comments Block (### Document/Page/Slide comment X of Y)\n   + Author, Date, Resolved Status, Quoted Anchor Text, Replies\n4. Inline Page/Section Accessibility & Tag Structure Block\n   + Exact Page Tag Tree in Reading Order (<H1> -> <P> -> <Figure> -> <Table>)\n   + Page/Section-specific Accessibility Warnings"]
            CHUNK_VEC["embedding (Vector) + Chunk Metadata\n• id, document_id, file_name, page_number, chunk_sequence\n• author, title, keywords (copied from parent)"]
        end
    end

    subgraph ChatRAG["4. How Chat Retrieves & Combines Both"]
        RAG_SEARCH["Hybrid + Vector Search on AI Search\nRetrieves relevant page chunks with inline text,\ninline comments, native image alt text & page tag tree"]
        RAG_META["get_document_metadata_for_citations()\nFetches parent Cosmos accessibility_metadata + core metadata\nand injects 'Accessibility' context into retrieved_texts"]
        LLM["LLM Accessibility & Content Review\nHas BOTH document-wide accessibility metadata (Cosmos)\nAND exact page-level tag trees, figures, and comments (AI Search)"]
    end

    PDF --> CU_DI
    PDF --> PDF_PARSER
    WORD_OOXML --> CU_DI
    WORD_OOXML --> OOXML_PARSER
    WORD_LEGACY --> CU_DI
    WORD_LEGACY --> OLE_PARSER
    PPTX --> CU_DI
    PPTX --> OOXML_PARSER

    CU_DI --> CHUNK_TEXT
    PDF_PARSER --> COSMOS_CORE
    PDF_PARSER --> COSMOS_A11Y
    PDF_PARSER --> CHUNK_TEXT

    OOXML_PARSER --> COSMOS_CORE
    OOXML_PARSER --> COSMOS_A11Y
    OOXML_PARSER --> CHUNK_TEXT

    OLE_PARSER --> COSMOS_CORE
    OLE_PARSER --> COSMOS_A11Y
    OLE_PARSER --> CHUNK_TEXT

    CHUNK_TEXT --> CHUNK_VEC
    AISearch --> RAG_SEARCH
    Cosmos --> RAG_META
    RAG_SEARCH --> LLM
    RAG_META --> LLM
```

---

### PDF (`.pdf`) Dissection & Storage Routing

```mermaid
flowchart LR
    subgraph PDFFile["PDF File (.pdf)"]
        P1["Catalog Dictionary\n• /MarkInfo (/Marked, /Suspects)\n• /Lang (e.g. en-US)\n• /ViewerPreferences (/DisplayDocTitle)\n• /Outlines (Bookmarks)"]
        P2["Info Dict & XMP Stream\n• /Title, /Author, /Subject, /Keywords\n• dc:title, dc:language, pdfuaid:part"]
        P3["/StructTreeRoot (Tag Tree)\n• Semantic Tags: Document, Part, Sect,\n  H1-H6, P, L/LI/Lbl/LBody,\n  Table/TR/TH/TD (/Scope, /Headers),\n  Figure (/Alt, /ActualText), Link, Form\n• Attributed <Span> (/Lang, /Alt, /E)\n• Page pointer (/Pg) & reading order"]
        P4["/AcroForm & Fields\n• Interactive controls (/FT)\n• Accessible tooltip (/TU)\n• Required/ReadOnly flags (/Ff)"]
        P5["Per-Page Content & Dictionaries\n• Visual text, tables, figures (via CU/DI)\n• Content stream /Artifact BDC..EMC blocks\n• Page /Tabs order (/S = Structure)\n• Page /Annots (Sticky notes /Text,\n  /FreeText, /Highlight, /Underline, /StrikeOut)"]
    end

    subgraph DestCosmos["Parent Cosmos Record"]
        C_META["Top-Level Fields\n• title, authors, abstract, keywords, language"]
        C_A11Y["accessibility_metadata\n• is_tagged, suspects, language, display_doc_title\n• bookmark_count, page_tabs_order\n• tag_counts, heading_outline\n• figures_summary (/Alt status per page)\n• tables_summary (<TH> & /Scope status)\n• forms_summary (/TU tooltip status)\n• artifacts_summary per page\n• semantic_tag_tree + detected issues"]
    end

    subgraph DestSearch["AI Search Page Chunk (Page N)"]
        S_BODY["1. Page N Text & Tables (from CU / DI)"]
        S_FIG["2. Page N Figure Summaries (CU / DI)\n+ Native PDF <Figure /Alt> & /ActualText"]
        S_COM["3. Page N Inline Annotations / Comments\n(### Page comment X of Y from /Annots)"]
        S_TAG["4. Page N Inline Tag Tree & Reading Order\n(### Page Accessibility & Tag Structure:\nexact ordered tags on Page N + page warnings)"]
    end

    P1 --> C_A11Y
    P2 --> C_META
    P2 --> C_A11Y
    P3 --> C_A11Y
    P3 -->|"Filtered by /Pg = Page N"| S_TAG
    P3 -->|"Figure /Alt on Page N"| S_FIG
    P4 --> C_A11Y
    P4 -->|"Widget on Page N"| S_TAG
    P5 -->|"Visual text & figures"| S_BODY
    P5 -->|"/Annots on Page N"| S_COM
    P5 -->|"/Artifact & /Tabs on Page N"| S_TAG
    P5 -->|"/Artifact & /Tabs rollup"| C_A11Y
```

---

### Office (`.docx`, `.docm`, `.dotx`, `.doc`, `.pptx`) Dissection & Storage Routing

```mermaid
flowchart LR
    subgraph OfficeFile["Office File (.docx / .docm / .dotx / .doc / .pptx)"]
        O1["Package Metadata & Styles\n• docProps/core.xml (title, creator, subject, keywords)\n• word/styles.xml & theme1.xml (w:lang default language)\n• OLE SummaryInformation (for .doc)"]
        O2["Document Structure (word/document.xml or ppt/slides/slide*.xml)\n• Real Headings (w:pStyle Heading / w:outlineLvl)\n• Pseudo-Headings (Normal style + bold/larger font)\n• Lists (w:numPr true lists vs manual bullet chars)\n• Tables (w:tblHeader repeat rows, w:gridSpan/w:vMerge merges)\n• Hyperlinks (@w:tooltip ScreenTip, link text quality)"]
        O3["Embedded Media & Shapes\n• Image bytes (word/media/*, ppt/media/*)\n• wp:docPr (@descr, @title Native Alt Text)\n• adec:decorative='1' Decorative Flag\n• Placement: wp:inline vs wp:anchor (floating, @allowOverlap)"]
        O4["Formatting & Hidden/Visual Cues\n• Hidden text runs (w:vanish)\n• Text boxes (w:txbxContent)\n• Explicit run color (w:color) vs shading (w:shd) contrast"]
        O5["Comments & Review Threads\n• Word: word/comments.xml + commentsExtended.xml\n  + w:commentRangeStart/End (anchor_text & word_offset)\n• Legacy .doc: FIB PlcfandRef / PlcfandTxt (anchor_text & word_offset)\n• PPTX: ppt/comments/comment*.xml & modernComment*.xml (per slide)"]
    end

    subgraph OffCosmos["Parent Cosmos Record"]
        OC_META["Top-Level Fields\n• title, authors, abstract, keywords, language\n• word_comment_count, pptx_comment_count"]
        OC_A11Y["accessibility_metadata\n• language, title_present\n• heading_outline + pseudo_headings list\n• lists_summary (structured vs manual)\n• tables_summary (tblHeader, merged cells, nested)\n• figures_summary (native alt text, decorative, floating/overlap)\n• links_summary (missing tooltips, generic link text)\n• formatting_and_layout (hidden text, textboxes, low-contrast runs)\n• detected issues"]
    end

    subgraph OffSearch["AI Search Chunk (Page / Section / Slide N)"]
        OS_BODY["1. Chunk / Slide Text & Tables (CU / DI / python-docx)"]
        OS_IMG["2. Inline Embedded Image Block (by word_offset / slide)\n(### Embedded image X of Y\n+ Native Alt Text, Decorative status & Placement\n+ AI Visual Description from CU/DI)"]
        OS_COM["3. Inline Comment Block (by word_offset / slide)\n(### Document/Slide comment X of Y by Author [Date]\non 'anchor_text' + replies)"]
        OS_A11Y["4. Inline Chunk Structure & Accessibility Notes\n(### Section/Slide Accessibility & Structure:\nHeadings, pseudo-headings, tables, figures, reading order)"]
    end

    O1 --> OC_META
    O1 --> OC_A11Y
    O2 --> OC_A11Y
    O2 --> OS_BODY
    O2 --> OS_A11Y
    O3 --> OC_A11Y
    O3 -->|"Mapped by word_offset / slide"| OS_IMG
    O4 --> OC_A11Y
    O4 --> OS_A11Y
    O5 --> OC_META
    O5 -->|"Mapped by word_offset / slide"| OS_COM
```

---

## 3. Technical Specifications

### Zero-Loss PDF `/StructTreeRoot` Handling
In PDFs exported from desktop publishing tools, 80–90% of raw `/StructTreeRoot` nodes are unattributed font-kerning `<Span>` or `<MCR>` leaves inside a paragraph (`<P>`). `_walk_pdf_struct_tree()` in `application/single_app/functions_accessibility.py`:
1. **Preserves 100% of structural/semantic tags** (`Document`, `Part`, `Art`, `Sect`, `Div`, `H`, `H1`–`H6`, `Title`, `P`, `L`, `LI`, `Lbl`, `LBody`, `Table`, `TR`, `TH`, `TD`, `Figure`, `Formula`, `Caption`, `Link`, `Form`, `Annot`, `Note`, `Reference`, `BlockQuote`, `TOC`, `TOCI`) and maps custom tags via `/RoleMap`.
2. **Preserves 100% of attributed `<Span>` nodes** carrying `/Lang`, `/Alt`, `/ActualText`, `/E`, or `/T`.
3. **Coalesces only unattributed kerning `<Span>` leaves** into their parent semantic element while recording `raw_tag_node_count` and `coalesced_span_count`.
4. **Maps every tag node by `/Pg` to its 1-based page number** and writes each page's ordered tag hierarchy inline into that page's AI Search chunk (`### Page Accessibility & Tag Structure (Page N)`), while storing the document-wide inventory and `accessibility_metadata` on the parent Cosmos DB record.

### Key Modules Modified
- `application/single_app/functions_accessibility.py`:
  - `extract_pdf_accessibility_metadata(pdf_path)` and `extract_pdf_page_annotations(pdf_path)`
  - `extract_office_accessibility_metadata(file_path, file_ext)` and `extract_pptx_comments(file_path)`
  - `build_word_chunk_accessibility_items(cosmos_meta, structural_events)`
  - `format_accessibility_metadata_for_chat(accessibility_metadata)`
- `application/single_app/functions_office_media.py`:
  - `_build_office_media_accessibility_map(archive)` enriches extracted embedded images with `alt_text`, `title_text`, `is_decorative`, `placement`, `allow_overlap`, and `behind_doc`.
- `application/single_app/functions_documents.py`:
  - Integrates PDF, Word (`.docx`, `.docm`, `.dotx`, `.doc`), and PowerPoint (`.pptx`) accessibility metadata and inline chunk enrichment into `process_di_document`, `process_doc`, and `process_office_template`.
  - Extends `get_document_metadata_for_citations()` to return `accessibility_metadata`, `accessibility_summary`, and `vision_analysis`.
- `application/single_app/route_backend_chats.py`:
  - Surfaces `accessibility_summary` as a synthetic `"Accessibility"` metadata citation and injects it into `retrieved_texts` during chat RAG.

### Formatting and Style Inventory (0.261.392)

Accessibility structure alone cannot answer questions such as "is the body text at least 11 pt?" or "does this deck use more than two fonts?". Version 0.261.392 also records fonts, sizes, colours, emphasis, and layout while the file is processed.

| File type | What is read | Fidelity |
|---|---|---|
| PDF | Per-span font name, size, colour, bold/italic flags, and whether each font is embedded (PyMuPDF). | Full for text spans. Base-14 fonts that are not embedded raise `PDF_FONTS_NOT_EMBEDDED` (low severity). |
| Word (`.docx`, `.docm`, `.dotx`) | Run properties resolved through the document defaults, style chain, and theme fonts and colours; paragraph alignment and line spacing; section page setup. | Theme colour tint/shade and table styles are not applied. Words with no size anywhere in the chain default to 10 pt. |
| PowerPoint (`.pptx`) | Run properties resolved through shape, layout placeholder, master text styles, and theme. | The colour map (`clrMap`) is not applied. Text with no size anywhere in the chain is assumed to be 18 pt. |
| Legacy Word (`.doc`) | Direct character properties from the CHPX/FKP binary tables and the font table. | **Best effort.** There is no style-sheet inheritance, so unset values stay unresolved and the inventory is marked `coverage: "partial"`. It was validated against a synthetic file, not a corpus of Word-authored documents. |

Anything that could not be resolved is stated in the inventory's `coverage_notes` rather than guessed.

```mermaid
flowchart LR
    F["Uploaded file"] --> X["functions_document_style.py<br/>per-format extractor"]
    X --> ACC["Style accumulator<br/>(bounded histograms + outliers)"]
    ACC -->|"document-wide inventory"| COS["Cosmos parent record<br/>accessibility_metadata.style_inventory"]
    ACC -->|"one Formatting line per page / slide / word-offset bucket"| CHK["AI Search chunk text"]
    COS --> SK["get_document_accessibility_report<br/>(Semantic Kernel function)"]
    COS --> CHAT["Chat context block"]
    CHK --> RAG["Normal grounded retrieval"]
```

**What is stored where**

- **Cosmos parent record** (`accessibility_metadata.style_inventory`): the document-wide inventory. It is bounded rather than raw: up to 25 fonts, 40 sizes, 25 colours, 100 outlier runs (text that differs from the body font or size, such as undersized text), with the true counts (`font_count`, `outlier_run_count`, `outliers_truncated`) kept so a consumer can tell when the list was capped. Also holds `body_font`, `body_size_pt`, `min_size_pt`, `max_size_pt`, emphasis totals, `layout`, and `page_setup`.
- **AI Search chunk text**: a compact `Formatting (characters): ...` line per page (PDF), slide (PPTX), or word-offset bucket (Word), so retrieval can answer location-specific formatting questions.
- **Not kept**: the full uncapped list of every run. Style is computed at ingestion, so documents uploaded before 0.261.392 have no style data until they are re-uploaded.

### Programmatic Access: `get_document_accessibility_report`

The **Document Search** action exposes a `get_document_accessibility_report` Semantic Kernel function that returns the stored metadata for one document. It is the supported way for a custom agent or workflow to read the complete accessibility, style, and issue data.

| Argument | Meaning |
|---|---|
| `document_id` | The document to read (required). |
| `doc_scope` | `all`, `personal`, `group`, or `public`. |
| `sections` | Comma-separated subset of `accessibility`, `style`, `issues`. Defaults to all three. |
| `page_number` | Optional 1-based page or slide. Also returns that page's stored chunk text, which carries the inline structure, formatting, and comment lines. |

Access follows the existing Document Search rules: the current user's workspace, group, and public access and the action's allowed scopes. Chat-scope uploads are refused, and documents without stored metadata return guidance to re-upload. There is deliberately no REST endpoint for this.

### Building Custom Checks

SimpleChat extracts and exposes the facts. It does **not** decide conformance: the built-in `issues` list is a set of heuristics, not a formal WCAG, Section 508, or PDF/UA conformance check, and passing it does not certify a document.

An organisation can still build its own style-guide or accessibility review:

1. Create an agent that has the Document Search action.
2. In its instructions, state the rules in measurable terms, for example "body text must be at least 11 pt", "no more than two font families", "every figure needs alternative text", "the document language must be set".
3. Tell the agent to call `get_document_accessibility_report` for the document and compare the returned `style_inventory`, `accessibility_metadata`, and `issues` against those rules, citing the values it used.
4. For location-specific findings, have it call the function again with `page_number` and read the returned chunk text.

Rules that need data SimpleChat does not extract (for example full tint/shade colour contrast, or table-style-derived formatting) will come back with unresolved values; the agent should report those as "could not be determined" rather than pass or fail.

---

## 4. Testing and Validation

- **Functional Test**: `functional_tests/test_document_accessibility_extraction.py`
  - Validates tagged vs. untagged PDF `/StructTreeRoot` traversal, attributed vs. unattributed `<Span>` handling, `<Figure /Alt>`, `<Table>/<TH /Scope>`, `/AcroForm` `/TU` tooltips, `/Artifact` detection, and PDF page `/Annots` comment extraction.
  - Validates Word (`.docx` / `.docm`) heading outline vs. pseudo-headings, structured vs. manual lists, table `w:tblHeader` and merged cells, embedded object `wp:docPr/@descr` and `adec:decorative`, floating `wp:anchor` overlap, hidden text (`w:vanish`), WCAG hex contrast ratio checks, and inline chunk placement.
  - Validates PowerPoint (`.pptx`) slide title checks, shape Z-order vs. visual reading order, slide comments, and chat metadata citation formatting.
- **Functional Test**: `functional_tests/test_document_style_extraction.py`
  - Validates PDF, DOCX (style chain, theme, page setup), PPTX, and legacy `.doc` best-effort style extraction, accumulator caps, and the chat formatting block.
- **Functional Test**: `functional_tests/test_document_accessibility_report_action.py`
  - Validates `get_document_accessibility_report` section filtering, page chunks, chat-scope and missing-metadata errors, and the plugin and citation wiring.
