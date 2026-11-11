---
layout: page
title: "Model Catalog"
description: "Describe model strengths, manage shared profiles, and influence per-step orchestration without changing deployment access."
section: "Administration"
audience: admin
admin_tab: model-catalog
version: "0.261.429"
---

# Model Catalog

Implemented in version: **0.261.126**.

## Profiles versus connections

The Model Catalog describes what a model is good at. AI Connections supplies the
actual endpoint, credentials, request name, and enabled deployments. A profile
alone cannot receive a request or grant access to a deployment.

Use **Admin Settings > AI Models > Model Catalog** in either classic or React V2.
Search by model name, identifier, alias, or summary; filter by publisher, task,
capability, origin, favorites, global connection availability, or archived status.
The detail panel explains task suitability, limitations, technical evidence,
and the global models using that profile. Personal and group connections remain
managed in their own workspaces; the catalog does not expose their deployment lists.

## Update built-in metadata without deploying

Implemented in version: **0.261.425**, tracked in
`application/single_app/config.py`.

Use **Catalog updates** to inspect the installed revision and publication date.
These updates change metadata understood by the installed application, not provider
client code. An installation needs one application upgrade to gain this workflow;
subsequent compatible catalog revisions do not need `azd deploy` or a restart.

| Setting | Default | Purpose |
| --- | --- | --- |
| `enable_model_catalog_online_updates` — Allow online catalog update checks | Disabled | Permits an administrator to explicitly contact the official GitHub catalog source from this deployment. Offline signed uploads remain available without this permission. |

The interface displays the repository and exact discovery URL before online access
is enabled. **Check for updates** reads
`https://raw.githubusercontent.com/microsoft/simplechat/model-catalog/model-catalog/latest.json`.
Packages come from the same repository at an immutable Git commit; the resolved
download URL appears in the check result. The destination cannot be edited in the
browser, settings, or a package. Outbound requests do not include chats, documents,
AI connection settings, or credentials. Repeated checks are limited to one per minute.
The existing application-release check is separate and is not changed by this setting.
Since **0.261.428**, isolated publisher test deployments can select the fixed
development feed with the server startup policy `MODEL_CATALOG_CHANNEL=development`.
Their interface displays that development URL. Normal customer deployments remain
on the production feed and reject development-signed packages; this is not an
administrator-editable URL or an unsigned testing bypass.
Since **0.261.426**, **Allow online catalog update checks** uses the standard
on/off switch in both classic and V2, matching the other admin settings.

After a successful check, choose **Preview available update**. Alternatively, download
the publisher's signed package and select **Upload signed package**, including on an
offline installation. Both paths require a signature from a public key bundled with
SimpleChat. An ordinary unsigned catalog JSON file is not an import package.

Review the signature, version, source commit, package digest, model additions and
changes, and operation-metadata change indicator. **Apply catalog update** changes
the shared active revision only after validation and a concurrency check. Uploading,
checking, and previewing alone do not install it. Custom profiles, priorities,
favorites, connection credentials, and deployment overrides remain unchanged.

**Preview rollback** reviews the previous verified revision or, after the first
import, the catalog bundled with the application. Apply rollback separately.
Updates and rollback cannot remove model IDs, because personal/group connections
may still reference them. An incompatible schema, unknown publisher key, broken
signature, removed ID, or conflicting custom alias blocks installation.

If another administrator changes settings, reload update status and preview again.
If the active shared catalog cannot be read, affected new model operations fail
rather than quietly changing technical facts back to the bundled catalog.

An unconfigured publisher key is shown explicitly and prevents signed imports.
Public keys are not credentials and do not require a customer Key Vault.
Publisher setup and key rotation are described in
[Signed model catalog updates]({{ '/explanation/features/SIGNED_MODEL_CATALOG_UPDATES/' | relative_url }}).

## Find and inspect a profile in V2

V2 lays the catalog out as a workbench. Search and the filters sit across the top:
**Origin**, **Task strength**, **Publisher**, **Capability**, **Connections**, and
**Status**, with **Favorites only** beside the search. **Clear filters** resets the
filters and keeps the search text.

Each profile in the list is one line: its name, its publisher, and the number of
global AI Connection models that use it. The list and the selected profile scroll
separately, so a long catalog does not push AI Connections further down the page.

The selected profile shows its publisher, origin, evidence source, and lifecycle
stage, its **Favorite** and **Priority** preferences, and four tabs:

| Tab | What it shows |
| --- | --- |
| Overview | Strengths, limitations, and a rating for every task: Strong, Suitable, Unsuitable, or Unknown. |
| Capabilities | Which inputs, outputs, and features are supported, unsupported, or unknown, with documented token limits and lifecycle. |
| Connections | The global models that use the profile, whether each is enabled, and the capabilities each model ends up with. |
| Evidence | Where the ratings come from, the profile ID, its HTTPS sources, and its aliases. |

Select the connected-model count on a row to open that profile's **Connections**
tab. **Open in AI Connections** opens the model's connection editor with that model
outlined, which is where its **Catalog profile** association is changed. When a
settings search had hidden AI Connections, the search is cleared first.

The classic interface keeps its existing catalog layout. The V2 workbench was
implemented in **0.261.258**.

## Favorites and priority

Favorites and priority are organization-wide preferences, not chat defaults.
In V2 orchestration's explicit **Auto** mode, eligibility comes first, followed
by task suitability, priority, favorite, and a stable identity tie-breaker.
A preferred general-purpose model does not displace a better documented specialist.
When no connected model is rated for a step's task, Auto ranks the capable models
by their general-answering suitability instead, and the step's reason says so.

| Preference | Effect |
| --- | --- |
| Favorite | Breaks a tie after suitability and priority; also supports the favorites filter |
| Preferred | Ranks ahead of Standard and Lower at equal suitability |
| Standard | Default priority for a profile without an administrator preference |
| Lower | Keeps an eligible profile available but ranks it below equal-fit alternatives |

These preferences never enable a connection, bypass governance, alter an agent's
configured model, or replace a user's manually pinned selection.

## Create and associate a custom profile

Choose **Add custom profile**, or inspect a built-in profile and choose
**Duplicate as custom**. Give it a recognizable name, describe its strengths and
limitations, and declare task suitability and technical support. Leave unverified
capabilities **Unknown** rather than treating a descriptive claim as evidence.
Evidence links must use HTTPS and contain no credentials.

Save the profile, then edit an existing model in **AI Connections** and choose
its **Catalog profile**. Save that connection using the interface's normal save
workflow. One profile can describe several deployments. Its immutable identity
does not replace the model's deployment name or request identifier.

Explicit model capability overrides take precedence over endpoint overrides and
profile declarations. Since **0.261.410**, explicitly choosing a built-in model in
the V2 connection editor also fills **Catalog model ID** from that verified model
and the underlying model name on native Azure connections.
The deployment/request name, Custom gateway route, authentication, publication,
and existing overrides remain unchanged. Choosing **Automatic exact match** restores
name matching when the canonical ID came from the previous built-in selection.

Custom profiles, imported descriptive associations, and profile preferences do
not invent numeric identity or provider-specific operation support. **Catalog
model ID** remains the technical identity used to look up audited capacities,
model policies, and native Foundry contracts. The implementation version is tracked
in `application/single_app/config.py`.

## Evidence, bounds, and lifecycle

Built-in facts are read-only. Some profiles have publisher-reviewed task strengths;
others conservatively derive suitability from existing capability evidence. Neither
is a benchmark, price estimate, or latency promise. Custom profiles are labeled
administrator-declared, never publisher-verified.

Custom names allow 160 characters, publisher names 120, and summaries 1,200.
Strengths, limitations, aliases, and evidence each allow up to 12 entries of
500 characters. Aliases cannot collide with another profile. The catalog supports
200 custom profiles and a maximum serialized catalog size of 512 KiB.

Archive a custom profile to remove it from new profile choices and Auto routing.
Existing manual links remain readable and do not silently detach. Unarchive to
offer it again. Technical edits invalidate approved Auto bindings; preference-only
edits affect new plans without rerouting a plan already approved.

## Save conflicts and unavailable models

Catalog saves use optimistic concurrency. If another administrator changes the
settings while you edit, a conflict preserves your form instead of overwriting
their work. Copy any draft content you need, reload the catalog, and review the
current profile before saving again.

Auto uses only enabled, published connections the requesting user can access.
Incompatible capabilities, archived profiles, a task marked **Unsuitable**, and
documented Responses-only models cannot be repaired by marking a profile Favorite.
**Unknown** task support never outranks a model rated for that task. It matters only
when no connected model is rated for the task, and then only through the profile's
general-answering suitability. Rate the task explicitly when you know how a model
performs it. The existing deployment-specific token guards still apply during
execution; Auto does not truncate evidence or silently swap models after a budget
failure.

See [Choose models for orchestration]({{ '/guides/model-catalog-routing/' | relative_url }})
for the user workflow and [AI Models settings]({{ '/admin/ai-models/' | relative_url }})
for connection configuration.
