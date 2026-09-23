---
layout: page
title: "Choose models for orchestration"
description: "Use explicit per-step Auto selection or pin a model while keeping ordinary chat selections separate."
section: "Guides"
audience: user
version: "0.261.131"
---

# Choose models for orchestration

Implemented in version: **0.261.126**.

## When Auto is useful

A request can need inexpensive summarization followed by specialized coding or
reasoning. In React V2's **Orchestrate** mode, **Auto - choose per step** lets the
server choose a connected model for each model-backed step rather than forcing
the whole plan through one model. The administrator must enable orchestration
and publish usable connections with suitable catalog profiles.

This is not the **Auto** approval preference: approval controls whether a plan
runs automatically; model Auto controls which model each step uses.

When an administrator enables the **Gather / Reason / Render harness (preview)**,
Auto requests still use standard orchestration, where these per-step bindings are
enforced. Since **0.261.131**, harness plans require a specific model selection;
the server never shows harness bindings that its executor would not apply.

## Select and review

In the V2 composer, enable **Orchestrate** and use the visible model picker.
Choose **Auto - choose per step**, enter the request, and inspect the plan.
Each model-backed step shows its planned model and selection reason. The ranking
prefers task suitability before administrator priority and favorites.

Choose a specific model instead when you need a pinned deployment. The separate
planner configuration can still use its administrator-selected model. Delegated
agents retain their own model configuration in either mode, and deterministic
search/fetch operations do not receive a model assignment.

Normal V2 chat and classic chat remain manual-only. Switching out of orchestration
retains the ordinary-chat model choice; no Auto sentinel is sent as a deployment.
Per-model reasoning preferences apply to explicit selections. Auto uses each
chosen model's default reasoning behavior instead of borrowing the normal-chat
model's reasoning level.

## Execution and recovery

Completed step records show their execution model; pending steps show the planned
model. Reloading a saved run preserves the recorded attribution. Reused results
remain marked as reused rather than being described as new model calls.

Before executing or reusing work, SimpleChat rechecks model access, enabled
state, profile revisions, and the required capabilities. A changed or unavailable
binding requires a reviewed new plan; the system does not quietly pick another
model. Request context, generation limits, and provider errors can still block an
otherwise eligible model. Auto does not guarantee that an unknown future document
or tool result will fit, and it does not discard source content to make it fit.

If no connected model is suitable, ask an administrator to review the profile
and connection rather than favoriting an incompatible model. A custom profile
does not install tools, create credentials, or grant workspace access.

See [Model Catalog]({{ '/admin/model-catalog/' | relative_url }}) for profile
management, precedence, evidence, and limits.
