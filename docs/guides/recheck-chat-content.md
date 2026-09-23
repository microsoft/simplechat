---
layout: page
title: "Recheck chat content"
description: "Find chat messages that could not be checked, retry the configured scanners, and remove AI replies with confirmed findings."
section: "Guides"
audience: admin
version: "0.261.127"
---

## What this does

Chat can continue when a content checker is unavailable. Instead of telling the user about that technical problem, SimpleChat records which required check did not finish. The administrator queue lets you retry after correcting the problem.

**Implemented in version: 0.261.127**, tracked in `application/single_app/config.py`.

Use this queue to close gaps caused by service outages, missing scanner configuration, timeouts, or incomplete inspection. **Not checked** does not mean that a message passed, and it does not mean that the user did anything wrong.

## Choose where checking applies

Under **Admin Settings > Security**, Content Screening provides separate switches for workspace uploads, submitted chat messages, and AI replies. Chat reuses the global PII/regex/literal/optional AI baseline. Content Safety separately selects submitted-message and AI-reply checks.

Both scanners use **Content Screening > Chat check behavior (both scanners)**:

- **Stream first, then remove flagged replies** keeps the live typing experience. A confirmed finding replaces the answer after checking.
- **Check before displaying the reply** holds the answer while the check runs.
- **Allow quietly and mark not checked for admins** is the default failure action. Choose **Stop messages or remove unchecked replies** if the application should not continue without a completed check.

Holding the answer and handling checker failures are separate choices. With allow-through selected, a failed check can still release a held answer.

Workspace upload checks keep their document-review workflow. For chat-only PII checking without Enhanced Citations, disable **Screen workspace uploads** before enabling Content Screening.

## Find unchecked messages

Select **Review unchecked chat content** from either feature's settings, or open the administrator **Safety Violations** page. The queue requires the same reviewer permission as that report; deployments requiring `SafetyViolationAdmin` do not grant it merely because someone has the general Admin role.

Filter by message type or incomplete scanner. **All sources** includes ordinary chat and canonical AI messages, followed by shared user messages. Use **Load more** to page through the metadata. The list does not copy full message text or matched sensitive values.

Read the failure code before retrying. A missing policy needs configured checks; an unavailable Azure client needs a working endpoint and authentication; a window or runtime limit means required coverage was not achieved. Repeatedly clicking Recheck does not fix those prerequisites.

## Recheck a message

Select **Recheck**, then confirm **Recheck and apply rules**. The operation uses current saved rules and the current stored message revision, not a text copy from the browser.

| Result | What happens |
| --- | --- |
| Required checks pass | The private result is updated and the message leaves the unchecked queue. |
| An AI reply has a finding | The reply is automatically replaced in saved chat and shared representations. Old replayed text cannot restore it. |
| A submitted message has a finding | The finding is recorded for administrator review. Earlier model calls or actions are not undone. |
| A checker still cannot finish | Content stays available and marked for another attempt; the end user receives no technical warning. |
| The message changed or was deleted | Reload the queue. A stale revision is not permission to check or remove different content. |

AI-generated findings are separate from user misconduct. Warning, suspension, and blocking actions cannot be applied to AI-output incidents.

## Understand removal limits

Live streaming may show text before checking finishes. Removing it cannot make someone forget what they saw, empty a clipboard, recall a download, or undo an external action.

These switches inspect submitted text and final reply text. They do not add checks for retrieved websites, tool results, outbound requests, chat-only attachments, or file contents generated for download. Existing workspace screening still applies to files admitted to workspace knowledge.

Private failure details stay out of normal message inspectors, user violation reports, and chat exports. A confirmed removal appears as a neutral content-check notice.

See [Security settings]({{ '/admin/security/#chat-check-behavior' | relative_url }}) for setting names and defaults.
