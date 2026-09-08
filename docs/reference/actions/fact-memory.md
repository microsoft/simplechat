---
layout: page
title: "Fact Memory"
description: "Reference for the Fact Memory SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: fact-memory -->

{% include media.html src="reference/actions-fact-memory-configuration.png" alt="Fact Memory action setup or assignment UI." title="Fact Memory action" capture="Capture the Fact Memory action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Stores, updates, deletes, and retrieves persistent facts for agent context.

## Why and when to use it

Use it for durable preferences or background facts. Do not store secrets or regulated data as memory facts.

## Before you start

- Built-in storage; controlled by `enable_fact_memory_plugin` and user memory preferences.
- The setting lives in [Chat settings]({{ '/admin/chat/#fact-memory-section' | relative_url }}), not in Agents & Actions. Enabling it does not require agents or actions, and standard chat uses memories on its own.
- Assigning this action to an agent lets the agent read and write memories as part of its own tool calls.
- Users also need access to the action through workspace or governance policy where applicable.

## Orchestration context

Since **0.261.104**, private-conversation orchestration also recalls enabled saved
instructions and relevant embedded facts when planning, editing a plan, and
answering. This automatic context is read-only; it does not require assigning
the action to an agent and does not autosave or backfill memory embeddings.
Current requests override saved preferences. Scope and membership are rechecked
before answering, and memory provenance remains available in citations.

Shared conversations, including their hidden backing records, do not receive
this automatic memory context. See the
[orchestration memory boundaries](https://github.com/microsoft/simplechat/blob/main/docs/explanation/fixes/ORCHESTRATION_CAPABILITY_CONTEXT_FIX.md#read-only-saved-memory)
for scope selection and missing-embedding behavior.

## Configuration overview

Assign/enable the built-in memory action; no external service fields are required.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
