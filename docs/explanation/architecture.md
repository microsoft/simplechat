---
layout: showcase-page
title: "Architecture"
permalink: /explanation/architecture/
menubar: docs_menu
accent: slate
eyebrow: "Explanation"
description: "Understand the major platform layers in Simple Chat and how data, AI services, identity, and operations interact."
version: "0.261.398"
hero_icons: ["bi-diagram-3", "bi-hdd-network", "bi-cpu"]
hero_pills: ["Application, data, and AI layers", "Security and scale concerns", "Azure-native service composition"]
hero_links: [{ label: "Explanation index", url: "/explanation/", style: "primary" }, { label: "Design principles", url: "/explanation/design_principles/", style: "secondary" }]
order: 110
category: Explanation
---

Simple Chat coordinates identity, conversations, workspace knowledge, and
configured AI services. Use this page to locate responsibilities and data paths;
use the linked operational guides to configure and test them.

The full-slide illustrations describe capability snapshot **0.261.398**. They
are logical architecture views, not proof of a particular network topology,
service entitlement, compliance certification, or data-residency arrangement.

## System Overview

The application runs the request flow. Cosmos DB holds application records,
Azure AI Search holds the workspace retrieval indexes, and configured model and
processing services perform the AI operations a capability needs.

### Core Principles

- **Identity is not authorization.** Sign-in identifies the user; application
  roles, governance policies, workspace membership, and source access determine
  what that user may do.
- **Capabilities have dependencies.** A model connection does not automatically
  configure extraction, citations, media processing, or external tools.
- **Scaling requires shared state and coordination.** Adding web instances does
  not add Search capacity or model quota.

## High-Level Architecture

{% include media.html id="slide-azure-services" %}

The slide groups the Azure services that can participate in a deployment.
App Service, identity, application records, and configured models form the chat
foundation. Grounded workspace search adds Search, embeddings, and a suitable
extraction path. Storage, Content Safety, media services, APIM, and Redis enter
the design according to the enabled capabilities and operating requirements.
Not every pictured service is mandatory for every use case.

## Core Components

### Application Tier

The Python/Flask backend handles conversation and document APIs, configuration,
authentication and authorization, and calls to configured services. The classic
web interface and React V2 expose those capabilities through their respective
controls. The diagram does not imply separately deployed chat, document, and
admin microservices.

For supported deployment choices, start with
[Choose a deployment path]({{ '/start/deployment-options/' | relative_url }}).

### Data Layer

| Component | Responsibility | Important boundary |
| --- | --- | --- |
| Azure Cosmos DB | Conversations, document records and processing status, users, groups, settings, and other application records. | A document record is not the searchable content or the original file. |
| Azure AI Search | Chunk text, vectors, and retrieval metadata in personal, group, and public workspace indexes. | Query scope and current source authorization still constrain retrieval. |
| Azure Storage | Source/preview files for Enhanced Citations and storage-backed outputs where configured. | Blob storage access, application access, and retention need their own configuration. |

Classification and tags describe or filter documents; they do not grant access.
Workspace permissions and authorized sharing remain the access controls.
See [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}) and
[Knowledge settings]({{ '/admin/knowledge/' | relative_url }}).

### AI Services Layer

Chat, embeddings, and image generation use configured connections and compatible
models, with separate task defaults. Available models depend on the provider,
cloud, deployment, permissions, and published capabilities; this architecture
does not prescribe a fixed model generation or embedding model.

Document Intelligence processes PDF/image extraction paths. Enhanced extraction
can use Content Understanding where configured and available; other file types
have their own parsers. Speech and Video Indexer support enabled media paths.
Content Safety is a separate, configurable check rather than a universal
pre-processing step for every operation.

Use [AI Models settings]({{ '/admin/ai-models/' | relative_url }}) for
connections and [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
for extraction, search, and media dependencies.

## Data Flow and Processing

{% include media.html id="slide-data-paths" %}

Keep the core data stores distinct from services that receive content during
processing. A request can send relevant text to a configured model, an extraction
service, or an approved integration without moving the whole application into
that service.

Before enabling an outbound path, review its destination, authentication,
permitted content, network reachability, and retained results:

- **Models and processing:** selected endpoints or gateways receive the content
  needed for the requested operation.
- **Web research:** Web Search, URL Access, and Deep Research introduce paths
  outside workspace retrieval and have separate consent or destination policy.
- **Microsoft 365, APIs, and MCP:** the connection's credentials, tool permissions,
  and applicable approvals determine what it can read or change.

Neither the application region nor the boundary in the slide establishes that
every optional destination is in the same tenant, cloud, or geography.

### Document Ingestion Workflow

An authorized upload is routed by format, extracted, split into retrieval units,
embedded, and indexed. Cosmos DB tracks its parent record and processing state;
configured storage retains the files or derivatives used by citations and other
features. Applicable document screening can hold content before knowledge use.

Processing and indexing are separate operations. Verify that a file is ready
and retrievable rather than treating upload acceptance as successful ingestion.
See [Upload and manage documents]({{ '/guides/upload-and-manage-documents/' | relative_url }})
and the [ingestion walkthrough]({{ '/reference/application-workflows/#add-your-data-workflow' | relative_url }}).

### Chat Processing Workflow

For grounded chat, the application retrieves relevant authorized excerpts and
combines them with the current request and applicable history for the selected
model. Configured input and output checks can affect that path. The response is
presented with the source information available for inspection.

Follow the [eight-stage request walkthrough]({{ '/reference/application-workflows/#grounded-chat-request-walkthrough' | relative_url }})
for the complete illustrated flow, including the distinction between provider
data-use terms and application conversation storage.

## Security Architecture

{% include media.html id="slide-application-boundaries" %}

The application boundary brings identity, knowledge, and configured AI services
together. It does not replace source permissions or the review of external
connections.

### Authentication & Authorization

Microsoft Entra ID supplies application sign-in. App roles govern application
access and can narrow specific capabilities or administrative reports when
their requirements are enabled. Managed identity can authenticate supported
service connections; it does not replace the signed-in user's authorization.

Personal workspaces, group membership and roles, and public-workspace publishing
serve different audiences. **Public workspaces are visible to signed-in app
users, not anonymous visitors.** Management rights remain separate from
visibility.

[Workspace scope lock]({{ '/guides/lock-workspace-scope/' | relative_url }})
keeps workspace retrieval tied to the selected scope. It does not make stored
documents immutable or constrain every web or integration tool.
See [Security settings]({{ '/admin/security/' | relative_url }}) and
[Governance settings]({{ '/admin/governance/' | relative_url }}) for the
independent access and capability controls.

### Network Security

Private endpoints, App Service VNet integration, private DNS, and routing can
provide a configured private path to supported services. They are not a default
assurance attached to every deployment or optional connection.

Plan inbound access, app-to-service access, and deployment-runner connectivity
separately. Validate name resolution and actual service calls before disabling
public paths. The [enterprise networking guide]({{ '/guides/enterprise-networking/' | relative_url }})
retains the detailed cloud-specific diagrams, subnet tables, and procedures.

### Encryption and Secrets

{% include media.html id="slide-encryption" %}

Azure data-service encryption at rest and TLS-protected transport address
different parts of the data path. Verify the actual service and key
configuration, endpoint scheme, certificate trust, and any gateway between
components. An explicitly permitted plaintext Custom endpoint is not an
encrypted transport path.

Use [managed identity]({{ '/guides/use-managed-identity/' | relative_url }})
where supported and [Key Vault settings]({{ '/admin/security/#keyvault-section' | relative_url }})
for supported application-managed secrets. These choices do not certify the
whole deployment or remove the need to review access to stored outputs.

### Configured Content Checks

Azure model filtering, application Content Safety, and Content Screening are
distinct controls. Administrators select checkpoints, rules, reply-display
behavior, and what happens when a chat check cannot finish. Streaming before a
check completes can expose text that is subsequently removed.

Use [Security settings]({{ '/admin/security/#content-safety-section' | relative_url }})
and the [content-check walkthrough]({{ '/reference/application-workflows/#content-safety-workflow' | relative_url }})
to understand the configured coverage, document holds, and review paths.

### Optional Azure Platform Protection

{% include media.html id="slide-azure-platform-protection" %}

Defender for Cloud illustrates an **optional Azure platform control**, not a
Simple Chat feature that automatically activates with deployment. Operators
must choose applicable plans, verify supported resource coverage, and route
findings to an accountable response process. Its presence in this reference is
not proof that protection is enabled or that the environment has no risks.

## Scalability Architecture

### Horizontal Scaling Design

Configure shared Redis session storage before running multiple App Service
instances, then verify authentication and background-work coordination under
scale-out. Do not assume that all transient processing state is shared merely
because persistent records are in Cosmos DB.

App Service capacity, Cosmos DB RU/s, Search replicas and partitions, and AI
service quotas are separate bottlenecks. The
[scaling guide]({{ '/guides/scale-simplechat-on-azure/' | relative_url }}) explains
how to identify and expand the constrained component.

### Performance Optimization

Measure request latency, indexing backlog, throttling, and resource utilization
before changing sizes. Workspace search-result caching uses the Cosmos DB
`search_cache` container, not Redis; cached results still undergo access and
availability checks. See [Search result cache]({{ '/admin/knowledge/#search-result-cache' | relative_url }}).

Use [Scale settings]({{ '/admin/scale/' | relative_url }}) for the application's
coordination and caching controls rather than assuming a fixed capacity or
autoscale threshold from this overview.

## Integration Architecture

### External Service Integration

Agents and actions can call approved tools, while saved workflows make supported
tasks repeatable. Model connections, File Sync sources, Microsoft 365 actions,
OpenAPI endpoints, and MCP servers each add their own identity and data-sharing
considerations. Enabling one does not authorize every destination.

Review [Governance settings]({{ '/admin/governance/' | relative_url }}) before
publishing integrations, then use the [agent and action guides]({{ '/guides/#agents-and-actions' | relative_url }})
or [workflow guides]({{ '/guides/#automation' | relative_url }}).

### Monitoring and Observability

Configured application logging, Application Insights, and Azure Monitor help
operators correlate failures, latency, usage, and capacity. Diagnostic content,
retention, alerts, and SIEM routing are configuration decisions, not automatic
guarantees of complete auditing.

Use [Operations settings]({{ '/admin/operations/' | relative_url }}) and
[Operate Simple Chat day to day]({{ '/guides/admin-operate-simplechat/' | relative_url }}).

## Deployment Architectures

Choose a supported [deployment path]({{ '/start/deployment-options/' | relative_url }})
and verify its actual resource, region, identity, and network configuration.
Service availability and optional endpoint locations can differ from the
application's hosting region. The diagrams do not promise an automatically
replicated multi-region deployment or failover process.

Treat retention, archiving, backup, restore, and migration as separate lifecycle
decisions. Archiving is not legal hold, and a backup is not a tested recovery.
Use [Backup and Recovery]({{ '/admin/backup-recovery/' | relative_url }}) to plan
and rehearse recovery, including dependencies and access after restore.

## Design Patterns and Best Practices

### Data Consistency Patterns

An accepted upload, completed extraction, usable search index, and delivered
answer are different milestones. Follow processing status and source coverage
instead of interpreting an intermediate success as a completed operation.

### Source and Result Lifecycles

Saved analyses and workflow results describe a past run. Reading or discussing
them does not re-fetch the original sources. In particular,
[saved Analyze results]({{ '/guides/analyze-results/' | relative_url }}) take
access from their conversation and can remain readable after an original source
changes or is removed. Review retained outputs as well as live sources when
planning sharing and lifecycle policy.

## Technology Choices and Rationale

Flask coordinates the application APIs and service calls; Cosmos DB retains
application records; AI Search supplies hybrid retrieval; configured model
connections perform generation and embeddings. These responsibilities explain
where to investigate a problem without implying that one service's guarantees
apply to the whole system.

For capability-specific dependencies, use the
[features reference]({{ '/reference/features/' | relative_url }}) and
[feature guidance]({{ '/explanation/feature_guidance/' | relative_url }}).
