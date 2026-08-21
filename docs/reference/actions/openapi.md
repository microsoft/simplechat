---
layout: page
title: "OpenAPI"
description: "Full guide for the OpenAPI SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: openapi -->

{% include media.html src="reference/actions-openapi-configuration.png" alt="OpenAPI action configuration UI." title="OpenAPI configuration" capture="Capture OpenAPI Configuration, Authentication Configuration, API Information, and Test Connection. Redact secrets." %}

## What this action does

OpenAPI turns a YAML or JSON OpenAPI specification into callable operations. The action can list available APIs, inspect operation details, and call operations by `operationId` with configured authentication.

## Why and when to use it

Use OpenAPI when an HTTP API has a maintained OpenAPI spec and users need agents to call multiple documented operations. Do not use it for arbitrary web pages or PDFs; use Smart HTTP. Do not use it for MCP servers; use MCP. Tool-call quality depends on clear operation IDs and parameter schemas.

## Before you start

- An OpenAPI specification file in YAML or JSON, max 5 MB according to the modal help.
- API **Base URL**, auto-populated from the spec when available but editable.
- Authentication details: no auth, API key, bearer token, basic auth, OAuth2 access token, or compatible reusable identity.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

The base URL must use HTTPS on port 443 with a public DNS hostname. SimpleChat rejects IP literals,
embedded URL credentials, local or private network destinations, and hostnames that resolve to any
non-public address. Redirects are revalidated and must remain on the original origin so configured
credentials are never forwarded to another host. APIs reachable only through private DNS or custom
ports are not supported by this action.

## Configure the action

1. Choose **OpenAPI**.
2. Upload **OpenAPI Specification File**.
3. Review or edit **Base URL**.
4. Read the **API Information** panel after parsing.
5. Choose **Authentication Type**: **No Authentication**, **API Key**, bearer token, **Basic Auth**, or **OAuth2**.
6. For API key auth, choose **Location**, fill **Key Name**, and fill **API Key**.
7. For bearer, basic, or OAuth2 auth, fill the shown token, username/password, or access token fields.
8. Use **Test Connection**.

## Example prompts

- "List the available API operation IDs for this action."
- "Call the customer status endpoint for account 12345 and summarize the response."
- "Get operation details for createIncident before using it."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Operation names are hard for the agent to choose | The spec has missing or ambiguous operation IDs. | Improve operation IDs and summaries, then re-upload. |
| Authentication fails | Wrong auth type, header name, token, or query parameter is configured. | Match modal auth fields to the API security scheme. |
| Spec upload fails | File is invalid JSON/YAML or too large. | Validate the spec and keep it under the documented upload limit. |
| Connection is rejected before the API responds | The base URL is not public HTTPS, resolves to a non-public address, or redirects to another origin. | Use the API's canonical public HTTPS origin and keep redirects on that origin. |

## Related

- [MCP](../mcp/)
- [Smart HTTP](../smart-http/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})

