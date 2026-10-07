---
layout: page
title: "OpenAPI"
description: "Full guide for the OpenAPI SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: openapi -->

{% include media.html src="reference/actions-openapi-configuration.png" alt="The API configuration pane showing the OpenAPI specification file picker, the base URL field with a note that it is auto-populated from the spec, the authentication type selector, and a Test Connection button." title="OpenAPI action configuration" capture="Capture OpenAPI Configuration, Authentication Configuration, API Information, and Test Connection. Redact secrets." %}

## What this action does

OpenAPI turns a YAML or JSON OpenAPI specification into callable operations. The action can list available APIs, inspect operation details, and call operations by `operationId` with configured authentication.

## Why and when to use it

Use OpenAPI when an HTTP API has a maintained OpenAPI spec and users need agents to call multiple documented operations. Do not use it for arbitrary web pages or PDFs; use Smart HTTP. Do not use it for MCP servers; use MCP. Tool-call quality depends on clear operation IDs and parameter schemas.


## Before you start

- An OpenAPI specification file in YAML or JSON, max 5 MB according to the modal help.
- A server URL in the spec's `servers` list. V2 populates the API base URL from that spec value and keeps it read-only unless **Override base URL** is enabled.
- Authentication details: no auth, API key, bearer token, basic auth, OAuth2 access token, or compatible reusable identity.
- A decision about which operations to expose. An empty allow-list keeps the backward-compatible behavior where all operations are enabled.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **OpenAPI**.
2. Upload **OpenAPI Specification File**. The V2 picker shows the selected or imported file name and a **Replace file** button instead of the browser's native empty file text.
3. Review **API base URL** from the spec. Turn on **Override base URL** only when the deployed API is hosted somewhere else.
4. Read the **API Information** panel after parsing.
5. Enable only the operations the agent should call, or use **Enable all** and **Disable all** to manage the list quickly. Selections are stored in `additionalFields.allowed_operations`; an empty list means every operation is enabled for compatibility.
6. Choose **Authentication Type**: **No Authentication**, **API Key**, bearer token, **Basic Auth**, or **OAuth2**.
7. For API key auth, choose **Location**, fill **Key Name**, and fill **API Key**.
8. For bearer, basic, or OAuth2 auth, fill the shown token, username/password, or access token fields.
9. Use **Validate and test** in **Authentication**.

OpenAPI runtime registration and direct calls both enforce `allowed_operations`, so a disabled operation is rejected before an HTTP request is sent.

The V2 editor no longer offers ad hoc custom fields. Use **Advanced → JSON** only to review preserved legacy values.

## Example prompts

- "List the available API operation IDs for this action."
- "Call the customer status endpoint for account 12345 and summarize the response."
- "Get operation details for createIncident before using it."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Operation names are hard for the agent to choose | The spec has missing or ambiguous operation IDs. | Improve operation IDs and summaries, then re-upload. |
| Authentication fails | Wrong auth type, header name, token, or query parameter is configured. | Match modal auth fields to the API security scheme. |
| A needed operation is missing | The operation switch is off or **Disable all** was used. | Re-enable the operation and save. |
| Spec upload fails | File is invalid JSON/YAML or too large. | Validate the spec and keep it under the documented upload limit. |

## Related

- [MCP](../mcp/)
- [Smart HTTP](../smart-http/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})

