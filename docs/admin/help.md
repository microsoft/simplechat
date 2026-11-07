---
layout: page
title: "Help settings"
description: "The end-user Support menu and its feedback mailbox, which release announcements users see, feedback to the SimpleChat team, and the admin release catalog."
section: "Administration"
audience: admin
admin_tab: help
redirect_from:
  - /admin/send-feedback/
  - /admin/latest-features/
---


# Help settings

## What this group controls

Help is where you give your users a supported way to ask for help and learn what changed. It also gives you a direct line to the SimpleChat product team. It covers four things:

- The **Support** menu end users see in navigation.
- The **Send Feedback** cards you use to report a bug or request a feature from the SimpleChat team.
- The release announcements users see under **Latest Features**.
- **Admin Latest Features**, a catalog of what each release changed for administrators.

## Why it matters

Users who cannot find help ask in the wrong place, or not at all. A Support menu with a working feedback address and a curated set of announcements routes requests to the people who own them. It also cuts down "what changed?" questions after an upgrade.

{% include media.html src="admin-settings/send-feedback.png" alt="Screenshot of the Help group in Admin Settings." title="Help settings" %}

{% include media.html type="video" title="Help settings walkthrough" poster="video-posters/admin-help.png" capture="Recording planned. Walk through each tab in the Help group and explain when to change each setting." %}

## Before you change anything

- Agree on the internal mailbox that should receive end-user feedback, and confirm someone reads it.
- Decide which release announcements fit your rollout. Features you have not enabled yet are usually worth hiding.
- Confirm the Support menu name with service owners if "Support" does not match your organization's language.

## Support Menu {#support-menu}

### Support {#support-menu-section}

The Support menu appears in navigation for signed-in users with the User or Admin role once at least one destination is available. **Send Feedback** opens a form that prepares an email draft to your support mailbox. **Latest Features** opens the release announcements you have chosen to share.

Both interfaces show the menu under the name you choose: the classic interface in its sidebar and top navigation, and V2 as a collapsible group in its navigation rail. In V2 both destinations open as V2 pages, and a user who collapses the group in one interface finds it collapsed in the other.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Support Menu for End Users | Adds the Support menu to user navigation. Nothing below reaches users while it is off. | Off | `enable_support_menu` |
| Menu Name | The menu's title in navigation. Left blank, it reads "Support". | Support | `support_menu_name`; up to 60 characters in V2 |
| Enable Send Feedback Destination | Lets users prepare bug reports and feature requests as email drafts to your support mailbox. | On | `enable_support_send_feedback` |
| Support Recipient Email | The mailbox user feedback drafts are addressed to. Users do not see Send Feedback until it is set. | Empty | `support_feedback_recipient_email`; one address |
| Enable Latest Features Destination | Publishes the Latest Features page from the Support menu. | On | `enable_support_latest_features` |

#### How the two interfaces treat a missing recipient

Send Feedback is on by default, but it has nowhere to send until a recipient is set.

- **V2** saves what you chose. While the destination is on without a recipient, the Support card reads **Needs configuration** and the recipient field is marked **Required**. Saving shows a note that users will not see Send Feedback yet. A malformed address, such as two addresses or an address with spaces, is refused beside the field so you can correct it.
- **The classic page** switches Send Feedback off when you save without a recipient, or with an address that has no "@", and shows a warning.

In both interfaces, users only see Send Feedback once a recipient exists.

In V2, the Latest Features destination links straight to the User-Facing Latest Features card, where you choose what users see.

## Send Feedback {#send-feedback}

These cards send feedback about SimpleChat itself to the SimpleChat product team. They are separate from the Support menu's Send Feedback destination, which routes your users' feedback to your own mailbox. Nothing on these cards is a setting, and nothing is saved with the page.

### Overview {#send-feedback-overview-card}

Each submission is recorded in the activity log. A text-only email draft then opens in your mail app, addressed to the SimpleChat team. To share screenshots or files, attach them to the draft before you send it. In V2, the overview also links to the Support settings, for when it is your users' feedback you want to route.

### Report a Bug {#send-feedback-bug-card}

Describe what happened, what you expected, and how to reproduce it. The draft's subject names the report type and your organization, and its body includes your name, email, organization, and the running application version.

### Request a Feature {#send-feedback-feature-card}

Describe the problem, the improvement you want, and the outcome you need. The draft is prepared the same way as a bug report.

#### Form fields

Both cards ask for the same details. Name and email start from your signed-in account. In V2, text you type is kept when you search or switch categories, until you reload the page.

| Field | What it is for | Notes |
| --- | --- | --- |
| Name | Who the SimpleChat team should reply to. | `send_feedback_bug_name`, `send_feedback_feature_name` |
| Email | Where the team can reach you. | `send_feedback_bug_email`, `send_feedback_feature_email` |
| Organization | Which deployment the feedback comes from. It is also part of the subject line. | `send_feedback_bug_org`, `send_feedback_feature_org` |
| Bug Details / Feature Request Details | The report itself. | `send_feedback_bug_details`, `send_feedback_feature_details` |

## User-Facing Latest Features {#user-facing-latest-features}

This tab decides which release announcements users see on the Support menu's Latest Features page. Announcements are grouped by release: the current release, the previous release, and an archive of older highlights. Every announcement is shared by default except two archive items, Deployment and Redis. Those are mainly about administrator rollout and infrastructure.

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Show Simple Chat Documentation Guide Links | Adds public documentation guide buttons to the cards, alongside the in-app shortcuts. | Off | `enable_support_latest_feature_documentation_links` |
| Announcements shared with users | Which announcements appear on the user page. | All but Deployment and Redis | `support_latest_features_visibility`; one entry per announcement |

In V2, each announcement has a share checkbox and a **Preview**. The preview shows the details, the steps users are given, the screenshots, and the shortcuts users would see with your current, unsaved choices. For example, the documentation guide buttons appear as soon as you turn that switch on. **Share all** and **Hide all** act on one release at a time. Your choices are saved with the rest of the page.

V2 keeps this card editable while the Support menu or the Latest Features destination is off, so you can prepare the announcements before you publish them. A **Publication** notice at the top of the card tells you:

- whether users can reach the page yet;
- how many announcements they will see;
- when no announcements are shared, which hides Latest Features from the menu.

When something is off, the notice links to the Support settings. The classic page hides this checklist until the destination is on.

## Admin Latest Features {#latest-features}

Admin Latest Features is a guided tour of what each release changed for administrators. Each entry covers what the change does, why it matters, and how to roll it out. Some include screenshots, and most include shortcuts to the settings involved. It is generated from the release catalog, so it declares no settings of its own.

V2 shows it as a card at the end of the Help group, marked **New**, and the Help category in the settings rail carries the same marker. The current release opens by default and older releases are collapsed. A page search also finds announcements by their content.

A shortcut opens the matching settings card when V2 shows that card. When the work still lives on the classic page, such as Backup, the shortcut opens that tab on the classic admin page instead. What end users are told about each release is chosen on **User-Facing Latest Features**.

## Release notifications registration

The badge beside the version number shows whether this deployment is registered for SimpleChat release updates and community call notifications.

When you register, your name, email, and organization are saved in Admin Settings and the registration is recorded in the activity log. A prefilled email draft to simplechat@microsoft.com then opens in your mail app. Once registered, the badge reads **Registered** and opens a summary of the stored details, with an option to edit them.

The badge appears in both the classic and V2 Admin Settings.

## Common tasks

1. **Publish support navigation.** Turn on the Support menu, set the recipient email, and choose which announcements to share. Then sign in as a non-admin user. *Verify:* the Support menu appears with Send Feedback and Latest Features.
2. **Route feedback.** Set the Support Recipient Email and submit a test draft from the user Send Feedback page. *Verify:* the draft is addressed to your mailbox, and in V2 the Support card reads **Configured**.
3. **Prepare announcements before launch.** Leave the Support menu off and curate the User-Facing Latest Features choices, checking previews as you go. Then turn the menu on. *Verify:* the Publication notice reads **Published** with the count you expect.
4. **Report an issue to the SimpleChat team.** Complete **Report a Bug** and open the email draft. *Verify:* the draft includes the details and the application version.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Users do not see Send Feedback | The destination is on but no recipient is set. In V2 the Support card reads **Needs configuration**. | Set Support Recipient Email and save. |
| The Support menu does not appear | The menu is off, or no destination has anything to show. For example, Send Feedback has no recipient and every announcement is hidden. | Turn the menu on and give at least one destination something to show. |
| Latest Features is missing from the Support menu | No announcements are shared, or the destination is off. A user can also hide the entry until the next release. | Share at least one announcement, or turn on Enable Latest Features Destination. A user who hid the entry can restore it from their own preferences, or wait for the next upgrade, which brings it back. |
| No email draft opens | The browser has no default mail app. | In V2, use the **open the draft** link that appears after you submit, or set a default mail app. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Appearance settings]({{ '/admin/appearance/' | relative_url }})
- [Operations settings]({{ '/admin/operations/' | relative_url }})
