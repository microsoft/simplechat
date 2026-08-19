---
layout: page
title: "Review pasted URLs"
description: "Use URL Access to review links included in the current chat message."
section: "Guides"
audience: user
---

## What this does

**URLs** turns on URL Access for the current message so pasted links are reviewed instead of treated as plain text. The control appears when URL Access is available for the prompt.

{% include media.html type="video"
                      title="Review pasted URLs walkthrough"
                      poster="video-posters/guide-review-pasted-urls.png"
                      capture="Recording planned. Show review pasted urls end to end and explain why this task helps a user." %}

## Why you would use this

Use URL Access when you already know the exact pages the model should review. It is more precise than broad web search because you provide the URLs; use web search or Deep Research when discovery or deeper review is the real task.

## Before you start

- Admins must enable `enable_url_access`; see [Search and Extract]({{ '/admin/search-extract/' | relative_url }}).
- The prompt must include valid `http://` or `https://` URLs.
- Chat warns when the URL count exceeds the configured limit.

## Steps

1. Open **Chat**.
2. Paste one or more URLs into **Type your message...** with your question.
3. Select **URLs**; its tooltip is **Review pasted URLs**.

{% include media.html src="guides/review-pasted-urls-step-3.png"
                      alt="Screenshot showing review pasted urls step 3."
                      title="Review pasted URLs step 3"
                      capture="Capture the review pasted urls task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Select **Send Message**.
5. Review the answer and URL review progress.

{% include media.html src="guides/review-pasted-urls-step-5.png"
                      alt="Screenshot showing review pasted urls step 5."
                      title="Review pasted URLs step 5"
                      capture="Capture the review pasted urls task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. Use **Research** instead when the source review needs deeper investigation.

## Verify it worked

The response uses information from the pasted URLs, or SimpleChat warns when too many URLs were included.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **URLs** is hidden | URL Access is disabled or no URL is detected | Paste a valid URL or ask an admin to enable it. |
| A URL limit warning appears | Too many URLs are in one prompt | Split the work across messages. |

## Related

- [Use deep research]({{ '/guides/use-deep-research/' | relative_url }})
- [Use web search]({{ '/guides/use-web-search/' | relative_url }})
- [Search and Extract]({{ '/admin/search-extract/' | relative_url }})
