---
layout: page
title: "Microsoft Decision-1"
description: "Reference for the Microsoft Decision-1 SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: microsoft-decision -->

## What this action does

Microsoft Decision-1 evaluates bounded decision questions and returns typed answers
with probabilities. Agents can use it for binary conditions, selecting from a
defined set of options, and scoring against ordered levels.

It does not generate a written rationale. Any explanation in an agent response is
the agent's interpretation of the returned decision and must not be presented as
reasoning supplied by Decision-1.

## Why and when to use it

Use this action when a workflow needs a constrained classification, routing, or
scoring input. It is not a conversational model and does not appear in chat-model
selection.

Low-confidence results are returned with a review signal. Do not use the action
as the sole decision-maker for consequential decisions about people.

## Before you start

- A Microsoft Decision-1 deployment name.
- Either a Foundry resource endpoint or the exact Decision API endpoint.
- An API key or a system-assigned/reusable managed identity authorized for the
  selected Azure endpoint.
- For an API Management route, the subscription-key header name required by the
  gateway policy.

## Configuration overview

Choose **Foundry resource URL** to have SimpleChat append
`/providers/microsoft/v1/systemone`. Choose **Exact Decision API URL** when an
API Management route owns the full path; the supplied URL must end with that
path. Exact paths preserve APIM revision selectors such as `;rev=2`.

Direct Foundry API-key requests use the `api-key` header by default. Change
**API Key Header** only when a gateway requires another header, such as
`Ocp-Apim-Subscription-Key`. The key stays in the existing action secret flow;
it is never returned in action configuration responses.

Managed identity is limited to trusted Azure Foundry and Azure API Management
hostnames. Use API-key authentication for custom gateway domains so a workload
identity token is never sent to an arbitrary host.

Set **Minimum Confidence** to control when a result includes
`requires_review`. A value of `0` retains every result without a confidence-based
review flag.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
