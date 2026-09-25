---
layout: page
title: "Choose models for orchestration"
description: "Use explicit per-step Auto selection or pin a model while keeping ordinary chat selections separate."
section: "Guides"
audience: user
version: "0.261.137"
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

Auto applies to every orchestration plan, including plans that save files. Since
**0.261.134**, each model-backed step, including the step that writes the answer,
runs on its planned model. Searches, file rendering, and delegated agents take no
model assignment.

## Select and review

In the V2 composer, enable **Orchestrate** and open **Manual controls**. The model
picker sits where the normal model picker does, and since **0.261.137** it starts on
**Auto - choose per step** wherever a connected model can be chosen per step. Enter
the request and inspect the plan. Each model-backed step shows its planned model and
selection reason. The ranking prefers task suitability before administrator priority
and favorites.

Choose a specific model instead when you need a pinned deployment. Your choice, Auto
or a pinned model, is saved to your account, so it stays selected when you leave the
chat, start a new chat, reload the page, or sign in on another device. Auto is not
offered when no connected model has a catalog profile rated for general answering; ask
an administrator to review the profiles. When an administrator hides Manual controls,
orchestration uses Auto (or the default model when Auto cannot be used). The separate
planner configuration can still use its administrator-selected model. Delegated
agents retain their own model configuration in either mode, and deterministic
search/fetch operations do not receive a model assignment.

Normal V2 chat and classic chat remain manual-only. Switching out of orchestration
retains the ordinary-chat model choice; no Auto sentinel is sent as a deployment, and
a model pinned for orchestration does not change the ordinary-chat model.
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

Few catalog profiles rate specialist tasks such as structured data analysis or
reasoning. When no connected model is rated for a step's task, the step runs on
the capable model best rated for general answering, and its reason starts with
"General answering, because no connected model is rated for ...". A model rated
as unsuitable for the task, or lacking a required capability such as tool calling
for actions, is never chosen this way. Planning stops with "No eligible connected
model for ..." only when this fallback finds no model either.

In that case, ask an administrator to review the profile and connection rather
than favoriting an incompatible model. The plan is not created, and a plan
revision that cannot be assigned models keeps your previous plan. A custom
profile does not install tools, create credentials, or grant workspace access.

See [Model Catalog]({{ '/admin/model-catalog/' | relative_url }}) for profile
management, precedence, evidence, and limits.
