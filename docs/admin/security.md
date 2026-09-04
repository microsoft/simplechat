---
layout: page
title: "Security settings"
description: "Security covers access roles, Key Vault integration, Content Safety, idle session behavior, Front Door-aware network URLs, and the message shown to rate limited users."
section: "Administration"
audience: admin
admin_tab: security
redirect_from:
  - /admin/safety/
  - /admin/workspace-identities/
---


# Security settings

## What this group controls

Security covers access roles, Key Vault integration, Content Safety, idle session behavior, Front Door-aware network URLs, and the message shown to rate limited users.

## Why it matters

This group protects who can enter the app, what secrets the app can use, what content is blocked, and which hostnames are trusted for redirects. Treat changes as security controls.

{% include media.html src="admin-settings/security.png" alt="Screenshot of the Security group in Admin Settings." title="Security settings" %}

{% include media.html src="admin-settings/safety.png" alt="Screenshot of the Security group in Admin Settings." title="Security settings" %}

{% include media.html type="video" title="Security settings walkthrough" poster="video-posters/admin-security.png" capture="Recording planned. Walk through each tab in the Security group and explain when to change each setting." %}

## Before you change anything

- Create Entra app roles before requiring them.
- Provision Key Vault or Content Safety resources before enabling integrations.
- Validate Front Door hostnames and OAuth redirects before switching users to the routed URL.

## Access & Roles {#access-roles}

Everything on this tab decides who gets in and what they can reach once they are in. It is deliberately separate from Content Safety, which governs what may be said by someone already inside.

SimpleChat recognises a general `Admin` role and a set of narrower Entra app roles. By default the narrower roles are not required, so anyone holding `Admin` can reach every admin surface and any signed-in user can use every enabled feature. Requiring a role is what splits that apart.

### Permissions {#permissions-section}

### Permissions {#permissions-section}

Two administrative reports can be narrowed beyond the general Admin role: Safety Violations,
which shows flagged message text, and User Feedback. Both are readable by any Admin unless a
dedicated role is required here, so these are the settings to reach for when "administrator"
and "may read what users typed" should not be the same group of people.

The FeedbackAdmin requirement only governs the User Feedback report, so it does nothing until
User Feedback is enabled under Chat.

Assign the role in the Enterprise App before enabling the requirement. Enabling it first locks
out every administrator, including you.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Require SafetyViolationAdmin App Role | Narrows the Safety Violations report, including the flagged message text, to holders of the `SafetyViolationAdmin` role. Left off, any account with `Admin` can open it. | Off | `require_member_of_safety_violation_admin` |
| Require FeedbackAdmin App Role | Narrows the User Feedback report to holders of the `FeedbackAdmin` role. Has no effect until User Feedback is enabled under Chat. | Off | `require_member_of_feedback_admin` |

### App Role Requirements {#app-role-requirements-section}

Every setting in the application that can demand an Entra app role, gathered in one place.
Each switch is the same stored value as the one on the tab that owns the feature, not a copy
of it, so changing it here changes it there.

The reason for the duplication is that a role requirement read on its own tells you very
little. Read together they are the deployment's access policy, and deciding whether that
policy is coherent -- whether the same people can create groups, publish public workspaces,
run workflows and read the Control Center -- means seeing all of them at once.

Each row names the exact Entra app role value to assign, states what enforcing it restricts
and who retains access when it is left off, and links to the tab that owns it. A requirement
whose feature is currently switched off is marked as having no effect, because enforcing a
role for a disabled feature looks like protection and is not.

The eleven requirements cover the two admin reports above, Control Center access and its
dashboard-only tier, group and public workspace creation, chat file uploads, personal
workflows, URL Access, Deep Research, and personal workspace file sync.

Assign a role in the Enterprise App before requiring it. Switching a requirement on before
anyone holds the role removes the capability from everybody.

### Access Denied Message {#access-denied-message-section}

Someone who signs in successfully but holds none of the required roles reaches a dead end. They authenticated, so retrying will not help, and they cannot see which role they are missing. This message is the only thing standing between them and a support ticket, so it should name the team or process that grants access rather than restating the refusal.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Access Denied Message | Shown to a signed-in user who holds none of the roles the application requires. Line breaks are preserved. | You are logged in but do not have the required permissions to access this application. Please contact an administrator for access. | `access_denied_message` |

## Secrets {#secrets}

### Key Vault {#keyvault-section}

Agents and actions hold credentials: API keys for the services they call, subscription keys for gateways in front of them. By default those live in the settings document. Enabling Key Vault moves them into Azure Key Vault instead, leaving only a reference behind, which is what deployments with a policy against secrets at rest outside a vault need.

Treat enabling this as one-way. Secrets saved afterwards are referenced by name, so turning it back off leaves those references pointing at values the application can no longer read, and every agent and action depending on them stops working.

The vault identity needs Get, Set and List on secrets. Use the Test Key Vault connection button before saving: a wrong identity is otherwise invisible until an agent tries to read a secret at runtime.

**Expiration reminders.** Secret names written by SimpleChat are content hashes, so a Key Vault expiry alert from Azure names something like `sc-a1b2c3` and nothing an operator can act on. Reminder tracking records the missing half: which user or group owns each secret, which action and field it backs, and who to contact. The tracked secret inventory in this section is the lookup from an opaque secret name back to that context.

SimpleChat does not send the reminder emails. It raises them in-app and emits an Application Insights event named `key_vault_expiration_reminder_triggered`. Route that to a recipient with an Azure Monitor scheduled query alert, a Logic App, a Function, or a webhook, and keep the vault's own expiry alerts configured in Azure Monitor or Event Grid as well.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Store agent and action secrets in Key Vault | Writes agent and action credentials to Azure Key Vault and keeps only a reference in the settings document. | Off | `enable_key_vault_secret_storage`; capability toggle |
| Key Vault Name | The vault resource name, not a URL. The endpoint suffix comes from the `AZURE_ENVIRONMENT` App Service setting. | Empty | `key_vault_name` |
| Key Vault Managed Identity Client ID | Client ID of the user-assigned managed identity holding Get, Set and List on the vault. Blank uses the App Service system-assigned identity. | Empty | `key_vault_identity` |
| Track secret expiration dates | Records owner, source and field for each tracked secret, and warns before it expires. | Off | `enable_key_vault_secret_expiration_reminders`; capability toggle |
| Default lead days | How far ahead of expiry the first reminder is raised. Accepts 1 to 3650. | 30 | `key_vault_secret_expiration_default_lead_days` |
| Default reminder email | Recorded against secrets that name no owner of their own, for downstream automation to route to. SimpleChat does not email it. | Empty | `key_vault_secret_expiration_default_contact_email` |
| Admin notification roles | Roles notified in-app about global-scope reminders, meaning secrets with no individual owner. Comma separated. | Admin | `key_vault_secret_expiration_admin_roles` |
| Scan interval (seconds) | How often the background sweep re-checks tracked secrets. Accepts 900 to 86400. | 21600 | `key_vault_secret_expiration_scan_interval_seconds` |
| Require an expiration date when users enable tracking | Refuses to create a tracked secret with no expiry date, since it could never raise a reminder. | Off | `key_vault_secret_expiration_require_expiration` |
| Include the contact email in external telemetry | Adds `contact_email` to the Application Insights reminder event. Enable only when downstream automation needs the address, since it puts an email address into telemetry. | Off | `key_vault_secret_expiration_emit_contact_email_in_telemetry` |

## Global Identities {#workspace-identities}

### Global Identities {#workspace-identities-section}

A global identity is a credential for a system SimpleChat connects out to -- a SharePoint
site, an HTTP API behind a key, a database -- saved once and referenced by name everywhere it
is used. It is not an account for signing in to SimpleChat. Two things consume them: File
Sync sources, which authenticate when they pull documents, and actions, which authenticate
when an agent calls out.

Storing the credential once and referencing it by name means the secret itself never travels
with a source or action configuration, never appears in an export, and can be rotated in one
place. Where Key Vault is configured, the secret is held there rather than in the settings
document, which is why this sits next to Secrets rather than with the features that use it.

An identity that is still referenced by a File Sync source or an action cannot be deleted;
remove the reference first.

{% include media.html src="admin-settings/global-identity.png" alt="Screenshot of the Global Identities tab in Admin Settings." title="Global Identities" %}

## Content Safety {#content-safety}

### Content Safety {#content-safety-section}

Every user message is sent to Azure AI Content Safety before it reaches a model. A message that trips the configured thresholds is blocked, replaced with your violation message, and recorded as a safety violation for the report on the Access & Roles tab.

Content Safety can reach the service directly or through Azure API Management. Route it through APIM when the rest of your Azure AI traffic already goes that way, so this traffic is subject to the same policy, quota and logging. Direct connections authenticate with a key or with the App Service managed identity; managed identity avoids storing a key and needs the Cognitive Services User role on the resource.

Test the connection before saving. A broken Content Safety connection blocks chat rather than failing quietly, so the failure mode is loud and immediate.

**Trigger information** appends the detected categories, their severities and any blocklist matches beneath the message. It helps users self-correct instead of rephrasing blindly, at the cost of telling them exactly which thresholds are set.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Content Safety | Sends user messages to Azure AI Content Safety before a model sees them, and blocks anything that trips the configured thresholds. | Off | `enable_content_safety`; capability toggle |
| Route through Azure API Management | Sends Content Safety calls to an APIM front end rather than the service endpoint. | Off | `enable_content_safety_apim`; capability toggle |
| Content Safety Endpoint | The resource endpoint from the Content Safety resource in Azure. Used for direct connections. | Empty | `content_safety_endpoint` |
| Authentication Type | Whether a direct connection authenticates with a key or the App Service managed identity. | key | `content_safety_authentication_type` |
| Content Safety Key | Either key from the Content Safety resource. Stored write-only: the admin surface shows whether a value is stored, never the value. | Empty | `content_safety_key` |
| APIM Content Safety Endpoint | The APIM API base URL fronting the Content Safety resource. | Empty | `azure_apim_content_safety_endpoint` |
| APIM Subscription Key | The APIM subscription key authorised for that API. Stored write-only. | Empty | `azure_apim_content_safety_subscription_key` |
| Safety Violation Message | Markdown that replaces the blocked message in the conversation. Say what to do next, since the user cannot see the cause unless trigger information is on. | Your message was blocked by Content Safety. | `content_safety_violation_message` |
| Show what triggered the block | Appends detected categories, severities and blocklist matches beneath the message. | On | `content_safety_include_trigger_information` |

## Session {#session}

### Idle Session Timeout {#idle-timeout-section}

An unattended browser on a shared or kiosk machine stays signed in indefinitely. This ends the local session after a period without interaction, with a warning first so nobody loses a message mid-compose.

This is a client-side timer, not a token lifetime. It closes the "walked away from the desk" gap; it does not shorten how long an issued token remains valid, which is an Entra Conditional Access decision.

The warning has to arrive before the sign-out it warns about. Set the two values equal to skip the warning entirely; a warning time beyond the sign-out time is lowered to match on save.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Sign out inactive users | Ends the local session after a period without interaction. | Off | `enable_idle_timeout`; capability toggle |
| Sign out after (minutes) | Inactivity before sign-out. Minimum 10, since anything shorter interrupts people reading a long response. | 30 | `idle_timeout_minutes` |
| Warn after (minutes) | When the warning dialog appears. Equal to the sign-out time disables the warning. | 28 | `idle_warning_minutes` |
| Idle Warning Message | Heading of the dialog offering to keep the session alive. | You've been inactive for a while. | `idle_warning_message` |

## Network {#network}

### Azure Front Door {#front-door-section}

Behind Front Door or a load balancer, the App Service sees its own internal hostname rather than the one users typed. Sign-in redirects built from that hostname send people back to a host they cannot reach, so authentication completes at Entra and then fails on the return trip with a Microsoft error page and nothing in your logs.

Enabling this makes the configured origin the base of every generated redirect. Two URIs are derived from it and both must be registered as redirect URIs on the Entra app registration before you save, or sign-in fails with a redirect mismatch:

- the origin itself, for the post-sign-in landing redirect
- the origin plus `/getAToken`, for the MSAL callback

Enter the origin only, with no path or query string.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Behind Azure Front Door or a load balancer | Builds sign-in and redirect URLs from the configured public origin instead of the App Service hostname. | Off | `enable_front_door`; capability toggle |
| Front Door URL | The public origin, scheme and host only. Must match a redirect URI registered on the Entra app registration. | Empty | `front_door_url` |

## Rate Limiting {#rate-limiting}

### Rate Limit Message {#rate-limit-message-section}

SimpleChat retries throttled calls with backoff, so most rate limiting is absorbed before anyone notices. This section covers what happens when that runs out: the request finally fails with HTTP 429 and the user has to be told something.

Without a message configured, a throttled chat response reads like an unexplained failure, which sends users straight to a retry loop or a support ticket. This matters most in deployments that front their model endpoints with API Management, where throttling is a deliberate capacity decision rather than a fault, and where the admin usually knows something useful to say: how long the window is, which quota was hit, or who to contact for more capacity.

The message is Markdown, so it can carry a link to an internal runbook or request form. It reaches every surface that returns a 429, including chat, text to speech, the Swagger specification endpoints, and inbound MCP tool calls.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Use a custom rate limit message | Replaces the built-in throttling explanation with your own wording. | Off | `enable_custom_rate_limit_message`; capability toggle |
| Rate Limit Message (Markdown supported) | The Markdown shown to a user whose request was refused with HTTP 429. Clearing it falls back to the built-in message, so users never receive an empty response. | You have reached the request limit. Too many requests were sent in a short period of time. Please wait a moment and try again. | `rate_limit_message` |

## Common tasks

1. **Require a role.** Assign the role in the Enterprise App first, then enable the requirement and sign in as both an assigned and an unassigned account. Outcome to verify: only the assigned account reaches the protected surface, and the unassigned one sees your Access Denied Message.
2. **Read the access policy.** Open App Role Requirements and check the enforced count against what you expect. Outcome to verify: no requirement is marked as having no effect unless you intended the feature it guards to be off.
3. **Move secrets to Key Vault.** Grant the identity Get, Set and List, enable Key Vault storage, run Test Key Vault connection, then rotate one low-risk secret. Outcome to verify: the test succeeds and the rotated secret still works in its agent or action.
4. **Turn on Content Safety.** Choose direct or APIM routing, supply credentials, run Test Content Safety connection, then send a prompt you expect to be blocked. Outcome to verify: the test succeeds and the blocked prompt shows your violation message.
5. **Move to a Front Door hostname.** Register both generated redirect URIs on the app registration, then enable Front Door support and sign in through the routed domain. Outcome to verify: sign-in completes and lands on the Front Door hostname.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Every administrator is locked out of a report | The role requirement was enabled before anyone was assigned the role. | Assign the role in the Enterprise App. The requirement itself can only be changed by an account that still holds admin access. |
| A role requirement is marked as having no effect | The feature it guards is switched off, so nothing is being restricted. | Enable the feature, or leave the requirement off until you do. |
| Sign-in returns a redirect mismatch error from Microsoft | One of the two generated redirect URIs is not registered on the Entra app registration. | Copy both from the Azure Front Door section and register them, then retry. |
| Sign-in redirects use the wrong host | Front Door support is off, or the origin is wrong or carries a path. | Enter the origin only and test sign-in through the routed domain. |
| An expiry alert names a secret nobody recognises | Secret names are content hashes, so the alert alone cannot identify an owner. | Look the secret name up in the tracked secret inventory under Key Vault. |
| Chat fails for everyone right after enabling Content Safety | The endpoint or credential is wrong, so every message fails the safety check. | Run Test Content Safety connection and correct the connection details. |
| A saved secret appears to have been cleared | The field was opened for replacement, a value was typed and then deleted, and the empty value was saved. | Re-enter the credential. Leaving the field blank without typing keeps the stored value untouched. |
| Throttled users still see the built-in rate limit wording | The custom message toggle is off, or the message was saved empty. | Turn on the custom message and save non-empty Markdown. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Governance settings]({{ '/admin/governance/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
