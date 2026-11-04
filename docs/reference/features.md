---
layout: page
title: "Features Reference"
permalink: /reference/features/
menubar: docs_menu
description: "Connect Simple Chat capabilities to their service dependencies, access boundaries, readiness checks, and operational guides."
version: "0.261.398"
---

Use the [feature catalog]({{ '/features/' | relative_url }}) to explore what a
capability does. Use this operator map to connect that capability to the services,
permissions, and verification work behind it. The illustrations reflect
capability snapshot **0.261.398**, not a guarantee that every deployment enables
every capability.

## Conversation surface

Chat combines configured models with optional workspace retrieval, source
citations, saved prompts, and reusable conversation context. Model availability
is a connection and governance decision, not a fixed model default in this guide.

[Conversation details]({{ '/features/conversation-details/' | relative_url }})
and [message details]({{ '/features/message-details/' | relative_url }}) help
readers inspect context and sources. [Generated deliverables]({{ '/features/generated-deliverables/' | relative_url }})
are outputs to review and download, not proof that the underlying answer is
correct.

## Workspace ingestion

Personal, group, and public workspaces organize different audiences for
knowledge. Public content is shared with signed-in application users, not
anonymous visitors. Uploads use format-specific extraction, chunking, embeddings,
and indexing; Document Intelligence is not the parser for every file format.

[Enhanced Citations]({{ '/features/enhanced-citations/' | relative_url }}) adds
storage-backed source inspection.
[Analyze and Compare]({{ '/features/document-analysis/' | relative_url }})
work with selected sources and bounded evidence; ordinary retrieval remains
relevance-bounded. Labels and metadata organize content without granting access.

## Governance and safety

Application roles, workspace permissions, feature policies, and external
destination controls solve different problems. Content Safety and Content
Screening add configured checks; input/output coverage, display timing, and
unfinished-check behavior must be chosen and tested.

Retention, conversation archiving, and feedback review also need an operating
process. Archiving is not legal hold, and backups need recovery testing.
Use [Security]({{ '/admin/security/' | relative_url }}),
[Governance]({{ '/admin/governance/' | relative_url }}), and
[Backup and Recovery]({{ '/admin/backup-recovery/' | relative_url }}) to map
those responsibilities.

## Agents and integrations

[Agents]({{ '/features/agents/' | relative_url }}) reuse a role and instructions;
[actions]({{ '/features/core-actions/' | relative_url }}) connect them to approved
tools. [Orchestration]({{ '/features/chat-orchestration/' | relative_url }})
can turn a goal into a plan for review, while
[saved workflows]({{ '/features/workflows/' | relative_url }}) make supported
tasks repeatable.

Each model endpoint, API, Microsoft 365 connection, or MCP destination needs its
own access and data-sharing review. Workspace scope lock is not an immutable
source snapshot or a universal boundary on these external tools.

## Use the narrative page and the reference page differently

The [catalog]({{ '/features/' | relative_url }}) carries capability explanations
and full-slide illustrations. [Feature guidance]({{ '/explanation/feature_guidance/' | relative_url }})
helps choose a rollout sequence. This reference connects them to dependencies;
the [guides]({{ '/guides/' | relative_url }}) teach the actual tasks.

## Feature map by operating area

{% include media.html id="slide-azure-services" %}

The full slide is a logical service map, not a mandatory bill of materials.
Additional processing, storage, protection, gateways, and caching apply only to
the capabilities and operating patterns that use them.

| Area | Capability and dependency story | Configuration and task guidance |
| --- | --- | --- |
| Chat and model routing | A compatible published model connection, sign-in, and conversation storage establish the basic chat path. Chat, image, and embedding defaults are separate. | [AI Models]({{ '/admin/ai-models/' | relative_url }}), [Configure AI Connections]({{ '/guides/configure-ai-connections/' | relative_url }}) |
| Grounded workspace knowledge | Search and compatible embeddings retrieve indexed content. The file format and enabled extraction/media paths determine processing dependencies. | [Knowledge]({{ '/admin/knowledge/' | relative_url }}), [Upload and manage documents]({{ '/guides/upload-and-manage-documents/' | relative_url }}) |
| Citations, Analyze, and Compare | Storage-backed Enhanced Citations supports richer source access and native spreadsheet/mixed-source handling. Analysis still has selected-source, coverage, and validation limits. | [Chat settings]({{ '/admin/chat/' | relative_url }}), [Read saved Analyze results]({{ '/guides/analyze-results/' | relative_url }}) |
| Content checks and review | Content Safety needs its service connection; screening uses applicable saved rules and optionally a scanner model. Workspace screening also needs Enhanced Citations storage. | [Security]({{ '/admin/security/' | relative_url }}), [Review screened documents]({{ '/guides/review-screened-documents/' | relative_url }}) |
| Agents, actions, and orchestration | Enabled capabilities, suitable models, approved destinations, and connection credentials constrain the tools a plan can use. | [Agents and Actions]({{ '/admin/agents-actions/' | relative_url }}), [Orchestration]({{ '/admin/orchestration/' | relative_url }}), [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }}) |
| Repeatable workflow automation | Saved definitions, source permissions, runner connections, and applicable schedules or approvals determine what a run can do. Stored results describe that run, not fresh source verification. | [Workflow settings]({{ '/admin/workflow/' | relative_url }}), [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }}) |
| Operations and scale | Shared sessions and coordination precede web scale-out; Cosmos DB, Search, and AI quota need separate sizing. Logging and Azure routing determine observability. | [Scale]({{ '/admin/scale/' | relative_url }}), [Operations]({{ '/admin/operations/' | relative_url }}), [Scale Simple Chat]({{ '/guides/scale-simplechat-on-azure/' | relative_url }}) |

For the actual application/data boundaries and optional outbound paths, read
[Architecture]({{ '/explanation/architecture/' | relative_url }}). The
application hosting region alone does not establish where every configured
model or integration processes content.

## Readiness is more than enablement

Before publishing a capability to users:

1. Test the saved connection and a representative operation, including the
   expected model task, extraction format, or external action.
2. Verify both permitted and denied access using the intended user and workspace
   roles. A successful administrator test does not prove a user's access.
3. Exercise missing dependencies, throttling, and configured check failures.
   Confirm that partial or unchecked work is not presented as verified success.
4. Assign owners for cost, review queues, retained outputs, and recovery.

The [capability rollout guide]({{ '/guides/admin-enable-a-capability/' | relative_url }})
provides a repeatable enable/verify/rollback process.

## Where to go deeper

### Admin settings

Use the [admin reference]({{ '/admin/' | relative_url }}) for settings,
prerequisites, roles, and service tests rather than assuming a capability has a
single independent switch.

### Workflows

For user-authored automation, follow
[Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }}),
[Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }}), and
[Ask about workflow results]({{ '/guides/ask-about-workflow-results/' | relative_url }}).
For the application's internal ingestion and grounded-request pipelines, use
[Application workflows]({{ '/reference/application-workflows/' | relative_url }}).

### Latest release changes

[Latest release highlights]({{ '/latest-release/' | relative_url }}) explain
recent changes separately from this long-lived dependency map.

### Tutorials and how-to guides

Choose a practical task in the [guides]({{ '/guides/' | relative_url }}), or start
with [first configuration]({{ '/guides/admin-first-configuration/' | relative_url }})
when the deployment is new.
