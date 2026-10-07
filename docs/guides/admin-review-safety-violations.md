---
layout: page
title: "Review safety violations"
description: "Review flagged activity, manage remediation requests, and recheck chat messages whose required safety checks did not finish."
section: "Guides"
audience: admin
version: "0.261.277"
---

## What this covers

The React v2 Safety Violations page separates administrator review from a user's personal Violations tab. It combines the violation queue with the unchecked-chat-content queue used when a required check could not finish.

## Who can use it

The page appears in the account menu when either **Content Safety** or **Content Screening** is enabled. By default, users with the **Admin** app role can open it. When **Require Safety Violation Admin Role** is enabled, only users with the **SafetyViolationAdmin** app role can use the review APIs and the v2 menu shows the page to that role.

## Review violations

The summary shows total, open, resolved, dismissed, recent, and escalated-or-blocked counts, plus status and action distributions. Filter by status, recorded action, and active/archived records. Choose the page size and list or card view; export CSV downloads all violations matching the active filters.

Open **Review** to inspect the flagged message, triggered categories, user notes, and current review status. Reviewers can set a status and administrator notes. Actions that warn or restrict a user require notification details and use the existing approval and access-restriction workflow. A suspension also requires a restore date. The server validates the action and reviewer permissions; AI-generated findings cannot be used to warn or restrict a user.

Archive preserves a violation outside the active queue and can be reversed from the archived view. Permanent deletion cannot be undone, is confirmed in the page, preserves audit history, and is refused by the server while a remediation approval is pending.

## Recheck unchecked chat content

The unchecked queue shows check metadata, not message bodies. Filter it by conversation source, message type, or incomplete scanner, then load further results as needed. **Recheck** applies current rules to the selected message and requires explicit confirmation. A confirmed finding on an AI reply can remove it from saved and shared chat; rechecking cannot undo earlier views or external actions. A checker outage leaves the message available and marked for another attempt.

## Version

Implemented in version **0.261.277** (`application/single_app/config.py`).
