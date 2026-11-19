#!/usr/bin/env python3
"""
Functional test for V2 UI local browser asset compliance.

Version: 0.261.458
Implemented in: 0.261.003

This test ensures the compiled V2 bundle loads no browser runtime code from the public
Internet, as required by .github/instructions/local_browser_assets.instructions.md. All
JavaScript, CSS and fonts must be bundled locally and served from the SimpleChat app so
the Content-Security-Policy can stay at default-src 'self'.

It also verifies the SPA source declares no CDN dependency, so a violation is caught even
in a checkout where the bundle has not been compiled.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SOURCE_DIR = REPO_ROOT / "application" / "v2_ui"
V2_BUILD_DIR = REPO_ROOT / "application" / "single_app" / "static" / "v2"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_browser_assets import check_text, scan

# Matches src/href/url()/import() targets pointing at an absolute external URL.
EXTERNAL_ASSET_REFERENCE_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']https?://|url\(\s*["']?https?://|import\(\s*["']https?://""",
    re.IGNORECASE,
)


def _iter_build_assets():
    """Yield the compiled files whose contents reach the browser."""
    if not V2_BUILD_DIR.is_dir():
        return

    for path in V2_BUILD_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".html", ".js", ".css"}:
            yield path


def test_built_bundle_has_no_cdn_hosts():
    """No compiled asset references a known public CDN host."""
    print("Testing compiled bundle for CDN references...")

    assets = list(_iter_build_assets())
    if not assets:
        print(
            "  Bundle not compiled in this checkout; skipping. "
            "Run 'npm run build' in application/v2_ui to include this check."
        )
        return True

    violations = [
        str(finding)
        for path in assets
        for finding in check_text(path, path.read_text(encoding="utf-8"))
    ]

    assert violations == [], "CDN references found in the compiled V2 bundle:\n  " + "\n  ".join(
        violations
    )

    print(f"  Checked {len(assets)} compiled asset(s); no CDN hosts found.")
    print("Compiled bundle CDN test passed!")
    return True


def test_bundle_html_loads_only_local_assets():
    """The SPA shell references only same-origin assets."""
    print("Testing SPA shell asset references...")

    index_path = V2_BUILD_DIR / "index.html"
    if not index_path.is_file():
        print("  Bundle not compiled in this checkout; skipping.")
        return True

    html = index_path.read_text(encoding="utf-8")
    external = EXTERNAL_ASSET_REFERENCE_RE.findall(html)

    assert external == [], (
        f"The V2 SPA shell must reference only local assets, found: {external}"
    )

    # Every emitted asset URL must sit under the Flask static path so the built-in static
    # handler serves it and the CSP's 'self' source covers it.
    asset_urls = re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']', html)
    for url in asset_urls:
        if url.startswith("data:") or url.startswith("#"):
            continue
        assert url.startswith("/static/"), (
            f"SPA shell asset {url!r} must be served from /static/ so the CSP allows it"
        )

    print(f"  Verified {len(asset_urls)} shell asset reference(s) are local.")
    print("SPA shell asset test passed!")
    return True


def test_source_declares_no_cdn_dependency():
    """The SPA source contains no CDN URL, so violations are caught pre-build."""
    print("Testing V2 source for CDN references...")

    assert (V2_SOURCE_DIR / "src").is_dir(), f"No V2 source found under {V2_SOURCE_DIR}"
    violations = [
        str(finding)
        for finding in scan(paths=[V2_SOURCE_DIR.relative_to(REPO_ROOT)])
    ]

    assert violations == [], "CDN references found in V2 source:\n  " + "\n  ".join(violations)

    print("  Checked V2 source and vendor assets; no external asset loaders found.")
    print("V2 source CDN test passed!")
    return True


def test_build_output_is_not_committed():
    """The compiled bundle is gitignored, so build artefacts never enter version control."""
    print("Testing build output is gitignored...")

    gitignore = REPO_ROOT / "application" / "single_app" / ".gitignore"
    assert gitignore.is_file(), "application/single_app/.gitignore is missing"

    content = gitignore.read_text(encoding="utf-8")
    assert "static/v2/" in content, (
        "application/single_app/.gitignore must ignore static/v2/ so the compiled "
        "V2 bundle is not committed"
    )

    print("Build output gitignore test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_built_bundle_has_no_cdn_hosts,
        test_bundle_html_loads_only_local_assets,
        test_source_declares_no_cdn_dependency,
        test_build_output_is_not_committed,
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
