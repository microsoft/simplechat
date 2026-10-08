---
layout: page
title: "Use the Review center"
description: "Review user feedback and safety violations from dashboards, workbenches and full-page editors, one record or many at a time."
section: "Guides"
audience: admin
version: "0.261.298"
---

## What this covers

The **Review center** is the V2 interface's one place for administrator review. It has a **Feedback** section and a **Safety** section; each has a dashboard that shows what needs attention, a workbench for reviewing records one at a time or many at once, and full-page editors. It replaces the separate V2 Feedback Review and Safety Violations pages, whose old addresses now open the matching workbench.

## Who can use it

**Review center** appears in the account menu when you can open at least one of its sections:

- **Feedback**, while **User Feedback** is turned on: the **Admin** role, or the **FeedbackAdmin** role when **Require Feedback Admin Role** is on.
- **Safety**, while **Content Safety** or **Content Screening** is turned on: the **Admin** role, or the **SafetyViolationAdmin** role when **Require Safety Violation Admin Role** is on.

You only see the sections you can open. The rail on the left lists them; collapse it to icons with **Collapse**, and on a narrow screen pick a page from the list above the content instead.

## Start from a dashboard

Each dashboard covers the last 7, 30 or 90 days; change **Period** to switch. Every figure opens the workbench already filtered to the records it counts, so you go from "12 awaiting review" to those 12 records in one step. Every chart also offers its numbers as a data table.

- **Feedback**: feedback awaiting review, negative feedback in the period, the acknowledgement rate, archived feedback, feedback per day by rating, and the oldest feedback waiting for a reviewer.
- **Safety**: open violations, suspensions and blocks waiting for another reviewer (which opens them in **Approval requests**), users restricted now, warnings sent and whether they were acknowledged, unchecked chat content, violations per day by category, severity, action taken, and users with repeat violations.

Figures for the period include archived records, so the workbench they open shows active and archived records together.

## Work through the queue

The workbench lists records as one-line rows beside the selected record's detail. Search, filter, and page through the list; the filters, page and selected record are kept in the address, so you can bookmark a view or share it with another reviewer. Filters the toolbar has no control for, such as a user, a category or a period a dashboard figure applied, appear as chips you can remove one at a time.

Select a row to read it in the detail pane: for feedback, the conversation, the review so far and a retest of the prompt against the current model; for a violation, the flagged message, the user's history and current access, and where any warning, suspension or block stands, with a link to its approval request.

Use the arrow keys, Home and End to move through the list, and **Review** to open the record's editor.

## Act on many records at once

Check the box on each row you want, or Shift+click a second box to check the rows between. The header box checks the whole page; when more records match than the page shows, **Select all matching** checks every one of them, up to 500, and says when there were more.

The bar that appears offers what applies to all of them:

| Section | Actions |
| --- | --- |
| Feedback | **Acknowledge**, **Archive** or **Restore**, **Delete** |
| Safety violations | **Set status**, **Archive** or **Restore**, **Delete** |
| Unchecked chat content | **Recheck selected** |

Each record is changed exactly as saving it on its own would change it, and the report under the bar names every record that could not be changed and why: for example a violation waiting for a suspension to be approved, or a record someone else changed in the meantime. Only those records stay checked, so you can deal with them and try again. Deleting always asks first and says how many records it will delete.

## Review one record

The editor opens as a full page. **Back** returns to the workbench with the same filters and the record still selected; if you have unsaved changes, you are asked before they are discarded. Saving returns to the workbench and says what happened.

If someone else changed the record after you opened it, your save is refused rather than overwriting their change. Select **Reload** to see the latest version, then make your change again.

- **Feedback**: acknowledge it, record analysis notes, the action taken and a response to the user, and retest the prompt beside the original response. Your name is recorded with the review. Turn on **Notify the user** to send them a notification with your response, which opens their feedback.
- **Violation**: set the status, add notes, and choose an action. A warning is sent as soon as you save; a suspension or block waits for another eligible reviewer to approve it. The notification title and message start as the standard text for the action and follow your notes until you edit them. For a suspension, choose 24 hours, 7 days, 30 days or a custom time for access to return. Saving a violation that already has a suspension or block requests nothing more unless you tick **Request this suspension again** (or block).

See [Review user feedback]({{ '/guides/admin-review-feedback/' | relative_url }}) and [Review safety violations]({{ '/guides/admin-review-safety-violations/' | relative_url }}) for what each field and action does.

## Recheck unchecked chat content

**Unchecked chat content** lists messages that were allowed through when a required check could not finish. Recheck one message, or check several and select **Recheck selected**; they are rechecked one after another, and the report says what happened to each. See [Recheck chat content]({{ '/guides/recheck-chat-content/' | relative_url }}).

## Related

- [Review approval requests]({{ '/guides/review-approval-requests/' | relative_url }}), including the Approvals **Dashboard** and **Safety remediation** categories.

## Version

Implemented in version **0.261.298** (`application/single_app/config.py`).
