# Global Agent Action Disable Controls

Version: 0.241.076

Fixed/Implemented in version: **0.241.076**

Dependencies: `functions_global_actions.py`, `functions_global_agents.py`, `route_backend_plugins.py`, `route_backend_agents.py`, `static/js/admin/admin_plugins.js`, `static/js/admin/admin_agents.js`, `templates/admin_settings.html`

## Overview

This feature adds a reversible enabled-state for global actions and global agents.

Admins can now disable a global item from Admin Settings without deleting it. Disabled items remain stored for later reuse, but they are excluded from runtime loading and user-facing global selection flows until they are re-enabled.

## Technical Specifications

Global action and global agent container helpers now persist an `is_enabled` flag and default new records to `true`.

Runtime helper reads now filter out disabled records by default while admin-management routes explicitly opt into `include_disabled=True` so the Admin Settings page can still list, edit, re-enable, or delete disabled records.

Two new admin endpoints handle partial enabled-state updates:

- `PATCH /api/admin/plugins/<plugin_name>/enabled`
- `PATCH /api/admin/agents/<agent_name>/enabled`

When an admin disables the currently selected global agent, the backend now attempts to switch `global_selected_agent` to the first remaining enabled global agent. If none remain, the selected-agent setting is cleared so the system does not continue pointing at a disabled record.

## Usage Instructions

Open Admin Settings and go to the `Agents` tab.

- In `Global Agents`, use the new `Enable` or `Disable` button on each row to control whether the global agent is available at runtime.
- In `Global Actions`, use the new `Enable` or `Disable` button on each row to control whether the global action is loaded at runtime.
- Disabled items remain visible to admins with a `Disabled` badge so they can be reviewed and re-enabled later.

Selected-agent dropdowns only include enabled global agents.

## Testing And Validation

Coverage for this feature includes:

- `functional_tests/test_admin_global_item_enabled_state.py` for helper, route, schema, and admin UI wiring checks
- targeted Python compilation for the modified helper and route modules
- editor diagnostics for the touched Python, JavaScript, HTML, and schema files

Known limitation:

- disabling all global agents is allowed; in that case the selected global agent is cleared and runtime falls back to kernel-only behavior until an agent is re-enabled or a new one is created.