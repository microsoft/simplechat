#!/usr/bin/env python3
"""
Functional test for V2 enhanced citations.

Version: 0.261.010
Implemented in: 0.261.010

This test ensures the V2 enhanced citation viewers agree with the endpoints they call and
reproduce V1's gating decisions.

Two behaviours are easy to get wrong and are asserted directly:

* The per-document gate is deliberately permissive. Only an explicit
  ``enhanced_citations == false`` disables enhanced rendering; missing metadata still
  attempts it and relies on the failure fallback. Treating a lookup failure as a refusal
  would silently downgrade every citation whose document cannot be resolved.
* The PDF endpoint returns a narrow window around the cited page, not the whole document,
  and reports which page of that extract to open at via the ``X-Sub-PDF-Page`` header.
  Ignoring the header opens every PDF citation on the wrong page.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
LEGACY_JS = APP_DIR / "static" / "js" / "chat" / "chat-enhanced-citations.js"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def test_all_viewer_endpoints_exist():
    """Every endpoint the V2 viewers call is still registered."""
    print("Testing enhanced citation endpoints...")

    routes = _read(APP_DIR / "route_enhanced_citations.py")
    for route in (
        "/api/enhanced_citations/document_metadata",
        "/api/enhanced_citations/image",
        "/api/enhanced_citations/pdf",
        "/api/enhanced_citations/video",
        "/api/enhanced_citations/audio",
        "/api/enhanced_citations/tabular_preview",
        "/api/enhanced_citations/tabular_workspace",
        "/api/enhanced_citations/visio",
        "/api/workspace_documents/download",
    ):
        assert f'"{route}"' in routes, f"Route {route} is missing"

    # All of them are gated on the same capability.
    assert routes.count('@enabled_required("enable_enhanced_citations")') >= 8, (
        "Enhanced citation routes should be gated on enable_enhanced_citations"
    )

    print("Endpoint existence test passed!")
    return True


def test_viewer_type_map_matches_the_existing_client():
    """The extension-to-viewer map is the same one V1 uses."""
    print("Testing viewer type map parity...")

    legacy = _read(LEGACY_JS)
    v2 = _read(V2_SRC / "lib" / "enhancedCitations.ts")

    # Each list is compared by membership rather than literal text, since the two files
    # format them differently.
    expected = {
        "image": ["jpg", "jpeg", "png", "bmp", "tiff", "tif"],
        "video": ["mp4", "mov", "avi", "mkv", "flv", "webm", "wmv", "m4v", "3gp"],
        "audio": ["mp3", "wav", "ogg", "aac", "flac", "m4a"],
        "tabular": ["csv", "xlsx", "xls", "xlsm"],
        "visio": ["vsdx"],
    }

    for kind, extensions in expected.items():
        for extension in extensions:
            assert f"'{extension}'" in legacy, (
                f"chat-enhanced-citations.js no longer lists {extension!r}"
            )
            assert f"'{extension}'" in v2, (
                f"The V2 viewer map is missing the {kind} extension {extension!r}"
            )

    assert "'pdf'" in v2, "The V2 viewer map is missing pdf"

    print("Viewer type map test passed!")
    return True


def test_per_document_gate_is_permissive():
    """Only an explicit false disables enhanced rendering."""
    print("Testing per-document gate semantics...")

    routes = _read(APP_DIR / "route_enhanced_citations.py")
    assert '"enhanced_citations": bool(raw_doc.get("enhanced_citations", False))' in routes, (
        "document_metadata no longer returns the per-document enhanced_citations flag"
    )

    chip = _read(V2_SRC / "components" / "chat" / "CitationChip.tsx")

    # The exact comparison matters: a truthiness check would also disable on undefined,
    # which V1 explicitly treats as "attempt enhanced".
    assert "enhanced_citations === false" in chip, (
        "The gate must compare against false explicitly; a truthiness check would "
        "downgrade documents whose flag is merely absent"
    )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    metadata_block = endpoints[endpoints.index("fetchEnhancedCitationMetadata") :][:700]
    assert "return null" in metadata_block, (
        "A metadata lookup failure must return null rather than throwing, so the caller "
        "can still attempt enhanced rendering as V1 does"
    )

    print("Per-document gate test passed!")
    return True


def test_pdf_uses_the_sub_page_header():
    """The PDF viewer opens at the page the server reports, not page 1."""
    print("Testing PDF sub-page handling...")

    routes = _read(APP_DIR / "route_enhanced_citations.py")
    assert "X-Sub-PDF-Page" in routes, (
        "The PDF endpoint no longer reports which page of the extract to open at"
    )
    # The server narrows the document rather than returning all of it by default.
    assert "show_all" in routes, "The PDF endpoint should still support show_all"

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "X-Sub-PDF-Page" in endpoints, (
        "The PDF wrapper must read X-Sub-PDF-Page; a JSON-only helper discards headers"
    )

    viewer = _read(V2_SRC / "components" / "chat" / "EnhancedCitationViewer.tsx")
    assert re.search(r"#page=\$\{subPage\}", viewer), (
        "The iframe fragment must use the server-reported sub-page"
    )
    assert "show_all" in endpoints, "The viewer must be able to request the full document"

    print("PDF sub-page test passed!")
    return True


def test_pdf_needs_no_vendored_engine():
    """PDFs render through the browser, so no third-party engine is bundled."""
    print("Testing PDF rendering approach...")

    viewer = _read(V2_SRC / "components" / "chat" / "EnhancedCitationViewer.tsx")

    # V1 renders PDFs in an iframe from a blob URL and vendors no pdf.js. Matching that
    # keeps V2 free of a new third-party browser asset, which the local-assets rule bans
    # from CDNs and would otherwise require vendoring and pinning.
    assert "createObjectURL" in viewer and "<iframe" in viewer, (
        "PDFs should render via a blob URL in an iframe, as V1 does"
    )
    assert "revokeObjectURL" in viewer, (
        "Object URLs hold the whole document in memory and must be revoked"
    )

    package_json = _read(REPO_ROOT / "application" / "v2_ui" / "package.json")
    for engine in ("pdfjs-dist", "react-pdf", "pdf-lib"):
        assert engine not in package_json, (
            f"{engine} was added; the browser renders these PDFs already and bundling an "
            "engine adds a large dependency for no gain"
        )

    # The CSP must still permit the blob iframe and media this relies on.
    config = _read(APP_DIR / "config.py")
    assert "frame-src 'self' blob:" in config, (
        "The CSP must allow blob: frames for the PDF viewer"
    )
    assert "media-src 'self' blob:" in config, (
        "The CSP must allow blob: media"
    )

    print("PDF rendering approach test passed!")
    return True


def test_media_seeks_to_the_cited_offset():
    """Audio and video citations carry a time offset and seek to it."""
    print("Testing media seek...")

    v2 = _read(V2_SRC / "lib" / "enhancedCitations.ts")
    assert "convertTimestampToSeconds" in v2

    # The clock format must be tried before a bare numeric parse. parseFloat("0:02")
    # returns 0, so the V1 ordering silently seeks a cited moment back to the start.
    clock_index = v2.index("includes(':')")
    numeric_index = v2.index("Number.parseFloat(timestamp)", v2.index("convertTimestampToSeconds"))
    assert clock_index < numeric_index, (
        "The HH:MM:SS branch must be checked before parseFloat, otherwise '0:02' parses "
        "as 0 and the citation seeks to the beginning"
    )

    viewer = _read(V2_SRC / "components" / "chat" / "EnhancedCitationViewer.tsx")
    assert "currentTime" in viewer, "Media must seek to the cited offset"
    assert "onLoadedMetadata" in viewer, (
        "Seeking requires duration, which is only known once metadata has loaded"
    )
    # Media points at the endpoint rather than a blob so the browser can range-request.
    assert "enhancedCitationMediaUrl" in viewer, (
        "Media should stream from the endpoint rather than a fully buffered blob"
    )

    print("Media seek test passed!")
    return True


def test_every_failure_falls_back_to_the_text_passage():
    """A citation that cannot show its source still shows its text."""
    print("Testing fallback behaviour...")

    viewer = _read(V2_SRC / "components" / "chat" / "EnhancedCitationViewer.tsx")
    # Each viewer reports failure rather than rendering a dead panel.
    assert viewer.count("onFail(") >= 5, (
        "Every viewer should report failure so the caller can fall back"
    )

    chip = _read(V2_SRC / "components" / "chat" / "CitationChip.tsx")
    assert "onFallback" in chip, "The chip must handle a viewer reporting failure"
    assert "notice={fallbackReason}" in chip, (
        "The fallback must be visible to the user rather than a silent downgrade"
    )

    print("Fallback test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added the viewers."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.010")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_all_viewer_endpoints_exist,
        test_viewer_type_map_matches_the_existing_client,
        test_per_document_gate_is_permissive,
        test_pdf_uses_the_sub_page_header,
        test_pdf_needs_no_vendored_engine,
        test_media_seeks_to_the_cited_offset,
        test_every_failure_falls_back_to_the_text_passage,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
