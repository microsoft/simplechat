---
layout: page
title: "Connect personal models in V2"
description: "Configure your own model connections, verify saved chat models, and maintain their capacity metadata without leaving V2."
section: "Guides"
audience: user
version: "0.261.315"
---

## What this does

**My Workspace > Endpoints** keeps the resource address, authentication, and
models for a personal connection together. Use it when your agents or workflows
need a permitted model resource that is not supplied by an administrator.
Creation and editing stay in V2; no classic workspace page is required.

Implemented in version: **0.261.315**, recorded in
`application/single_app/config.py`. This closes the personal endpoint editor
gap in row 6 of [issue #1722](https://github.com/microsoft/simplechat/issues/1722).

The section depends on administrator-enabled personal endpoints and governance
access. It does not grant resource permissions or change global chat, image,
or embedding defaults.

## Configure a personal connection

Choose **Add connection**, or **Edit** beside an existing connection. Give it a
recognizable purpose, select the provider, and enter the resource's actual
endpoint and API versions. Foundry project URLs and inference resource URLs
serve different purposes; use the provider-specific field guidance.

Select an authentication method that has access to that resource. Managed
identity still uses the application's approved identity; a personal endpoint
cannot grant access to an arbitrary host or token audience. Azure service
principals need tenant/client details and a secret. Custom APIs offer API keys,
bearer tokens, or OAuth2 client credentials, subject to the administrator's
network policy.

A stored credential is never shown. Leave its field blank to keep it, or enter
a replacement deliberately. The draft remains only in the current editor;
closing it without saving discards those changes.

## Add and verify models

For Azure/Foundry, discovery reads existing deployments when the selected
credentials have the necessary management/project access. An inference-only
Azure API key does not enumerate resource deployments; use **Add manually**
and enter the deployment name instead.

For Custom connections, choose the real API contract: OpenAI, Azure OpenAI,
Anthropic, or Gemini. Enter the model name or deployment identifier expected
by that contract. Keep gateway base paths intact. Selecting a contract does
not make an incompatible service support it.

Discovery merges new models without replacing your existing descriptions or
overrides. Newly discovered and manually added models start disabled. Enable
the intended models and publish only supported operations.

**Save changes before discovering or testing an edited existing endpoint.**
These personal operations resolve the saved resource and enabled model list,
not unsaved connection overrides. Discovery that changes the list also needs
a save before chat tests. A new connection can discover/test its transient
configuration before creation when the server permits it.

**Test chat** sends an inference request and may incur provider costs. A
successful save is not a connection test; a successful chat test does not
prove image or embedding readiness. Personal connections have no tenant
connection test or image/embedding inference-test buttons.

## Record verified capacity and model identity

Expand **Advanced endpoint capacity** for shared defaults, or **Advanced model
capacity** for a model-specific override. Each blank field inherits independently:
model override, then endpoint default, then exact catalog metadata where available.
Never guess limits to make a model seem usable.

| Field | Meaning |
| --- | --- |
| Context window | Verified shared capacity for input and generation together. |
| Input/output token limits | Independent provider ceilings; these maxima do not have to fit simultaneously in the context window. |
| Catalog model ID and model version | The published model and exact snapshot, not a deployment alias or endpoint API version. |
| Token limit provider and output accounting | Provenance and whether reasoning generation counts toward output capacity. |
| Response length | Optional per-request generation allowance for standard chat, not model capacity. |

Numeric values must be positive whole numbers no greater than
`9007199254740991`. Fractions, exponent notation, zero, and negative values are
rejected. Clear an override and save to restore inheritance.

## Customize model presentation

Give each model a useful description. Under **Model icon**, search Bootstrap
icons; **Load all local icons** reads the application's local catalogue.
Alternatively upload PNG/JPEG. The browser resizes it to at most 128 by 128
pixels and rejects oversized stored payloads. SVG and remote image URLs are
not accepted. **Use default icon** clears the custom icon.

## Maintain and troubleshoot

Disable a connection temporarily without losing its configuration. Delete
only when it is no longer needed; confirmation removes that connection and
its stored credentials. Other personal connections remain unchanged.

Failed reads offer **Retry connections**, rather than pretending the list is
empty. Failed saves, discovery, and tests keep the editor available and explain
the error. Resolve resource permissions or network policy instead of changing
to an unapproved endpoint to bypass a failure.

Personal saves do not have group-style optimistic revisions. Coordinate with
another editor using the same account before editing the same connection.

## Related

- [Build agents and actions in My Workspace]({{ '/guides/workspace-agents-and-actions/' | relative_url }})
- [Model endpoint identity setup]({{ '/guides/model-endpoint-identity-setup/' | relative_url }})
- [Configure global AI Connections]({{ '/guides/configure-ai-connections/' | relative_url }})
