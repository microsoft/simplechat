---
layout: page
title: "Simple Chat Documentation"
description: "Deploy, operate, and extend Simple Chat: an Azure-native chat platform with retrieval, workspaces, agents, and enterprise controls."
section: "Start"
hide_toc: false
version: "0.261.398"
---

Simple Chat gives teams an Azure-native way to deploy, ground, govern, and
extend AI experiences without stitching together a separate chat app, search
layer, and admin plane.

New here? Start with [what Simple Chat is]({{ '/start/about/' | relative_url }}), then
pick a [deployment path]({{ '/start/deployment-options/' | relative_url }}).

## Find what you need

| I want to... | Go to |
| --- | --- |
| Understand what Simple Chat is | [About Simple Chat]({{ '/start/about/' | relative_url }}) |
| Deploy it for the first time | [Choose a deployment path]({{ '/start/deployment-options/' | relative_url }}) |
| Learn a task step by step | [Guides]({{ '/guides/' | relative_url }}) |
| Configure a setting | [Admin settings]({{ '/admin/' | relative_url }}) |
| See what the product can do | [Feature map]({{ '/features/' | relative_url }}) |
| Look up an API | [API reference]({{ '/reference/api_reference/' | relative_url }}) |
| See what changed | [Release notes]({{ '/explanation/release_notes/' | relative_url }}) |
| Find something specific | [Search the docs]({{ '/search/' | relative_url }}) |

## Documentation sections

### Start

Orientation and first deployment. Covers what Simple Chat is, the deployment
options and their tradeoffs, the architecture, and the
[FAQ]({{ '/start/faqs/' | relative_url }}).

### Guides

Task-oriented, step-by-step instructions for users and admins. Each guide
explains what the task does and why you would do it before listing the steps.
See [tutorials]({{ '/guides/' | relative_url }}) and
[how-to guides]({{ '/guides/' | relative_url }}).

### Features

What the product can do, including the
[feature map]({{ '/features/' | relative_url }}),
[latest release highlights]({{ '/latest-release/' | relative_url }}), and
[worked scenarios]({{ '/explanation/scenarios/' | relative_url }}).

### Administration

One page per [admin settings tab]({{ '/admin/' | relative_url }}), covering what
each tab controls, why it matters, every setting and its default, prerequisites,
and the common tasks admins perform there.

### Deploy and operate

[Deployment paths]({{ '/reference/deploy/' | relative_url }}) for Azure Developer
CLI, Bicep, Terraform, Azure CLI, and manual setup, plus
[networking]({{ '/guides/enterprise-networking/' | relative_url }}),
[scaling]({{ '/guides/scale-simplechat-on-azure/' | relative_url }}),
[upgrades]({{ '/guides/upgrade-paths/' | relative_url }}), and
[troubleshooting]({{ '/troubleshooting/' | relative_url }}).

### Reference

[API reference]({{ '/reference/api_reference/' | relative_url }}), configuration
reference, [application workflows]({{ '/reference/application-workflows/' | relative_url }}),
and [release notes]({{ '/explanation/release_notes/' | relative_url }}).

## What Simple Chat does

### Context-aware AI conversations

Combines a configured model with hybrid retrieval over authorized personal,
group, and public workspace content. Citations help readers inspect the
supporting material; a grounded answer still needs review. Public workspaces
share curated content with signed-in application users, not anonymous visitors.

### Document pipelines that stay searchable

Uses format-specific extraction, chunking, and embeddings to make supported
files searchable. PDF/image extraction and optional audio/video processing have
their own service dependencies. Start with
[uploading and managing documents]({{ '/guides/upload-and-manage-documents/' | relative_url }}).

### Controls for enterprise rollouts

Combines Entra ID roles and workspace permissions with configurable content
checks, feedback review, data lifecycle controls, and operational logging.
[Feature guidance]({{ '/explanation/feature_guidance/' | relative_url }}) explains
what to validate before widening a rollout.

### From answers to repeatable work

Saved prompts and agents make useful instructions reusable. Approved actions,
reviewed orchestration plans, and saved workflows can extend that work into
external systems or generated files when configured. Browse the
[feature catalog]({{ '/features/' | relative_url }}) or start with
[creating a workflow]({{ '/guides/create-a-workflow/' | relative_url }}).

## Platform at a glance

The Flask application coordinates sign-in, conversation state, retrieval, and
configured AI connections. Entra ID establishes identity, Cosmos DB stores
application records, and Azure AI Search supplies workspace retrieval.

{% include media.html id="slide-azure-services" %}

The full slide is a service map, not a requirement to deploy every pictured
service. Storage-backed citations, media processing, Content Safety, API
Management, and Redis depend on the capabilities and topology you choose.
Read [Architecture]({{ '/explanation/architecture/' | relative_url }}) for the
application boundaries and approved outbound paths.

## Contributing

The docs, application, and deployers are maintained together. Read the
[contributing guide]({{ '/contributing/' | relative_url }}) for the fork-based
workflow, target branch expectations, and local development setup before editing
code or documentation.

Documentation contributors should also check the
[media status page]({{ '/contributing/media-status/' | relative_url }}), which
lists every screenshot and video slot that still needs to be captured.
