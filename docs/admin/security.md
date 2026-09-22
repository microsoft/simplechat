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

Agents, actions, and AI Connections hold credentials: API keys for the services they call, subscription keys for gateways in front of them. By default those live in the settings document. Enabling Key Vault stores supported application-managed credentials in Azure Key Vault instead, leaving only a reference behind, which is what deployments with a policy against secrets at rest outside a vault need.

Treat enabling this as one-way. Secrets saved afterwards are referenced by name, so turning it back off leaves those references pointing at values the application can no longer read, and every agent and action depending on them stops working.

Assign **Key Vault Secrets Officer at the vault scope** to the application's selected managed identity. **Key Vault Secrets User is read-only**: it can read existing secrets but cannot save new credentials. Leave the managed identity client ID blank for the App Service system-assigned identity, or supply the client ID of the attached user-assigned identity. Permissions on the deploying administrator do not give the application access. A vault using legacy access policies needs **Get, List, Set, and Delete** secret permissions.

**Permission test (0.261.125).** Before saving a vault change, run **Test Key Vault connection** in either interface. The test uses the draft vault and identity, lists secret properties, writes a uniquely named `simplechat-connection-test-*` secret containing a synthetic value, reads it back, and deletes it. Success requires every stage, including cleanup; it never changes existing secrets or purges deleted secrets.

The temporary secret expires after ten minutes, but expiration is not deletion. If cleanup cannot be confirmed, the result identifies the generated secret for an administrator to remove. Soft-deleted test metadata remains under the vault's retention policy. Do not remove other application secrets when cleaning up a test.

A denied-write result or save error names the missing permission rather than suggesting that a successful list operation proves write access. Check the identity, vault-scoped role or access policy, propagation of a recent role assignment, and network restrictions. A failed secret write does not fall back to storing the submitted credential as plaintext. See [Admin settings troubleshooting]({{ '/troubleshooting/#admin-settings-saves-and-connection-tests' | relative_url }}).

**Expiration reminders.** Secret names written by SimpleChat are content hashes, so a Key Vault expiry alert from Azure names something like `sc-a1b2c3` and nothing an operator can act on. Reminder tracking records the missing half: which user or group owns each secret, which action and field it backs, and who to contact. The tracked secret inventory in this section is the lookup from an opaque secret name back to that context.

SimpleChat does not send the reminder emails. It raises them in-app and emits an Application Insights event named `key_vault_expiration_reminder_triggered`. Route that to a recipient with an Azure Monitor scheduled query alert, a Logic App, a Function, or a webhook, and keep the vault's own expiry alerts configured in Azure Monitor or Event Grid as well.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Store agent and action secrets in Key Vault | Writes agent and action credentials to Azure Key Vault and keeps only a reference in the settings document. | Off | `enable_key_vault_secret_storage`; capability toggle |
| Key Vault Name | The vault resource name, not a URL. The endpoint suffix comes from the `AZURE_ENVIRONMENT` App Service setting. | Empty | `key_vault_name` |
| Key Vault Managed Identity Client ID | Selects the user-assigned identity granted vault-scoped Secrets Officer, or equivalent Get, List, Set, and Delete secret permissions. Blank uses the App Service system-assigned identity. | Empty | `key_vault_identity` |
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

## Content Screening {#content-screening}

### Policies and scans {#content-screening-section}

Content screening applies saved PII, regex, literal, and optional model rules at administrator-selected checkpoints. Workspace uploads retain their hold-and-review workflow. Submitted chat messages and AI reply text can use the same global baseline without inheriting workspace-specific additions.

Workspace screening requires Enhanced Citations and reuses its storage account for private evidence and clean derivatives. Chat-only checks do not require that storage: turn off **Screen workspace uploads** before enabling the master for chat-only use. Administrators define required baseline rules; workspace managers can add document checks without weakening that baseline. This is separate from Azure AI Content Safety below.

Open **Admin Settings > Security > Content Screening** in either interface. The tab and policy editor remain visible without Enhanced Citations. The storage prerequisite applies to uploads and explicit document scans, not to chat-text checkpoints. Content Screening does not depend on **Enable Content Safety**.

You can enable Content Screening before choosing checks. First activation creates an enabled empty baseline if no policy has been saved; it never replaces an existing policy or activates a deliberately disabled baseline. In V2, change **Enable Content Screening**, then use **Save changes**. The classic master switch saves immediately with the current upload selection; other checkpoint and behavior controls use the main Save button.

Use **Save screening policy** to persist rules and model criteria independently of the main Admin Settings save. An enabled policy with no checks is valid and stays enabled after saving. New uploads follow normal processing when their effective policy has no checks; no screening result or hold is created. Enabled workspace additions can supply checks even when the baseline is empty. Adding checks later screens subsequent uploads; use an explicit workspace scan for existing knowledge.

Both editors provide **Add literal rule**, **Add regex rule**, and **Add PII rule**, plus the same four **Starter rule pack** choices. Deterministic rules run in code, not through a model. Adding a pack again leaves existing rules and their edits intact.

**Enable AI checks** controls the actual scanner for that policy. Select one **Scanner model**, supply or adapt starter criteria, and choose its page/chunk window. When AI checks are off, those controls are disabled and their saved values are retained. This does not disable AI used independently for extraction, embeddings, or other application features.

The separate **Models workspaces may use** section is a permission list, not additional scanners to execute. It remains editable while baseline AI checks are off. The baseline's saved scanner is automatically permitted; its marked checkbox does not create an additional explicit permission. Workspace managers must enable their own AI check to use a permitted model.

The **Configured screening checks** summary describes the current draft and explicitly identifies an enabled policy with no active checks. Workspace summaries include required administrator checks even when local additions are off. A disabled baseline makes workspace additions inactive; emptying a policy or disabling future scans never releases an existing document hold. Sample testing requires a check to evaluate, but an empty policy can still be saved.

Added in **0.261.106**; admin discovery and save feedback corrected in **0.261.107**; classic/V2 policy-editor alignment implemented in **0.261.108**; enabled-empty policy configuration implemented in **0.261.114**, tracked in `application\single_app\config.py`. See [Screen and review workspace documents]({{ '/guides/review-screened-documents/' | relative_url }}) for policy selection, existing-workspace scans, reviewer roles, and remediation limits.

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Content Screening | Makes the selected checkpoints use the saved screening policies. Disabling it does not release document holds or restore removed replies. | Off | `enable_content_screening`; creates an enabled empty baseline if absent |
| Screen workspace uploads | Keeps new workspace content out of knowledge use until its applicable checks and review finish. Existing holds stay enforced when this is disabled. | On beneath the master | `enable_content_screening_workspace_uploads`; requires Enhanced Citations and working storage |
| Screen submitted chat messages | Checks submitted text against the global baseline before it reaches the answering model or chat actions. | Off | `enable_content_screening_chat_input`; includes chat retries and message edits |
| Screen AI replies | Checks complete reply text against the global baseline and replaces replies with confirmed findings. | Off | `enable_content_screening_chat_output`; uses the shared chat behavior controls below |

**Chat checkpoints implemented in version: 0.261.127**, tracked in `application/single_app/config.py`. Empty policies remain valid for document configuration, but an enabled chat checkpoint without usable checks records **not checked**, never a passing scan. Review the configured rules before enabling that checkpoint.

## Content Safety {#content-safety}

### Content Safety {#content-safety-section}

Choose whether submitted messages, AI replies, or both are sent to Azure AI Content Safety. A category severity of 4 or higher, or a returned blocklist match, is a finding. Submitted-message findings stop the request; reply findings replace the answer with a neutral content-check notice.

Content Safety can reach the service directly or through Azure API Management. Route it through APIM when the rest of your Azure AI traffic already goes that way, so this traffic is subject to the same policy, quota and logging. Direct connections authenticate with a key or with the App Service managed identity; managed identity avoids storing a key and needs the Cognitive Services User role on the resource.

Test the connection before saving. By default, a check that cannot finish allows chat to continue without a technical warning to the user and records private **not checked** metadata for administrators. Choose the stricter failure action below when an unavailable check should stop the request instead.

**Trigger information** appends safe category and severity information to blocked-input notices. The expanded chat checks do not echo matched sensitive values, and removed-output notices do not repeat the rejected answer. AI-generated findings are not user misconduct and cannot be used to warn, suspend, or block the user through the remediation actions.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Content Safety | Makes Azure AI Content Safety available at the selected chat checkpoints. Its existing document-metadata behavior is unchanged; this does not add full-file safety scans. | Off | `enable_content_safety`; master switch |
| Check submitted messages with Content Safety | Screens typed requests before they reach a model or action. | On beneath the master | `enable_content_safety_chat_input`; preserves existing input coverage |
| Check AI replies with Content Safety | Inspects the complete reply text and removes confirmed violations. | Off | `enable_content_safety_chat_output`; optional output checkpoint |
| Route through Azure API Management | Sends Content Safety calls to an APIM front end rather than the service endpoint. | Off | `enable_content_safety_apim`; capability toggle |
| Content Safety Endpoint | The resource endpoint from the Content Safety resource in Azure. Used for direct connections. | Empty | `content_safety_endpoint` |
| Authentication Type | Whether a direct connection authenticates with a key or the App Service managed identity. | key | `content_safety_authentication_type` |
| Content Safety Key | Either key from the Content Safety resource. Stored write-only: the admin surface shows whether a value is stored, never the value. | Empty | `content_safety_key` |
| APIM Content Safety Endpoint | The APIM API base URL fronting the Content Safety resource. | Empty | `azure_apim_content_safety_endpoint` |
| APIM Subscription Key | The APIM subscription key authorised for that API. Stored write-only. | Empty | `azure_apim_content_safety_subscription_key` |
| Safety Violation Message | Markdown that replaces the blocked message in the conversation. Say what to do next, since the user cannot see the cause unless trigger information is on. | Your message was blocked by Content Safety. | `content_safety_violation_message` |
| Show what triggered the block | Appends safe detected-category and severity details to blocked-input notices. Output notices remain generic. | On | `content_safety_include_trigger_information` |

## Chat check behavior

These controls live under **Content Screening > Chat check behavior (both scanners)** and apply to both scanners. Content Safety links to the same controls; there are not two competing copies.

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| When to show AI replies | Streams provisional text and checks it at completion, or holds reply text until checking finishes. A confirmed finding replaces the entire reply, not just matching characters. | Stream first, then remove flagged replies | `chat_content_output_mode`: `stream_then_check` or `check_before_display` |
| When a chat check cannot finish | Allows content without a technical warning and queues private metadata for review, or stops messages/removes unchecked replies. A finding always wins over allow-on-error. | Allow quietly and mark not checked for admins | `chat_content_scan_failure_action`: `allow_unchecked` or `block`; does not change document holds or access controls |

Streaming first is **post-response moderation**. Removing an answer cannot undo text already read, copied, downloaded, or sent elsewhere. Checking before display avoids showing provisional reply text, but still follows the failure action when a check cannot finish.

Use **Review unchecked chat content** to open the protected report. It lists incomplete checks without duplicating message bodies, and offers a revision-bound **Recheck** action. A later finding automatically removes an AI reply from stored chat and shared representations. Outages remain retryable; old submitted-message findings are recorded for review rather than pretending earlier model calls can be undone.

See [Recheck chat content]({{ '/guides/recheck-chat-content/' | relative_url }}) for the workflow and [Chat content checks]({{ '/explanation/features/CHAT_CONTENT_CHECKS/' | relative_url }}) for the coverage boundary.

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
