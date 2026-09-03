#!/usr/bin/env python3
"""
Functional test for the V2 diagram viewer: sizing, resizing, expanding and render recovery.

Version: 0.261.037
Implemented in: 0.261.037

Four reported problems, each reproduced against the vendored mermaid 11.17.2 bundle in
Chromium before anything was changed:

  - **Diagrams rendered far too small, and jumped larger when the colour menu was opened.**
    The assistant bubble is shrink-to-fit and mermaid emits ``width="100%"``, which contributes
    nothing to intrinsic sizing, so the bubble collapsed to the width of the diagram's own
    toolbar. Opening the colour menu introduced a palette row that *does* have a natural width,
    which is why the same diagram suddenly became legible. The panel now takes its width from
    the diagram's measured natural width.

  - **A long diagram made the thread unusable.** A flowchart at mermaid's default limit of 500
    edges measures 50,466 pixels tall. With no cap it went straight into the scroll container.
    The stage now has a bounded height and scrolls internally.

  - **Some diagrams never rendered, with nothing to go on.** The error was caught and
    discarded: no message, no console entry. It is now shown, logged, and the source is
    repaired and retried once before the reader is given up on.

  - **There was no way to make a diagram bigger.** Zoom, a drag-to-resize handle whose height is
    kept on the message, and a full-screen viewer.

The strongest assertion here is negative: ``repairMermaidSource`` must be a no-op for every
diagram mermaid already accepts. It only ever runs after a failure, so rewriting working output
would be a regression with nothing gained.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
sys.path.insert(0, str(APP_DIR))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

from functions_message_visual_styles import (  # noqa: E402
    MAX_BLOCK_HEIGHT,
    MIN_BLOCK_HEIGHT,
    UNSET,
    VisualStyleError,
    apply_visual_style,
    read_visual_styles,
    validate_block_height,
)

IMPLEMENTED_IN = "0.261.037"

MERMAID_TSX = V2_SRC / "components" / "chat" / "MermaidDiagram.tsx"
STAGE_TSX = V2_SRC / "components" / "chat" / "DiagramStage.tsx"
MESSAGE_LIST_TSX = V2_SRC / "components" / "chat" / "MessageList.tsx"
SOURCE_TS = V2_SRC / "lib" / "mermaidSource.ts"
BLOCK_STYLE_TS = V2_SRC / "lib" / "blockVisualStyle.ts"


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def test_version_is_at_least_the_implementing_release():
    """The fix is present from the version it was implemented in onwards."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_the_panel_takes_its_width_from_the_diagram():
    """The diagram sizes the panel, rather than the panel sizing the diagram."""
    source = _read(MERMAID_TSX)

    assert "MIN_FIGURE_WIDTH" in source, (
        "the panel needs a floor so a narrow diagram does not squeeze the toolbar"
    )
    assert re.search(r"width:\s*Math\.max\(size\.width,\s*MIN_FIGURE_WIDTH\)", source), (
        "the figure must be given the diagram's measured natural width. Without a definite "
        "width the shrink-to-fit assistant bubble collapses to the toolbar and mermaid's "
        "width:100% SVG is drawn illegibly small."
    )
    assert "maxWidth: '100%'" in source, (
        "a diagram wider than the bubble must be held inside it rather than overflowing"
    )

    stage = _read(STAGE_TSX)
    assert "max-width:\\s*([0-9.]+)px" in stage or "max-width:" in stage, (
        "the natural width is read back out of the max-width mermaid emits"
    )
    print("  ok  the panel is sized from the diagram's natural width")


def test_a_long_diagram_cannot_fill_the_thread():
    """The stage is bounded and scrolls, so a tall diagram stays a panel."""
    stage = _read(STAGE_TSX)

    assert "DEFAULT_MAX_STAGE_HEIGHT" in stage, "a default height ceiling must exist"
    assert "MAX_STAGE_HEIGHT" in stage and "MIN_STAGE_HEIGHT" in stage, (
        "the resize handle must have bounds"
    )
    assert "overflow-auto" in stage, "the stage must scroll rather than grow without limit"
    assert "[contain:content]" in stage, (
        "paint containment is what stops a large diagram re-rasterizing the thread on scroll"
    )
    print("  ok  a long diagram is capped and scrolls inside its own panel")


def test_the_render_failure_is_reported_rather_than_swallowed():
    """A diagram that will not draw says why, in the panel and in the console."""
    source = _read(MERMAID_TSX)

    assert "console.warn(" in source, (
        "the parser's own words must reach the console; the previous `.catch(() => ...)` "
        "discarded the error entirely, which is why a failure could not be diagnosed"
    )
    assert "describeMermaidError(" in source, "the reason must be turned into something readable"
    assert re.search(r"status:\s*'error';\s*reason:\s*string", source), (
        "the error state must carry the reason, not just the fact of failure"
    )
    assert "Show details" in source, "the reason must be reachable from the fallback panel"
    assert "Copy source" in source, "the source must be copyable when it cannot be drawn"
    print("  ok  a render failure reports why, in the panel and the console")


def test_rendering_is_bounded():
    """A render cannot hang, and an oversized source is refused with its own message."""
    source = _read(MERMAID_TSX)

    assert "RENDER_TIMEOUT_MS = 10000" in source, (
        "matches MERMAID_RENDER_TIMEOUT_MS in chat-mermaid-runtime.js; without it a wedged "
        "render leaves 'Rendering diagram…' on screen for the life of the page"
    )
    assert "withTimeout(" in source, "the timeout must actually be applied to the render"
    assert "MAX_SOURCE_LENGTH" in source, (
        "matches INLINE_DIAGRAM_MAX_SOURCE_LENGTH in chat-inline-diagrams.js"
    )
    assert "maxTextSize: MERMAID_MAX_TEXT_SIZE" in source, "mermaid's ceilings must be stated"
    assert "maxEdges: MERMAID_MAX_EDGES" in source, "mermaid's ceilings must be stated"
    print("  ok  rendering is bounded by a timeout and by size limits")


def test_the_repair_only_runs_after_a_failure():
    """A diagram mermaid accepts is handed over untouched."""
    source = _read(MERMAID_TSX)

    first = source.index("svg = await draw(source);")
    repair = source.index("repairMermaidSource(source)")
    assert first < repair, (
        "the original source must be attempted before any rewrite, so a diagram that renders "
        "today can never be changed by the repair pass"
    )
    assert "isRepairWorthTrying(source)" in source, (
        "a second render must be skipped when the repair would change nothing"
    )
    assert "catch (error)" in source[first:repair], "the retry must be reached only on failure"
    print("  ok  source is only repaired after mermaid has already refused it")


def test_labels_wrap_at_a_readable_width():
    """Mermaid's 200px default turns long labels into unreadable columns of text."""
    source = _read(MERMAID_TSX)

    assert "MERMAID_WRAPPING_WIDTH" in source, "the wrapping width must be set explicitly"
    assert "wrappingWidth: MERMAID_WRAPPING_WIDTH" in source, (
        "the wrapping width must actually be passed to the flowchart renderer"
    )
    match = re.search(r"MERMAID_WRAPPING_WIDTH\s*=\s*(\d+)", source)
    assert match and int(match.group(1)) > 200, (
        "the point of setting it is to be wider than mermaid's default of 200"
    )
    print("  ok  labels wrap at a width wider than mermaid's default")


def test_the_diagram_can_be_enlarged():
    """Zoom, a resize handle and a full-screen viewer."""
    source = _read(MERMAID_TSX)
    stage = _read(STAGE_TSX)

    assert "ZoomControls" in source, "zoom controls must exist"
    assert "MIN_ZOOM" in stage and "MAX_ZOOM" in stage, "zoom must be bounded"
    assert "DiagramLightbox" in source, "a full-screen viewer must exist"
    assert 'role="dialog"' in source and 'aria-modal="true"' in source, (
        "the viewer is a dialog and must say so"
    )
    assert "'Escape'" in source, "Escape must dismiss the viewer, as it does for the image one"

    assert 'role="slider"' in stage, (
        "the resize handle must be a slider: it has a value, a range and a reset, and a "
        "drag-only affordance would be unusable from the keyboard"
    )
    assert "aria-valuemin" in stage and "aria-valuemax" in stage, "the handle must expose its range"
    assert "'Home'" in stage, "there must be a way back to the automatic height"
    assert "ArrowDown" in stage and "ArrowUp" in stage, "the handle must be keyboard operable"
    print("  ok  a diagram can be zoomed, resized and opened full screen")


def test_the_chosen_height_is_kept_on_the_message():
    """A resize is stored beside the colours, and the two do not disturb each other."""
    message = {"id": "m1"}

    apply_visual_style(message, "mermaid", 0, None, "abc123", 400)
    stored = read_visual_styles(message)["mermaid"]["0"]
    assert stored["height"] == 400, stored
    assert "palette" not in stored, (
        "a resize alone must not become a colour override, or a diagram someone merely made "
        "bigger would stop following their default palette"
    )

    # Recolouring says nothing about the height, so the height survives.
    apply_visual_style(
        message,
        "mermaid",
        0,
        {"palette": "vivid", "background": "theme", "colors": {}},
        "abc123",
    )
    stored = read_visual_styles(message)["mermaid"]["0"]
    assert stored["height"] == 400, stored
    assert stored["palette"] == "vivid", stored

    # Resetting the colours says nothing about the height either.
    apply_visual_style(message, "mermaid", 0, None, "abc123")
    stored = read_visual_styles(message)["mermaid"]["0"]
    assert stored["height"] == 400, stored
    assert "palette" not in stored, stored

    # Clearing the height with no colours left removes the entry entirely.
    apply_visual_style(message, "mermaid", 0, None, "abc123", None)
    assert read_visual_styles(message) == {}, read_visual_styles(message)
    assert "visual_styles" not in message.get("metadata", {}), message
    print("  ok  a chosen height is stored, kept and cleared independently of the colours")


def test_a_stored_height_is_bounded_and_validated():
    """The value comes from a drag, so it is clamped rather than trusted."""
    assert validate_block_height(10) == MIN_BLOCK_HEIGHT
    assert validate_block_height(99999) == MAX_BLOCK_HEIGHT
    assert validate_block_height(300.4) == 300
    assert validate_block_height(None) is None

    # json.loads accepts the bare Infinity and NaN tokens, and round(inf) raises OverflowError,
    # which would escape the route's VisualStyleError handling and turn a bad request into a
    # 500 with an ERROR-level traceback.
    for bad in ("400", True, [400], {"height": 400}, float("nan"), float("inf"), float("-inf")):
        try:
            validate_block_height(bad)
        except VisualStyleError:
            continue
        except Exception as error:  # noqa: BLE001
            raise AssertionError(
                f"a height of {bad!r} raised {type(error).__name__}, which the route does not "
                "handle; it must raise VisualStyleError so the request fails with a 400"
            ) from error
        raise AssertionError(f"a height of {bad!r} should have been rejected")

    message = {"id": "m2"}
    apply_visual_style(message, "mermaid", 0, None, "abc123", 10_000_000)
    assert read_visual_styles(message)["mermaid"]["0"]["height"] == MAX_BLOCK_HEIGHT
    print("  ok  a stored height is clamped and non-numbers are refused")


def test_a_height_is_not_carried_across_a_source_change():
    """A size chosen for different content must not become authoritative for this block."""
    message = {"id": "m4"}

    apply_visual_style(message, "mermaid", 0, None, "aaaa1111", 800)
    assert read_visual_styles(message)["mermaid"]["0"]["height"] == 800

    # The block at index 0 is now different content: an edit or a mask shifted the positions.
    # The client already ignores the stored entry, so carrying the height forward would
    # resurrect it and re-stamp it with the new fingerprint.
    apply_visual_style(
        message,
        "mermaid",
        0,
        {"palette": "vivid", "background": "theme", "colors": {}},
        "bbbb2222",
    )
    stored = read_visual_styles(message)["mermaid"]["0"]
    assert "height" not in stored, (
        f"a height stored against source aaaa1111 was carried onto bbbb2222: {stored}"
    )
    assert stored["source_hash"] == "bbbb2222", stored

    # A matching fingerprint still keeps the height, which is the whole point of storing it.
    apply_visual_style(message, "mermaid", 1, None, "cccc3333", 700)
    apply_visual_style(
        message,
        "mermaid",
        1,
        {"palette": "calm", "background": "theme", "colors": {}},
        "cccc3333",
    )
    assert read_visual_styles(message)["mermaid"]["1"]["height"] == 700
    print("  ok  a stored height does not survive a source-hash change")


def test_an_absent_height_is_not_a_cleared_height():
    """The route must tell "said nothing" apart from "clear it"."""
    route = _read(APP_DIR / "route_backend_chats.py")

    assert "VISUAL_STYLE_HEIGHT_UNSET" in route, "the sentinel must be imported"
    assert "data.get('height') if 'height' in data else VISUAL_STYLE_HEIGHT_UNSET" in route, (
        "a body that omits the height must leave the stored one alone; only an explicit null "
        "clears it"
    )

    message = {"id": "m3"}
    apply_visual_style(message, "mermaid", 0, None, "abc123", 500)
    apply_visual_style(message, "mermaid", 0, None, "abc123", UNSET)
    assert read_visual_styles(message)["mermaid"]["0"]["height"] == 500
    print("  ok  omitting the height keeps it; sending null clears it")


def test_a_height_only_entry_does_not_shadow_the_reader_default():
    """The client must read the colour override from the palette, not the entry."""
    source = _read(BLOCK_STYLE_TS)

    assert "readStoredEntry" in source, "reading the entry and reading the override are separate"
    assert re.search(r"typeof entry\.palette !== 'string'", source), (
        "an entry carrying only a height is not a colour override; treating it as one would "
        "pin a resized diagram to the built-in palette"
    )
    assert "readStoredHeight" in source, "the stored height must be read back"
    print("  ok  a height-only entry still follows the reader's colour default")


def test_the_thread_does_not_re_render_on_every_scroll():
    """The scroll position must not re-run every message's markdown."""
    source = _read(MESSAGE_LIST_TSX)

    assert "const MessageBubble = memo(MessageBubbleInner)" in source, (
        "without memoisation every streaming token re-runs the whole markdown pipeline for "
        "every message in the thread"
    )
    assert "pinnedRef" in source, "the pinned flag must be a ref"
    assert "pinnedToBottom" not in source, (
        "holding the pinned flag in state re-rendered the entire thread on every scroll that "
        "crossed the threshold"
    )
    assert ".scrollIntoView(" not in source, (
        "scrollIntoView also scrolls every scrollable ancestor; the container's own scrollTop "
        "is what should move"
    )
    assert "ResizeObserver" in source, (
        "a diagram renders asynchronously and grows the thread after the scroll that was meant "
        "to land at the bottom, which is why the bottom became unreachable"
    )
    assert "useMemo(() => readMaskState(message)" in source, (
        "mask state is walked on every render of every message and must be memoised"
    )
    print("  ok  scrolling and streaming no longer re-render the whole thread")


def test_the_sanitizer_boundary_is_still_a_single_reviewed_file():
    """The expanded viewer must not become a second, unreviewed HTML sink."""
    sinks = [
        path
        for path in (V2_SRC / "components").rglob("*.tsx")
        if "dangerouslySetInnerHTML" in _read(path)
    ]
    names = sorted(path.name for path in sinks)
    assert names == ["MathBlock.tsx", "MermaidDiagram.tsx"], (
        f"unexpected HTML sink(s): {names}. The full-screen viewer deliberately lives inside "
        "MermaidDiagram.tsx so every place diagram markup reaches the DOM stays in one file "
        "that test_v2_rich_rendering.py reviews."
    )

    assert "purify.sanitize(" in _read(MERMAID_TSX), "the boundary itself must still be there"
    assert "dangerouslySetInnerHTML" not in _read(STAGE_TSX), (
        "DiagramStage owns sizing only; markup must not reach the DOM through it"
    )
    print("  ok  diagram markup still reaches the DOM in exactly one reviewed file")


def test_no_new_browser_dependency_was_introduced():
    """Nothing here may reach the public Internet or add a package."""
    package = _read(REPO_ROOT / "application" / "v2_ui" / "package.json")
    for banned in ("mermaid", "dompurify", "react-zoom", "panzoom", "re-resizable"):
        assert f'"{banned}"' not in package, f"{banned} must not become an npm dependency"

    for path in (MERMAID_TSX, STAGE_TSX, SOURCE_TS):
        text = _read(path)
        urls = re.findall(r"https?://[^\s'\"`)]+", text)
        unexpected = [
            url
            for url in urls
            if url not in ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink")
        ]
        assert not unexpected, f"{path.name} references {unexpected}"
    print("  ok  no new browser dependency and no remote asset")


def test_the_prompt_guidance_warns_about_what_actually_breaks():
    """Guidance covers the failures reproduced against mermaid, not invented ones."""
    from functions_diagram_operations import build_diagram_guidance_message

    guidance = build_diagram_guidance_message()

    assert "reserved words" in guidance, (
        "`end` as a node id is the single most common parse failure in model output"
    )
    for word in ("`end`", "`graph`", "`class`", "`style`"):
        assert word in guidance, f"{word} is reserved and must be named"
    assert "lowercase `end`" in guidance, "`End` and `END` are not accepted by the grammar"
    assert "<random GUID>" in guidance, (
        "carrying angle-bracketed placeholders out of pasted text into labels is what produced "
        "the reported failures"
    )
    assert "short phrase" in guidance, (
        "one node holding a dozen <br/> lines renders as a column of text nobody can read"
    )
    print("  ok  the guidance warns about the failures that were actually reproduced")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    ui_dir = REPO_ROOT / "application" / "v2_ui"
    check = Path(__file__).with_name("test_v2_diagram_viewer_logic.ts")

    assert check.exists(), "the logic check file is missing"

    if not (ui_dir / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    # The check file lives in functional_tests/, which has no node_modules of its own, so bare
    # imports are left for node to resolve at run time from where the bundle is written.
    bundle = ui_dir / "node_modules" / ".cache-diagram-viewer-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(check),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(ui_dir),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(ui_dir),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed > 45, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_the_panel_takes_its_width_from_the_diagram,
    test_a_long_diagram_cannot_fill_the_thread,
    test_the_render_failure_is_reported_rather_than_swallowed,
    test_rendering_is_bounded,
    test_the_repair_only_runs_after_a_failure,
    test_labels_wrap_at_a_readable_width,
    test_the_diagram_can_be_enlarged,
    test_the_chosen_height_is_kept_on_the_message,
    test_a_stored_height_is_bounded_and_validated,
    test_a_height_is_not_carried_across_a_source_change,
    test_an_absent_height_is_not_a_cleared_height,
    test_a_height_only_entry_does_not_shadow_the_reader_default,
    test_the_thread_does_not_re_render_on_every_scroll,
    test_the_sanitizer_boundary_is_still_a_single_reviewed_file,
    test_no_new_browser_dependency_was_introduced,
    test_the_prompt_guidance_warns_about_what_actually_breaks,
    test_the_typescript_logic_checks_pass,
]


def main():
    print("Testing the V2 diagram viewer...\n")
    failures = []

    for test in TESTS:
        try:
            test()
        except Exception as error:  # noqa: BLE001
            failures.append((test.__name__, error))
            print(f"  FAIL  {test.__name__}: {error}")

    print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} checks passed")
    if failures:
        import traceback

        for name, error in failures:
            print(f"\n--- {name} ---")
            traceback.print_exception(type(error), error, error.__traceback__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
