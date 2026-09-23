---
layout: page
title: "Model Catalog"
description: "Describe model strengths, manage shared profiles, and influence per-step orchestration without changing deployment access."
section: "Administration"
audience: admin
admin_tab: model-catalog
version: "0.261.126"
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

## Favorites and priority

Favorites and priority are organization-wide preferences, not chat defaults.
In V2 orchestration's explicit **Auto** mode, eligibility comes first, followed
by task suitability, priority, favorite, and a stable identity tie-breaker.
A preferred general-purpose model does not displace a better documented specialist.

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
profile declarations. The separate **Catalog model ID** capacity setting still
controls audited numeric identity: a descriptive profile association does not
invent context limits, reasoning policies, or provider-specific operation support.

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
Unknown task support, incompatible capabilities, archived profiles, and documented
Responses-only models cannot be repaired by marking a profile Favorite. The
existing deployment-specific token guards still apply during execution; Auto
does not truncate evidence or silently swap models after a budget failure.

See [Choose models for orchestration]({{ '/guides/model-catalog-routing/' | relative_url }})
for the user workflow and [AI Models settings]({{ '/admin/ai-models/' | relative_url }})
for connection configuration.
