---
layout: latest-release-feature
title: "Source Review and Deep Research"
description: "How Source Review inspects web evidence before final chat answers"
section: "Latest Release"
---

Source Review adds a governed evidence-review layer for URLs and web-search citations before the assistant prepares a final answer.

## Why It Matters

Users can ground answers in reviewed source-page evidence instead of depending only on snippets or unsupported browsing assumptions.

## How to Try It

1. Ask a web-grounded question in Chat and enable the **Sources** experience when available.
2. Paste URLs or use Web Search citations that should be reviewed before the final answer.
3. Use Deep Source Review when bounded source traversal is helpful for archives, press-release lists, or official source indexes.
4. Admins can tune allowlists, blocklists, page budgets, rendering, and access controls from **Search & Extract**.

## Notes

- Source Review treats fetched pages as untrusted evidence.
- Deep traversal remains bounded by admin-controlled budgets and safety checks.
- JavaScript rendering and Load More hydration are optional because they add runtime cost.
