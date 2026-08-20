---
layout: page
title: "Use web search"
description: "Send the current chat message to Bing web search when fresh web information is needed."
section: "Guides"
audience: user
---

## What this does

**Web** turns on Bing web search for the current chat message. When the user notice is enabled, SimpleChat explains that only the current message is sent for web search.

{% include media.html type="video"
                      title="Use web search walkthrough"
                      poster="video-posters/guide-use-web-search.png"
                      capture="Recording planned. Show use web search end to end and explain why this task helps a user." %}

## Why you would use this

Use web search when an answer depends on current public information rather than workspace documents or model memory. It replaces searching the web yourself and pasting snippets; it is wrong for confidential prompts or answers that must come only from approved internal files.

## Before you start

- Admins must enable `enable_web_search` and complete consent/configuration; see [Search and Extract]({{ '/admin/knowledge/' | relative_url }}).
- `enable_web_search_user_notice` may show a notice while web search is active.
- Do not include sensitive content in a web-search prompt.

## Steps

1. Open **Chat**.
2. Write a question that needs current public information.
3. Select **Web**.

{% include media.html src="guides/use-web-search-step-3.png"
                      alt="Screenshot showing use web search step 3."
                      title="Use web search step 3"
                      capture="Capture the use web search task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Read and dismiss the web search notice if it appears.
5. Select **Send Message**.

{% include media.html src="guides/use-web-search-step-5.png"
                      alt="Screenshot showing use web search step 5."
                      title="Use web search step 5"
                      capture="Capture the use web search task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. Turn **Web** off for later messages that should not use public search.

## Verify it worked

The answer should use web search when relevant. The notice appears only while web search is active and the tenant settings allow it.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Web** is missing | Web search is disabled or consent is not accepted | Ask an admin to review `enable_web_search`. |
| Web turns off in **Image** mode | Image generation disables source controls | Turn off **Image** first. |

## Related

- [Review pasted URLs]({{ '/guides/review-pasted-urls/' | relative_url }})
- [Use deep research]({{ '/guides/use-deep-research/' | relative_url }})
- [Search and Extract]({{ '/admin/knowledge/' | relative_url }})
