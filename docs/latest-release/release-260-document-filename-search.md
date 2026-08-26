---
layout: latest-release-feature
title: Find a Document by Its File Name
description: The document picker now matches file names, not just document titles, so a file is findable by what it is actually called.
section: Latest Release
generated_from_catalog: true
---

Current release version for Find a Document by Its File Name: **0.261.001**

Typing any fragment of a file name now surfaces the document, anywhere in the name, so searching 200 finds Quarterly_Report_200_final.pdf. Multi-word queries work too, with underscores, hyphens, and dots treated as word breaks, so "report 200" matches the same file. The same improvement applies to the scope, tags, prompt, model, and agent selectors, and document rows show the file name beneath the title whenever the two differ.

## Why It Matters

This matters because any document with extracted title metadata used to be completely unfindable by its own file name.

## How to Try It

1. Open Chat and open the workspace document picker.
2. Type a fragment from the middle of a known file name.
3. Confirm the document appears even though the fragment is not in its title.
4. Try a two-word query separated by a space, such as "report 200".
5. Note the file name shown beneath the title where the two differ.
6. Open the scope, tags, or agent selector and confirm searching behaves the same way.
7. Clear the search and confirm the list structure returns without stray divider lines.

## Where to Find It

- **Open Chat** &mdash; Search the document picker by file name fragment.
