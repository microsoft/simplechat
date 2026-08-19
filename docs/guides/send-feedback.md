---
layout: page
title: "Send feedback"
description: "Prepare a bug report or feature request email for your SimpleChat administrators."
section: "Guides"
audience: user
---

## What this does

The **Send Feedback** page prepares a text-only email draft in your local mail client. You choose a bug report or feature request and review the draft before sending.

{% include media.html type="video"
                      title="Send feedback walkthrough"
                      poster="video-posters/guide-send-feedback.png"
                      capture="Recording planned. Show send feedback end to end and explain why this task helps a user." %}

## Why you would use this

Use the feedback form when admins need enough context to reproduce a problem or evaluate an improvement. It replaces informal messages that omit expected outcome, impact, or steps to reproduce. It is not an in-app support ticket system; the final message is sent from your mail client.

## Before you start

- Admins must enable `enable_support_menu` and `enable_support_send_feedback`; see [General settings]({{ '/admin/general/' | relative_url }}).
- Your device needs a local mail client or mail handler.
- Collect reproduction steps, screenshots, business impact, or desired outcome before filling the form.

## Steps

1. Open the **Support** menu.
2. Select **Send Feedback**.
3. For a bug, use **Bug Report** and fill **Name**, **Email**, **Organization**, and **Bug Details**.

{% include media.html src="guides/send-feedback-step-3.png"
                      alt="Screenshot showing send feedback step 3."
                      title="Send feedback step 3"
                      capture="Capture the send feedback task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Include what happened, what you expected, and how to reproduce it.
5. Select **Open Bug Report Draft**.
6. For an improvement, use **Feature Request**, fill the same contact fields, and describe the problem and desired outcome.

{% include media.html src="guides/send-feedback-step-6.png"
                      alt="Screenshot showing send feedback step 6."
                      title="Send feedback step 6"
                      capture="Capture the send feedback task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Review the email draft in your mail client and send it when ready.

## Verify it worked

Your mail client opens a draft addressed according to tenant feedback configuration, and the draft includes the details you entered.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Send Feedback is missing | The support menu or destination is disabled | Ask an admin to enable `enable_support_menu` and `enable_support_send_feedback`. |
| No email draft opens | No local mail handler is configured | Set a default mail app or copy the content into email manually. |

## Related

- [Update profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
- [General settings]({{ '/admin/general/' | relative_url }})
- [Send Feedback settings]({{ '/admin/send-feedback/' | relative_url }})
