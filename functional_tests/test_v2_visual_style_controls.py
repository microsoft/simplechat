#!/usr/bin/env python3
"""
Functional test for V2 diagram and chart colour controls, and mermaid PNG download.

Version: 0.261.033
Implemented in: 0.261.033

The V2 chat could render mermaid diagrams and SimpleChart charts, but a diagram could not be
saved as an image and neither could be recoloured. This covers the feature that fixed both:

  - A PNG download on every rendered diagram, rasterized from the SVG already on screen so the
    file matches what the reader is looking at.
  - Palette presets, per-series colours and a background colour for both block kinds, resolved
    from the built-in default, then the reader's own default, then an override saved against
    one block of one message.

The behaviour that matters most is negative: a block nobody has touched must render exactly as
it did before. The rest of what is asserted here is the security boundary. Colours end up in
inline style attributes and in mermaid's theme configuration in a browser, so the server stores
nothing that is not a plain ``#rrggbb`` value, and the stored map is bounded so a message
document cannot be grown by repeated requests.
"""

import json
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
    MAX_SERIES_COLOR_OVERRIDES,
    MAX_STORED_ENTRIES,
    THEME_BACKGROUND,
    VISUAL_STYLE_KINDS,
    VISUAL_STYLE_PALETTES,
    VISUAL_STYLES_METADATA_KEY,
    VisualStyleError,
    apply_visual_style,
    normalize_hex_color,
    read_visual_styles,
    sanitize_visual_style,
)

IMPLEMENTED_IN = "0.261.033"


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def test_version_is_at_least_the_implementing_release():
    """The feature is present from the version it was implemented in onwards."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  application version is at or beyond the implementing release")


def test_only_hex_colours_are_stored():
    """A colour is reduced to `#rrggbb`, or it is not stored at all."""
    assert normalize_hex_color("#ABCDEF") == "#abcdef"
    assert normalize_hex_color("  #123456  ") == "#123456"

    # Every one of these is a valid CSS colour that the browser would happily apply. None is
    # stored, because a single accepted form is what makes the stored value safe to write into
    # a style attribute without further thought.
    for rejected in (
        "red",
        "#abc",
        "rgb(1,2,3)",
        "rgba(1,2,3,0.5)",
        "url(https://example.invalid/x)",
        "expression(alert(1))",
        "#12345",
        "#1234567",
        "",
        None,
        123,
        ["#ffffff"],
    ):
        assert normalize_hex_color(rejected) is None, rejected

    print("  ok  only #rrggbb colours are accepted")


def test_style_sanitisation_drops_everything_unrecognised():
    """A style keeps its palette, background and colours, and nothing else."""
    sanitized = sanitize_visual_style(
        {
            "palette": "vivid",
            "background": "#FFEEDD",
            "colors": {"0": "#123456", "2": "#abcdef"},
            "onclick": "alert(1)",
            "source_hash": "attacker-supplied",
        }
    )

    assert sanitized == {
        "palette": "vivid",
        "background": "#ffeedd",
        "colors": {"0": "#123456", "2": "#abcdef"},
    }, sanitized

    # An unknown palette is refused rather than quietly replaced. The client falls back to a
    # default when it reads a stored value it does not recognise, because it has to draw
    # something; a request is different, and storing a palette nobody asked for would be worse
    # than saying no.
    try:
        sanitize_visual_style({"palette": "../../etc/passwd"})
        raise AssertionError("accepted an unknown palette")
    except VisualStyleError:
        pass

    assert sanitize_visual_style({})["palette"] == "default"
    assert sanitize_visual_style({})["background"] == THEME_BACKGROUND

    for palette in VISUAL_STYLE_PALETTES:
        assert sanitize_visual_style({"palette": palette})["palette"] == palette

    print("  ok  unrecognised style fields are dropped")


def test_style_sanitisation_rejects_malformed_input():
    """Anything that is not a style is refused rather than coerced into one."""
    for rejected in (None, "vivid", 5, ["vivid"]):
        try:
            sanitize_visual_style(rejected)
        except VisualStyleError:
            continue
        raise AssertionError(f"accepted a non-style value: {rejected!r}")

    for rejected in (
        {"background": "javascript:alert(1)"},
        {"colors": ["#ffffff"]},
        {"colors": {"0": "red"}},
        {"colors": {"nope": "#ffffff"}},
        {"colors": {"-1": "#ffffff"}},
        {"colors": {str(MAX_SERIES_COLOR_OVERRIDES): "#ffffff"}},
    ):
        try:
            sanitize_visual_style(rejected)
        except VisualStyleError:
            continue
        raise AssertionError(f"accepted malformed style: {rejected!r}")

    too_many = {"colors": {str(i): "#ffffff" for i in range(MAX_SERIES_COLOR_OVERRIDES + 1)}}
    try:
        sanitize_visual_style(too_many)
        raise AssertionError("accepted an unbounded colour map")
    except VisualStyleError:
        pass

    print("  ok  malformed styles are rejected")


def test_one_block_is_styled_without_disturbing_the_others():
    """Recolouring one chart leaves every other block in the message alone."""
    message = {"id": "m1", "metadata": {}}

    apply_visual_style(
        message,
        "simplechart",
        0,
        {"palette": "vivid", "background": "#ffffff", "colors": {}},
        source_hash="aaaa1111",
    )
    apply_visual_style(
        message,
        "mermaid",
        1,
        {"palette": "warm", "background": THEME_BACKGROUND, "colors": {}},
        source_hash="bbbb2222",
    )

    stored = read_visual_styles(message)
    assert set(stored) == {"simplechart", "mermaid"}, stored
    assert stored["simplechart"]["0"]["palette"] == "vivid"
    assert stored["mermaid"]["1"]["palette"] == "warm"

    # The block that was not addressed has no entry at all, so it follows the reader's own
    # default rather than inheriting its neighbour's colours.
    assert "1" not in stored["simplechart"], stored["simplechart"]
    assert "0" not in stored["mermaid"], stored["mermaid"]

    print("  ok  styling one block leaves the others untouched")


def test_a_style_can_be_removed_and_the_metadata_key_disappears():
    """Clearing the last style removes the key rather than leaving an empty map behind."""
    message = {"id": "m1", "metadata": {}}
    apply_visual_style(message, "mermaid", 0, {"palette": "calm"}, source_hash="cccc3333")
    assert VISUAL_STYLES_METADATA_KEY in message["metadata"]

    result = apply_visual_style(message, "mermaid", 0, None)
    assert result == {}, result
    assert VISUAL_STYLES_METADATA_KEY not in message["metadata"], message["metadata"]

    print("  ok  clearing a style removes the stored entry")


def test_the_source_fingerprint_is_stored_with_the_style():
    """A style records what the block looked like, so it is not reused for other content."""
    message = {"id": "m1", "metadata": {}}
    apply_visual_style(message, "mermaid", 0, {"palette": "calm"}, source_hash="deadbeef")

    entry = read_visual_styles(message)["mermaid"]["0"]
    assert entry["source_hash"] == "deadbeef", entry

    for rejected in ("../../etc", "has space", "x" * 65, {"a": 1}):
        try:
            apply_visual_style(message, "mermaid", 0, {"palette": "calm"}, source_hash=rejected)
        except VisualStyleError:
            continue
        raise AssertionError(f"accepted a malformed fingerprint: {rejected!r}")

    print("  ok  the source fingerprint is stored and validated")


def test_stored_entries_are_bounded():
    """Neither the block index nor the number of entries can grow without limit."""
    message = {"id": "m1", "metadata": {}}

    for rejected in (-1, 200, "0", True, 1.5, None):
        try:
            apply_visual_style(message, "mermaid", rejected, {"palette": "calm"})
        except VisualStyleError:
            continue
        raise AssertionError(f"accepted an out-of-range block index: {rejected!r}")

    try:
        apply_visual_style(message, "not-a-kind", 0, {"palette": "calm"})
        raise AssertionError("accepted an unsupported block kind")
    except VisualStyleError:
        pass

    filled = {"id": "m2", "metadata": {}}
    for index in range(MAX_STORED_ENTRIES):
        apply_visual_style(filled, "mermaid", index, {"palette": "calm"})

    try:
        apply_visual_style(filled, "simplechart", 0, {"palette": "calm"})
        raise AssertionError("stored more entries than the cap allows")
    except VisualStyleError:
        pass

    # Replacing an entry that already exists is not adding one, so it stays possible at the cap.
    apply_visual_style(filled, "mermaid", 0, {"palette": "vivid"})
    assert read_visual_styles(filled)["mermaid"]["0"]["palette"] == "vivid"

    print("  ok  stored entries are bounded")


def test_corrupt_stored_metadata_is_ignored():
    """A message whose stored map is not a map renders with defaults instead of failing."""
    for corrupt in ("nonsense", 5, ["mermaid"], {"mermaid": "nonsense"}, {"evil": {"0": {}}}):
        message = {"id": "m1", "metadata": {VISUAL_STYLES_METADATA_KEY: corrupt}}
        assert read_visual_styles(message) in ({}, {"mermaid": {}}), corrupt

    assert read_visual_styles({"id": "m1"}) == {}
    print("  ok  unreadable stored metadata is ignored")


def test_the_route_is_registered_with_the_standard_protections():
    """The endpoint carries the decorators every route in this project must have."""
    source = _read(APP_DIR / "route_backend_chats.py")

    assert "'/api/message/<message_id>/visual-style'" in source

    start = source.index("'/api/message/<message_id>/visual-style'")
    block = source[start : start + 2600]
    for decorator in (
        "@swagger_route(security=get_auth_security())",
        "@login_required",
        "@user_required",
    ):
        assert decorator in block, f"missing {decorator}"

    # The conversation is authorized rather than the message: a diagram lives in an assistant
    # message, which has no author of its own to compare against.
    assert "_authorize_personal_conversation_access" in block
    assert "PermissionError" in block

    print("  ok  the endpoint is authenticated and authorized")


def test_the_user_default_keys_are_allowlisted_and_validated():
    """The two preference keys are accepted, and sanitised rather than stored as sent."""
    source = _read(APP_DIR / "route_backend_users.py")

    for key in ("v2MermaidStyle", "v2ChartStyle"):
        assert f"'{key}'" in source, key

    assert "sanitize_visual_style" in source
    assert "VisualStyleError" in source

    print("  ok  user default keys are allowlisted and sanitised")


def test_the_client_keeps_its_sanitiser_boundaries():
    """Rendering untrusted output still passes through the guarantees it always had."""
    mermaid = _read(V2_SRC / "components" / "chat" / "MermaidDiagram.tsx")

    assert "securityLevel: 'strict'" in mermaid
    assert "purify.sanitize(svg)" in mermaid
    assert "bindFunctions" not in mermaid.split("export function MermaidDiagram")[1]

    # htmlLabels must stay off. It is a security property, and it is also the only reason the
    # PNG has any text in it: a <foreignObject> label disappears when an SVG is painted onto a
    # canvas.
    assert "htmlLabels: false" in mermaid

    # Theme variables are only ever the sanitised palette output.
    assert "mermaidThemeVariables(style, background)" in mermaid

    print("  ok  the diagram renderer keeps its sanitiser boundaries")


def test_the_diagram_offers_a_png_download():
    """A rendered diagram can be saved, from the SVG on screen rather than a re-render."""
    mermaid = _read(V2_SRC / "components" / "chat" / "MermaidDiagram.tsx")
    raster = _read(V2_SRC / "lib" / "svgRaster.ts")

    assert "svgElementToPngDataUri" in mermaid
    assert "containerRef.current?.querySelector('svg')" in mermaid
    assert "downloadDataUri" in mermaid

    # An opaque fill first, or dark diagram text is invisible wherever the PNG is pasted.
    assert "context.fillStyle = background" in raster
    assert "context.fillRect(0, 0, canvas.width, canvas.height)" in raster
    assert "toDataURL('image/png')" in raster

    # Explicit dimensions, or an <img> given mermaid's width="100%" has nothing to rasterize at.
    assert "clone.setAttribute('width'" in raster
    assert "viewBox" in raster

    print("  ok  a diagram can be downloaded as a PNG")


def test_no_new_browser_dependency_was_introduced():
    """The feature adds no npm package and no asset fetched from the internet."""
    package_json = json.loads(_read(REPO_ROOT / "application" / "v2_ui" / "package.json"))
    declared = set(package_json.get("dependencies", {})) | set(
        package_json.get("devDependencies", {})
    )

    # Each of these is the obvious way to build one part of this feature, and each would move
    # browser code back out of this repository.
    for forbidden in (
        "html-to-image",
        "dom-to-image",
        "canvg",
        "save-svg-as-png",
        "file-saver",
        "react-colorful",
        "react-color",
        "chroma-js",
        "color",
        "tinycolor2",
        "mermaid",
        "chart.js",
        "dompurify",
    ):
        assert forbidden not in declared, f"{forbidden} was added as a dependency"

    # The new browser code must not reach the network. The only permitted absolute URL is the
    # SVG namespace, which is an identifier rather than something that is fetched.
    for path in (
        V2_SRC / "lib" / "visualPalettes.ts",
        V2_SRC / "lib" / "svgRaster.ts",
        V2_SRC / "lib" / "blockVisualStyle.ts",
        V2_SRC / "components" / "chat" / "VisualStyleMenu.tsx",
    ):
        text = _read(path)
        urls = re.findall(r"https?://[^\s'\"`)]+", text)
        unexpected = [
            url
            for url in urls
            if url not in ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink")
        ]
        assert not unexpected, f"{path.name} references {unexpected}"

    print("  ok  no new browser dependency was introduced")


def test_the_content_security_policy_is_unchanged():
    """Rasterizing needs a data: image source, which the policy already permits."""
    config = _read(APP_DIR / "config.py")
    assert "img-src 'self' data: https: blob:;" in config
    print("  ok  the Content-Security-Policy already allows data: images")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    ui_dir = REPO_ROOT / "application" / "v2_ui"
    check = Path(__file__).with_suffix(".ts").with_name("test_v2_visual_style_logic.ts")

    assert check.exists(), "the logic check file is missing"

    if not (ui_dir / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm install in application/v2_ui")
        return

    # The check file lives in functional_tests/, which has no node_modules of its own, so bare
    # imports are left for node to resolve at run time from where the bundle is written.
    bundle = ui_dir / "node_modules" / ".cache-visual-style-check.mjs"
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
    assert passed > 40, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_only_hex_colours_are_stored,
    test_style_sanitisation_drops_everything_unrecognised,
    test_style_sanitisation_rejects_malformed_input,
    test_one_block_is_styled_without_disturbing_the_others,
    test_a_style_can_be_removed_and_the_metadata_key_disappears,
    test_the_source_fingerprint_is_stored_with_the_style,
    test_stored_entries_are_bounded,
    test_corrupt_stored_metadata_is_ignored,
    test_the_route_is_registered_with_the_standard_protections,
    test_the_user_default_keys_are_allowlisted_and_validated,
    test_the_client_keeps_its_sanitiser_boundaries,
    test_the_diagram_offers_a_png_download,
    test_no_new_browser_dependency_was_introduced,
    test_the_content_security_policy_is_unchanged,
    test_the_typescript_logic_checks_pass,
]


def main():
    print("Testing V2 diagram and chart colour controls...\n")
    failures = []

    for test in TESTS:
        try:
            test()
        except Exception as error:  # noqa: BLE001 - a failure must not stop the rest
            failures.append(test.__name__)
            print(f"FAIL  {test.__name__}: {error}")
            import traceback

            traceback.print_exc()

    print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} tests passed")
    if failures:
        print("Failed: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
