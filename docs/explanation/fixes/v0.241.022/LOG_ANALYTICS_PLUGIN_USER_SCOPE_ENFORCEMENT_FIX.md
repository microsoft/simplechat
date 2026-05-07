# Log Analytics Plugin User Scope Enforcement Fix

Fixed/Implemented in version: **0.241.012**

## Header Information

Issue description:
This fix closes a broken-access-control path where the Log Analytics plugin exposed a caller-controlled `user_id` parameter for query-history reads and writes. In the affected flow, an LLM-chosen `user_id` could be forwarded into `get_user_settings(...)` and `update_user_settings(...)`, enabling cross-user query-history access and writes.

Root cause analysis:
The plugin schema and Python method signatures treated `user_id` as a tool-call argument instead of binding it to the authenticated session on the server. The shared user-settings helpers also had no default request-time cross-user authorization check, so any caller that passed another user's id could read or write that user's settings document unless the route performed its own guard.

Version implemented:
`config.py` was updated to `VERSION = "0.241.012"` for this fix.

## Technical Details

Files modified:
- `application/single_app/semantic_kernel_plugins/log_analytics_plugin.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/config.py`
- `functional_tests/test_log_analytics_plugin_user_scope_enforcement.py`
- `functional_tests/test_keyvault_plugin_secret_scope_enforcement.py`
- `functional_tests/test_security_authorization_hardening.py`
- `functional_tests/test_stored_xss_admin_rendering_fix.py`
- `functional_tests/test_conversations_read_ownership_authorization.py`
- `functional_tests/test_multimedia_support_reorganization.py`

Code changes summary:
- Removed `user_id` from the Log Analytics plugin metadata and method signatures for `run_query(...)` and `get_query_history(...)`.
- Added `_get_authenticated_history_user_id()` so query-history persistence and reads resolve the authenticated user on the server instead of trusting tool-call parameters.
- Added `_authorize_user_settings_access(...)` and `_should_sync_session_profile(...)` in `functions_settings.py`.
- Hardened `get_user_settings(...)` and `update_user_settings(...)` with an explicit `allow_cross_user=False` default and request-time cross-user denial.
- Prevented cross-user `get_user_settings(...)` calls from mutating the target document with the current session user's email, display name, or profile image.
- Updated the reviewed Control Center admin paths to use `allow_cross_user=True` explicitly for legitimate administrative writes.

Testing approach:
- Added a focused functional regression test covering Log Analytics tool-surface removal of `user_id`, shared-helper default-deny behavior, explicit Control Center bypass call sites, and the versioned fix-document target.
- Recompiled the touched Python modules after each edit slice to catch parse errors in the plugin and helper layers.

Impact analysis:
Normal self-scoped settings reads and writes are unchanged. The only behavior change is that cross-user settings access now requires an explicit opt-in at reviewed privileged call sites. For the Log Analytics plugin, query history remains available to the authenticated user, but the model can no longer steer reads or writes into another user's settings document.

## Validation

Test results:
- `python -m py_compile application/single_app/semantic_kernel_plugins/log_analytics_plugin.py application/single_app/functions_settings.py application/single_app/route_backend_control_center.py`
- `python functional_tests/test_log_analytics_plugin_user_scope_enforcement.py`

Before/after comparison:
- Before: the Log Analytics plugin exposed `user_id` in its tool surface, and shared settings helpers allowed cross-user reads/writes when called with another user's id.
- After: the plugin binds query history to the authenticated user, shared settings helpers default-deny cross-user request-time access, and the reviewed Control Center admin flows opt into a privileged bypass explicitly.

User experience improvements:
Regular users continue to see their own Log Analytics query history with no prompt changes required. Administrative settings operations still work, but the privilege boundary is now explicit in code instead of being implicit and easy to reuse accidentally.