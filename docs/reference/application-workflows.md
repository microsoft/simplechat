---
layout: showcase-page
title: "Application Workflows"
section: "Reference"
permalink: /reference/application-workflows/
menubar: docs_menu
accent: violet
eyebrow: "How Requests Move"
description: "Follow document ingestion, configurable content checks, and the complete eight-stage grounded request with its separate data-use qualification."
version: "0.261.398"
hero_icons:
  - bi-shield-check
  - bi-arrow-repeat
  - bi-diagram-2
hero_pills:
  - Configurable content checks
  - Search-ready document processing
  - Eight-stage grounded request
hero_links:
  - label: Review features
    url: /features/
    style: primary
  - label: Open troubleshooting
    url: /troubleshooting/
    style: secondary
redirect_from:
  - /application_workflows/
---

These are the application's internal ingestion and request pipelines. They
explain where content goes, when configured checks can intervene, and how source
material becomes a grounded answer. For saved, repeatable automations instead,
see [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }}).

The full-slide illustrations reflect capability snapshot **0.261.398**. They
show logical responsibilities, not a tracing contract or proof that every
deployment uses identical services, checks, or network paths.

## Content Safety Workflow

Administrators choose the checks and review behavior appropriate to their
deployment. There is no single always-on gate that proves all content safe.

{% include media.html id="slide-safety-and-screening" %}

Keep three different mechanisms separate:

| Mechanism | What it evaluates | Configuration boundary |
| --- | --- | --- |
| Azure AI Content Safety | Configured category thresholds and blocklists at selected chat checkpoints. | Submitted-message and AI-reply checks are independent choices beneath the master setting. |
| Content Screening | Saved PII, literal, regex, and optional model rules. | Workspace uploads, submitted chat text, and AI replies have their own checkpoints and applicable policies. |
| Model-provider filtering | Content handled by the selected model service. | The provider, model, and deployment determine that service's filtering behavior. |

When an enabled input check finds a violation, the submitted request is stopped.
When an enabled reply check confirms a finding, the reply is replaced with a
neutral notice. Administrators separately choose whether to **stream, then
check** or **check before display**, and whether an unfinished chat check should
allow content marked privately as **not checked** or stop/remove it. Removing a
streamed reply cannot undo text someone already read or copied.

Workspace screening has a different publication boundary: applicable checks
stage extracted content privately and can hold a document out of knowledge use
pending review. It requires the Enhanced Citations storage path; chat-text-only
checks do not require that upload storage.

Use [Security settings]({{ '/admin/security/#content-screening-section' | relative_url }})
for checkpoint and failure choices,
[Screen and review workspace documents]({{ '/guides/review-screened-documents/' | relative_url }})
for held files, and [Recheck chat content]({{ '/guides/recheck-chat-content/' | relative_url }})
for checks that could not finish.

## Add Your Data Workflow

An upload becomes useful knowledge only after the appropriate processing and
publication steps finish. This applies to authorized workspace uploads and the
document paths available through chat; choosing a public workspace still means
sharing with signed-in application users.

{% include media.html id="slide-feed-anything-get-knowledge" %}

1. A user uploads a supported file into a scope where they have permission.
2. The backend identifies the format and chooses its extraction path. Office
   and text formats can use internal parsers; PDF/image paths use configured
   Document Intelligence or enhanced extraction. Enabled audio and video paths
   use their corresponding media services.
3. Extracted material retains available structural references such as pages,
   slides, timestamps, tables, and sequence. Applicable workspace screening
   policies can stage and hold it before knowledge publication.
4. The content is split into retrieval units appropriate to the format and
   chunking configuration. There is no universal character count or overlap for
   every file type.
5. The configured embedding connection supplies vectors compatible with the
   workspace index. Changing the embedding vector space requires a controlled
   rebuild, not simply selecting another model for existing vectors.
6. Azure AI Search receives chunk text, vectors, and retrieval metadata.
7. Cosmos DB records the parent document and processing status. Enhanced
   Citations and other storage-backed paths retain the files or derivatives
   they need in configured storage.
8. Once processing, applicable review, and indexing permit use, the file can
   participate in workspace retrieval. Verify readiness and a cited answer
   rather than assuming an accepted upload is already searchable.

Typical retrieval metadata includes the document identity, filename, workspace
scope, sequence, available page/timestamp references, and optional classification
or extraction metadata. Labels and tags help organize retrieval; they are not
access control.

For the actual controls and troubleshooting, use
[Upload and manage documents]({{ '/guides/upload-and-manage-documents/' | relative_url }})
and [Knowledge settings]({{ '/admin/knowledge/#extraction' | relative_url }}).

## Grounded chat request walkthrough

The following **eight numbered stages** follow one illustrative workspace-grounded
question. The additional data-use slide qualifies model execution; it is not a
ninth request stage. The sequence explains information movement rather than the
exact order of every application hook: configured input checks run before the
downstream model or action, and reply checks operate on the returned text.

### 1. Submit the question

The signed-in user sends a question in a conversation with the desired context.
The application still checks access to the selected workspace and sources.
Scope selection is not permission to read every document in the deployment.

{% include media.html id="slide-grounded-request-user" %}

### 2. Retrieve relevant workspace evidence

Simple Chat uses the question to search authorized workspace knowledge. Selected
documents, scope, and filters constrain the candidates. Hybrid retrieval returns
relevant excerpts and metadata; it is not an exhaustive analysis of every source.
The slide's agency boundary is illustrative, not a guarantee about optional
external connections.

{% include media.html id="slide-grounded-request-search" %}

### 3. Assemble the model context

The application combines the current message, retrieved excerpts, and applicable
conversation history within the model's context limits. The model does not
remember previous calls on its own. The pictured completion request illustrates
the responsibility; the configured connection determines the actual API contract.

{% include media.html id="slide-grounded-request-context" %}

### 4. Apply the configured content checks

Provider filtering and application checks are distinct. Azure model services
apply their configured filters; Simple Chat can add Content Safety and Content
Screening at selected checkpoints. The checkmark does not mean every service,
attachment, or operation receives the same inspection.

{% include media.html id="slide-grounded-request-content-checks" %}

### 5. Account for provider monitoring and retention

Abuse-monitoring and retention arrangements depend on the selected Azure service,
model, cloud, deployment, and approved arrangements. Confirm the current terms
for that environment rather than inferring a universal retention period or
monitoring exemption from this diagram.

{% include media.html id="slide-grounded-request-provider-monitoring" %}

Application conversation storage is a separate lifecycle, configured through
[Data Lifecycle settings]({{ '/admin/data-lifecycle/' | relative_url }}).

### 6. Execute the model request

The configured model analyzes the context supplied by the application and
generates a response. Retrieved passages support the answer, but model execution
does not independently verify every source or guarantee that all relevant
material was retrieved.

{% include media.html id="slide-grounded-request-model" %}

### Data-use qualification

This separate slide qualifies stage 6. Review provider data-use terms for the
selected service and deployment, identify which optional connections receive
request content, and define application retention and access independently.
It is not a deployment-wide training-data policy or a data-residency guarantee.

{% include media.html id="slide-grounded-request-data-use" %}

The [architecture data paths]({{ '/explanation/architecture/#data-flow-and-processing' | relative_url }})
and [Governance settings]({{ '/admin/governance/' | relative_url }}) help review
the destinations separately from the application's own records.

### 7. Return the model response

The model returns its answer to Simple Chat. If reply checks are enabled, the
configured display and failure behavior determines whether text is held before
display or streamed provisionally and checked at completion.

{% include media.html id="slide-grounded-request-response" %}

### 8. Present the answer and supporting material

Simple Chat presents the answer in the conversation. Inspect the available
citations and source details before relying on a conclusion. Displaying an
answer is not a correctness guarantee, and source access or freshness can change
after the answer was produced.

{% include media.html id="slide-grounded-request-delivery" %}

Use [Message details and sources]({{ '/features/message-details/' | relative_url }})
and [Conversation details]({{ '/features/conversation-details/' | relative_url }})
to understand the metadata available for inspection.

## Mixed-Source Document Actions

Choose the operation that fits the question:

| Operation | Evidence and limits |
| --- | --- |
| Chat or Search | Relevance-bounded retrieval of supporting excerpts, not a complete document pass. |
| Analyze | Reviews selected authorized sources, using bounded windows for narrative content and native tabular tools for supported spreadsheets when Enhanced Citations is enabled. Findings remain subject to source coverage and validation limits. |
| Compare | Requires a prepared Source and at least one prepared Target. An unavailable Target can leave partial coverage; if no Target is prepared, no comparison is produced. |

With Enhanced Citations, mixed-source processing resolves an ordered authorized
source manifest and combines bounded evidence summaries. Without it there is no
native spreadsheet engine: a comparison mixing a narrative document and a
spreadsheet is refused with an Enhanced Citations requirement rather than
treating spreadsheet text as an equivalent calculation.

Inspect per-source coverage and reasons for partial, failed, or skipped work.
Analyze needs at least one successful source to combine findings; pending required
evidence prevents final combination. Cancellation stops active work and later
finalization, but cannot recall content already delivered or earlier saved
results. The selected-source controls and configured operation limits still apply.

[Saved Analyze results]({{ '/guides/analyze-results/' | relative_url }}) retain
accepted findings and evidence for later reading and discussion. That is not a
fresh source pass: their access follows the originating conversation, and changing
or removing an original document does not withdraw an already saved result.
For React V2 operation selection and approval, see
[Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).
