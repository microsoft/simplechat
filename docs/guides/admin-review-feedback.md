---
layout: page
title: "Review user feedback"
description: "Use the Review center's feedback dashboard, workbench and editor to understand user sentiment, classify feedback by theme, and track review follow-up, with optional AI-suggested reviews."
section: "Guides"
audience: admin
version: "0.261.299"
---

## What this covers

Feedback review gives authorized reviewers a queue for the feedback users submit on assistant replies. It is distinct from the personal Feedback tab, which only shows a user's own submissions. In the V2 interface it is the **Feedback** section of the [Review center]({{ '/guides/admin-review-center/' | relative_url }}); the classic **Feedback Review** page offers the same review through the same APIs.

## Who can use it

Feedback review is available while **User Feedback** is enabled. By default, users with the **Admin** app role can use it. When **Require Feedback Admin Role** is enabled, only users with the **FeedbackAdmin** app role can use the review APIs, and the V2 account menu shows **Review center** to that role.

## See what needs attention

The feedback dashboard shows feedback awaiting review, negative feedback and the acknowledgement rate for the last 7, 30 or 90 days, archived feedback, feedback per day by rating, the period's feedback by theme, and the oldest feedback still waiting for a reviewer. Select any figure or theme to open the queue filtered to the feedback it counts, or open one of the oldest entries directly. Feedback nobody has classified yet is counted separately, so you can tell how much of the period the breakdown covers.

## Review the queue

The queue lists feedback as rows beside the selected record. Search the prompt, response, reason, review notes and the user's name or email; filter by rating, review state, theme, and active or archived records. **Export CSV** downloads every record matching the current search and filters.

Select a row to read the prompt, the assistant response and the user's reason, the review so far, and to **Retest** the prompt. Select **Review** to open the editor, where you can mark the feedback acknowledged, choose its theme, and save analysis notes, the action taken, and a response to the user. The server records the review time and who reviewed it; the user never sees the reviewer's name or the theme.

The theme says what the feedback was about: **Accuracy**, **Citations**, **Retrieval**, **Formatting**, **Tone**, **Speed**, **Safety**, **Praise** or **Other**. Classifying feedback is what lets the dashboard show where answers fall short, for example whether complaints are mostly about missing sources or about tone.

Turn on **Notify the user** before saving to send the user a notification with your response. It opens their own feedback list, where the response is shown. Leave it off to save the review without telling them.

**Retest** runs the captured prompt against the current model configuration and shows the new answer beside the original one, so you can tell whether a change since then already addresses the feedback. It does not change the feedback record.

## Act on several records at once

Check the rows you want, or Shift+click to check a range, then **Acknowledge**, **Archive** or **Restore**, or **Delete** them together. **Select all matching** extends the selection to every record matching the filters, up to 500. The report under the bar names any record that could not be changed and why, for example because someone else changed it in the meantime.

## Get AI-suggested reviews

When **Enable AI Assist in the Review Center** is on, AI can draft reviews for you:

- In the editor, **Ask AI** then **Analyze this record** suggests whether to acknowledge the feedback, analysis notes, an action, a response to the user, a theme and whether to archive it, with the AI's reason and confidence. **Apply to draft** fills your unsaved review and marks what it changed; check it, edit it, and save.
- In the queue, check records and select **Triage with AI** to store a suggested review on each. Then open **AI suggestions** to approve them one at a time or together, or dismiss them.

Approving a suggestion saves it as your review, with your name, and sets its theme. The user who gave the feedback can read a review's analysis notes, action taken and response to the user with their feedback, so the queue shows that text in full under **Visible to the user** for you to check before you approve; a field the suggestion would empty is shown as **Cleared**. Approving a suggestion never sends the user a notification. To notify the user, open the feedback and save it with **Notify the user**.

The AI is sent the rating, the prompt, the response, the user's reason and the review so far, shortened, with email addresses and GUIDs in the text replaced. It is never told who the user is, and it is only ever asked about one user's feedback at a time. Text it writes for a review that repeats a long passage of another feedback record in the same request is refused. An administrator turns AI assist on, and can give it your organization's review guidance, in [Security settings]({{ '/admin/security/' | relative_url }}#permissions-section).

## Archive and delete

Archive keeps a record out of the active queue while preserving it for later review; show **Archived** records to restore it. Permanent deletion cannot be undone. It is always confirmed with the number of records, and the server keeps the lifecycle audit entry.

## Version

Implemented in version **0.261.277** (`application/single_app/config.py`). The Review center's dashboard, workbench, bulk actions, reviewer attribution and user notification were added in version **0.261.298**. Themes and AI-suggested reviews were added in version **0.261.299**.
