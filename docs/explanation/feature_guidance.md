---
layout: showcase-page
title: "Feature Guidance"
permalink: /explanation/feature_guidance/
menubar: docs_menu
accent: orange
eyebrow: "Explanation"
description: "Choose a capability rollout by its dependencies, access and data paths, operating responsibilities, and readiness checks."
version: "0.261.398"
hero_icons: ["bi-grid-1x2", "bi-signpost-split", "bi-stars"]
hero_pills: ["Foundational features first", "Dependency-aware rollout", "Optional packs after the core loop works"]
hero_links: [{ label: "Features overview", url: "/features/", style: "primary" }, { label: "Admin configuration", url: "/admin/", style: "secondary" }]
order: 130
category: Explanation
---

Choose features by the work people need to do, then verify the dependencies and
operating process. A capability being available is different from its services,
permissions, review queues, and support arrangements being ready.

This guidance accompanies the **0.261.398** capability snapshot. Use the
[feature catalog]({{ '/features/' | relative_url }}) for the capability stories
and the [features reference]({{ '/reference/features/' | relative_url }}) for
their service and configuration map.

## Start with the core loop

Prove that a user can sign in, reach the intended model, upload a suitable
document, and inspect a grounded answer. Choose the audience for that knowledge
before adding more content.

{% include media.html id="slide-workspace-scopes" %}

Personal workspaces support private working material; group workspaces support
membership-based collaboration; public workspaces offer curated knowledge to
signed-in application users, not anonymous visitors. Sharing and management
rights remain explicit. A classification label is not an access grant.

Follow [first configuration]({{ '/guides/admin-first-configuration/' | relative_url }})
and [upload and manage documents]({{ '/guides/upload-and-manage-documents/' | relative_url }})
to verify the loop with both an authorized reader and someone who should not
see the source.

## Layer governance deliberately

Decide the permitted users, sources, and destinations before opening a capability
widely. A successful connection test does not settle those access decisions.

{% include media.html id="slide-governance" %}

Use [Governance settings]({{ '/admin/governance/' | relative_url }}) to review
capability and delegated item access alongside approved tools and destinations.
[Security settings]({{ '/admin/security/' | relative_url }}) separately configure
Content Safety, screening checkpoints, and how chat behaves when a check cannot
finish. Test input findings, output findings, and service outages; do not assume
that enabling a master setting makes every checkpoint active.

Governance required by your organization belongs before production use, not at
the end of a feature rollout. Reviewer access, feedback handling, retention, and
recovery are operating responsibilities as well as configuration choices.

## Treat media as an expansion pack

Add audio, video, richer extraction, and generated images when there is a useful
task and an owner for their cost and failures. Speech, Video Indexer, extraction
engines, compatible image models, and storage have different availability and
permission requirements. A model that accepts image input is not automatically
an image-generation model.

Use [Knowledge settings]({{ '/admin/knowledge/' | relative_url }}) for ingestion
paths and [AI Models settings]({{ '/admin/ai-models/' | relative_url }}) for
task-compatible connections rather than assuming one model or Azure service
covers every format.

## Add agents after the platform is predictable

First prove the manual task and source boundaries. Then give an agent only the
approved actions it needs, review orchestration plans, or save a workflow when
the task should be repeatable.

[Agents with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
introduce tool credentials and external-system effects.
[Orchestration plan review]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }})
lets users inspect proposed operations.
[Saved workflows]({{ '/guides/create-a-workflow/' | relative_url }}) add run
definitions, schedules, results, and their associated lifecycle.
Workspace scope lock does not govern every web or integration call.

## Rollout groups

| Feature group | Readiness prerequisite | Outcome to verify |
| --- | --- | --- |
| Authentication, chat, model connections | Entra access, conversation storage, a compatible published model, and a support owner. | The intended user can complete chat; an unassigned user cannot bypass required access. |
| Workspace retrieval | Search, compatible embeddings, the required extraction path, and the intended workspace permissions. | A ready document is retrievable and cited only in the permitted scope. |
| Content checks, review, and lifecycle | Organization policy, configured checkpoints, reviewer roles, and retention/recovery decisions. | Findings and unfinished checks follow the chosen behavior; reviewers can act without overbroad access. |
| Classification, metadata, richer citations, and media | A demonstrated need, applicable storage and AI services, quota, and format-specific tests. | Enrichment or previews help the task and failures do not masquerade as successfully processed sources. |
| Agents, actions, and external research | Approved destinations, suitable model/tool capabilities, credentials, and applicable consent or approvals. | Expected calls succeed; disallowed sources and destinations remain unavailable. |
| Repeatable workflows | A tested task, permitted sources, runner connections, and an owner for schedules, alerts, and stored results. | A representative run records usable results and reports partial or failed work clearly. |

The groups are dependency guidance, not a promise that every diagrammed service
is deployed or every capability is appropriate for every tenant. Consult the
[architecture data paths]({{ '/explanation/architecture/#data-flow-and-processing' | relative_url }})
before approving additional outbound connections.

## Questions to ask before enabling a feature

1. Which user task improves, and how will we recognize a successful result?
2. Which service, quota, credential, or storage path does this add?
3. Who may use it, which sources may it read, and which destinations receive data?
4. What happens when a source, model, content check, or integration cannot finish?
5. Who owns review queues, support, retained outputs, and recovery?

## Practical guidance

- Start with a smaller, verified capability set rather than enabling everything.
- Use [Enable a capability safely]({{ '/guides/admin-enable-a-capability/' | relative_url }})
  to plan validation and rollback for each expansion.
- Review [Operations settings]({{ '/admin/operations/' | relative_url }}) and
  [scaling guidance]({{ '/guides/scale-simplechat-on-azure/' | relative_url }})
  before capacity becomes a user-facing failure.
- Treat saved analyses and workflow results as records of past work, not fresh
  source verification. Include them in sharing and lifecycle decisions.
- Rehearse [backup and recovery]({{ '/admin/backup-recovery/' | relative_url }});
  archiving is not legal hold and a saved backup is not a tested restore.
