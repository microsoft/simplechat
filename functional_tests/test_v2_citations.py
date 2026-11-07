#!/usr/bin/env python3
"""
Functional test for V2 chat citation parsing.

Version: 0.261.008
Implemented in: 0.261.008

This test ensures the V2 citation parser recognises exactly the marker grammar the
application emits. Assistant answers carry citations as trailing markers of the form

    (Source: <file>, Page: <n>) [#<documentId>_<page>]

and if the parser does not match that grammar the markers render as literal noise in the
middle of an answer. The grammar lives in chat-citations.js, so this test compares the two
directly rather than trusting a copy.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def _normalize_regex(source: str) -> str:
    """Strip whitespace so the two copies compare on structure alone."""
    return re.sub(r"\s+", "", source)


def test_citation_grammar_matches_the_existing_client():
    """The V2 marker pattern is the same grammar chat-citations.js uses."""
    print("Testing citation grammar parity...")

    legacy = _read(APP_DIR / "static" / "js" / "chat" / "chat-citations.js")
    v2 = _read(V2_SRC / "lib" / "citations.ts")

    legacy_match = re.search(r"const citationRegex = (/.+/gi);", legacy)
    assert legacy_match, "Could not find the citation regex in chat-citations.js"

    v2_match = re.search(r"const CITATION_MARKER =\s*(/.+?/gi);", v2, re.DOTALL)
    assert v2_match, "Could not find CITATION_MARKER in the V2 citation parser"

    assert _normalize_regex(legacy_match.group(1)) == _normalize_regex(v2_match.group(1)), (
        "The V2 citation grammar has diverged from chat-citations.js. Markers the "
        "application emits would render as raw text.\n"
        f"  legacy: {legacy_match.group(1)}\n"
        f"  v2:     {v2_match.group(1)}"
    )

    print("Citation grammar parity test passed!")
    return True


def test_parser_handles_every_location_label():
    """Page, Sheet and Location labels are all recognised."""
    print("Testing location label coverage...")

    v2 = _read(V2_SRC / "lib" / "citations.ts")
    marker = re.search(r"const CITATION_MARKER =\s*(/.+?/gi);", v2, re.DOTALL).group(1)

    for label in ("Page", "Sheet", "Location"):
        assert label in marker, f"The marker pattern must accept the {label!r} label"

    # Pages arrive as a comma-separated list aligned with the citation ids; sheet and
    # location are single opaque tokens and must not be split.
    assert "startsWith('page')" in v2, (
        "Only page locations should be split on commas"
    )

    print("Location label test passed!")
    return True


def test_citation_kinds_are_distinguished():
    """Document, web and agent citations resolve differently and must be told apart."""
    print("Testing citation kind classification...")

    v2 = _read(V2_SRC / "lib" / "citations.ts")
    assert "'document' | 'web' | 'agent'" in v2, "All three citation kinds must be modelled"
    assert "^https?:\\/\\//i" in v2 or "^https?:" in v2, (
        "A web citation is identified by its file name being a URL"
    )

    chip = _read(V2_SRC / "components" / "chat" / "CitationChip.tsx")
    assert "group.kind === 'web'" in chip, (
        "Web citations must link out rather than resolving stored text, which they do "
        "not have"
    )
    assert 'rel="noopener noreferrer"' in chip, (
        "External citation links must be rel-protected"
    )

    print("Citation kind test passed!")
    return True


def test_citation_lookup_payload_matches_the_route():
    """The citation request sends the fields the route reads."""
    print("Testing citation lookup payload...")

    documents = _read(APP_DIR / "route_backend_documents.py")
    for field in ("citation_id", "document_id", "page_number", "chunk_id"):
        assert f'data.get("{field}")' in documents, (
            f"The get_citation route no longer reads {field!r}"
        )

    # The response drives the detail panel.
    for field in ("cited_text", "file_name", "page_number"):
        assert f'"{field}"' in documents, (
            f"The get_citation response no longer includes {field!r}"
        )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "CitationRequest" in endpoints, "The citation request should be typed"
    assert "citation_id: string;" in endpoints, "citation_id is required by the route"

    print("Citation lookup payload test passed!")
    return True


def test_markers_are_replaced_without_injecting_html():
    """Citations become components, not raw HTML in model output."""
    print("Testing citation rendering safety...")

    v2 = _read(V2_SRC / "lib" / "citations.ts")
    assert "CITATION_PLACEHOLDER" in v2, (
        "Markers should be swapped for placeholders so the markdown renderer stays in "
        "charge of the surrounding text"
    )

    assistant_markdown = _read(V2_SRC / "components" / "chat" / "AssistantMarkdown.tsx")
    assert "dangerouslySetInnerHTML" not in assistant_markdown, (
        "Citations must never be injected as raw HTML into untrusted model output"
    )
    assert "CitationChip" in assistant_markdown, "Placeholders must render as chip components"

    print("Citation rendering safety test passed!")
    return True


def test_citation_replacement_restores_the_whitespace_it_consumed():
    """The blank line after a citation must survive, or the next block merges into it.

    The marker grammar ends with ``((?:\\[#.*?\\]\\s*)+)``. ``\\s`` matches newlines, so
    that trailing ``\\s*`` swallows the blank line separating the citation from whatever
    follows it. Because the whole match is replaced, dropping that whitespace glues the
    next markdown block onto the citation's paragraph, and bullet lists, headings and
    paragraph breaks after a citation stop rendering.

    chat-citations.js avoids this by capturing the whitespace and appending it to the
    replacement, so this asserts V2 does the same thing.
    """
    print("Testing citation trailing whitespace restoration...")

    legacy = _read(APP_DIR / "static" / "js" / "chat" / "chat-citations.js")
    v2 = _read(V2_SRC / "lib" / "citations.ts")

    assert re.search(r"/\\s\*\$/\.exec\(bracketSection\)", legacy), (
        "chat-citations.js no longer captures the whitespace after the bracket run; "
        "this test's premise needs rechecking against the current client"
    )

    assert re.search(r"/\\s\*\$/\.exec\(brackets\)", v2), (
        "The V2 parser must capture the whitespace the bracket group consumed. Without "
        "it, a bullet list or paragraph following a citation is merged into the "
        "citation's own line."
    )

    # Both exits from the replacer have to restore it: the resolvable case that emits a
    # placeholder, and the unresolvable case that drops the marker entirely.
    assert "${CITATION_PLACEHOLDER(groupIndex)}${trailingWhitespace}" in v2, (
        "The placeholder replacement must re-append the captured whitespace"
    )
    assert "return trailingWhitespace;" in v2, (
        "Dropping an unresolvable marker must still preserve the structure around it"
    )

    # The orphan-bracket sweep runs over text that has already been through the marker
    # replacement, so it must not eat newlines of its own.
    orphan = re.search(r"const ORPHAN_BRACKET_RUN =\s*(/.+?/g);", v2, re.DOTALL)
    assert orphan, "Could not find ORPHAN_BRACKET_RUN in the V2 citation parser"
    assert "\\s*" not in orphan.group(1), (
        "The orphan bracket sweep must use [ \\t]* rather than \\s* so it cannot consume "
        f"paragraph breaks: {orphan.group(1)}"
    )

    print("Citation trailing whitespace test passed!")
    return True


def test_placeholders_are_substituted_in_every_block_element():
    """A placeholder must resolve wherever markdown puts it, not just in a paragraph.

    Citations legitimately land in list items, table cells, headings and blockquotes. Any
    block type missing from the renderer's component map would print the raw
    ``[cite:N]`` sentinel as visible text.
    """
    print("Testing placeholder substitution coverage...")

    assistant_markdown = _read(V2_SRC / "components" / "chat" / "AssistantMarkdown.tsx")

    for element in ("p", "li", "td", "th", "h1", "h2", "h3", "h4", "blockquote", "em", "strong"):
        assert re.search(rf"\b{element}:\s*\(", assistant_markdown), (
            f"The markdown component map has no {element!r} handler, so a citation "
            "landing there would render as a raw placeholder"
        )

    print("Placeholder substitution coverage test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added citations."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.008")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_citation_grammar_matches_the_existing_client,
        test_parser_handles_every_location_label,
        test_citation_kinds_are_distinguished,
        test_citation_lookup_payload_matches_the_route,
        test_markers_are_replaced_without_injecting_html,
        test_citation_replacement_restores_the_whitespace_it_consumed,
        test_placeholders_are_substituted_in_every_block_element,
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
