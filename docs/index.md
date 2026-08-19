---
layout: page
title: "Simple Chat Documentation"
description: "Deploy, operate, and extend Simple Chat: an Azure-native chat platform with retrieval, workspaces, agents, and enterprise controls."
section: "Start"
hide_toc: false
---

Simple Chat gives teams an Azure-native way to deploy, ground, govern, and
extend AI experiences without stitching together a separate chat app, search
layer, and admin plane.

New here? Start with [what Simple Chat is]({{ '/about/' | relative_url }}), then
pick a [deployment path]({{ '/setup_instructions/' | relative_url }}).

## Find what you need

| I want to... | Go to |
| --- | --- |
| Understand what Simple Chat is | [About Simple Chat]({{ '/about/' | relative_url }}) |
| Deploy it for the first time | [Choose a deployment path]({{ '/setup_instructions/' | relative_url }}) |
| Learn a task step by step | [Guides]({{ '/tutorials/' | relative_url }}) |
| Configure a setting | [Admin settings]({{ '/admin/' | relative_url }}) |
| See what the product can do | [Feature map]({{ '/features/' | relative_url }}) |
| Look up an API | [API reference]({{ '/reference/api_reference/' | relative_url }}) |
| See what changed | [Release notes]({{ '/explanation/release_notes/' | relative_url }}) |
| Find something specific | [Search the docs]({{ '/search/' | relative_url }}) |

## Documentation sections

### Start

Orientation and first deployment. Covers what Simple Chat is, the deployment
options and their tradeoffs, the architecture, and the
[FAQ]({{ '/faqs/' | relative_url }}).

### Guides

Task-oriented, step-by-step instructions for users and admins. Each guide
explains what the task does and why you would do it before listing the steps.
See [tutorials]({{ '/tutorials/' | relative_url }}) and
[how-to guides]({{ '/how-to/' | relative_url }}).

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
[networking]({{ '/how-to/enterprise_networking/' | relative_url }}),
[scaling]({{ '/application_scaling/' | relative_url }}),
[upgrades]({{ '/how-to/upgrade_paths/' | relative_url }}), and
[troubleshooting]({{ '/troubleshooting/' | relative_url }}).

### Reference

[API reference]({{ '/reference/api_reference/' | relative_url }}), configuration
reference, [application workflows]({{ '/application_workflows/' | relative_url }}),
and [release notes]({{ '/explanation/release_notes/' | relative_url }}).

## What Simple Chat does

### Context-aware AI conversations

Uses Azure OpenAI with hybrid retrieval over personal, group, and public
workspace content, so responses stay tied to your own data rather than to the
model's general knowledge.

### Document pipelines that stay searchable

Ingests PDFs, Office files, images, audio, and video through Azure AI services,
then retrieves them with citations and optional metadata enrichment.

### Controls for enterprise rollouts

Adds Entra ID roles, content safety, feedback review, conversation archiving,
and operational logging without rebuilding the application.

## Platform at a glance

Core application state lives in Azure Cosmos DB. Document retrieval runs through
Azure AI Search. Ingestion is handled by Azure AI Document Intelligence and
related media services. Authentication uses Entra ID.

That combination makes it practical to run Simple Chat as a governed internal
tool rather than a demo-only sample.

{% include media.html src="architecture.png"
                      alt="Architecture diagram showing Simple Chat running on Azure App Service with Azure OpenAI, Azure AI Search, Cosmos DB, and storage services."
                      title="Simple Chat architecture"
                      caption="Simple Chat on Azure App Service, composing search, storage, document processing, and conversation state into one application." %}

## Contributing

The docs, application, and deployers are maintained together. Read the
[contributing guide]({{ '/contributing/' | relative_url }}) for the fork-based
workflow, target branch expectations, and local development setup before editing
code or documentation.

Documentation contributors should also check the
[media status page]({{ '/contributing/media-status/' | relative_url }}), which
lists every screenshot and video slot that still needs to be captured.
