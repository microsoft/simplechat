# Public Prompt Visibility And Editor Dark Mode Fix

Fixed/Implemented in version: **0.239.196**

## Issue Description

Public workspace prompts were not consistently appearing in chat selector lists even when the workspace had been marked visible by the user. In dark mode, the prompt editor toolbar was also difficult to use because the editor still relied on the default light SimpleMDE presentation and missing Font Awesome icons.

## Root Cause Analysis

The public prompt CRUD routes were passing the active public workspace ID as a group scope identifier. That caused public prompts to be stored and queried through the group prompt container instead of the public prompt container. The chat bootstrap logic correctly filtered by visible public workspaces, but it queried the public prompt scope, so prompts saved through the broken route path were invisible there.

The editor usability issue came from SimpleMDE defaulting to Font Awesome class names and light-mode styling. The application ships Bootstrap Icons and dark theme variables, but the prompt editor did not remap those toolbar classes or override the default white editor surfaces.

## Technical Details

Files modified:

- `application/single_app/functions_prompts.py`
- `application/single_app/route_backend_public_prompts.py`
- `application/single_app/route_backend_public_workspaces.py`
- `application/single_app/templates/base.html`
- `application/single_app/static/css/simplemde-overrides.css`
- `application/single_app/config.py`
- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`

Code changes summary:

- Corrected public prompt routes to use `public_workspace_id` instead of `group_id`.
- Added legacy fallback reads for public prompts that were previously written to the group prompt container.
- Updated public workspace prompt counts to include both correctly stored and legacy public prompts.
- Added a shared SimpleMDE override stylesheet that remaps toolbar icons to Bootstrap Icons and applies dark-mode editor styling.
- Loaded the shared SimpleMDE override stylesheet from the base template so prompt editors pick it up consistently.

## Testing Approach

Functional validation was added in `functional_tests/test_public_prompt_visibility_and_editor_theming.py`.

The test verifies:

- public prompt routes use public workspace scope wiring
- public prompt helpers include legacy fallback support
- public workspace prompt counts use the shared counting helper
- the shared SimpleMDE override stylesheet is loaded from the base template
- the override stylesheet contains icon remapping and dark-mode editor rules
- the application version is updated to `0.239.196`

## Impact Analysis

Before:

- visible public workspace prompts could disappear from chat selector lists because they were stored in the wrong container
- prompt count displays for public workspaces could undercount or disagree with actual prompt availability
- dark-mode prompt editors showed low-contrast white editing surfaces and invisible toolbar controls

After:

- visible public workspace prompts load consistently in chat bootstrap lists
- existing legacy public prompts remain available through fallback reads
- public workspace prompt counts align with actual accessible prompts
- prompt editors use readable dark surfaces and visible toolbar icons without adding a second icon library

## Validation

Test results:

- `functional_tests/test_public_prompt_visibility_and_editor_theming.py`

User experience improvements:

- public prompts from visible workspaces appear where users expect them
- prompt creation and editing modals remain usable in dark mode