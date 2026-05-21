# Visio Preview Fidelity Fix

Fixed/Implemented in version: **0.241.077**

## Issue Description

The initial Visio enhanced-citation preview proved that `.vsdx` pages could be parsed and rendered, but it produced a simplified structural sketch. The preview omitted much of the real diagram fidelity, including richer connector lines, embedded icons, and stencil artwork.

## Root Cause Analysis

The first renderer intentionally used a lightweight parser-only approach. It drew text-bearing shapes as generic boxes and connected known endpoints, but did not preserve enough nested group transforms or foreign image references to resemble Visio's actual view.

## Version Implemented

0.241.077

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `application/single_app/functions_visio.py`
- `functional_tests/test_visio_ingestion_preview.py`
- `ui_tests/test_chat_visio_citation_modal.py`
- `docs/explanation/features/VISIO_INGESTION.md`
- `docs/explanation/release_notes.md`

### Code Changes Summary

- Improved the structural fallback renderer by preserving nested shape coordinates, connector endpoints, geometry rows, and supported embedded media references.
- Removed the optional LibreOffice conversion branch after confirming Azure Linux `tdnf` does not provide LibreOffice packages in the app builder image.
- Added rendering for supported VSDX geometry path rows: `MoveTo`, `LineTo`, `RelMoveTo`, `RelLineTo`, and `Ellipse`.
- Bumped `application/single_app/config.py` to `VERSION = "0.241.077"`.

### Testing Approach

- Re-ran the Visio functional parser and preview rendering test against `artifacts/architecture.vsdx`.
- Re-ran Python compilation and JavaScript syntax checks for affected files.
- Kept UI test coverage for the Visio citation modal path.

### Impact Analysis

Users get a richer built-in Visio structural preview than the original sketch renderer without adding a large external office-suite dependency. Original `.vsdx` downloads remain unchanged.

## Validation

### Test Results

- `python functional_tests/test_visio_ingestion_preview.py` passes.
- `python -m py_compile` passes for affected Python files.
- `node --check application/single_app/static/js/chat/chat-enhanced-citations.js` passes.

### Before/After Comparison

Before, Visio previews rendered as sparse text boxes with limited connector context. After, previews use a parser renderer that includes more actual page geometry paths, media, and connector information.

### User Experience Improvements

Citation previews are more recognizable as Visio diagrams while remaining dependency-light for the existing app container.