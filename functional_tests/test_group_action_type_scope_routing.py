# test_group_action_type_scope_routing.py
#!/usr/bin/env python3
"""
Functional test for group action type scope routing.
Version: 0.250.061
Implemented in: 0.250.061

This test ensures the shared action modal uses the group-scoped action type
endpoint for group actions instead of applying personal action governance.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PLUGIN_MODAL_JS = ROOT_DIR / "application" / "single_app" / "static" / "js" / "plugin_modal_stepper.js"
PLUGIN_ROUTES = ROOT_DIR / "application" / "single_app" / "route_backend_plugins.py"


def test_group_action_type_endpoint_is_scope_specific():
    """Validate group action type discovery does not route through personal governance."""
    modal_source = PLUGIN_MODAL_JS.read_text(encoding="utf-8")
    route_source = PLUGIN_ROUTES.read_text(encoding="utf-8")

    assert "getActionTypesEndpoint()" in modal_source
    assert "scope === 'group'" in modal_source
    assert "return '/api/group/plugins/types';" in modal_source
    assert "return '/api/user/plugins/types';" in modal_source

    group_branch_index = modal_source.index("scope === 'group'")
    group_endpoint_index = modal_source.index("return '/api/group/plugins/types';")
    personal_endpoint_index = modal_source.index("return '/api/user/plugins/types';")
    assert group_branch_index < group_endpoint_index < personal_endpoint_index

    assert "@bpap.route('/api/group/plugins/types', methods=['GET'])" in route_source
    assert "def get_group_plugin_types():" in route_source
    assert "'governance_group_actions'" in route_source
    assert "'governance_user_actions'" in route_source

    group_route_index = route_source.index("def get_group_plugin_types():")
    admin_section_index = route_source.index("# === ADMIN PLUGINS ENDPOINTS ===", group_route_index)
    group_route_source = route_source[group_route_index:admin_section_index]
    assert "'governance_group_actions'" in group_route_source
    assert "'governance_user_actions'" not in group_route_source


if __name__ == "__main__":
    try:
        test_group_action_type_endpoint_is_scope_specific()
        success = True
    except Exception as ex:
        print(f"Group action type scope routing test failed: {ex}")
        import traceback

        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
