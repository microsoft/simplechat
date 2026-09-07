---
layout: latest-release-feature
title: Refer Back to a File You Already Talked About
description: A follow-up question can say "that XML file" or "the same spreadsheet" and SimpleChat works out which source you mean.
section: Latest Release
generated_from_catalog: true
---

Current release version for Refer Back to a File You Already Talked About: **0.261.001**

Follow-up turns detect references such as "that XML file", "same template", or "previous spreadsheet" and combine the earlier grounded sources with whatever you have selected now. Access is rechecked rather than assumed: prior sources are resolved from the conversation's recorded grounded references and revalidated against your current permissions before they are used again.

## Why It Matters

This matters because natural follow-ups are how people actually talk, and reselecting the same document on every single turn is needless friction.

## How to Try It

1. Open Chat and ground a question on a specific workspace document.
2. Read the answer and note which document was used.
3. Ask a follow-up that refers to it indirectly, such as "summarize that spreadsheet".
4. Confirm the answer uses the earlier document without you reselecting it.
5. Try a phrase like "the same template" on a different source type.
6. Expand Sources on the follow-up answer to confirm the right file was used.
7. Continue the thread and confirm the reference still resolves several turns later.

## Where to Find It

- **Open Chat** &mdash; Ask a follow-up that refers to an earlier document indirectly.
