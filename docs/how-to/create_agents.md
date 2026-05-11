---
layout: showcase-page
title: "Create Agents"
permalink: /how-to/create_agents/
menubar: docs_menu
accent: teal
eyebrow: "How-To Guide"
description: "Use this guide when you want a repeatable process for creating focused agents, attaching the right actions, and validating their behavior before wider rollout."
hero_icons:
  - bi-robot
  - bi-tools
  - bi-clipboard-check
hero_pills:
  - Global, group, and personal scope
  - Focused instructions over generic prompts
  - Validate before publishing
hero_links:
  - label: "First agent tutorial"
    url: /tutorials/first_agent/
    style: primary
  - label: "Admin configuration"
    url: /admin_configuration/
    style: secondary
---

Create agents around a specific job to be done, not around a vague persona. The most reliable agents in Simple Chat have narrow instructions, deliberate tool access, and a test set that proves they behave the way you expect.

<section class="latest-release-card-grid">
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-bullseye"></i></div>
				<h2>Start with one use case</h2>
				<p>Define the exact task, audience, and boundary for the agent before you write instructions or connect tools.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-signpost-split"></i></div>
				<h2>Choose the right scope</h2>
				<p>Pick global, group, or personal scope based on who should use the agent and where its actions or documents live.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-plug"></i></div>
				<h2>Attach only the tools it needs</h2>
				<p>Actions and plugins should widen capability intentionally, not create a grab bag of tools the agent will misuse.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-clipboard-check"></i></div>
				<h2>Validate with real prompts</h2>
				<p>Test against typical, edge-case, and failure-mode prompts before making the agent widely available.</p>
		</article>
</section>

<div class="latest-release-note-panel">
		<h2>Agents depend on admin enablement and workspace context</h2>
		<p>Semantic Kernel agents, actions, and workspace-scoped agent surfaces have to be enabled first. If the right scope or action type is disabled in Admin Settings, the agent design work will never show up where users need it.</p>
</div>

## Minimum viable agent setup

1. Write a single-sentence mission for the agent.
2. Decide whether the agent should be global, group-scoped, or personal.
3. Add instructions that define what the agent should do, what it should avoid, and when it should ask for clarification.
4. Attach only the actions, knowledge sources, or workspace access needed for that mission.
5. Test the agent with representative prompts before broader rollout.

## Scope decisions

- Use **global agents** when the same capability should be shared across the whole deployment.
- Use **group agents** when the behavior, documents, or actions are tied to one team or workspace.
- Use **personal agents** when users need private experimentation or individualized tool combinations.

## Prompt and tool design rules

- Prefer specific instructions over aspirational descriptions.
- Tell the agent what evidence or citations it should rely on when grounded answers matter.
- Avoid attaching write-capable actions unless the workflow truly needs them.
- Give the agent permission to decline when the request falls outside its domain.

## Validation checklist

- Test a prompt the agent should answer well.
- Test a prompt it should refuse or redirect.
- Test a prompt that exercises each attached action.
- Review whether the agent cites the correct workspace content or asks for missing context when needed.

## Related guides

- [Create Your First Agent](../tutorials/first_agent.md)
- [Admin Configuration Reference](../reference/admin_configuration.md)
- [API Reference](../reference/api_reference.md)
- [ServiceNow Agent Examples](./agents/ServiceNow/)
