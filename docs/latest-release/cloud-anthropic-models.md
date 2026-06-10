---
layout: latest-release-feature
title: "Cloud and Anthropic Model Support"
description: "How admins can expose Azure OpenAI, Foundry, New Foundry, and Claude-capable model endpoints"
section: "Latest Release"
---

Current release version: **0.241.183**

Cloud and Anthropic Model Support lets admins configure Azure OpenAI, Foundry, New Foundry, and Claude-capable deployments in the same model endpoint system users already see in Chat.

## User Side

Users choose from the model picker when admins expose multiple options. A Claude-backed endpoint appears as another approved model choice, so users can select it for the next turn without changing how they use prompts, agents, workspace grounding, or chat history.

## Admin Side

Admins configure model endpoints from **Admin Settings > AI Models**. Provider metadata distinguishes Azure OpenAI, Foundry, and New Foundry endpoints, and cloud-aware fields support Azure Public, Azure Government, and custom authority scenarios. Claude deployments are detected from the configured model name or Anthropic endpoint path and route through the Anthropic messages protocol at runtime.

## Screenshot Placeholder

Add an admin screenshot showing the model endpoint modal with provider, project endpoint, cloud, and model choices filled in for a Claude deployment.

Add a user screenshot showing the Chat model picker with an Azure OpenAI model and a Claude-capable Foundry model visible in the same menu.

## Why It Matters

Teams can adopt Anthropic models through approved Azure AI Foundry endpoints without building a separate chat experience or losing existing model-governance controls.

## How to Try It

1. Open **Admin Settings > AI Models** and enable multi-model endpoints.
2. Add or edit a Foundry or New Foundry endpoint that exposes a Claude deployment.
3. Save the endpoint and make the model available to the intended users or scopes.
4. Open Chat and select the model from the model picker before sending a prompt.

## Notes

- Claude deployments use the Anthropic messages protocol instead of the legacy Azure OpenAI client path.
- OpenAI-compatible Foundry models continue through the Foundry OpenAI-compatible path.
- Summary generation, endpoint-bound agents, and direct chat calls preserve endpoint metadata so Claude selections stay on the right protocol.