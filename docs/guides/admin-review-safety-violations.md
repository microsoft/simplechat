---
layout: page
title: "Review safety violations"
description: "Review flagged activity, warn, suspend, or block a user, and recheck chat messages whose required safety checks did not finish."
section: "Guides"
audience: admin
version: "0.261.297"
---

## What this covers

The React v2 Safety Violations page separates administrator review from a user's personal Violations tab. It combines the violation queue with the unchecked-chat-content queue used when a required check could not finish.

## Who can use it

The page appears in the account menu when either **Content Safety** or **Content Screening** is enabled. By default, users with the **Admin** app role can open it. When **Require Safety Violation Admin Role** is enabled, only users with the **SafetyViolationAdmin** app role can use the review APIs and the v2 menu shows the page to that role.

## Review violations

The summary shows total, open, resolved, dismissed, recent, and blocked counts, plus status and action distributions. Filter by status, recorded action, and active/archived records. Choose the page size and list or card view; export CSV downloads all violations matching the active filters.

Open **Review** to inspect the flagged message, triggered categories, user notes, and current review status. Reviewers can set a status and administrator notes, and choose an action. The server validates the action and reviewer permissions; AI-generated findings cannot be used to warn or restrict a user.

Archive preserves a violation outside the active queue and can be reversed from the archived view. Permanent deletion cannot be undone, is confirmed in the page, preserves audit history, and is refused by the server while a remediation approval is pending.

## Warn, suspend, or block a user

Each action sends the user the notification text in the review. Leave it as generated, or edit it: the default text names the violation, its triggered categories and your administrator notes.

| Action | What happens when you save | Who else is involved |
| --- | --- | --- |
| **Warn user** | The warning is sent to the user straight away. | Nobody. A warning restricts nothing, so it doesn't wait for another reviewer. Your decision is recorded in the activity log. |
| **Suspend user** | An approval request is created. Access is restricted until the restore date you set only once the request is approved. | Another eligible reviewer approves it in **Approval Requests**. You can deny your own request to cancel it, but never approve it. |
| **Block user** | An approval request is created. Access is blocked, with no restore date, only once the request is approved. | The same as a suspension. |

Suspensions and blocks need a second reviewer because they take away a person's access; requiring two people for that decision protects users from a single mistaken or malicious reviewer. A record with a pending approval can't be changed or deleted until the request is decided.

Saving a warned record again, for example to resolve it, doesn't send the warning a second time.

### Warning acknowledgment

A warning has to be acknowledged. The V2 interface shows it in a dialog the next time the user opens SimpleChat, and again in every tab and on every device until they select **I understand**. In the classic interface the warning arrives as a notification.

The review shows **Warning acknowledged** with the date, or **Not yet acknowledged**, so you can tell whether the user has read it before deciding on a further step. Warnings sent before version 0.261.297 are shown as sent before acknowledgment was tracked, and are never shown to the user again.

### What a suspended or blocked user sees

Once a suspension or block takes effect, the user can still sign in, but every page opens an **Access restricted** screen instead of an error. It shows the notification text from the review, the restore date and time for a suspension in the user's own time zone, the violation id, and a **Sign out** link. A suspension ends by itself at the restore time; restore access earlier from Control Center. A restriction applied from Control Center shows generic text, since it carries no notification.

Users with the **Admin** role are never restricted, even when an access restriction is stored for them.

### Escalate

**Escalate** was a label with no workflow behind it, and it can no longer be chosen. Records that already carry it show **Escalated (legacy)** and can still be saved, so you can resolve them or replace the action with another one. The summary only mentions legacy escalations when there are some.

## Recheck unchecked chat content

The unchecked queue shows check metadata, not message bodies. Filter it by conversation source, message type, or incomplete scanner, then load further results as needed. **Recheck** applies current rules to the selected message and requires explicit confirmation. A confirmed finding on an AI reply can remove it from saved and shared chat; rechecking cannot undo earlier views or external actions. A checker outage leaves the message available and marked for another attempt.

## Version

Implemented in version **0.261.277** (`application/single_app/config.py`). Warnings without a second reviewer, warning acknowledgment, the Access restricted screen and the removal of Escalate were added in version **0.261.297**.
