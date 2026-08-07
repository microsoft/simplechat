# test_admin_tabular_run_controls.py
"""
UI test for Admin Settings tabular run controls.
Version: 0.250.131
Implemented in: 0.250.131

This test ensures admins can configure large tabular run confirmation and
chunk-processing model settings from the Admin Settings template.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"


def test_admin_tabular_run_controls_render_from_template():
    """Validate Phase 5 tabular run controls are present in Admin Settings."""
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")

    required_ids = [
        "enable_tabular_durable_run_confirmation",
        "tabular_durable_run_confirmation_threshold_rows",
        "tabular_durable_run_confirmation_threshold_batches",
        "tabular_generated_output_chunk_model_mode",
        "tabular_generated_output_chunk_model_deployment",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in template
        assert f'name="{element_id}"' in template

    assert "Large Tabular Run Controls" in template
    assert "Use the user's selected model" in template
    assert "Use a configured deployment for chunk work" in template