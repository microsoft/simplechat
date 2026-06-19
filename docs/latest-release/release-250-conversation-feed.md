---
layout: latest-release-feature
title: "Faster Conversation Lists"
description: "Conversation lists now load in pages, improving startup performance for users with large chat histories."
section: "Latest Release"
---

Current release version: **0.250.001**

Chat startup now loads pinned, unread, and recent conversations first, then loads more as needed. Search can still query titles beyond the currently loaded page.

## User Side

Conversation lists now load in pages, improving startup performance for users with large chat histories.

## Admin Side

Availability may depend on tenant settings, governance policies, workspace scope, action configuration, or admin-managed identities. If you do not see this capability, contact your SimpleChat admin.

## Screenshot Placeholder

Replace `/images/latest-release/release_250_conversation_feed.png` with a screenshot showing faster conversation lists in the app.

## Why It Matters

This matters because large conversation histories should not slow down everyday chat startup.

## How to Try It

1. Use Load More or scroll near the bottom of the conversation list to bring in older conversations.
2. Use title search when you need a conversation that is not loaded on the current page.
3. Hidden conversations stay out of the default feed until you enable the hidden-conversation toggle.

## Notes

- This guide is part of the SimpleChat 0.250.001 latest-feature set.
- Screenshot filenames are placeholders until final captures are added.
