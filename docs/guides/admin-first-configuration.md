---
layout: page
title: "Configure SimpleChat for the first time"
description: "Walk the Admin Settings tabs in the safest order after a successful SimpleChat deployment."
section: "Guides"
audience: admin
---

## What this covers

This guide gives administrators the first-run order for Admin Settings after deployment. It starts with identity-facing and security decisions, then configures models, retrieval, workspaces, and optional capabilities that depend on those foundations.

{% include media.html type="video"
                      title="Configure SimpleChat for the first time walkthrough"
                      poster="video-posters/guide-admin-first-configuration.png"
                      capture="Recording planned. Walk the full journey end to end and explain the decisions an admin makes along the way." %}

## Why it matters

Some Admin Settings tabs unlock experiences that depend on earlier tabs. Workspace search depends on embeddings and Azure AI Search. Agents depend on a working GPT model. Enhanced citations depend on storage. Role requirements depend on Entra app roles that already exist. Following the order below prevents users from seeing controls that cannot work yet.

## Before you start

- Finish deployment and verify an administrator can open Admin Settings.
- Have endpoint names, deployment names, authentication choices, and keys or managed identity assignments for the Azure resources that were deployed.
- Create required Entra app roles before enforcing role-gated features such as `CreateGroups`, `WorkflowUser`, `ChatFileUploadUser`, `SafetyViolationAdmin`, `FeedbackAdmin`, `UrlAccessUser`, or `DeepResearchUser`.
- Keep a non-admin test account available so you can verify what normal users see after each major change.

## Step 1: Set tenant identity, notices, and visible app behavior

Start with [General settings]({{ '/admin/appearance/' | relative_url }}). Publish the approved application title, logo, landing page copy, access-denied message, support destinations, health-check behavior, Terms of Use, AI notice, idle timeout, and upload/session limits. These are first because every user sees them before feature-specific settings matter.

{% include media.html src="guides/admin-first-configuration-general.png"
                      alt="General settings page showing tenant branding, terms, support, health check, and session controls."
                      title="Configure general settings first"
                      capture="Capture the General tab after tenant-facing copy and support controls are populated, with any private URLs redacted." %}

## Step 2: Configure secret handling before users create tools

Use [Security settings]({{ '/admin/security/' | relative_url }}) if the deployment will store agent or action secrets in Azure Key Vault. Enable Key Vault-backed secrets only after the vault exists and the configured identity can read and write the required secrets. Decide reminder recipients before enabling expiration reminder tracking or requiring expiration dates.

## Step 3: Configure chat and embedding models

Open [AI Models settings]({{ '/admin/ai-models/' | relative_url }}) and configure GPT routing before users test chat or agents. Configure embeddings before enabling document-heavy workspace use because retrieval depends on embeddings and Azure AI Search. Add image generation only after the image deployment, quota, and policy approval are ready.

{% include media.html src="guides/admin-first-configuration-models.png"
                      alt="AI Models settings page with chat and embedding endpoint sections configured."
                      title="Configure model endpoints"
                      capture="Capture the AI Models tab showing chat and embedding sections complete, with keys and subscription details redacted." %}

## Step 4: Configure search, extraction, and web evidence boundaries

Use [Search and Extract settings]({{ '/admin/knowledge/' | relative_url }}) next. Configure Azure AI Search, Document Intelligence, chunking, and extraction modes before promoting workspace uploads. If enabling URL Access, Web Search, Deep Research, Speech, or Video Indexer, configure limits, domain policy, roles, and backing service details before turning on user-facing controls.

## Step 5: Decide workspace scopes and data policies

Move to [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}) after model and retrieval prerequisites are ready. Enable only the personal, group, public, workflow, upload, download, retention, classification, and agreement capabilities the tenant has approved. Test role-gated behavior with assigned and unassigned users before wider rollout.

{% include media.html src="guides/admin-first-configuration-workspaces.png"
                      alt="Workspaces settings page showing enabled scopes, role requirements, retention, and agreement choices."
                      title="Set workspace scope and retention"
                      capture="Capture the Workspaces tab with approved scopes and retention controls visible." %}

## Step 6: Add citation storage when source previews are required

Configure [Citations settings]({{ '/admin/chat/' | relative_url }}) when users need richer source previews or tabular source access. Provision and authorize storage before enabling Enhanced Citations. Set tabular preview and large-run confirmation thresholds according to available memory and cost tolerance.

## Step 7: Enable safety review and feedback paths

Use [Safety settings]({{ '/admin/security/' | relative_url }}) after core chat works. Content Safety needs an Azure AI Content Safety resource or APIM route and matching authentication. Feedback and safety review role requirements should be enabled only after the `SafetyViolationAdmin` and `FeedbackAdmin` assignments are ready.

## Step 8: Roll out agents, actions, governance, and sync only after foundations pass

Configure [Agents settings]({{ '/admin/agents-actions/' | relative_url }}) after a GPT model works. Use [Governance settings]({{ '/admin/governance/' | relative_url }}) before opening broad user-created endpoints, agents, actions, or MCP destinations. Enable [File Sync settings]({{ '/admin/knowledge/' | relative_url }}) only after target workspace scopes exist and ingestion limits are set.

## Step 9: Turn on operational controls

Finish the first configuration pass with [Logging settings]({{ '/admin/operations/' | relative_url }}), [Scale settings]({{ '/admin/scale/' | relative_url }}), [Control Center settings]({{ '/admin/operations/' | relative_url }}), and [Backup, Migrate & Restore settings]({{ '/admin/backup-recovery/' | relative_url }}). Logging, backups, cache behavior, Front Door support, and throughput automation should be ready before the environment becomes business critical.

## Verify it worked

- A non-admin test user sees only approved navigation, workspace scopes, and optional controls.
- Basic chat works with the configured GPT model.
- A representative document can be uploaded, extracted, indexed, and used in grounded chat.
- Role-gated actions are visible to assigned users and hidden or blocked for unassigned users.
- Logging and backup settings are ready for day-two operations.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Workspace answers do not use uploaded documents | Embeddings, Azure AI Search, or extraction settings are incomplete | Revisit [AI Models settings]({{ '/admin/ai-models/' | relative_url }}) and [Search and Extract settings]({{ '/admin/knowledge/' | relative_url }}), then re-test ingestion. |
| Users cannot create groups or workflows after the toggle is enabled | The matching Entra app role requirement is on but assignments are missing | Assign the app role or disable the requirement until assignments are complete. |
| Agent controls appear but agents fail | Agents were enabled before a working GPT endpoint was available | Validate chat model routing, then return to [Agents settings]({{ '/admin/agents-actions/' | relative_url }}). |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Enable a capability safely]({{ '/guides/admin-enable-a-capability/' | relative_url }})
- [Operate SimpleChat day to day]({{ '/guides/admin-operate-simplechat/' | relative_url }})
