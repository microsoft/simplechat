---
layout: page
title: "Send Feedback Settings"
description: "Provides admin-side forms for reporting bugs and feature requests to the SimpleChat team."
section: "Administration"
audience: admin
admin_tab: send-feedback
---

## What this tab controls

Provides admin-side forms for reporting bugs and feature requests to the SimpleChat team.

## Why it matters

This page gives admins a structured way to report bugs and feature requests with contact and organization context. It is not an end-user feature toggle; its value is in producing reproducible, routed feedback instead of informal messages with missing details.

{% include media.html src="admin-settings/send-feedback.png" alt="Screenshot of the Send Feedback settings tab showing the admin forms for reporting bugs and feature requests with organization context." title="Send Feedback settings tab" %}

{% include media.html type="video" title="Send Feedback settings walkthrough" poster="video-posters/admin-send-feedback.png" capture="Recording planned. Walk through every setting on the Send Feedback tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Name | Controls the user-facing copy or name shown for name. | Not specified in defaults | `send_feedback_bug_name` |
| Email | Supplies the email address used for email. | Not specified in defaults | `send_feedback_bug_email` |
| Organization | Controls how SimpleChat uses organization on this tab. | Not specified in defaults | `send_feedback_bug_org` |
| Bug Details | Controls how SimpleChat uses bug details on this tab. | Not specified in defaults | `send_feedback_bug_details` |
| Name | Controls the user-facing copy or name shown for name. | Not specified in defaults | `send_feedback_feature_name` |
| Email | Supplies the email address used for email. | Not specified in defaults | `send_feedback_feature_email` |
| Organization | Controls how SimpleChat uses organization on this tab. | Not specified in defaults | `send_feedback_feature_org` |
| Feature Request Details | Controls how SimpleChat uses feature request details on this tab. | Not specified in defaults | `send_feedback_feature_details` |

## Before you change anything

- Know whether the report is a product bug or feature request before filling the form.
- Collect reproduction steps, tenant context, and business impact first.

## Common tasks

1. **Report a bug.**
    1. Fill in **Name**, **Email**, and **Organization**.
    2. Describe reproduction steps and impact in **Bug Details**.
    3. Submit through the feedback form.
    Outcome to verify: The bug report contains enough context to triage.

{% include media.html src="admin/send-feedback-report-a-bug.png" alt="Screenshot of the Send Feedback settings tab showing report a bug." title="Send Feedback: Report a bug" capture="Capture the Send Feedback tab while performing Report a bug. Show the relevant controls and redact secrets." %}

2. **Request a feature.**
    1. Fill in **Name**, **Email**, and **Organization**.
    2. Describe the scenario, users, and expected outcome in **Feature Request Details**.
    3. Submit the feature request.
    Outcome to verify: The request explains the problem and desired capability.

{% include media.html src="admin/send-feedback-request-a-feature.png" alt="Screenshot of the Send Feedback settings tab showing request a feature." title="Send Feedback: Request a feature" capture="Capture the Send Feedback tab while performing Request a feature. Show the relevant controls and redact secrets." %}

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [General]({{ '/admin/general/' | relative_url }})
