---
layout: page
title: "Review approval requests"
description: "Find, approve, or deny requests that need reviewer action."
section: "Guides"
audience: user
---

## What this does

The **Approval Requests** page lists pending and historical requests such as ownership changes, document deletion, group deletion, user actions, and agent template submissions. Reviewers inspect details, comment, and approve or deny eligible requests.

{% include media.html type="video"
                      title="Review approval requests walkthrough"
                      poster="video-posters/guide-review-approval-requests.png"
                      capture="Recording planned. Show review approval requests end to end and explain why this task helps a user." %}

## Why you would use this

Approvals create a checkpoint before sensitive actions execute. Use this page when a request can affect another user, remove shared content, or publish a template. It is not a general task inbox; only approval-backed actions appear here.

## Before you start

- You must have reviewer access for the request type.
- Agent template approvals depend on `enable_agent_template_gallery`; see [Agents settings]({{ '/admin/agents-actions/' | relative_url }}).
- Safety and feedback review roles may be governed from [Safety settings]({{ '/admin/security/' | relative_url }}).

## Steps

1. Open **Approval Requests**.
2. Use **Search approvals...** to find a request.
3. Set **Pending Only** or **All Statuses**.

{% include media.html src="guides/review-approval-requests-step-3.png"
                      alt="The Approval Requests page with the search box, the Pending Only status filter, the request type filter, and the results table, shown here with an empty queue."
                      title="Review approval requests step 3"
                      capture="Capture the review approval requests task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Use **All Types** to filter by request type.
5. Open the request action from **Actions**.
6. Review **Request Details**, including **Request Type**, **Target**, **Requested By**, **Date**, and **Reason**.
7. Add a comment and select **Approve & Execute** or **Deny Request**.

{% include media.html src="guides/review-approval-requests-step-7.png"
                      alt="Screenshot showing review approval requests step 7."
                      title="Review approval requests step 7"
                      capture="Capture the review approval requests task at this step in SimpleChat with realistic sample data and redact secrets." %}

8. For templates, use **Agent Template Approvals** and its status filters.

## Verify it worked

The request status changes in the table. Approved executable requests complete the requested action, while denied requests remain recorded with the decision.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| You cannot approve a request | You are not an eligible reviewer | Ask an eligible reviewer or admin to handle it. |
| Completed requests are hidden | The status filter is **Pending Only** | Change it to **All Statuses**. |

## Related

- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Agents settings]({{ '/admin/agents-actions/' | relative_url }})
- [Safety settings]({{ '/admin/security/' | relative_url }})
