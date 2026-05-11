---
layout: showcase-page
title: "Feature Guidance"
permalink: /explanation/feature_guidance/
menubar: docs_menu
accent: orange
eyebrow: "Explanation"
description: "Use this page to decide which Simple Chat capabilities belong in a first rollout, which ones depend on more Azure services, and which ones should wait until the platform is stable."
hero_icons: ["bi-grid-1x2", "bi-signpost-split", "bi-stars"]
hero_pills: ["Foundational features first", "Dependency-aware rollout", "Optional packs after the core loop works"]
hero_links: [{ label: "Features overview", url: "/features/", style: "primary" }, { label: "Admin configuration", url: "/admin_configuration/", style: "secondary" }]
order: 130
category: Explanation
---

Feature rollout goes better when capabilities are grouped by operational risk instead of novelty. The right question is usually not “Can we turn this on?” but “What extra service, process, or support burden does this add?”

<section class="latest-release-card-grid">
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-chat-dots"></i></div>
		<h2>Start with the core loop</h2>
		<p>Get sign-in, model routing, workspace access, document upload, embeddings, AI Search, and grounded chat working before you widen the feature surface.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-shield-check"></i></div>
		<h2>Layer governance deliberately</h2>
		<p>Content Safety, feedback review, archiving, API documentation controls, and role-scoped admin features are valuable, but they also create operational review work.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-camera-video"></i></div>
		<h2>Treat media as an expansion pack</h2>
		<p>Audio, video, speech, enhanced citations, and metadata extraction increase capability and complexity at the same time because they pull in extra Azure services and processing paths.</p>
	</article>
	<article class="latest-release-card">
		<div class="latest-release-card-icon"><i class="bi bi-robot"></i></div>
		<h2>Add agents after the platform is predictable</h2>
		<p>Agents, actions, and external system integrations work best once the base chat and workspace behavior is stable, observable, and well understood.</p>
	</article>
</section>

<div class="latest-release-note-panel">
	<h2>A good rollout sequence reduces support load</h2>
	<p>If users can already sign in, upload content, search it, and get grounded answers, later feature additions feel like improvements. If the core loop is unstable, every optional feature makes triage harder.</p>
</div>

## Rollout groups

| Feature group | Enable early? | Typical dependencies | Why it belongs there |
| :--- | :--- | :--- | :--- |
| Authentication, chat, base model routing | Yes | Entra ID, Azure OpenAI | Users need a stable starting point before anything else matters. |
| Workspaces, ingestion, embeddings, AI Search | Yes | Azure AI Search, embeddings, Document Intelligence | This is the foundation of grounded chat and document-backed workflows. |
| Classification, metadata, enhanced citations | Usually after core search works | Storage, admin process decisions, optional GPT extraction | Useful, but easier to operationalize after the retrieval path is already trusted. |
| Content Safety, feedback, archiving | Based on governance needs | Content Safety, Cosmos containers, reviewer roles | These features change process and oversight, not just UI behavior. |
| Audio, video, speech, image generation | Later | Speech, Video Indexer, DALL-E, storage | Strong value, but each one adds cost, service dependencies, and user-experience edge cases. |
| Agents, OpenAPI actions, SQL workflows | Later | Agent enablement, actions, external systems, model discipline | Best added once prompt boundaries, workspace scope, and admin ownership are clear. |

## Questions to ask before enabling a feature

1. Which Azure service or quota does this add?
2. Which admin setting or role boundary controls it?
3. What new failure mode does it introduce?
4. Who owns support when the feature misbehaves?
5. Does the feature help the core user workflow or distract from it?

## Practical guidance

- Prefer a smaller, reliable feature set for the first production rollout.
- Turn on media and agent capabilities only after you have baseline monitoring and support habits in place.
- Use the admin reference to map each feature toggle back to its service dependency before enabling it.
- Revisit the rollout after users have proven which workflows matter enough to justify extra complexity.
