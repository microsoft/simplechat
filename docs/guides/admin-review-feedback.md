---
layout: page
title: "Review user feedback"
description: "Use the Review center's feedback dashboard, workbench and editor to understand user sentiment and track review follow-up."
section: "Guides"
audience: admin
version: "0.261.298"
---

## What this covers

Feedback review gives authorized reviewers a queue for the feedback users submit on assistant replies. It is distinct from the personal Feedback tab, which only shows a user's own submissions. In the V2 interface it is the **Feedback** section of the [Review center]({{ '/guides/admin-review-center/' | relative_url }}); the classic **Feedback Review** page offers the same review through the same APIs.

## Who can use it

Feedback review is available while **User Feedback** is enabled. By default, users with the **Admin** app role can use it. When **Require Feedback Admin Role** is enabled, only users with the **FeedbackAdmin** app role can use the review APIs, and the V2 account menu shows **Review center** to that role.

## See what needs attention

The feedback dashboard shows feedback awaiting review, negative feedback and the acknowledgement rate for the last 7, 30 or 90 days, archived feedback, feedback per day by rating, and the oldest feedback still waiting for a reviewer. Select any figure to open the queue filtered to the feedback it counts, or open one of the oldest entries directly.

## Review the queue

The queue lists feedback as rows beside the selected record. Search the prompt, response, reason, review notes and the user's name or email; filter by rating, review state, and active or archived records. **Export CSV** downloads every record matching the current search and filters.

Select a row to read the prompt, the assistant response and the user's reason, the review so far, and to **Retest** the prompt. Select **Review** to open the editor, where you can mark the feedback acknowledged and save analysis notes, the action taken, and a response to the user. The server records the review time and who reviewed it; the user never sees the reviewer's name.

Turn on **Notify the user** before saving to send the user a notification with your response. It opens their own feedback list, where the response is shown. Leave it off to save the review without telling them.

**Retest** runs the captured prompt against the current model configuration and shows the new answer beside the original one, so you can tell whether a change since then already addresses the feedback. It does not change the feedback record.

## Act on several records at once

Check the rows you want, or Shift+click to check a range, then **Acknowledge**, **Archive** or **Restore**, or **Delete** them together. **Select all matching** extends the selection to every record matching the filters, up to 500. The report under the bar names any record that could not be changed and why, for example because someone else changed it in the meantime.

## Archive and delete

Archive keeps a record out of the active queue while preserving it for later review; show **Archived** records to restore it. Permanent deletion cannot be undone. It is always confirmed with the number of records, and the server keeps the lifecycle audit entry.

## Version

Implemented in version **0.261.277** (`application/single_app/config.py`). The Review center's dashboard, workbench, bulk actions, reviewer attribution and user notification were added in version **0.261.298**.
