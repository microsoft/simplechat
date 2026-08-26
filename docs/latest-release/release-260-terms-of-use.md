---
layout: latest-release-feature
title: "Terms of Use Acceptance"
description: "Your organization can require you to accept a terms of use or rules of behavior notice before using SimpleChat, with the reminder repeating on a schedule your admins choose."
section: "Latest Release"
---

Current release version for Terms of Use Acceptance: **0.261.001**

When enabled, an acceptance screen appears before you reach the app. Admins choose whether it returns every session, once per day, or only when the text changes. Your accept and decline choices are recorded in the activity log, and the gate is enforced on the server so it cannot be skipped by navigating directly to a page.

## User Side

Your organization can require you to accept a terms of use or rules of behavior notice before using SimpleChat, with the reminder repeating on a schedule your admins choose.

## Admin Side

The gate is configured under Notices & Agreements, in the Terms of Use section. An admin supplies the popup title, the body text, and the wording on the accept and cancel buttons, so the notice can carry your organization's own language rather than a generic label.

Show Frequency decides how often the gate returns: at the start of every session, once per day, or just once per terms version. The last option is the one that matters for policy changes, because editing the text makes the gate reappear for people who already accepted the previous wording.

Declining sends the user to a configurable redirect, which defaults to `/`. That target is restricted to local paths, so the gate cannot be turned into an open redirect. Accept and decline are both written to the activity log, and enforcement happens on the server, so navigating straight to an internal URL does not bypass it.

## Why It Matters

This matters because many organizations must record that users acknowledged acceptable-use rules before working with an AI assistant.

## How to Try It

1. Sign in to SimpleChat and read the terms of use notice if your organization has enabled one.
2. Scroll through the full text before responding, since the content is set by your organization.
3. Choose Accept to continue into the app.
4. Expect the notice to reappear according to the schedule your admins configured.
5. If the wording changes, expect to be asked again even if you accepted the earlier version.
6. Choose Decline if you do not agree, which will end your session rather than continuing.
7. Contact your admin if you believe the notice is appearing more often than intended.

## Notes

- The Terms of Use Acceptance guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_terms_of_use_1.png`, `release_260_terms_of_use_2.png`, `release_260_terms_of_use_3.png` from the app Latest Features catalog.
