# Group Prompts Role UI Null Guard Fix

Fixed/Implemented in version: **0.241.003**

## Header Information

Issue description:
The group workspace page could throw a client-side exception while refreshing active group state: `Cannot read properties of null (reading 'style')` from `updateGroupPromptsRoleUI()`.

Root cause analysis:
The prompt role-toggle logic assumed `create-group-prompt-section` and `group-prompts-role-warning` always existed in the DOM and wrote directly to `.style.display` without checking for missing nodes.

Version implemented:
`config.py` was updated to `VERSION = "0.241.003"` for this fix.

## Technical Details

Files modified:
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `ui_tests/test_group_workspace_prompt_role_ui_resilience.py`

Code changes summary:
- Switched the prompt role warning and create button containers to Bootstrap `d-none` state classes instead of inline `display: none` styles.
- Updated `updateGroupPromptsRoleUI()` to tolerate missing prompt DOM nodes and toggle visibility via `classList` instead of unsafe `.style` access.
- Added an early return in `fetchGroupPrompts()` when the prompt table container is unavailable.
- Added a UI regression test that removes the prompt role UI containers before changing the active group and asserts that no page error is raised.

Testing approach:
- Added a Playwright UI regression test covering group changes with missing prompt role containers.
- Targeted validation should include the new UI test file plus a syntax/error pass on the updated template and config version bump.

Impact analysis:
The group workspace now keeps loading and switching groups even when prompt role UI fragments are omitted, customized, or temporarily unavailable.

## Validation

Test results:
The regression test is designed to fail on the old `.style` access and pass once the null-safe toggle logic is present.

Before/after comparison:
- Before: group changes could throw an uncaught promise error from `updateGroupPromptsRoleUI()`.
- After: group changes skip missing prompt role nodes safely and continue updating the rest of the workspace.

User experience improvements:
Users no longer see the prompt role UI exception interrupt the group workspace load flow when those prompt elements are missing.