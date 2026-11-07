#!/usr/bin/env python3
"""
Functional test for V2 message copy, download and reuse as plain text.

Version: 0.261.018
Implemented in: 0.261.018

Copying a message used to write `message.content` to the clipboard verbatim. That is not
what is on screen, and it fails in two different ways.

The visible one: citation markers are lifted out of the text and shown as chips, so the raw
content still carries them. Pasted into an email or a document you get

    ...up to 0.2 mm/s at full load. (Source: NanoPZ.pdf, Page: 13) [#0d4d4eb0-...-...f_13]

in the middle of every other sentence. The classic client has the same problem.

The quieter one: masked spans are redactions a reader has deliberately applied, and the raw
content still contains the hidden text. Copying it put that text back on the clipboard,
which defeats the redaction.

This test ensures every path that takes a message out of the app -- clipboard, downloaded
file, and reuse as a prompt -- goes through the shared conversion rather than the raw
content, and that the conversion strips citations and preserves redactions.
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


def test_plain_text_conversion_exists_and_is_shared():
    """One conversion, used by every path that takes a message out of the app."""
    print("Testing plain text conversion...")

    module = V2_SRC / "lib" / "messageText.ts"
    assert module.exists(), "messageText.ts should hold the shared conversion"

    actions = _read(V2_SRC / "components" / "chat" / "MessageActions.tsx")
    assert "messageToPlainText" in actions, (
        "The message actions must use the shared conversion"
    )

    # Every exit path is covered. `message.content` must not reach any of them directly.
    assert "writeText(messageToPlainText(message))" in actions, (
        "Copy must write the converted text, not the raw content"
    )
    assert re.search(r"function downloadMarkdown(.|\n)*?messageToPlainText\(", actions), (
        "The markdown download must use the converted text"
    )
    assert re.search(r"Use as prompt(.|\n)*?messageToPlainText\(message\)", actions), (
        "Reusing a message as a prompt must not feed citation markers back to the model"
    )

    assert "writeText(message.content)" not in actions, (
        "Raw content must never reach the clipboard"
    )
    assert "new Blob([message.content]" not in actions, (
        "Raw content must never be written to a downloaded file"
    )

    print("Plain text conversion test passed!")
    return True


def test_citations_are_stripped_with_their_leading_space():
    """A removed citation must not leave a trailing or doubled space behind."""
    print("Testing citation removal...")

    module = _read(V2_SRC / "lib" / "messageText.ts")
    citations = _read(V2_SRC / "lib" / "citations.ts")

    # The placeholder the conversion strips has to be the one the parser emits. Both are
    # written literally, so compare the escape used in each.
    assert "\\u27E6cite:" in module, (
        "The conversion must strip the citation placeholder the parser produces"
    )
    assert "\\u27E6cite:" in citations, (
        "CITATION_PLACEHOLDER changed; the copy conversion strips a stale token"
    )

    # Taking the leading space is what keeps "at full load. [cite]" from becoming
    # "at full load. " and "before [cite] after" from becoming "before  after".
    assert "[ \\t]*\\u27E6cite:\\d+\\u27E7" in module, (
        "The placeholder must be stripped together with the space in front of it"
    )
    assert "replace(/[ \\t]+$/gm, '')" in module, (
        "Trailing whitespace left on a line must be trimmed"
    )
    assert "replace(/\\n{3,}/g, '\\n\\n')" in module, (
        "A citation that occupied a whole line leaves a blank line behind"
    )

    print("Citation removal test passed!")
    return True


def test_redactions_survive_leaving_the_app():
    """Masked text must not be recoverable from the clipboard or a saved file."""
    print("Testing redaction preservation...")

    module = _read(V2_SRC / "lib" / "messageText.ts")

    assert "readMaskState" in module and "applyMasks" in module, (
        "The conversion must apply the message's masks, not read raw content"
    )
    assert "MASK_PLACEHOLDER_PATTERN" in module, (
        "Mask placeholders must be replaced with readable text rather than left as sentinels"
    )
    assert re.search(r"if \(masks\.fullyMasked\) \{\s*return MASK_TEXT;", module), (
        "A wholly masked message must be withheld outright rather than partially cut"
    )

    # The masks the client applies are the ones the server recorded; this is presentation,
    # not enforcement, and the server is what actually withholds content from the model.
    masking_route = _read(APP_DIR / "functions_message_masking.py")
    assert "masked_ranges" in masking_route, (
        "The server no longer stores masked_ranges; the client conversion reads that field"
    )

    print("Redaction preservation test passed!")
    return True


def test_sources_are_offered_rather_than_silently_discarded():
    """Attribution is still available, just not interleaved with the prose."""
    print("Testing source reference list...")

    module = _read(V2_SRC / "lib" / "messageText.ts")
    assert "includeSources" in module, (
        "There must be a way to keep the citations when they are wanted"
    )
    assert "Sources:" in module, "The reference list needs a heading"
    assert "lines.includes(line)" in module, (
        "The same page is commonly cited several times and should be listed once"
    )

    actions = _read(V2_SRC / "components" / "chat" / "MessageActions.tsx")
    assert "Copy with sources" in actions, (
        "The overflow menu should offer a copy that keeps the attribution"
    )
    assert re.search(r"downloadMarkdown(.|\n)*?includeSources: true", actions), (
        "A saved file should keep its references"
    )

    print("Source reference list test passed!")
    return True


def test_markdown_is_preserved():
    """Bold, lists and headings are what make a pasted answer readable."""
    print("Testing markdown preservation...")

    module = _read(V2_SRC / "lib" / "messageText.ts")

    # The conversion only removes the machine-facing parts; nothing strips markdown syntax.
    for stripper in ("replace(/\\*\\*", "stripMarkdown", "textContent", "innerText"):
        assert stripper not in module, (
            f"The conversion must not strip markdown ({stripper!r} found)"
        )

    print("Markdown preservation test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added this."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.018")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_plain_text_conversion_exists_and_is_shared,
        test_citations_are_stripped_with_their_leading_space,
        test_redactions_survive_leaving_the_app,
        test_sources_are_offered_rather_than_silently_discarded,
        test_markdown_is_preserved,
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
