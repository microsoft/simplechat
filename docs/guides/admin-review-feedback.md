---
layout: page
title: "Review user feedback"
description: "Use the React v2 administrator feedback queue to understand user sentiment and track review follow-up."
section: "Guides"
audience: admin
version: "0.261.277"
---

## What this covers

The React v2 Feedback Review page gives authorized reviewers a separate queue for feedback submitted on assistant replies. It is distinct from the personal Feedback tab, which only shows a user's own submissions.

## Who can use it

The page appears in the account menu when **User Feedback** is enabled. By default, users with the **Admin** app role can open it. When **Require Feedback Admin Role** is enabled, only users with the **FeedbackAdmin** app role can use the review APIs and the v2 menu shows the page to that role.

## Review the queue

Feedback Review summarizes the total, positive, negative, neutral, acknowledged, and recent submissions. Filter the queue by feedback type, acknowledgement status, or active/archived records, then choose a page size and list or card view. Export CSV downloads all records matching the active filters.

Open **Review** on an entry to read the prompt, assistant response, and user reason. Reviewers can mark a submission acknowledged and save analysis notes, a response to the user, and an action taken. Saving updates the review timestamp on the server.

Use **Retest** to run the captured prompt against the current model configuration and compare the returned response with the original. This does not replace the original feedback record.

## Archive and delete

Archive keeps a record out of the active queue while preserving it for later review; switch the records filter to **Archived** to restore it. Permanent deletion cannot be undone. The page asks for confirmation, and the server retains the lifecycle audit entry.

## Version

Implemented in version **0.261.277** (`application/single_app/config.py`).
