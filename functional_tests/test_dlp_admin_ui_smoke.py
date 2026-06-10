# test_dlp_admin_ui_smoke.py
#!/usr/bin/env python3
"""
Functional test for DLP admin UI smoke.
Version: 0.242.069
Implemented in: 0.242.069

This test ensures the DLP admin settings card can be extracted into collapsed
and expanded previews for local visual review.
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE_FILE = ROOT_DIR / "application" / "single_app" / "templates" / "admin_settings.html"
PREVIEW_SCRIPT = ROOT_DIR / "tools" / "local_dev" / "render_dlp_admin_preview.py"


REQUIRED_CONTROLS = [
    "enable_dlp_control_plane",
    "dlp_default_engine",
    "dlp_regex_rules_json",
    "dlp_max_scan_chars",
    "enable_web_search_dlp",
    "web_search_dlp_mode",
    "enable_upload_dlp",
    "upload_dlp_mode",
    "upload_dlp_fail_upload_on_match",
]


RETIRED_CONTROLS = [
    "dlp_scanner_timeout_seconds",
    "web_search_dlp_redact_structured_identifiers",
    "web_search_dlp_block_on_internal_phrases",
    "upload_dlp_track_review_events",
]


def load_preview_module():
    spec = importlib.util.spec_from_file_location("render_dlp_admin_preview", PREVIEW_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dlp_admin_preview_extractor_writes_collapsed_and_expanded_files():
    """Preview extraction should work against the real admin settings template."""
    print("Testing DLP admin preview extraction...")
    module = load_preview_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        collapsed_path, expanded_path = module.render_previews(ADMIN_TEMPLATE_FILE, Path(temp_dir))

        assert collapsed_path.exists()
        assert expanded_path.exists()
        assert collapsed_path.name == "admin-dlp-preview.html"
        assert expanded_path.name == "admin-dlp-preview-expanded.html"

        collapsed_html = collapsed_path.read_text(encoding="utf-8")
        expanded_html = expanded_path.read_text(encoding="utf-8")

    assert "Data Loss Prevention" in collapsed_html
    assert "Data Loss Prevention" in expanded_html
    assert 'id="dlp_control_plane_settings"' in collapsed_html
    assert 'id="dlp_control_plane_settings"' in expanded_html


def test_expanded_dlp_admin_preview_contains_expected_controls():
    """Expanded preview should expose all DLP controls needed for review."""
    print("Testing expanded DLP admin preview controls...")
    module = load_preview_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        _, expanded_path = module.render_previews(ADMIN_TEMPLATE_FILE, Path(temp_dir))
        expanded_html = expanded_path.read_text(encoding="utf-8")

    for control_id in REQUIRED_CONTROLS:
        assert (
            f'id="{control_id}"' in expanded_html or f'name="{control_id}"' in expanded_html
        ), f"Missing expanded DLP control: {control_id}"

    for control_id in RETIRED_CONTROLS:
        assert (
            f'id="{control_id}"' not in expanded_html and f'name="{control_id}"' not in expanded_html
        ), f"Retired DLP control still rendered: {control_id}"

    assert '<div class="d-none" id="dlp_control_plane_settings">' not in expanded_html
    assert '<div class="d-none" id="web_search_dlp_mode_settings">' not in expanded_html
    assert '<div class="d-none" id="upload_dlp_mode_settings">' not in expanded_html


def test_dlp_admin_preview_does_not_expose_raw_secret_values():
    """Preview files should include controls, not populated secrets or raw detector matches."""
    print("Testing DLP admin preview safety...")
    module = load_preview_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        collapsed_path, expanded_path = module.render_previews(ADMIN_TEMPLATE_FILE, Path(temp_dir))
        rendered = (
            collapsed_path.read_text(encoding="utf-8")
            + expanded_path.read_text(encoding="utf-8")
        )

    forbidden = [
        "123-45-6789",
        "4111 1111 1111 1111",
        "raw_matches",
    ]
    for value in forbidden:
        assert value not in rendered, f"Preview leaked forbidden value: {value}"


if __name__ == "__main__":
    tests = [
        test_dlp_admin_preview_extractor_writes_collapsed_and_expanded_files,
        test_expanded_dlp_admin_preview_contains_expected_controls,
        test_dlp_admin_preview_does_not_expose_raw_secret_values,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} DLP admin UI smoke tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
