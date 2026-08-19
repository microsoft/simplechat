---
layout: page
title: "Safety Settings"
description: "Controls Azure Content Safety, user feedback, desktop notifications, review-role requirements, and conversation archiving."
section: "Administration"
audience: admin
admin_tab: safety
---

## What this tab controls

Controls Azure Content Safety, user feedback, desktop notifications, review-role requirements, and conversation archiving.

## Why it matters

Safety settings control what happens when chat content violates policy, who can review those events, and whether conversations are archived instead of permanently deleted. Turning Content Safety on can block harmful or sensitive prompts before they reach a model, but a bad endpoint or overly strict message can interrupt normal work. Role requirements protect review data from casual admin access.

{% include media.html src="admin/safety-overview.png" alt="Screenshot of the Safety settings tab showing safety tab." title="Safety tab" capture="Capture the Safety tab for Safety tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Safety settings walkthrough" poster="video-posters/admin-safety.png" capture="Recording planned. Walk through every setting on the Safety tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Content Safety | Routes chat content through Azure AI Content Safety so blocked messages use the configured violation message instead of continuing through the normal chat flow. | Off | `enable_content_safety`; capability toggle |
| Use APIM instead of direct Content Safety endpoint | Makes use apim instead of direct content safety endpoint available in the product when its required service and access policy are configured. | Off | `enable_content_safety_apim`; capability toggle |
| Content Safety Endpoint | Points SimpleChat to the content safety endpoint used by this feature. | Empty | `content_safety_endpoint` |
| Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `content_safety_authentication_type` |
| Content Safety Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `content_safety_key` |
| Azure APIM Content Safety Endpoint | Points SimpleChat to the azure apim content safety endpoint used by this feature. | Empty | `azure_apim_content_safety_endpoint` |
| Azure APIM Content Safety Subscription Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | `azure_apim_content_safety_subscription_key` |
| Safety Violation Message (Markdown supported) | Displayed when Content Safety blocks a chat message. | Not specified in defaults | `content_safety_violation_message` |
| Include Trigger Information | Controls how SimpleChat uses include trigger information on this tab. | On | `content_safety_include_trigger_information` |
| Enable User Feedback (Thumbs Up/Down) | Shows thumbs up/down feedback controls on AI responses so users can submit response-level feedback for review. | On | `enable_user_feedback`; capability toggle |
| Enable Desktop Conversation Notifications | Allows browser desktop notifications for conversation events when the user grants browser permission. | Off | `enable_desktop_notifications`; capability toggle |
| Require SafetyViolationAdmin App Role | Requires the `SafetyViolationAdmin` app role before users can use this capability or view. | Off | `require_member_of_safety_violation_admin` |
| Require FeedbackAdmin App Role | Requires the `FeedbackAdmin` app role before users can use this capability or view. | Off | `require_member_of_feedback_admin` |
| Enable Conversation Archiving | Changes conversation deletion behavior to archive conversations instead of permanently deleting them immediately. | Off | `enable_conversation_archiving`; capability toggle |

### Content Safety

When enabled, SimpleChat uses the configured Content Safety endpoint before unsafe content proceeds through the chat flow. The violation message is what blocked users see, and trigger details can be included for reviewers when that option is on.

### Conversation archiving

Archiving changes delete behavior from immediate permanent removal to retained hidden records. Enable it when audit or recovery requirements matter more than immediate deletion, and pair it with retention policy decisions.

## Before you change anything

- Create an Azure AI Content Safety resource or APIM route before enabling `enable_content_safety`.
- Grant managed identity permissions or provide the Content Safety key according to the selected authentication type.
- Create `SafetyViolationAdmin` and `FeedbackAdmin` app roles before requiring them.
- Decide whether conversation archiving is part of your retention policy before enabling it.

## Common tasks

1. **Turn on Content Safety end to end.**
    1. Enable **Enable Content Safety**.
    2. Choose direct or APIM routing.
    3. Enter **Content Safety Endpoint** and authentication settings.
    4. Save and test with content that should be blocked.
    Outcome to verify: Blocked content is replaced by the configured violation message.

{% include media.html src="admin/safety-turn-on-content-safety-end-to-end.png" alt="Screenshot of the Safety settings tab showing turn on content safety end to end." title="Safety: Turn on Content Safety end to end" capture="Capture the Safety tab while performing Turn on Content Safety end to end. Show the relevant controls and redact secrets." %}

2. **Customize the blocked-user message.**
    1. Edit **Safety Violation Message**.
    2. Choose whether **Include Trigger Information** should be on.
    3. Save and trigger a test violation.
    Outcome to verify: Users and reviewers see the intended message and trigger detail behavior.

{% include media.html src="admin/safety-customize-the-blocked-user-message.png" alt="Screenshot of the Safety settings tab showing customize the blocked-user message." title="Safety: Customize the blocked-user message" capture="Capture the Safety tab while performing Customize the blocked-user message. Show the relevant controls and redact secrets." %}

3. **Restrict safety and feedback review.**
    1. Create `SafetyViolationAdmin` and `FeedbackAdmin` app roles.
    2. Enable **Require SafetyViolationAdmin App Role** and/or **Require FeedbackAdmin App Role**.
    3. Save and test with assigned and unassigned users.
    Outcome to verify: Review pages are accessible only to intended reviewers.

{% include media.html src="admin/safety-restrict-safety-and-feedback-review.png" alt="Screenshot of the Safety settings tab showing restrict safety and feedback review." title="Safety: Restrict safety and feedback review" capture="Capture the Safety tab while performing Restrict safety and feedback review. Show the relevant controls and redact secrets." %}

4. **Enable conversation archiving.**
    1. Enable **Enable Conversation Archiving**.
    2. Save settings.
    3. Delete a test conversation.
    4. Confirm it is archived rather than permanently removed.
    Outcome to verify: Deleted conversations follow the archive path.

{% include media.html src="admin/safety-enable-conversation-archiving.png" alt="Screenshot of the Safety settings tab showing enable conversation archiving." title="Safety: Enable conversation archiving" capture="Capture the Safety tab while performing Enable conversation archiving. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Violation review is inaccessible | The SafetyViolationAdmin role requirement is enabled. | Assign the SafetyViolationAdmin app role before enforcing it. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Logging]({{ '/admin/logging/' | relative_url }})
- [Control Center]({{ '/admin/control-center-config/' | relative_url }})
