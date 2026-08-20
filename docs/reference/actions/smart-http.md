---
layout: page
title: "Smart HTTP"
description: "Full guide for the Smart HTTP SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: smart-http -->

{% include media.html src="reference/actions-smart-http-configuration.png" alt="Smart HTTP action assignment or configuration UI." title="Smart HTTP configuration" capture="Capture the HTTP Action setting or Smart HTTP action assignment UI. Redact URLs if needed." %}

## What this action does

Smart HTTP fetches web content with size management and text extraction. It supports HTML, JSON, and PDF URLs. PDFs can be processed through Document Intelligence, and large documents can be summarized into model-sized content with transparency about original size, chunking, and reduction.

## Why and when to use it

Use Smart HTTP when the user gives a URL and the agent needs page or PDF content, especially when content may be large. Do not use it for APIs with structured operations; OpenAPI is safer. Do not use it for broad research over many sources; use Deep Research or web search controls when enabled. Be careful with private or sensitive URLs because the action fetches external content.

## Before you start

- Network access from the app to target URLs.
- Document Intelligence configuration if PDF extraction is expected.
- The global HTTP action controlled by [`enable_http_plugin`]({{ '/admin/agents-actions/' | relative_url }}).
- No Smart HTTP-specific panel was confirmed in `_plugin_modal.html`; behavior is implemented in `smart_http_plugin.py`.

## Configure the action

1. Enable **HTTP Action** on the Agents admin page when using the built-in Smart HTTP action.
2. Assign the action only to agents that should fetch URLs.
3. If your environment exposes Smart HTTP as a configurable action, use standard **Display Name**, **Name**, **Description**, and **Advanced** fields; the modal source does not show a dedicated Smart HTTP panel.
4. Document allowed-domain and data-handling rules in the agent instructions.

## Example prompts

- "Read this PDF URL and summarize the renewal obligations with source notes."
- "Fetch this public changelog page and list breaking changes since last month."
- "Compare these two documentation URLs and identify changed requirements."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A large page is summarized instead of returned verbatim | Smart HTTP intentionally reduces oversized content to avoid token-limit failures. | Ask for targeted sections or provide a smaller source URL. |
| PDF extraction is poor or unavailable | Document Intelligence is not configured or the PDF is difficult. | Enable/configure Document Intelligence or upload the PDF as a workspace document. |
| A site returns an HTTP error | The URL requires authentication, blocks scraping, or is unavailable. | Use an authenticated API/action or provide accessible content. |

## Related

- [OpenAPI](../openapi/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Search and Extract administration]({{ '/admin/knowledge/' | relative_url }})

