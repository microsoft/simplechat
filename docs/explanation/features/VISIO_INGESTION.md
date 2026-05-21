# Visio Ingestion

Implemented in version: **0.241.074**

Improved in versions: **0.241.078**, **0.241.079**

## Overview

Visio ingestion adds native `.vsdx` upload support so users can ask questions about the structured contents of Visio diagrams instead of only treating them as opaque files or converted PDFs.

The feature parses Visio Open Packaging Convention XML, indexes each Visio page as one searchable chunk, stores the original `.vsdx` for enhanced citations, and renders a built-in structural PNG preview for the cited page.

## Dependencies

- Python `zipfile` and `xml.etree.ElementTree` for reading VSDX package parts.
- Pillow for structural PNG preview rendering.
- Existing enhanced-citation blob storage for original file retrieval.
- Existing Azure AI Search chunk indexing pipeline.

## Technical Specifications

### Architecture

The VSDX parser reads `visio/pages/pages.xml` and its relationship file to discover page tabs and page XML parts. Each page XML is parsed for shapes, text, shape data, page dimensions, and connector records. Preview rendering can also expand referenced Visio master stencil shapes so common Azure and service icons have more of their original vector structure without adding an office-suite runtime.

Each page is converted to Markdown-like structured text and saved as one search chunk. The chunk page number matches the Visio page index, so enhanced citation clicks can request the matching visual preview.

### API Endpoint

- `GET /api/enhanced_citations/visio?doc_id={id}&page={page}` returns an `image/png` preview for a Visio page.
- `GET /api/enhanced_citations/visio?doc_id={id}&download=true` downloads the original `.vsdx` file.

Both routes use the existing enhanced-citation authorization path and require `enable_enhanced_citations`.

### File Structure

- `application/single_app/functions_visio.py` parses VSDX files and renders page previews.
- `application/single_app/config.py` declares the shared `VISIO_EXTENSIONS` allow-list used by upload validation and enhanced citations.
- `application/single_app/functions_documents.py` dispatches `.vsdx` uploads to the Visio ingestion flow.
- `application/single_app/route_enhanced_citations.py` serves Visio previews and downloads.
- `application/single_app/static/js/chat/chat-enhanced-citations.js` opens Visio citation previews in a Bootstrap modal.
- `functional_tests/test_visio_ingestion_preview.py` validates parser and renderer behavior.

## Usage Instructions

1. Upload a `.vsdx` file to a supported workspace.
2. Ask questions about the diagram contents in chat.
3. Click a Visio citation to open the rendered page preview.
4. Use the modal download button when the original `.vsdx` is needed.

No separate admin toggle is required beyond existing document upload and enhanced-citation settings.

## Testing and Validation

Test coverage is provided by `functional_tests/test_visio_ingestion_preview.py`, which validates that `artifacts/architecture.vsdx` can be parsed, indexed into page content, rendered as a PNG preview, and expanded with master stencil geometry only for preview rendering. `functional_tests/test_visio_extensions_config.py` validates that the shared Visio extension constant remains exported and included in allowed uploads.

## Performance Considerations

The built-in renderer draws positioned text, connector endpoints, supported VSDX path geometry, selected master stencil vector geometry, curve approximations, dashed containers, and supported embedded media using parsed Visio coordinates. Preview PNGs use bounded supersampling for smoother output. This keeps previews dependency-light and suitable for citation context, but it does not attempt full Visio theme, gradient, shadow, icon, or connector routing fidelity.

For very large diagrams, preview rendering is capped by a configurable maximum edge size.

## Known Limitations

- `.vsd` binary Visio files are not supported.
- Embedded stencil artwork, curves, gradients, shadows, and theme styling are approximated.
- Grouped shape coordinate transforms may not perfectly match the Visio desktop rendering.
- The preview is intended for citation orientation; the original `.vsdx` remains available for exact inspection.