#!/usr/bin/env python3
"""
Functional test for V2 TeX, Mermaid and SimpleChart rendering.

Version: 0.261.024
Implemented in: 0.261.024

Three kinds of block the application already produces were shown in the V2 chat as raw
text:

  - TeX, which models emit as \\(...\\), \\[...\\] and $$...$$.
  - Mermaid, which functions_content_understanding.py writes into extracted document text
    as ```mermaid fences, so it has been reaching the chat all along.
  - SimpleChart, which the built-in chart action emits as ```simplechart fences and the
    classic client renders via static/js/chat/chat-inline-charts.js.

This test ensures those three render, and -- more importantly -- that they render from
third-party code that is committed to this repository rather than fetched from a package
registry at build time or a CDN at run time. Vendoring pins the bytes the browser executes,
which is what makes a supply chain attack on any of these libraries a reviewable change
here rather than a silent one.

It also ensures the guarantees that make rendering untrusted model output safe are still in
place: a sanitizer boundary at every HTML sink, KaTeX's trust option off, mermaid's strict
security level on, and the Content-Security-Policy unchanged.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
VENDOR_DIR = V2_DIR / "public" / "vendor"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.024"

# Every vendored library, the file that must be present, and the marker proving the file is
# the library it claims to be rather than an empty or truncated download.
VENDORED_LIBRARIES = {
    "katex-0.18.4": {
        "files": ["katex.min.js", "katex.min.css", "LICENSE"],
        "marker": ("katex.min.js", "katex"),
        "min_bytes": 200_000,
    },
    "mermaid-11.17.2": {
        "files": ["mermaid.min.js", "LICENSE"],
        "marker": ("mermaid.min.js", "mermaid"),
        "min_bytes": 1_000_000,
    },
    "chartjs-4.5.1": {
        "files": ["chart.umd.min.js", "LICENSE.md"],
        "marker": ("chart.umd.min.js", "Chart.js"),
        "min_bytes": 100_000,
    },
    "dompurify-3.4.14": {
        "files": ["purify.min.js", "LICENSE"],
        "marker": ("purify.min.js", "DOMPurify"),
        "min_bytes": 10_000,
    },
}

# npm packages that would move this browser code back out of the repository. Each is the
# obvious way to add the corresponding capability, and each is deliberately not used.
FORBIDDEN_NPM_DEPENDENCIES = (
    "katex",
    "mermaid",
    "chart.js",
    "chartjs",
    "react-chartjs-2",
    "dompurify",
    "remark-math",
    "rehype-katex",
    "@types/katex",
)


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def test_libraries_are_vendored_into_the_repository():
    """Each browser library is committed here, with its licence, pinned by directory name."""
    print("Testing vendored browser libraries...")

    assert VENDOR_DIR.is_dir(), f"Vendored library directory is missing: {VENDOR_DIR}"

    for directory, spec in VENDORED_LIBRARIES.items():
        library_dir = VENDOR_DIR / directory
        assert library_dir.is_dir(), (
            f"{directory} is not vendored. Browser libraries must be committed under "
            f"{VENDOR_DIR.relative_to(REPO_ROOT)} so the executed bytes are pinned."
        )

        for name in spec["files"]:
            path = library_dir / name
            assert path.is_file(), f"{directory}/{name} is missing"
            assert path.stat().st_size > 0, f"{directory}/{name} is empty"

        marker_file, marker_text = spec["marker"]
        content = _read(library_dir / marker_file)
        assert marker_text.lower() in content.lower(), (
            f"{directory}/{marker_file} does not look like {marker_text}; "
            "the vendored file may be truncated or wrong"
        )
        assert (library_dir / marker_file).stat().st_size >= spec["min_bytes"], (
            f"{directory}/{marker_file} is smaller than expected for a complete build"
        )

        # The version must be recoverable from the path, so an upgrade is visible in review.
        assert re.search(r"\d+\.\d+", directory), (
            f"{directory} must pin its version in the directory name"
        )

    print(f"  {len(VENDORED_LIBRARIES)} vendored librarie(s) present, pinned and licensed.")
    print("Vendored library test passed!")
    return True


def test_katex_fonts_are_vendored():
    """KaTeX's fonts ship with it, so no glyph is fetched from outside the app."""
    print("Testing vendored KaTeX fonts...")

    fonts_dir = VENDOR_DIR / "katex-0.18.4" / "fonts"
    assert fonts_dir.is_dir(), "KaTeX fonts are not vendored"

    fonts = list(fonts_dir.iterdir())
    woff2 = [path for path in fonts if path.suffix == ".woff2"]
    assert len(woff2) >= 20, f"Expected the full KaTeX woff2 set, found {len(woff2)}"

    # The stylesheet is committed unmodified, so every format it names must be present too.
    stylesheet = _read(VENDOR_DIR / "katex-0.18.4" / "katex.min.css")
    referenced = set(re.findall(r"fonts/([\w.\-]+\.(?:woff2|woff|ttf))", stylesheet))
    available = {path.name for path in fonts}
    missing = sorted(referenced - available)
    assert not missing, (
        "katex.min.css references font files that were not vendored, which would make the "
        f"browser request them from outside the app: {missing[:5]}"
    )

    assert "http://" not in stylesheet and "https://" not in stylesheet, (
        "katex.min.css must not reference an absolute URL"
    )

    print(f"  {len(fonts)} font file(s) vendored; all {len(referenced)} references resolve.")
    print("KaTeX font test passed!")
    return True


def test_no_new_npm_dependencies():
    """None of these libraries is resolved from a package registry at build time."""
    print("Testing package.json for registry dependencies...")

    manifest = json.loads(_read(V2_DIR / "package.json"))
    declared = set(manifest.get("dependencies", {})) | set(manifest.get("devDependencies", {}))

    for package in FORBIDDEN_NPM_DEPENDENCIES:
        assert package not in declared, (
            f"{package!r} is declared in package.json. This library is vendored under "
            "public/vendor instead, so that the browser code is pinned in the repository "
            "rather than fetched from a registry at build time."
        )

    print(f"  {len(declared)} declared package(s); none of the vendored libraries among them.")
    print("Dependency test passed!")
    return True


def test_vendored_assets_are_loaded_from_local_paths():
    """The loader resolves every library to a path on the app's own origin."""
    print("Testing vendored asset loading...")

    source = _read(V2_SRC / "lib" / "vendorAssets.ts")

    for directory in VENDORED_LIBRARIES:
        assert f"vendor/{directory}/" in source, (
            f"vendorAssets.ts does not reference the vendored {directory} directory"
        )

    assert "import.meta.env.BASE_URL" in source, (
        "Vendored assets must resolve against the SPA's own base URL so they are served "
        "from the same origin as the bundle, including in the split-origin deployment"
    )
    assert "http://" not in source and "https://" not in source, (
        "vendorAssets.ts must not contain an absolute URL"
    )

    print("Vendored asset loading test passed!")
    return True


def test_sanitizer_boundary_at_every_html_sink():
    """Nothing derived from model output reaches the DOM without being sanitized."""
    print("Testing sanitizer boundaries...")

    sinks = {
        "MathBlock.tsx": V2_SRC / "components" / "chat" / "MathBlock.tsx",
        "MermaidDiagram.tsx": V2_SRC / "components" / "chat" / "MermaidDiagram.tsx",
    }

    for name, path in sinks.items():
        source = _read(path)
        assert "dangerouslySetInnerHTML" in source, f"{name} was expected to render markup"
        assert "purify.sanitize(" in source, (
            f"{name} writes markup to the DOM without a DOMPurify boundary"
        )

    # Any other component that reaches for the sink must be reviewed, so the set is fixed.
    for path in (V2_SRC / "components").rglob("*.tsx"):
        if "dangerouslySetInnerHTML" in _read(path):
            assert path.name in sinks, (
                f"{path.name} uses dangerouslySetInnerHTML but is not a reviewed sanitizer "
                "boundary. Model output must not reach the DOM as markup without one."
            )

    print(f"  {len(sinks)} reviewed sink(s); no others found.")
    print("Sanitizer boundary test passed!")
    return True


def test_katex_is_configured_for_untrusted_input():
    """KaTeX cannot emit links, load resources or expand without bound."""
    print("Testing KaTeX hardening...")

    source = _read(V2_SRC / "components" / "chat" / "MathBlock.tsx")

    assert "trust: false" in source, (
        "KaTeX must run with trust: false so \\href, \\url and \\includegraphics are "
        "disabled for model-authored expressions"
    )
    assert "throwOnError: false" in source, "Invalid TeX must not throw mid-render"
    assert "maxExpand" in source, "Macro expansion must be bounded"

    print("KaTeX hardening test passed!")
    return True


def test_mermaid_is_configured_for_untrusted_input():
    """Mermaid renders only on request, sanitizes strictly, and fetches nothing."""
    print("Testing Mermaid hardening...")

    source = _read(V2_SRC / "components" / "chat" / "MermaidDiagram.tsx")

    assert "securityLevel: 'strict'" in source, (
        "Mermaid must use securityLevel 'strict' for model-authored diagram source"
    )
    assert "startOnLoad: false" in source, "Mermaid must not scan and render the page itself"
    assert "htmlLabels: false" in source, "Diagram labels must stay SVG text, not HTML"
    assert "suppressErrorRendering: true" in source, (
        "Mermaid must not write its own error diagram into the page"
    )
    assert "bindFunctions" not in source.replace(
        "`bindFunctions` from the render result is deliberately never", ""
    ), "bindFunctions attaches mermaid's interaction handlers and must never be called"
    assert "registerIconPacks" not in source, (
        "Icon packs are fetched from the public Internet and must not be registered"
    )

    print("Mermaid hardening test passed!")
    return True


def test_single_dollar_is_not_treated_as_maths():
    """Prose about money survives, because a lone $ never opens an expression."""
    print("Testing TeX delimiter handling...")

    source = _read(V2_SRC / "lib" / "mathSegments.ts")

    # Only these three openers exist in the scanner.
    assert "'$' && input[index + 1] === '$'" in source, (
        "Double-dollar maths must require two dollar signs"
    )
    assert "next === '[' || next === '('" in source, (
        "Backslash-bracket and backslash-paren delimiters must be recognised, because "
        "CommonMark strips those backslashes before any remark plugin can see them"
    )

    # Fenced and inline code must be copied through untouched.
    assert "skipFencedBlock" in source, "Fenced code blocks must be skipped"
    assert "skipInlineCode" in source, "Inline code spans must be skipped"

    # Placeholders, not markup, matching how citations and masks already work.
    assert "MATH_PLACEHOLDER" in source, "Maths must be lifted out as an inert placeholder"
    assert "dangerouslySetInnerHTML" not in source, "The parser must not produce markup"

    print("TeX delimiter test passed!")
    return True


def test_rich_fences_are_wired_into_the_renderer():
    """Mermaid and chart fences render as blocks rather than as code."""
    print("Testing fence wiring...")

    source = _read(V2_SRC / "components" / "chat" / "AssistantMarkdown.tsx")

    assert "MERMAID_LANGUAGE" in source and "<MermaidDiagram" in source, (
        "```mermaid fences must render as a diagram"
    )
    assert "INLINE_CHART_LANGUAGE" in source and "<InlineChart" in source, (
        "```simplechart fences must render as a chart"
    )
    assert "isRichFence" in source, (
        "The <pre> wrapper must be dropped for fences that render as something else"
    )
    assert "markPendingFences" in source, (
        "An unterminated fence must be held back while a reply streams, or the renderer is "
        "handed half a diagram on every token"
    )
    # Checked as an import rather than a bare substring, because the file's own comment
    # explains why rehype-raw is absent.
    assert "from 'rehype-raw'" not in source, (
        "Raw HTML must stay disabled: react-markdown escaping HTML is what keeps untrusted "
        "model output safe here"
    )
    assert "rehypePlugins={[rehypeHighlightSubset]}" in source, (
        "The rehype pipeline must stay limited to the curated highlighter"
    )

    print("Fence wiring test passed!")
    return True


def test_chart_fence_language_matches_the_backend():
    """The client reads the fence language the chart action actually writes."""
    print("Testing chart fence language parity...")

    backend = _read(APP_DIR / "functions_chart_operations.py")
    backend_language = re.search(
        r"INLINE_CHART_BLOCK_LANGUAGE\s*=\s*'([^']+)'", backend
    )
    assert backend_language, "INLINE_CHART_BLOCK_LANGUAGE not found in the backend"

    client = _read(V2_SRC / "lib" / "inlineChartSpec.ts")
    client_language = re.search(r"INLINE_CHART_LANGUAGE\s*=\s*'([^']+)'", client)
    assert client_language, "INLINE_CHART_LANGUAGE not found in the V2 client"

    assert backend_language.group(1) == client_language.group(1), (
        f"Chart fence language mismatch: backend emits {backend_language.group(1)!r} but "
        f"the client looks for {client_language.group(1)!r}"
    )

    print(f"  Both use {backend_language.group(1)!r}.")
    print("Chart fence language test passed!")
    return True


def test_copied_chart_is_readable_text():
    """A copied message carries the chart's numbers, not its JSON payload."""
    print("Testing chart handling in copied text...")

    source = _read(V2_SRC / "lib" / "messageText.ts")

    assert "renderChartsAsText" in source, (
        "messageToPlainText must replace chart fences, or a copied message contains "
        "kilobytes of minified JSON"
    )
    assert "resolveChartTable" in source, "The chart's data should come through as a table"
    assert "INLINE_CHART_LANGUAGE" in source, (
        "The fence language must come from the shared constant, not be duplicated"
    )

    print("Copied chart test passed!")
    return True


def test_content_security_policy_is_unchanged():
    """Vendoring must not have needed the policy relaxed."""
    print("Testing Content-Security-Policy...")

    config = _read(APP_DIR / "config.py")
    policy = re.search(
        r"'Content-Security-Policy':\s*\((.*?)\)\s*\n\s*\}", config, re.DOTALL
    )
    assert policy, "Content-Security-Policy not found in config.py"

    policy_text = policy.group(1)
    for directive in ("default-src 'self'", "script-src 'self'", "font-src 'self'"):
        assert directive in policy_text, f"CSP must still contain {directive!r}"

    for host in ("cdn.", "unpkg", "jsdelivr", "cdnjs", "googleapis", "gstatic"):
        assert host not in policy_text, (
            f"CSP must not have been widened to allow {host!r}"
        )

    print("Content-Security-Policy test passed!")
    return True


def test_version_was_incremented():
    """The application version records when this shipped."""
    print("Testing version...")
    version = assert_app_version_at_least(
        IMPLEMENTED_IN,
        reason="V2 TeX, Mermaid and SimpleChart rendering.",
    )
    print(f"  config.py VERSION is {version}.")
    print("Version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_libraries_are_vendored_into_the_repository,
        test_katex_fonts_are_vendored,
        test_no_new_npm_dependencies,
        test_vendored_assets_are_loaded_from_local_paths,
        test_sanitizer_boundary_at_every_html_sink,
        test_katex_is_configured_for_untrusted_input,
        test_mermaid_is_configured_for_untrusted_input,
        test_single_dollar_is_not_treated_as_maths,
        test_rich_fences_are_wired_into_the_renderer,
        test_chart_fence_language_matches_the_backend,
        test_copied_chart_is_readable_text,
        test_content_security_policy_is_unchanged,
        test_version_was_incremented,
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
