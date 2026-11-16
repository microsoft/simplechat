# Call Agent Action Save Fix

Fixed in version: **0.261.217**

## Issue

Saving any Call agent action failed, whether personal, group, or global. Admins saw "Invalid plugin configuration." and the server logged `Validation error adding plugin: Call agent actions cannot override target credentials, connections, or configuration.` As a result, an agent could not delegate to another agent.

## Root Cause

Every save binds the action to its collection with `bind_action_origin` before validating it. Since action authorization was hardened, binding adds a server-owned `scope_id` field alongside `scope`, `is_global` and `is_group`.

`validate_agent_action_manifest` accepts only the fields in its `_MANIFEST_FIELDS` allowlist, so it can reject anything a client might use to override the target's endpoint or credentials. The allowlist included `scope` but not `scope_id`, so every bound Call agent action was rejected as if it carried an override.

## Technical Details

Files modified:

- `application/single_app/functions_agent_delegation.py`
- `functional_tests/test_agent_delegation_scoped_action_save.py`
- `application/single_app/config.py`

`scope_id` is now on the allowlist. The value is always set by `bind_action_origin` from the authorized collection, so a client cannot choose it. All other extra fields are still rejected.

## Validation

`functional_tests/test_agent_delegation_scoped_action_save.py` binds a Call agent action with the real `bind_action_origin` for global, personal, and group scopes and validates it with the real `validate_agent_action_manifest`. It also checks that a bound manifest carrying another field, such as `api_key` or `base_url`, is still rejected.

Without the fix, all three scope cases fail.
