---
layout: latest-release-feature
title: Extract Metadata for Many Documents at Once
description: The workspace multi-select bar now includes Extract Metadata, so a whole batch of documents can be enriched in one action.
section: Latest Release
generated_from_catalog: true
---

Current release version for Extract Metadata for Many Documents at Once: **0.261.001**

Personal, group, and public workspace document lists all expose the action when metadata extraction is enabled for your environment. Selected documents are queued through the same background workflow used for a single file, preserving generated titles along with authors, abstracts, keywords, publication dates, and organization metadata.

## Why It Matters

This matters because running metadata extraction one document at a time does not scale past a handful of files.

## How to Try It

1. Open Personal Workspace and go to the Documents section.
2. Use the checkboxes to select several processed documents.
3. Find Extract Metadata in the multi-select bar that appears.
4. Start the action and let the background job run.
5. Refresh the list and open one of the selected documents.
6. Confirm authors, keywords, abstract, and publication date were populated.
7. If you do not see the action, ask your admin whether metadata extraction is enabled.

## Where to Find It

- **Open Personal Workspace** &mdash; Multi-select documents and run Extract Metadata.
