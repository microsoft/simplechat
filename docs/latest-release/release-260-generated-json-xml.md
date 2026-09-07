---
layout: latest-release-feature
title: Get Answers Back as JSON or XML Files
description: Requests that produce JSON or XML are saved as downloadable artifacts instead of dumping file-shaped content into the middle of a reply.
section: Latest Release
generated_from_catalog: true
---

Current release version for Get Answers Back as JSON or XML Files: **0.261.001**

Document Analyze and the generated export flows now recognize natural phrasing for JSON and XML conversion, including requests to populate an XML template, and XML serialization is supported by the durable export pipeline. Prompts that only read a source, such as "summarize this XML document" or "validate this JSON object", are deliberately not treated as generation requests, so you still get an answer rather than a file.

## Why It Matters

This matters because a thousand-line JSON payload pasted into a chat bubble is not something you can actually use.

## How to Try It

1. Open Chat and ground the conversation on a structured source such as a spreadsheet.
2. Ask for the result as JSON, for example "export this as JSON".
3. Wait for the run to finish and look for the generated artifact card in the reply.
4. Download the artifact and confirm it is valid, complete JSON.
5. Repeat the request asking for XML instead.
6. Try populating an XML template from a source document.
7. Ask a reading question such as "summarize this XML" and confirm you get an answer, not a file.

## Where to Find It

- **Open Chat** &mdash; Request JSON or XML output and download the generated artifact.
