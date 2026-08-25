---
layout: latest-release-feature
title: "AI Usage Guidance in Chat"
description: "Your organization can display its own AI guidance directly under the chat composer, with control over how often it reappears."
section: "Latest Release"
---

Current release version for AI Usage Guidance in Chat: **0.261.001**

Admins write the notice in Markdown and choose how it behaves: always visible, dismissible for the session, dismissible for the day, or dismissible until the wording changes. If your organization updates the text, the notice comes back automatically so you see the current guidance rather than a stale version you dismissed months ago.

## User Side

Your organization can display its own AI guidance directly under the chat composer, with control over how often it reappears.

## Admin Side

The notice is configured under Notices & Agreements, in the Chat AI Notice section. The text is Markdown, so guidance can link to an internal policy page instead of restating it.

Display Behavior sets how insistent the notice is: always visible with no dismiss control, dismissible once per session, dismissible once per day, or dismissible once per message version. The last option is the useful default for guidance that changes, because editing the text brings the notice back for everyone who had already dismissed the previous version.

This replaces the previous practice of editing templates to put usage guidance in front of users, which meant the wording drifted from whatever policy actually said.

## Why It Matters

This matters because AI usage rules differ by organization, and the reminder is most useful sitting right where you type rather than buried in a policy document.

## How to Try It

1. Open Chat and look directly beneath the message composer.
2. Read the AI usage notice if your organization has configured one.
3. Follow any links in the notice for your local policy details.
4. Dismiss the notice if your admins allowed dismissal and you have read it.
5. Expect it to return based on the schedule your admins chose, such as each session or each day.
6. Watch for it to reappear automatically whenever your organization updates the wording.
7. Contact your admin if the guidance looks out of date for your team.

## Notes

- The AI Usage Guidance in Chat guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_chat_ai_notice_1.png`, `release_260_chat_ai_notice_2.png`, `release_260_chat_ai_notice_3.png` from the app Latest Features catalog.
