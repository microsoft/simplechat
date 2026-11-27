# test_admin_settings_nonblocking_runtime_probe.py
"""
Functional regression for non-blocking V2 and classic admin settings runtime readouts.
Version: 0.261.463
Implemented in: 0.261.463

This test ensures the admin settings GET uses cached or path-only capability
inspection and never launches Chromium or FFmpeg subprocesses from the request.
"""

from pathlib import Path


V2_ROUTE = (
    Path(__file__).resolve().parents[1]
    / "application"
    / "single_app"
    / "route_backend_v2.py"
)
CLASSIC_ROUTE = V2_ROUTE.with_name("route_frontend_admin_settings.py")


def test_admin_settings_route_does_not_launch_runtime_probes():
    source = V2_ROUTE.read_text(encoding="utf-8")
    build_status_start = source.index("def _build_status_readouts():")
    build_status_end = source.index("def _build_appinsights_connection_readout():")
    status_block = source[build_status_start:build_status_end]

    assert "get_source_review_runtime_capabilities()" not in status_block
    assert "get_audio_runtime_capabilities()" not in status_block
    assert "peek_source_review_runtime_capabilities()" in status_block
    assert "peek_audio_runtime_capabilities()" in status_block


def test_classic_admin_get_does_not_launch_runtime_probes():
    source = CLASSIC_ROUTE.read_text(encoding="utf-8")
    get_start = source.index("if request.method == 'GET':")
    get_end = source.index("if request.method == 'POST':")
    get_block = source[get_start:get_end]

    assert "get_source_review_runtime_capabilities()" not in get_block
    assert "get_audio_runtime_capabilities()" not in get_block
    assert "peek_source_review_runtime_capabilities()" in get_block
    assert "peek_audio_runtime_capabilities()" in get_block
    assert "normalize_source_review_js_rendering_enabled(" not in get_block

    template_source = (
        V2_ROUTE.parents[0]
        / "templates"
        / "admin"
        / "_panes"
        / "web-research.html"
    ).read_text(encoding="utf-8")
    assert "not js_runtime.runtime_verified" in template_source
