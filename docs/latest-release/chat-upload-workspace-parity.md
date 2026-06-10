---
layout: latest-release-feature
title: "Chat Upload Workspace Parity"
description: "How chat uploads become personal or group workspace documents depending on conversation scope"
section: "Latest Release"
---

Current release version: **0.241.183**

Chat Upload Workspace Parity keeps chat uploads familiar while making the matching workspace document the durable source of truth whenever workspace processing is available.

## User Side

In personal conversations, an eligible chat upload becomes a personal workspace document, gets linked back to the conversation, and appears in chat as a workspace-backed file message. In group and group multi-user conversations, eligible uploads go to the writable group workspace instead of the user's personal workspace. After processing, the file can be searched, analyzed, compared, cited, tagged, and governed through normal workspace flows.

## Admin Side

Admins enable chat file uploads, personal workspaces, group workspaces, and the workspace upload pipeline that makes the handoff possible. Group upload destinations still respect group write roles, so users who can chat in a group do not automatically gain permission to add documents to that group workspace.

## Screenshot Placeholder

Add a personal chat screenshot showing an uploaded file message with workspace-backed processing progress and a linked personal workspace document.

Add a group chat screenshot showing the group upload destination picker or a group workspace document created from a group conversation.

## Why It Matters

A file added in chat should become useful workspace knowledge without asking users to re-upload it somewhere else.

## How to Try It

1. Open a personal chat and upload a supported file.
2. Wait for workspace processing to complete and confirm the file is linked from the conversation.
3. Open the Workspaces tool or Personal Workspace and use Search, Analyze, or Compare against the uploaded document.
4. Repeat from a group or group multi-user conversation and confirm the uploaded file lands in the group workspace when you have a writable group role.

## Notes

- Personal chat uploads hand off to personal workspace documents when personal workspaces are enabled.
- Group and group multi-user chat uploads hand off to group workspace documents and require a writable group role.
- When workspace handoff is not available, the existing chat-only upload behavior remains the fallback for eligible scenarios.