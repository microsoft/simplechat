---
layout: latest-release-feature
title: Agent Document Searches Now Produce Real Citations
description: Documents an agent finds through its document search action are now recorded as proper document sources instead of appearing only as a raw tool call.
section: Latest Release
generated_from_catalog: true
---

Current release version for Agent Document Searches Now Produce Real Citations: **0.261.001**

This covers all three document search functions: relevance-ranked search, ordered chunk retrieval, and document summarization, across personal, group, and public workspaces. Retrieved documents now appear in the message Sources list, are clickable, open in the enhanced citation viewer, and reach the Used documents drawer. It applies to streaming and non-streaming chat, document actions, cancelled and interrupted streams, and scheduled workflow runs.

## Why It Matters

This matters because an agent could previously read a dozen documents to answer you and none of them would show up as a source you could actually open and check.

## How to Try It

1. Open Chat and select an agent that has a document search action attached.
2. Ask a question that requires the agent to search your workspace documents.
3. When the answer arrives, expand the Sources disclosure below the message.
4. Confirm the retrieved documents are listed rather than only a raw tool call.
5. Select one of the document sources to open it in the citation viewer.
6. Open the Used documents drawer and confirm cited documents are recorded there.
7. Try the same question in a group or public workspace to confirm the behavior matches.

## Where to Find It

- **Open Chat** &mdash; Ask an agent a question that requires document search, then inspect Sources.
