---
layout: page
title: "Review safety violations"
description: "Review flagged activity, warn, suspend, or block a user, get AI-suggested reviews, and recheck chat messages whose required safety checks did not finish."
section: "Guides"
audience: admin
version: "0.261.299"
---

## What this covers

Safety review separates administrator review from a user's personal Violations tab. In the V2 interface it is the **Safety** section of the [Review center]({{ '/guides/admin-review-center/' | relative_url }}): a dashboard, a violations workbench, and the unchecked-chat-content queue used when a required check could not finish. The classic **Safety Violations** page offers the same review through the same APIs.

## Who can use it

Safety review is available when either **Content Safety** or **Content Screening** is enabled. By default, users with the **Admin** app role can use it. When **Require Safety Violation Admin Role** is enabled, only users with the **SafetyViolationAdmin** app role can use the review APIs, and the V2 account menu shows **Review center** to that role.

## See what needs attention

The safety dashboard shows open violations (new or in review), suspensions and blocks waiting for another reviewer, users restricted now, warnings sent in the last 7, 30 or 90 days and how many were acknowledged, and unchecked chat content. Charts break the period down by day and category, by severity and by the action taken, and list users with repeat violations. Select any figure to open the violations it counts; the remediation figure opens the waiting requests in **Approval requests**.

## Review violations

The workbench lists violations as rows beside the selected violation. Search the message, notes, categories and the user's name or email; filter by status (including **Open**), action, remediation state, and active or archived records. **Export CSV** downloads every violation matching the current search and filters.

Select a row to read the flagged message and triggered categories, the user's other violations and whether their access is restricted now, and where any warning, suspension or block stands, with a link to its approval request. Select **Review** to open the editor, where you set a status and notes and choose an action. The server validates the action and reviewer permissions; AI-generated findings cannot be used to warn or restrict a user.

To review several violations at once, check their rows, or Shift+click to check a range, then **Set status**, **Archive** or **Restore**, or **Delete**. **Select all matching** extends the selection to every violation matching the filters, up to 500. The report names any violation that could not be changed and why; a violation waiting for a suspension or block to be approved is always left as it is.

Archive preserves a violation outside the active queue and can be reversed from the archived view. Permanent deletion cannot be undone, is confirmed with the number of violations, preserves audit history, and is refused by the server while a remediation approval is pending.

## Warn, suspend, or block a user

Each action sends the user the notification in the review. The editor fills in the standard title and message for the action, which name the violation, its triggered categories and your administrator notes; change them as needed, or reset them to the standard text.

| Action | What happens when you save | Who else is involved |
| --- | --- | --- |
| **Warn user** | The warning is sent to the user straight away. | Nobody. A warning restricts nothing, so it doesn't wait for another reviewer. Your decision is recorded in the activity log. |
| **Suspend user** | An approval request is created. Access is restricted until the restore time you choose only once the request is approved. | Another eligible reviewer approves it in **Approval Requests**. You can deny your own request to cancel it, but never approve it. |
| **Block user** | An approval request is created. Access is blocked, with no restore date, only once the request is approved. | The same as a suspension. |

For a suspension, choose 24 hours, 7 days or 30 days from when you save, or a custom date and time.

Suspensions and blocks need a second reviewer because they take away a person's access; requiring two people for that decision protects users from a single mistaken or malicious reviewer. A record with a pending approval can't be changed or deleted until the request is decided. When the request is denied, or expires after three days without a decision, the violation is unlocked again and shows the outcome, so you can choose another action or request it again.

Saving a violation whose suspension or block was already requested or applied, for example to resolve it, doesn't request it again. To ask for it again -- after a request was denied, expired or couldn't be applied, or to change when access returns -- tick **Request this suspension again** (or block) before saving. Both the classic review and the Review center offer it whenever the violation already records that action and no request is waiting. Until you tick it, the review says where the last request stands and doesn't send the notification or restore time.

Saving a warned record again, for example to resolve it, doesn't send the warning a second time. Neither do two saves that overlap, such as a double-click or two reviewers saving the same violation at once: only the first sends it, and the other is refused and asks you to reload. While a warning is being sent, the violation shows **Sending** and can't be changed or deleted. If you change the action away from **Warn user**, save, and later choose **Warn user** again, a new warning is sent. It replaces the earlier one on the record, and the user has to acknowledge the new warning even if they acknowledged the earlier one.

If someone else changes a violation after you open it, including the user acknowledging a warning, your save is refused instead of overwriting their change. Reload the violation and make your change again. A suspension or block saved while another reviewer sends a warning or requests another restriction on the same violation is refused the same way, and the request it created is withdrawn, so only one request is ever left for the violation.

### Warning acknowledgment

A warning has to be acknowledged. The V2 interface shows it in a dialog the next time the user opens SimpleChat, and again in every tab and on every device until they select **I understand**. In the classic interface the warning arrives as a notification.

The review shows **Warning acknowledged** with the date, or **Not yet acknowledged**, so you can tell whether the user has read it before deciding on a further step. An acknowledgment always belongs to the warning the user read: if a newer warning replaces it while it is on their screen, selecting **I understand** shows the newer warning instead of recording anything. Warnings sent before version 0.261.297 are shown as sent before acknowledgment was tracked, and are never shown to the user again.

### What a suspended or blocked user sees

Once a suspension or block takes effect, the user can still sign in, but every page opens an **Access restricted** screen instead of an error. It shows the notification text from the review, the restore date and time for a suspension in the user's own time zone, the violation id, and a **Sign out** link. A suspension ends by itself at the restore time; restore access earlier from Control Center. A restriction applied from Control Center shows generic text, since it carries no notification.

Users with the **Admin** role are never restricted, even when an access restriction is stored for them.

### Escalate

**Escalate** was a label with no workflow behind it, and it can no longer be chosen. Records that already carry it show **Escalated (legacy)** and can still be saved, so you can resolve them or replace the action with another one. The dashboard only mentions legacy escalations when there are some.

## Get AI-suggested reviews

When **Enable AI Assist in the Review Center** is on, AI can suggest a status, an action, notes, the notification for a warning, suspension or block, a suspension's length, and whether to archive, with its reason and confidence. It suggests; you decide.

- In the editor, **Ask AI** then **Analyze this record** suggests a review, and **Apply to draft** fills your unsaved review and marks what it changed. Nothing is sent or requested until you save.
- In the workbench, check violations and select **Triage with AI** to store a suggested review on each. Violations held by a pending request or a warning being sent are skipped.
- **AI suggestions** lists them. Each row shows what approving it changes and sets off: **Sends a warning**, **Needs a second reviewer**, or **Already on this violation**. You can edit the notification's title and message on the row before you approve.

Approving a suggestion saves it exactly as saving the violation yourself would: a warning is sent straight away, and a suspension or block creates an approval request that another eligible reviewer must approve. That is why **Approve all ready** never includes a suspension or block; tick each one yourself. The confirmation says how many users are about to be warned. A suggestion that repeats a suspension or block the violation already records updates the review only and requests nothing new; to request it again, open the violation and select **Request this suspension again** (or block).

Some limits apply whatever the AI answers. It is never offered **Escalate**. A finding about an AI-generated response can only get **No action**, because it is about the AI, not the user. A warning, suspension or block that was already applied or sent is never replaced by a weaker action.

The AI is sent the flagged text, its categories and severity, whether the user or an AI response wrote it, the review so far, where any request stands, whether a warning was acknowledged, and how many earlier violations the same user has. It is never told who the user is, and email addresses and GUIDs in the text are replaced. Your organization's **Review Guidance for the AI Assistant**, in [Security settings]({{ '/admin/security/' | relative_url }}#permissions-section), tells it your policy, for example when a first violation only gets a warning.

## Recheck unchecked chat content

**Unchecked chat content** has its own page in the Safety section. It shows check metadata, not message bodies. Filter it by conversation source, message type, or incomplete scanner, then load further results as needed. **Recheck** applies current rules to a message and requires explicit confirmation; check several messages and select **Recheck selected** to recheck them one after another, with a report on each. A confirmed finding on an AI reply can remove it from saved and shared chat; rechecking cannot undo earlier views or external actions. A checker outage leaves the message available and marked for another attempt.

## Version

Implemented in version **0.261.277** (`application/single_app/config.py`). Warnings without a second reviewer, warning acknowledgment, the Access restricted screen and the removal of Escalate were added in version **0.261.297**. The Review center, bulk review, unlocking violations whose request was denied or expired, and requesting a suspension or block again only on purpose were added in version **0.261.298**. AI-suggested reviews were added in version **0.261.299**.
