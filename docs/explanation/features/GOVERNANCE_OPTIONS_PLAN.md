# Governance Options Implementation Plan

Planning baseline version: **0.250.185**

## Goal

Add governance options that align with the existing SimpleChat governance model for:

1. Plugin/action types: who can create or use each plugin family.
2. Workflows: who can create or manage personal and group workflows.
3. Content Safety: who can bypass checks or receive a different ruleset.
4. Endpoint/resource access separation: how admins can keep mutually exclusive user cohorts on the right APIM quota-backed endpoints without maintaining large positive allowlists.

## Current Governance Model

SimpleChat already has a reusable governance layer in `functions_governance.py`:

- Feature policies are keyed by settings toggles such as `governance_user_actions`.
- Item policies are keyed by entity type and item id, such as `global_action` or `global_endpoint`.
- Policies use `allow_all`, `allowed_users`, and `allowed_groups`.
- Empty allowlists with `allow_all = false` intentionally deny all access.
- Policies do not currently support deny/block lists, so "everyone except this cohort" requires disabling `allow_all` and maintaining the complete allowed population.
- User group membership and public workspace membership are usable as governance cohorts.
- Policy decisions are cached per request and process with cache invalidation after policy updates.
- Admin policy management already exists in `route_backend_governance.py` and `admin_governance.js`.

This means new governance options should extend the existing feature-policy and item-policy model instead of introducing a separate access-control system.

## Existing Coverage and Gaps

### Plugin/action type governance

Status: **Partially implemented already.**

Current support:

- `personal_action_type`, `group_action_type`, and `global_action_type` item policies already exist.
- `ensure_action_type_access()` applies plugin/action type policies.
- Personal and group action save paths enforce action type access.
- Plugin type discovery filters types with `is_action_type_access_allowed()`.
- Semantic Kernel runtime loading filters personal, group, and global action manifests through governed helpers.
- Known action type aliases include SQL, OpenAPI, MCP, Microsoft Graph, Databricks, Snowflake, Tableau, Chart, Azure Maps, Blob Storage, and Document Search.

Gaps to close:

- Admin UI language mostly says "Action Type"; the requested feature uses "Plugin Type." We should clarify labels/help text as "Action/Plugin Type" without changing stored entity names.
- The lookup list depends on known aliases. Custom or future plugin types can be governed by raw normalized type id, but they may not appear in the UI lookup until the registry discovers them.
- Creation and runtime use are intentionally tied together for personal/group action types. If admins need separate "can create" vs "can use" semantics later, that should be a separate design because it changes current behavior.

Recommended approach:

1. Keep existing entity types and helpers.
2. Audit all plugin type sources so the UI can list both built-in aliases and discovered custom plugin types.
3. Update admin labels/help text to make the relationship between "actions" and "plugins" explicit.
4. Add regression coverage for an unknown/custom type, proving that a policy for the normalized type id governs it.

### Workflow creation governance

Status: **Not centralized in governance yet.**

Current support:

- Personal workflows are controlled by `allow_user_workflows`.
- Personal workflow access can require the `WorkflowUser` app role through `require_member_of_workflow_user`.
- Group workflows are controlled by `allow_group_workflows`.
- Group workflows can be restricted to assigned groups through `require_group_assignment_for_group_workflows` and `group_workflow_allowed_group_ids`.
- Group workflow management currently requires group Owner/Admin roles through `get_group_workflow_management_roles()`.
- Routes use `@workflow_user_required`, group role checks, and `@enabled_required(...)`.

Gap:

- There is no governance feature policy for "who can create or manage workflows" using the same admin governance UI as endpoints, agents, and actions.

Recommended approach:

1. Add feature policy keys:
   - `governance_user_workflows`
   - `governance_group_workflows`
2. Add settings defaults and Admin Settings toggles:
   - `governance_user_workflows`: defaults to `false`.
   - `governance_group_workflows`: defaults to `false`.
   - Toggles should only be active when the corresponding workflow feature is enabled.
3. Enforce these policies only on authoring and management operations at first:
   - Personal workflow create/update/delete.
   - Personal workflow instruction drafting.
   - Group workflow create/update/delete.
   - Group workflow instruction drafting.
4. Do not initially block read/run/history of existing workflows unless explicitly requested. That preserves existing scheduled workflow behavior and avoids accidentally disabling operational workflows.
5. Keep existing checks as prerequisites:
   - Feature enabled.
   - `WorkflowUser` app role for personal workflows when configured.
   - Group Owner/Admin role for group workflow management.
   - Group workflow assignment rules.
6. Layer `ensure_governance_access(...)` after existing feature/role checks and before save/delete/draft work.

Future optional extension:

- Add item policy entity types `personal_workflow` and `group_workflow` if admins later need per-workflow run/read delegation controls. This is not required for the initial "who can create workflows" ask.

### Content Safety governance

Status: **Requested by existing issue #1048, not implemented in central governance yet.**

Existing issue:

- #1048: <https://github.com/microsoft/simplechat/issues/1048>

Current support:

- Global Content Safety enablement uses `enable_content_safety`.
- Chat processing calls Azure Content Safety in both non-streaming and streaming paths.
- The current block rule is hard-coded in chat routes:
  - block if max severity is greater than or equal to 4
  - block if any blocklist match exists
- Blocked prompts are saved to the safety container and returned as a safety-role message.
- Safety violation admin visibility is controlled separately by `require_member_of_safety_violation_admin`.

Gaps:

- No user/group governance policy can bypass Content Safety checks.
- No user/group governance policy can select a less strict or more strict ruleset.
- The blocking logic is duplicated in streaming and non-streaming chat paths.
- The hard-coded severity threshold is not modeled as an admin-managed ruleset.

Recommended approach:

1. Centralize evaluation in `functions_content_safety.py`:
   - Add a helper that resolves the effective Content Safety decision for a user.
   - Add a helper that evaluates Azure Content Safety responses against a ruleset.
   - Reuse the helper from both chat paths to keep behavior consistent.
2. Add feature policy key:
   - `governance_content_safety_bypass`
3. Add item policy entity type:
   - `content_safety_ruleset`
4. Add settings defaults:
   - `governance_content_safety_bypass`: defaults to `false`.
   - `governance_content_safety_rulesets`: defaults to `false`.
   - `content_safety_rulesets`: include a default ruleset that exactly matches current behavior.
5. Bypass behavior:
   - Only evaluated when global Content Safety is enabled.
   - If governance is enabled and the user passes `governance_content_safety_bypass`, skip the Content Safety call.
   - Log the bypass with a safe static logging tag and metadata, without logging prompt content.
6. Ruleset behavior:
   - Default ruleset preserves current behavior: severity >= 4 or any blocklist match blocks.
   - Admins can define named rulesets with category thresholds and blocklist behavior.
   - Policies on `content_safety_ruleset` determine who can receive a ruleset.
   - If multiple rulesets match, use a deterministic precedence:
     1. explicit user allowlist match
     2. group/workspace cohort match
     3. default ruleset
   - If no governed ruleset applies, use the default ruleset.
7. Keep bypass separate from rulesets:
   - Bypass is a high-risk entitlement and should be obvious in the UI.
   - Rulesets still call Content Safety but adjust enforcement thresholds.

### Endpoint/resource access separation and block lists

Status: **Not implemented in central governance yet.**

Customer scenario:

- Admins have multiple model endpoints backed by APIM token usage policies.
- One endpoint has a lower token threshold and another has a higher token threshold.
- High-threshold users should access the high-threshold endpoint.
- Low-threshold users should access the low-threshold endpoint.
- The current model makes the high endpoint easy: set `allow_all = false` and allow the high-access group.
- The current model makes the low endpoint harder at scale: leaving `allow_all = true` also lets the high group use the low endpoint, but setting `allow_all = false` forces admins to maintain a large allowlist that changes whenever normal users onboard.

Administrator-friendly options:

1. **Policy block lists / deny lists**
   - Extend every feature and item policy with:
     - `denied_users`
     - `denied_groups`
   - Deny/block entries override `allow_all`, `allowed_users`, and `allowed_groups`.
   - For the APIM threshold scenario:
     - High endpoint: `allow_all = false`, `allowed_groups = [HighAccessGroup]`.
     - Low endpoint: `allow_all = true`, `denied_groups = [HighAccessGroup]`.
   - This is the smallest change that directly solves the onboarding pain because new ordinary users automatically keep low-endpoint access, while high users are excluded from the low endpoint by one cohort entry.
   - Limitation: if there are many low-tier resources, admins may still need to add the same high-access block group to multiple policies unless policy templates or access tiers are added later.

2. **Endpoint access tiers / policy sets**
   - Add a higher-level admin concept such as "Endpoint Access Tier" or "Policy Set".
   - Admins define named tiers such as `Low APIM Threshold` and `High APIM Threshold`.
   - Endpoints are assigned to a tier.
   - Users/groups are assigned to allowed tiers, and optionally to excluded tiers.
   - The governance layer expands the tier decision into endpoint access decisions.
   - For the APIM threshold scenario:
     - High users are assigned to `High APIM Threshold`.
     - Low endpoint belongs to `Low APIM Threshold`.
     - High endpoint belongs to `High APIM Threshold`.
     - The tier can be configured as mutually exclusive so high users do not inherit low-tier endpoint access.
   - This is more administrator-friendly for large endpoint fleets because the same tier rule can govern many endpoints.
   - Limitation: this is a larger product feature than simple block lists and needs careful UI language so admins understand whether tiers are additive or mutually exclusive.

3. **Default endpoint routing only**
   - Instead of adding deny semantics, admins could assign a default/preferred endpoint per cohort and hide endpoint selection from users.
   - This can reduce accidental use of the wrong APIM quota bucket.
   - It does not fully solve access control if users or agents can still reference another endpoint through other paths.
   - This should be considered a usability enhancement, not a substitute for governance enforcement.

Recommended approach:

1. Implement generic policy block lists first because they align with the existing governance model and solve the specific onboarding problem with minimal new concepts.
2. In the admin UI, call them **Block List** or **Deny List** and explicitly state that block entries win over allow entries.
3. Add a follow-up design for reusable endpoint access tiers/policy sets if customers have many endpoints or repeated low/high quota classes.
4. Keep tiering as an optional abstraction over the same feature/item policy engine, not a separate access-control system.

## Proposed Data and Setting Additions

### Policy state fields

Add optional fields to normalized feature and item policy documents:

- `denied_users`: list of user ids blocked by the policy.
- `denied_groups`: list of group/cohort ids blocked by the policy.

Decision semantics:

1. If the relevant governance feature toggle is disabled, preserve current behavior and do not evaluate policy lists.
2. If the user id or any user group/cohort appears in a deny/block list, deny access.
3. Otherwise, evaluate the existing `allow_all`, `allowed_users`, and `allowed_groups` behavior.
4. If the same user or group is present in both allow and block lists, the block list wins.

### Feature policy keys

Add to `DEFAULT_FEATURE_POLICIES`:

- `governance_user_workflows`
- `governance_group_workflows`
- `governance_content_safety_bypass`
- `governance_content_safety_rulesets`

### Item policy entity types

Add to `DEFAULT_ITEM_POLICY_ENTITY_TYPES`:

- `content_safety_ruleset`

Optional future item policy entity types:

- `personal_workflow`
- `group_workflow`
- `endpoint_access_tier` or `governance_policy_set` if reusable endpoint tiering is added after generic block lists.

### Settings defaults

Add to `functions_settings.py`:

- `governance_user_workflows`: `false`
- `governance_group_workflows`: `false`
- `governance_content_safety_bypass`: `false`
- `governance_content_safety_rulesets`: `false`
- `content_safety_rulesets`: list with a default ruleset mirroring current behavior

## Admin UI and API Plan

1. Reuse existing governance APIs for feature and item policies.
2. Extend the governance policy editor so feature and item policies can edit both allow lists and block lists.
3. Add policy summaries that show:
   - All users allowed except blocked users/groups.
   - Explicit users/groups allowed.
   - Explicit users/groups blocked.
4. Add labels to `GOVERNANCE_FEATURE_LABELS`:
   - Personal Workflow Authoring
   - Group Workflow Authoring
   - Content Safety Bypass
   - Content Safety Rulesets
5. Add `content_safety_ruleset` to `GOVERNANCE_ITEM_ENTITY_LABELS`.
6. Add lookup support for configured rulesets.
7. Add Admin Settings toggles in the Governance section, gated by the corresponding primary feature settings.
8. Add a Content Safety ruleset editor under the Safety tab or Governance tab.
9. Update the governance help modal with:
   - Workflow authoring boundary.
   - Bypass warning.
   - Ruleset precedence.
   - Clarification that plugin type governance is action/plugin family governance.
   - Block-list precedence and endpoint quota-tier examples.

## Backend Enforcement Plan

### Workflows

Use `ensure_governance_access()` in `route_backend_workflows.py` after existing feature/app-role/group-role checks:

- `save_user_workflow()`
- `delete_user_workflow()`
- `draft_workflow_instructions()` for personal workflow context
- `save_group_workflow_route()`
- `delete_group_workflow_route()`
- `draft_workflow_instructions()` for group workflow context

Do not change scheduled execution until an explicit run/read governance scope is designed.

### Content Safety

Move duplicated Content Safety evaluation out of `route_backend_chats.py` and into `functions_content_safety.py`.

New helper responsibilities:

- Determine whether Content Safety is enabled.
- Determine whether the user has bypass governance.
- Resolve the effective ruleset.
- Build `AnalyzeTextOptions`.
- Evaluate category severities and blocklist matches.
- Return a normalized decision object used by both streaming and non-streaming chat paths.

### Plugin/action types

Keep existing enforcement in:

- `functions_personal_actions.py`
- `functions_group_actions.py`
- `route_backend_plugins.py`
- `semantic_kernel_loader.py`
- `functions_agent_catalog.py`

Add only gap-filling changes:

- UI label/help text updates.
- Custom/unknown type lookup discovery.
- Regression coverage.

### Block list enforcement

Update the central policy evaluator so every existing governance surface receives consistent deny/block semantics:

- Feature policies.
- Item policies such as `global_endpoint`, `global_action`, `personal_action_type`, `group_action_type`, and `global_action_type`.
- MCP destination/source policy helpers that currently duplicate principal matching.
- Any future workflow and Content Safety policies added by this plan.

The evaluator should return or expose enough information for logs/audit events to distinguish "not allowed" from "explicitly blocked" without exposing sensitive prompt or request content.

## Validation Plan

Add or update functional tests:

- `functional_tests/test_governance_enforcement_logic.py`
  - Block-list deny precedence for users and groups.
  - `allow_all = true` plus `denied_groups` blocks only that cohort.
  - Overlapping allow and deny entries deny access.
  - Existing allowlist-only behavior remains unchanged when deny lists are empty.
  - Endpoint quota-tier scenario: high group can access high endpoint and is blocked from low endpoint without enumerating every low user.
  - New workflow feature policy cases.
  - New Content Safety bypass and ruleset policy cases.
  - Custom plugin/action type policy case.
- `functional_tests/test_governance_route_and_wiring_coverage.py`
  - New settings keys, UI labels, and route enforcement markers.
- A focused Content Safety regression test:
  - Bypass user skips safety call.
  - Non-bypass user still calls safety.
  - Default ruleset matches existing severity >= 4 behavior.
  - Alternate ruleset changes the decision deterministically.
- A focused workflow governance test:
  - Personal workflow creation denied by feature policy.
  - Group workflow creation denied by feature policy after role/group validation.
  - Existing read/run behavior remains unchanged unless deliberately added.

Run targeted validation:

- New and changed functional tests.
- Route policy trio if routes change.
- `python -m py_compile` for changed Python files.
- `node --check` for changed JavaScript files.
- XSS and broken-access-control scanners for changed app files.
- `git diff --check`.

## Rollout Plan

1. Phase 1: Generic policy block lists
   - Add deny/block fields to feature and item policy normalization.
   - Apply deny-overrides-allow semantics centrally.
   - Update admin API/UI and tests.
   - Use the APIM low/high endpoint scenario as the primary validation case.
2. Phase 2: Plugin/action type governance cleanup
   - Clarify UI labels/help.
   - Add custom type lookup or tests.
   - No behavior change for existing policies.
3. Phase 3: Workflow authoring governance
   - Add feature keys, toggles, enforcement, tests.
   - Defaults off to preserve current behavior.
4. Phase 4: Content Safety bypass governance
   - Add bypass feature key and enforcement.
   - Centralize duplicated Content Safety logic.
   - Log bypass events safely.
5. Phase 5: Content Safety rulesets
   - Add ruleset data model, UI, item policies, and precedence.
   - Keep default ruleset identical to current behavior.
6. Phase 6: Optional endpoint access tiers / policy sets
   - Add only if repeated low/high quota class management becomes cumbersome with per-policy block lists.
   - Build on the same block-list-aware governance evaluator.
7. Phase 7: Documentation and release notes
   - Update governance docs and release notes after implementation.

## Open Questions

1. Should workflow governance cover only create/update/delete, or also run/read/history?
2. Should Content Safety bypass be restricted to admins configuring specific users/groups, or should group/workspace cohorts be allowed?
3. Should alternate Content Safety rulesets support only thresholds/blocklists first, or also separate endpoint/APIM configurations?
4. Should plugin/action type governance stay as one create/use entitlement, or should a later phase separate "can create" from "can use"?
5. Should deny/block lists apply only when the corresponding governance toggle is enabled? Recommended: yes, to preserve existing toggle semantics.
6. Should admins be prevented from saving the same principal in both allow and block lists, or should the backend simply make block wins? Recommended: warn in UI, enforce block wins in backend.
7. Should endpoint access tiers be added immediately, or should we first validate whether generic block lists are enough for APIM low/high threshold deployments?

## Related Issues

- #1048: Add governance options for Content Safety.
- No exact open issue was found for workflow creation governance during triage.
- Plugin/action type governance is already present; a follow-up issue is only needed if we want UI wording or custom type discovery tracked separately.
