# Governance

Implemented/Updated in version: **0.242.022**

## Overview

Governance provides administrative controls for limiting access to user, group, and global resources across endpoints, agents, and actions. It combines coarse feature-level controls with optional delegated item-level controls so administrators can decide whether a capability is open to all users or restricted to explicit users and groups.

SimpleChat application-level features are governed by identity and app roles. Capabilities and resources configured inside SimpleChat, including agents, actions, endpoints, and delegated items added by admins or users, are governed by in-app governance rules. Use app roles for platform access boundaries, and use in-app governance for resources and capabilities created inside SimpleChat.

The current implementation keeps backend enforcement as the source of truth. Frontend governance UI and Jinja rendering gates improve user experience by hiding disabled workspace modules before their JavaScript loads, but they are not treated as the authorization boundary.

## Purpose

Governance is intended to:

- Restrict access to user endpoints, group endpoints, global endpoints, user agents, group agents, global agent usage, user actions, group actions, and global action usage.
- Support allow lists containing explicit user IDs and group IDs.
- Support one or more delegated item whitelist policies for specific endpoints, global agents, and global actions.
- Provide admin tooling that scales to large allow lists.
- Minimize repeated governance reads on hot API paths through request-level memoization and short-lived process caching.

## Dependencies

- Flask backend routes and decorators for authenticated admin/user access.
- Cosmos DB containers for feature policies and item policies.
- Existing settings keys that enable or disable governance checks.
- Microsoft Graph-backed user lookup through `/api/userSearch`.
- Group discovery through `/api/groups/discover`.
- Bootstrap 5 modals, tables, forms, and toasts.
- `functions_governance.py` for policy normalization, enforcement, and caching.
- `app_settings_cache.py` for local or Redis-backed governance cache versioning.

## Feature Policies

Feature policies are keyed by governance setting names. Each policy stores:

- `allow_all`: whether every authenticated user can access the feature when governance is enabled.
- `allowed_users`: explicit user IDs allowed when `allow_all` is false.
- `allowed_groups`: explicit group or workspace IDs allowed when `allow_all` is false.
- audit metadata such as `updated_by` and `updated_at`.

Supported feature policy keys:

- `governance_user_endpoints`
- `governance_group_endpoints`
- `governance_global_endpoints`
- `governance_user_agents`
- `governance_group_agents`
- `governance_global_agents_usage`
- `governance_user_actions`
- `governance_group_actions`
- `governance_global_actions_usage`

If a governance setting is disabled, the enforcement helper exits early and allows access. If the setting is enabled, the related feature policy must pass.

## Delegated Item Policies

Item policies add a second layer of control for specific delegated resources. Supported item entity types are:

- `endpoint`
- `global_agent`
- `global_action`

Item policies use the same `allow_all`, `allowed_users`, and `allowed_groups` structure as feature policies, and also include a `policy_id`, `policy_name`, and optional `resource_label`. During enforcement, the user must pass the feature policy first and then at least one item policy when policies exist for the selected resource.

Multiple delegated item policies for the same resource are OR combined whitelists. A user is allowed when they are a member of any matching delegated item whitelist for that resource.

Delegated item policies do not override feature-level governance. A user must pass the matching feature policy first. For example, if a user is allowed by an item policy for a specific global agent but does not pass the Global Agent Usage feature policy, the user remains blocked from that global agent.

## Admin API Endpoints

Governance administration is exposed through these backend routes:

- `GET /api/admin/governance/policies`
- `PUT /api/admin/governance/policies/<feature_key>`
- `GET /api/admin/governance/item-policies`
- `GET /api/admin/governance/item-policies/review`
- `PUT /api/admin/governance/item-policies/<entity_type>/<item_id>`
- `DELETE /api/admin/governance/item-policies/<entity_type>/<item_id>/<policy_id>`

All governance admin routes are protected with Swagger security, login enforcement, and admin authorization.

## Enforcement Flow

Backend enforcement is centralized in `ensure_governance_access()` in `application/single_app/functions_governance.py`.

The flow is:

1. Normalize the feature key, user ID, optional item entity type, and optional item ID.
2. Check request-level cache for an already-approved decision.
3. Read settings and exit early if the relevant governance setting is disabled.
4. Resolve the user's governance group IDs from group workspaces and public workspaces.
5. Read and evaluate the feature policy.
6. If an item entity type and item ID are provided, read all matching item policies and allow access if any item policy passes.
7. If the feature policy fails, skip item policy evaluation and deny access. Item-level whitelists are additive only after the feature policy passes.
8. Cache successful decisions for the remainder of the request.
9. Raise `PermissionError` if the feature or item policy blocks access.

The policy pass rules are:

- `allow_all` passes immediately.
- Empty `allowed_users` and `allowed_groups` passes for backwards-compatible default behavior.
- The user passes if their user ID is explicitly listed.
- The user passes if any of their resolved group/workspace IDs intersects the allowed group list.

## Cache Strategy

Governance is called from hot API paths, so the implementation includes two cache layers.

### Request-Level Memoization

Request-level cache is stored on Flask `g` using the `simplechat_governance_request_cache` attribute. It avoids repeated reads within the same HTTP request for:

- settings
- feature policies
- item policies
- user governance group IDs
- successful access decisions

This is the safest cache layer because it naturally expires at the end of each request.

### Short-Lived Process Cache

A process-level cache stores feature policies, item policies, and user governance group IDs for `60` seconds. Cache entries are deep-copied on read/write to avoid mutation leaks between callers.

Process cache keys include the data type and normalized identifiers, for example:

- `("feature_policy", feature_key)`
- `("item_policies", entity_type, item_id)`
- `("user_governance_group_ids", user_id)`

The cache is guarded by an `RLock`. Each entry is stamped with the current shared governance cache version before it is stored. On read, entries are trusted only when their stamped version matches the current shared governance version and the entry has not expired.

### Shared Governance Cache Version

The governance cache version is exposed through `app_settings_cache.py`:

- `get_governance_cache_version()`
- `bump_governance_cache_version()`

The backing store is selected automatically by the existing app cache configuration:

- Redis enabled and app cache configured successfully: version is stored in Redis under `GOVERNANCE_CACHE_VERSION` and bumped with Redis `INCR`.
- Redis disabled: version is stored in a Cosmos-backed document in the governance policies container when Cosmos is available.
- Redis and Cosmos versioning unavailable: version falls back to local process memory.

The Cosmos version document ID is `governance_cache_version`, and each worker checks it with a local `15` second version-read TTL. This keeps the governance process cache fast while allowing both Redis-enabled and non-Redis deployments to invalidate stale process-cache entries across App Service workers.

### Invalidation

`invalidate_governance_cache()` bumps the shared cache version and clears the current process cache. It is called when:

- a feature policy is upserted
- an item policy is upserted
- default feature policies are bootstrapped

When Redis is enabled, other processes observe the bumped Redis version before trusting their local process-cache entries. When Redis is disabled, other workers observe the bumped Cosmos version document after their local version-read TTL expires. Stale entries are dropped lazily on their next read. If both Redis and the Cosmos version read/write fail, the code falls back to process-local versioning and workers converge when their short data-cache TTL expires.

## Admin UI

Governance administration is hosted in the Admin Settings governance tab.

Major UI areas include:

- Governance feature toggles grouped by User, Group, and Global scope.
- Feature policy table for all configured governance feature keys.
- Delegated item policy card with on-page search, entity-type filtering, paging, and page size selection.
- Dedicated delegated item edit modal for endpoints, global agents, and global actions.
- Allow-list editor modal for managing users and groups.
- Governance Configuration Guide modal explaining feature policies, workspace cohorts, delegated item policies, and evaluation flow.
- Govern buttons on configured global endpoints, global agents, and global actions that open a prefilled delegated item policy editor.
- Duplicate buttons for configured endpoints, agents, and actions. Endpoint duplicates start disabled, and key-based endpoint duplicates require the key to be re-entered.
- Bootstrap toast notifications for governance status messages.

Governance feature toggles also control the visible Feature Policies table. When a governance feature toggle is disabled, its matching policy row is hidden. Re-enabling the toggle immediately shows that policy row again.

## Governance Configuration Guide

The Governance tab includes a Configuration Guide modal. It follows the same explanatory modal pattern used by other Admin Settings areas and gives admins a compact reference for how governance works.

The guide covers:

- the difference between feature policies and delegated item policies;
- how feature toggles relate to all personal, group, and global feature policy rows;
- how group workspace membership can be reused as a governance cohort;
- how delegated item policies narrow access to specific global resources;
- backend evaluation order and caching behavior;
- troubleshooting guidance for common access surprises.

The most important concept is workspace cohorts. A group workspace can be used as a reusable group of users in an allow list. For example, admins can create a group workspace named **Personal Agents Pilot Users**, add pilot users to that workspace, then add that workspace ID to the **Personal Agents** feature policy's Allowed Groups list. Members can then use personal agents in their own personal workspaces.

Using a group workspace as a governance cohort does **not** grant access to that workspace's documents, does **not** grant access to group agents or group actions, and does **not** move personal agents into the group workspace. It only reuses membership as an access cohort for the selected governance policy.

## Delegated Item Lookup

The item policy editor is a dedicated Bootstrap modal opened from the Delegated Item Policies card. The card itself lists configured policies and supports search, entity-type filtering, paging, and page size selection so admins can manage large policy sets without opening a review modal.

The item policy editor uses dropdown lookup data instead of requiring admins to type IDs manually.

Lookup behavior:

- Endpoints are resolved from admin settings model endpoint data available on the page.
- Global agents are loaded from `/api/admin/agents`.
- Global actions are loaded from `/api/admin/plugins`.
- The refresh button reloads lookup values for the selected entity type.
- The delegated item filter narrows large lookup lists by item name, ID, or subtitle before selection.
- Empty or failed lookups show status text near the delegated item selector.

Delegated item policies are saved through a dedicated JavaScript handler in the edit modal instead of a nested HTML form, so saving a delegated item rule updates the governance item policy API rather than submitting the full Admin Settings form.

Existing delegated item policies can be edited from the on-page configured policy list. The row action opens the dedicated edit modal with the selected policy loaded, including entity type, item ID, allow-all state, and explicit users/groups.

When Allow All is disabled for a delegated item policy, the edit modal shows a direct principal editor. This editor supports user lookup, group lookup, CSV import, independent selected-user and selected-group search, paging, page size options, hydrated display labels, truncated IDs, and copy buttons. This keeps item policy editing usable when a delegated item contains hundreds or thousands of allowed principals.

Existing delegated item policies can also be deleted from the configured policy list. Deletion uses a Bootstrap confirmation modal, calls the delegated item policy DELETE API, clears matching editor state, refreshes the configured policy list, and writes governance audit activity.

The configured policy list shows hydrated user and group labels above the raw IDs. User entries show the best available display name and UPN/email, while group entries show group names. Raw IDs remain visible below the labels for traceability.

## Workspace Jinja Gating

Personal and group workspace templates receive a `workspace_governance` render-context object with the current user's feature-level governance decisions for agents, actions, and endpoints.

When a workspace feature is enabled in settings but governance blocks the current user:

- the tab remains available so the user sees why the module is unavailable;
- the tab body renders a Bootstrap warning message explaining that the capability is disabled by governance;
- the matching agent, action, or endpoint module JavaScript is not loaded;
- creation/edit modals for the disabled module are not rendered;
- endpoint lists passed to the browser are filtered through both feature and delegated endpoint item policies before sanitization.

Backend API routes still enforce governance for all affected operations. The Jinja gating only prevents unnecessary UI module loading and gives users a clearer disabled state.

## Allow-List Editor

The allow-list editor supports both lookup-based and bulk workflows.

User lookup:

- Searches by display name or email through `/api/userSearch`.
- Displays user name and email/UPN in the lookup result table.
- Adds selected users to the working allow list.

Group lookup:

- Searches groups through `/api/groups/discover`.
- Group discovery now matches group ID as well as name and description so existing selected group IDs can hydrate names.
- Displays group name and group ID in the lookup result table.
- Adds selected groups to the working allow list.

CSV import:

- Accepts one ID per line or comma-separated IDs.
- Can target users or groups.
- Supports merge and replace modes.

## Selected User and Group List Scalability

Selected allow lists are designed to stay usable with large lists.

Scalability controls include:

- Search within selected users and selected groups.
- Independent pagination state for users and groups.
- Page size options: `10`, `25`, `50`, and `100`.
- Bounded table height with internal scrolling.
- Previous and Next controls with disabled states at boundaries.
- Summary text showing the currently visible range and total selected count.

Search matches both raw IDs and hydrated display labels when labels are available.

## Selected Row Display

Selected user rows display the best available user label before the ID:

- display name plus UPN/email when both are available
- UPN/email when no display name is available
- raw ID as fallback

Selected group rows display the group name before the ID when available.

Long IDs are truncated in the visible row to protect table layout. The full ID remains available through the row tooltip and the copy button.

Each selected row includes a copy button that writes the full ID to the clipboard and briefly changes the icon to confirm the copy action.

## Metadata Hydration

Existing policies can contain raw user and group IDs without names. The allow-list editor performs best-effort metadata hydration when selected lists render.

User hydration:

- First tries `/api/userSearch` with the selected user ID.
- Falls back to `/api/user/info/<user_id>`.
- The user info endpoint first checks local user settings, then falls back to Microsoft Graph `/users/<user_id>` so selected users can display name and UPN/email even when an admin has not manually searched for that user during the current browser session.
- Stores display name and UPN/email in the selected-list display cache.

Group hydration:

- Uses `/api/groups/discover` with the selected group ID.
- Stores the group name in the selected-list display cache.

Hydration is de-duplicated with in-flight tracking so repeated renders do not launch duplicate lookup requests for the same ID.

## Frontend Governance Adherence

Chat-facing agent and model option lists are filtered through backend governance before they are sent to the browser.

Agent UI filtering applies to:

- preloaded chat agent dropdown options
- retry dialog agent options returned from user and group agent list endpoints
- global agent usage policy and global agent item policies
- user and group agent feature policies

Model/endpoint UI filtering applies to:

- global model endpoints through `governance_global_endpoints`
- user custom model endpoints through `governance_user_endpoints`
- group custom model endpoints through `governance_group_endpoints`
- endpoint item policies for all endpoint scopes when an endpoint ID is available

This filtering is a user-experience improvement only. Backend enforcement remains the final authorization boundary for selected agent and endpoint use.

## Toast Notifications

Governance UI status messages use Bootstrap toast popups.

Toast handling covers:

- feature policy save success
- item policy save success
- refresh messages
- search/load failures
- allow-list add/remove/clear messages
- CSV import results
- validation warnings

A small inline fallback remains for degraded cases where Bootstrap toast support or the toast container is unavailable.

## File Structure

Primary implementation files:

- `application/single_app/functions_governance.py`
- `application/single_app/app_settings_cache.py`
- `application/single_app/route_backend_governance.py`
- `application/single_app/route_backend_agents.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/static/js/admin/admin_governance.js`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/route_backend_groups.py`
- `application/single_app/route_backend_users.py`

Primary validation files:

- `functional_tests/test_governance_route_and_wiring_coverage.py`
- `ui_tests/test_admin_governance_tab.py`

## Security Notes

- Backend enforcement remains mandatory and centralized in `ensure_governance_access()`.
- Frontend controls and filtered option lists are only for administration and user experience; they are not authorization boundaries.
- Governance admin routes require login and admin access.
- The cache stores policy and membership decisions server-side only; it does not push full governance rules into user tokens.
- Cache invalidation happens centrally after policy updates.
- Redis-enabled deployments use a shared governance cache version for cross-process invalidation.
- Redis-disabled deployments rely on the short TTL for cross-process cache convergence.

## Testing and Validation

Current validation includes:

- governance route registration and guard checks
- enforcement hook coverage across changed backend routes
- cache optimization hook coverage
- admin governance tab UI test coverage
- JavaScript diagnostics for governance UI changes

Latest verified test commands:

```bash
python -m pytest functional_tests/test_governance_route_and_wiring_coverage.py -q
python -m pytest ui_tests/test_admin_governance_tab.py -q
```

Expected current result:

- functional governance coverage passes
- admin governance UI test may be skipped in environments where the UI preconditions are not available

## Known Limitations

- Redis-backed cross-process invalidation depends on Redis being enabled and successfully configured for the app cache.
- If Redis is disabled or falls back to local memory, cross-process or cross-instance invalidation is bounded by the `60` second TTL.
- Frontend option filtering exists for chat agent/model choices, but backend enforcement remains mandatory for all protected operations.
- User and group display names are best-effort metadata and may fall back to raw IDs if lookups fail.
- Clipboard copy requires browser clipboard API support.

## Future Enhancements

Recommended next steps:

- Add a broader frontend governance bootstrap endpoint for non-chat UI gating without repeated per-control calls.
- Add telemetry counters for cache hit/miss rates and policy block decisions.
- Add focused tests for cache invalidation behavior with mocked governance containers.
