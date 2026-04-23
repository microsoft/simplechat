# test_simplechat_admin_action_save_fix.py
"""
Functional test for SimpleChat admin action save fix.
Version: 0.241.066
Implemented in: 0.241.065

This test ensures the admin action modal summary path defines the SimpleChat
auth-type check correctly and the admin save route normalizes blank built-in
endpoints before manifest health validation runs.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_simplechat_admin_action_save_fix_contracts():
    plugin_modal_source = read_text("application/single_app/static/js/plugin_modal_stepper.js")
    backend_plugins_source = read_text("application/single_app/route_backend_plugins.py")
    config_source = read_text("application/single_app/config.py")

    assert 'VERSION = "0.241.066"' in config_source
    assert "const isSimpleChatType = this.isSimpleChatType();" in plugin_modal_source
    assert "new_plugin = apply_plugin_validation_defaults(new_plugin)" in backend_plugins_source
    assert "updated_plugin = apply_plugin_validation_defaults(updated_plugin)" in backend_plugins_source
    assert "if not str(plugin_payload.get('endpoint') or '').strip():" in backend_plugins_source
    assert "plugin_payload['endpoint'] = SIMPLECHAT_DEFAULT_ENDPOINT" in backend_plugins_source


if __name__ == "__main__":
    test_simplechat_admin_action_save_fix_contracts()
    print("SimpleChat admin action save fix checks passed.")