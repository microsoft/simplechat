---
layout: page
title: "Use deep research"
description: "Ask chat to perform deeper evidence review for URLs and sources in a message."
section: "Guides"
audience: user
---

## What this does

**Deep Research** is a chat control that reviews sources more deeply for the current message. It is separate from normal workspace search and direct URL Access.

{% include media.html type="video"
                      title="Use deep research walkthrough"
                      poster="video-posters/guide-use-deep-research.png"
                      capture="Recording planned. Show use deep research end to end and explain why this task helps a user." %}

## Why you would use this

Use Deep Research when the answer depends on evidence review rather than a quick model response, especially when pasted URLs need a deeper read. It is wrong for short drafting tasks, private content that should not leave approved paths, or work that only needs local workspace documents.

## Before you start

- Admins must enable `enable_source_review`; deeper behavior may depend on `enable_deep_source_review`; see [Search and Extract]({{ '/admin/search-extract/' | relative_url }}).
- Direct URLs in the prompt are subject to configured URL limits.
- Do not paste sensitive URLs unless your organization permits that review path.

## Steps

1. Open **Chat**.
2. Type the question that needs source review.
3. Include exact URLs when specific web pages should be reviewed.

{% include media.html src="guides/use-deep-research-step-3.png"
                      alt="Screenshot showing use deep research step 3."
                      title="Use deep research step 3"
                      capture="Capture the use deep research task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Select **Research**; its tooltip is **Deep Research**.
5. Select **Send Message**.

{% include media.html src="guides/use-deep-research-step-5.png"
                      alt="Screenshot showing use deep research step 5."
                      title="Use deep research step 5"
                      capture="Capture the use deep research task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. Review progress and the final answer; conversation details can show **Deep Research Enabled** and **Deep Research Used**.

## Verify it worked

The response reflects reviewed evidence rather than only general model knowledge, and metadata can show that Deep Research was enabled and used.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Research** is hidden | Source review is off or unavailable for the prompt | Add a valid URL or ask an admin to enable source review. |
| A URL count warning appears | The prompt exceeds the per-turn URL limit | Split URLs across multiple turns. |

## Related

- [Review pasted URLs]({{ '/guides/review-pasted-urls/' | relative_url }})
- [Use web search]({{ '/guides/use-web-search/' | relative_url }})
- [Search and Extract]({{ '/admin/search-extract/' | relative_url }})
