---
layout: showcase-page
title: "About Simple Chat"
section: "Start"
permalink: /start/about/
menubar: docs_menu
accent: teal
eyebrow: "Platform Overview"
description: "Simple Chat combines Azure-hosted chat, grounded retrieval, workspace management, and optional agent orchestration into one application surface."
version: "0.261.398"
hero_icons:
  - bi-chat-square-text
  - bi-database
  - bi-diagram-3
hero_pills:
  - Azure-native by design
  - Workspace-first document grounding
  - Optional agents and automation
hero_links:
  - label: Start with setup
    url: /start/deployment-options/
    style: primary
  - label: Explore features
    url: /features/
    style: secondary
redirect_from:
  - /about/
---

Simple Chat is an open-source Flask application for teams that want to work with
AI models and their own knowledge in one web experience. It brings conversations,
workspace documents, administrative settings, and optional tools together, while
leaving service connections and rollout decisions with the deployment's owners.

## What Simple Chat brings together

The product story is more than a chat box: teams can connect their knowledge,
reuse useful instructions, and decide which AI capabilities people may use.
The full presentation slide below introduces that combination.

{% include media.html id="slide-product-overview" %}

The illustrations describe capability snapshot **0.261.398**. Their enterprise
and Azure context is not a certification or a promise that every optional
connection stays inside one tenant.

## Grounded Chat

Ask a model directly, or ground a question in authorized documents from personal,
group, or public workspaces. Retrieval supplies relevant excerpts, and citations
let a reader inspect the supporting material instead of relying on the answer
alone. Public workspaces are curated content for signed-in application users;
they are not anonymous public websites.

Start with [uploading documents]({{ '/guides/upload-and-manage-documents/' | relative_url }})
and the [grounded request walkthrough]({{ '/reference/application-workflows/#grounded-chat-request-walkthrough' | relative_url }}).

## Document Workflows

Supported files move through format-specific extraction, chunking, embeddings,
and indexing. This makes them useful for retrieval without requiring users to
paste their contents into every message. The enabled extraction and media
services determine which processing paths are available.

For a more deliberate review, [Analyze and Compare]({{ '/features/document-analysis/' | relative_url }})
work with selected sources and report limitations. Saved results are records of
that review, not proof that the original documents have been checked again.

## Admin Control Surface

Administrators configure models, workspaces, branding, search, content checks,
logging, and other capabilities through [Admin Settings]({{ '/admin/' | relative_url }}).
Enabling a capability is separate from granting access to a source or approving
an external destination.

Teams can begin with chat and expand into [saved prompts]({{ '/features/saved-prompts/' | relative_url }}),
[agents]({{ '/features/agents/' | relative_url }}),
[approved actions]({{ '/features/core-actions/' | relative_url }}), and
[repeatable workflows]({{ '/features/workflows/' | relative_url }}).
These additions need their own permissions, connections, and operational checks.

## What the docs are optimized for

Use the docs to deploy the platform, configure the services behind a capability,
or teach a task. The [feature catalog]({{ '/features/' | relative_url }}) connects
capability explanations to guides and settings; the
[architecture]({{ '/explanation/architecture/' | relative_url }}) explains the
application, data, identity, and outbound-service boundaries.

## Follow the right path

### Deploy

Choose a [deployment path]({{ '/start/deployment-options/' | relative_url }})
before preparing resources. Then use
[first configuration]({{ '/guides/admin-first-configuration/' | relative_url }})
to verify sign-in, models, storage, and retrieval in dependency order.

### Understand capabilities

Browse the [feature catalog]({{ '/features/' | relative_url }}) for what each
capability does, or use [feature guidance]({{ '/explanation/feature_guidance/' | relative_url }})
to decide what belongs in your rollout.

### Operate and tune

Use the [day-to-day operations guide]({{ '/guides/admin-operate-simplechat/' | relative_url }})
for monitoring and review, the [scaling guide]({{ '/guides/scale-simplechat-on-azure/' | relative_url }})
for demonstrated bottlenecks, and [troubleshooting]({{ '/troubleshooting/' | relative_url }})
when an expected path fails.

### Teach the team

Start with [getting started]({{ '/guides/getting-started/' | relative_url }}),
then choose a task from the [guides]({{ '/guides/' | relative_url }}). People do
not need to read every service reference before asking a useful grounded question.

## Built as an open repo

The [source repository](https://github.com/microsoft/simplechat) includes the
application, deployers, documentation, functional tests, and UI tests.

### Source and contribution flow

Read [contribution guidance]({{ '/contributing/' | relative_url }}) for local
development and the fork-based contribution process.

### Release-by-release traceability

Use [latest release highlights]({{ '/latest-release/' | relative_url }}) for a
tour of changes and [release notes]({{ '/explanation/release_notes/' | relative_url }})
for release details. Internal implementation and fix records remain available in
the repository; they are not substitutes for the published user guides.
