---
layout: latest-release-feature
title: "Used Documents View and Conversation Forking"
description: "A Used Documents mode shows only the documents actually cited in a conversation, and you can fork a conversation from any response to explore a different direction."
section: "Latest Release"
---

Current release version for Used Documents View and Conversation Forking: **0.261.001**

The chat side pane gained a Used Documents mode that lists the documents a conversation has genuinely drawn on, without opening the full details modal, and it opens automatically the first time cited documents appear. Separately, forking from an assistant response creates an independent copy of the conversation through that message, so the original stays intact.

## User Side

A Used Documents mode shows only the documents actually cited in a conversation, and you can fork a conversation from any response to explore a different direction.

## Admin Side

Admins decide whether Used Documents View and Conversation Forking is available in your environment. If you cannot find Open Chat and Open Conversations, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Why It Matters

This matters because long conversations accumulate a lot of context, and both knowing what was actually used and being able to branch without losing the thread are hard problems otherwise.

## How to Try It

1. Open Chat and start a conversation grounded on several workspace documents.
2. Ask a few questions so the assistant cites real sources.
3. Watch the side pane open to Used Documents the first time a citation appears.
4. Switch the side pane to Used Documents manually at any time to see the current list.
5. Confirm the list shows only documents that were genuinely cited, not everything in scope.
6. Find an assistant response where you want to try a different direction and choose to fork from it.
7. Work in the forked copy and confirm the original conversation is unchanged.

## Notes

- The Used Documents View and Conversation Forking guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_used_documents_fork_1.png`, `release_260_used_documents_fork_2.png`, `release_260_used_documents_fork_3.png` from the app Latest Features catalog.
