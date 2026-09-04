---
layout: page
title: "Help settings"
description: "Help controls end-user support navigation, Send Feedback destinations, and Latest Features cards."
section: "Administration"
audience: admin
admin_tab: help
redirect_from:
  - /admin/send-feedback/
  - /admin/latest-features/
---


# Help settings

## What this group controls

Help controls end-user support navigation, Send Feedback destinations, and Latest Features cards.

## Why it matters

These settings give users a sanctioned place to ask for help and learn what changed. Keep addresses, labels, and feature visibility accurate so requests reach owners.

{% include media.html src="admin-settings/send-feedback.png" alt="Screenshot of the Help group in Admin Settings." title="Help settings" %}

{% include media.html type="video" title="Help settings walkthrough" poster="video-posters/admin-help.png" capture="Recording planned. Walk through each tab in the Help group and explain when to change each setting." %}

## Before you change anything

- Choose the internal mailbox or process for feedback.
- Review which release cards should be visible.
- Confirm Support menu naming with service owners.

## Support Menu {#support-menu}

### Support {#support-menu-section}

The Support section belongs to the Support Menu tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Support Menu for End Users | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_support_menu`; capability toggle |
| Menu Name | This name will appear in user navigation as the Support menu title. | Support | `support_menu_name` |
| Enable Send Feedback Destination | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_support_send_feedback`; capability toggle |
| Support Recipient Email | User Send Feedback drafts will be addressed to this internal email address. | Empty | `support_feedback_recipient_email` |
| Enable Latest Features Destination | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_support_latest_features`; capability toggle |
| Show Simple Chat Documentation Guide Links | When enabled, user-facing Latest Features cards can show public guide buttons in addition to the direct in-app shortcuts. | Off | `enable_support_latest_feature_documentation_links`; capability toggle |

## Send Feedback {#send-feedback}

### Overview {#send-feedback-overview-card}

The Overview section belongs to the Send Feedback tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Report a Bug {#send-feedback-bug-card}

The Report a Bug section belongs to the Send Feedback tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Request a Feature {#send-feedback-feature-card}

The Request a Feature section belongs to the Send Feedback tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Name | Provides displayed text that users see in the affected interface. | Not specified in defaults | `send_feedback_bug_name` |
| Email | Supplies the email address used for email. | Not specified in defaults | `send_feedback_bug_email` |
| Organization | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `send_feedback_bug_org` |
| Bug Details | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `send_feedback_bug_details` |
| Name | Provides displayed text that users see in the affected interface. | Not specified in defaults | `send_feedback_feature_name` |
| Email | Supplies the email address used for email. | Not specified in defaults | `send_feedback_feature_email` |
| Organization | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `send_feedback_feature_org` |
| Feature Request Details | Defines behavior for the related admin workflow; verify the affected feature after saving. | Not specified in defaults | `send_feedback_feature_details` |

## User-Facing Latest Features {#user-facing-latest-features}

This tab shows the release catalog exactly as end users see it under Support > Latest Features. It was split out of the Support Menu tab so the full card set can be reviewed on its own page instead of scrolling past the Support Menu settings.

Nothing is published from here. Visibility is still controlled by **Enable Latest Features Destination** on the Support Menu tab, and per-card visibility is stored with the catalog. Use this tab to read the cards, confirm the screenshots and wording are right for your tenant, and decide what to announce before turning the destination on.

## Admin Latest Features {#latest-features}

Admin Latest Features is the companion catalog covering capabilities admins configure rather than ones end users act on. It is rendered from the release catalog and does not declare static settings sections in `admin_settings_nav.py`.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Enhanced Citations | Preserves source files for richer citation preview and source-document access in chat answers. | Off | Mirrors `enable_enhanced_citations` |
| Storage Account Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | Mirrors `office_docs_authentication_type` |
| Storage Account Connection String | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | Mirrors `office_docs_storage_account_url` |
| Storage Account Blob Service Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | Mirrors `office_docs_storage_account_blob_endpoint` |
| Maximum File Size for Tabular Preview (MB) | Mirror of the Citations setting. Larger values support bigger previews but increase runtime memory pressure. | 200 | Mirrors `tabular_preview_max_blob_size_mb` |
| Enable Processing Thoughts | Exposes the capability after required services, permissions, and rollout policy are ready. | On | Mirrors `enable_thoughts` |
| Enable Redis Cache | Uses Redis for shared cache/session scenarios so multiple app instances can share cached state. | Off | Mirrors `enable_redis_cache` |
| Redis Server Host Name | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | Mirrors `redis_url` |
| Redis Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | Empty | Mirrors `redis_auth_type` |
| Key Vault Secret Name Redis Access Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | Mirrors `redis_key` |

## Common tasks

1. **Publish support navigation.** Enable the Support menu and approved destinations, then open the app as a non-admin user. Outcome to verify: The menu appears with only approved destinations.
2. **Route feedback.** Set the recipient email and submit a test feedback draft. Outcome to verify: The draft is addressed correctly.
3. **Review latest cards.** Hide or show entries according to rollout state. Outcome to verify: Users see relevant announcements.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Feedback opens with no recipient | The destination is enabled but recipient email is blank. | Set the recipient and submit another test draft. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Appearance settings]({{ '/admin/appearance/' | relative_url }})
- [Operations settings]({{ '/admin/operations/' | relative_url }})
