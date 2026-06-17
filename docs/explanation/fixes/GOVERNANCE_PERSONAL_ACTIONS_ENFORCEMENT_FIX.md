# Governance Personal Actions Enforcement Fix

Fixed/Implemented in version: **0.242.063**

## Issue Description

Governance feature policies treated `Allow All` off with no assigned users or groups as open access. Admins expected that state to deny everyone until explicit users or workspace groups were assigned, especially for personal actions where the Actions workspace tab should disappear and new action creation should be blocked.

Users could still see existing personal actions and create new personal actions after an admin enabled Govern Personal Actions, cleared Allow All, and saved an empty allowlist.

## Root Cause Analysis

`application/single_app/functions_governance.py` returned `True` when a policy had `allow_all: false` and empty `allowed_users` and `allowed_groups`. The workspace template and backend action save route both used the governance helper, so the permissive empty-policy interpretation made the UI and APIs behave as if the user was still allowed.

Personal action read paths also bypassed governance checks in API and Semantic Kernel runtime loading paths, which meant hidden personal actions could still be fetched or loaded if a caller reached those endpoints directly.

## Technical Details

Files modified:

- `application/single_app/functions_governance.py`
- `application/single_app/functions_personal_actions.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/functions_agent_catalog.py`
- `application/single_app/static/js/admin/admin_governance.js`
- `application/single_app/config.py`
- `functional_tests/test_governance_enforcement_logic.py`

Code changes summary:

- Empty allowlists now deny access when `allow_all` is disabled.
- Personal action GET, POST, DELETE, agent-catalog labels, and Semantic Kernel runtime loading now respect personal action governance.
- Raw personal action storage reads remain available for migration and internal helper flows, while governed read helpers are used at user-facing and runtime boundaries.
- The Governance tab now distinguishes `All users and groups allowed` from `No users or groups allowed`.
- The app version was updated to `0.242.063` in `application/single_app/config.py`.

## Delegated Action Boundary

Current delegated item policies apply to configured global action instances such as a deployed SQL action or a deployed SimpleChat action. They do not yet apply to broad action types such as every SQL action type regardless of deployment.

That means admins can govern use of a specific deployed global SQL action for selected users or groups, and separately govern a specific deployed global SimpleChat action for another set of users or groups. A future action-type policy layer would be needed to authorize all actions of a type before they are deployed as global action records.

## Validation

Functional coverage in `functional_tests/test_governance_enforcement_logic.py` now validates that:

- disabled governance toggles still bypass policy checks
- feature and item allowlists still allow assigned users or groups
- empty allowlists deny access when `allow_all` is disabled
- personal action API/runtime/catalog entry points use governed access checks

Before the fix, an empty allowlist effectively reopened the governed feature. After the fix, enabling a governance policy and clearing Allow All denies access until explicit users or workspace groups are assigned.