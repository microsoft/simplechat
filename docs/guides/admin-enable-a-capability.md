---
layout: page
title: "Enable a SimpleChat capability safely"
description: "Use a repeatable admin procedure to turn on optional SimpleChat capabilities without exposing broken controls to users."
section: "Guides"
audience: admin
---

## What this covers

This guide gives administrators a repeatable rollout pattern for any optional capability controlled by Admin Settings. Use it for features such as Content Safety, Enhanced Citations, File Sync, URL Access, Deep Research, image generation, Redis, Key Vault-backed secrets, and other tab-specific toggles.

{% include media.html type="video"
                      title="Enable a SimpleChat capability safely walkthrough"
                      poster="video-posters/guide-admin-enable-a-capability.png"
                      capture="Recording planned. Walk the full journey end to end and explain the decisions an admin makes along the way." %}

## Why it matters

A capability toggle is usually the last step, not the first one. Many SimpleChat switches expose UI or runtime paths that require Azure resources, managed identity roles, keys, domain policies, app roles, storage, quotas, or limits. Turning on the switch before the dependency is ready can give users a visible feature that fails when they try to use it.

## Before you start

- Identify the exact Admin Settings tab that owns the capability and read its page under [Administration]({{ '/admin/' | relative_url }}).
- Confirm whether the capability key appears in the docs inventory as one of the SimpleChat capability toggles.
- Know the user scope for the rollout: admin-only test, a pilot group, one workspace scope, or the whole tenant.
- Have a non-admin validation account that matches the intended user role and another account that should not have access when role gating is enabled.

## Step 1: Confirm the backing service or policy exists

Read the capability's tab page and list every dependency it names. Examples include Azure AI Content Safety for Content Safety, Storage for Enhanced Citations, Azure Cache for Redis for Redis-backed cache, Key Vault for agent and action secrets, Foundry agent details for Web Search, Speech service for audio and voice features, or Entra app roles for gated workspace actions.

{% include media.html src="guides/admin-enable-a-capability-dependencies.png"
                      alt="The Web Search configuration guide explaining Grounding with Bing Search, warning that customer data is transferred outside the Azure compliance boundary, and listing the numbered prerequisites for creating the agent and choosing a compatible model."
                      title="Confirm capability dependencies"
                      capture="Capture a dependency checklist for one capability with resource names redacted and readiness marked before the toggle is enabled." %}

## Step 2: Configure authentication before the toggle

Choose the authentication mode shown on the tab: key, managed identity, APIM subscription key, connection string, or another supported option. For managed identity, assign the App Service identity to the target Azure resource before saving the setting. For app-role requirements, assign users or groups in the Enterprise App before enforcing the requirement.

## Step 3: Set limits and allowlists first

Configure limits, domains, scopes, thresholds, retention windows, source counts, concurrency, or guardrails before making the capability visible. This is especially important for URL Access, Deep Research, File Sync, tabular runs, Cosmos throughput automation, MCP destinations, and workspace downloads because those controls define how far the feature can reach.

{% include media.html src="guides/admin-enable-a-capability-guardrails.png"
                      alt="The Web Search settings pane with the capability enabled, the user data notice switched on with its notice text, and the Foundry project endpoint, API version, agent ID and authentication fields populated above a Test Web Search button."
                      title="Set guardrails before enabling"
                      capture="Capture the relevant Admin Settings tab with limits and policy fields populated before the final capability switch is turned on." %}

## Step 4: Enable the capability for the smallest safe audience

Turn on the capability after dependencies, authentication, and guardrails are ready. If the tab supports role requirements, group assignment, admin-only management, or workspace-specific scope controls, use those controls to start with the smallest group that can validate the feature.

## Step 5: Validate with a non-admin account

Sign in as a user who should have access and complete the smallest real workflow: send a blocked Content Safety test, open an enhanced citation, create a sync source, use URL Access on an allowed domain, generate an image, or create a test action. Then sign in as a user who should not have access and confirm the control is hidden or blocked according to the tab's policy.

{% include media.html src="guides/admin-enable-a-capability-validate.png"
                      alt="Non-admin validation account using the newly enabled capability while an unassigned account is blocked."
                      title="Validate with normal users"
                      capture="Capture the capability working for an assigned non-admin account and redact any user content or secrets." %}

## Step 6: Watch telemetry and prepare rollback

After validation, check [Logging settings]({{ '/admin/operations/' | relative_url }}) and Application Insights for failures from the new path. Keep a rollback note with the setting names changed, the previous values, and any dependent resources or roles created. If the feature fails, disable the capability toggle first, then remove broader access or resource changes only after users are no longer hitting the path.

## Verify it worked

- The backing Azure resource, identity permission, key, APIM path, storage endpoint, or app role exists before the feature is enabled.
- The capability works for a non-admin account in the intended scope.
- Unassigned or out-of-scope users cannot use the feature when a role or assignment requirement is enabled.
- Telemetry does not show repeated failures from the newly enabled path.
- The rollback action is known and can be performed quickly.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Users see the control but the action fails | The toggle was enabled before endpoint, identity, key, or quota validation finished | Disable the toggle, finish dependency configuration, then test with a pilot user. |
| Assigned users are blocked | The Entra app role, workspace assignment, or allowed-list entry is missing | Add the assignment first, then re-test with the same account. |
| The feature works for admins but not normal users | Validation only used an admin account | Repeat validation with the intended non-admin role and check the tab's role requirement settings. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [First configuration guide]({{ '/guides/admin-first-configuration/' | relative_url }})
- [Operate SimpleChat day to day]({{ '/guides/admin-operate-simplechat/' | relative_url }})
- [Safety settings]({{ '/admin/security/' | relative_url }})
- [Agents settings]({{ '/admin/agents-actions/' | relative_url }})
