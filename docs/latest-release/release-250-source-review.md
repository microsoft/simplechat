---
layout: latest-release-feature
title: "Source Review and Deep Research"
description: "How Source Review inspects URLs, web-search citations, rendered pages, and bounded source links"
section: "Latest Release"
---

Current release version: **0.250.001**

Source Review can inspect URLs and web-search citations, follow bounded source links, use model-assisted link planning, hydrate Load More pages, and enforce allow-only user access for Deep Research.

## User Side

Users can ask questions against pasted URLs or web evidence and let Source Review inspect source pages before the final answer is generated.

## Admin Side

Admins control Source Review defaults, page budgets, domain policy, Deep Research access, rendered-page fallback, Load More limits, and audit logging.

## Screenshot Placeholder

Replace `/images/latest-release/release_250_source_review.png` with a screenshot of Source Review controls, Deep Research allowed users, rendered-page status, and reviewed source evidence in Chat.

## Why It Matters

Web-grounded answers are more useful when the app reviews real source pages under explicit limits instead of relying on snippets alone.

## How to Try It

1. Open **Admin Settings > Search & Extract** and review Source Review or Deep Research controls.
2. Open Chat and ask a URL or web-evidence question with Sources enabled.
3. Review citations, thoughts, and source audit details.

## Notes

- Fetched pages are treated as untrusted evidence and remain bounded by admin-controlled budgets.
