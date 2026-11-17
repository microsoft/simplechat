---
layout: page
title: "View workflow activity"
description: "Watch a workflow run as a timeline, cancel it, and review the email or invitation it saved."
section: "Guides"
audience: user
version: "0.261.448"
---

## What this does

The **Workflow activity** page shows one workflow run as a timeline of what it did, in order: the run itself, each tool it called, and any Microsoft 365 email or invitation it saved for you to review. While the run is going the page keeps itself current, and from it you can cancel the run or send or cancel a saved email.

This guide describes the page in the V2 interface. The classic interface has the same page at `/workflow-activity`, and every link to it opens the V2 page when you use V2.

## Why you would use this

A run's result tells you how it ended. The timeline tells you how it got there: which tool it called, how long each call took, where it stopped, and what a failed step reported. Use it to watch a long run, to find the step that failed, and to review an email or invitation a workflow prepared before it goes out, beside the run that prepared it.

## Before you start

- An administrator must have turned on personal workflows, or group workflows for a group's runs, and you must be allowed to use them. A refused page says what to ask for; see [Workflow settings]({{ '/admin/workflow/' | relative_url }}).
- The workflow needs a run to show. A workflow that has never run has no **Activity** button.
- To send or cancel a saved Microsoft 365 action you must be the person it runs as. Anyone else sees it read-only.

## Steps

1. Open the page from where you are:
   - **From the Workflows section.** Select the workflow and choose **Activity** in its header, or open its **Runs** tab and choose **Open activity** beside the run you want.
   - **From chat.** In a workflow's conversation, choose the **Open workflow activity** icon in the header.
   - **From a notification.** Choose a workflow notice in the bell. Notices about a run you can open, such as a result that could not be posted to your chat, open the page for that run.

   These buttons open the page in a new tab, so the workflow list or the chat stays where you left it.

{% include media.html src="guides/view-workflow-activity-step-1.png"
                      alt="The Runs tab of a workflow in the Workflows section, with an Open activity button beside each run."
                      title="View workflow activity step 1"
                      capture="Capture the Runs tab of a workflow with several runs, showing the Open activity button on each row. Redact workflow names." %}

2. Read the header. It names the workflow, shows the run's status and says how it started and what ran it, for example "manual run completed using Weekly digest agent." The four figures give the run's short id, how many activities it recorded, how many were tool calls, and when it started.
3. Choose **Show response preview** to see what the run answered, or **Show run error** when it failed. It starts closed so the timeline keeps the room. If a task saved an answer check, its result is in the same panel.
4. Read the timeline. Each card is one activity, with its status, lane and duration. Each tool the run called sits in a lane of its own, further to the right on a wide screen, and the workflow itself stays in the main lane.
5. Select a card to see its details: what it did, **Technical Detail**, and the **Event History** of everything it recorded.
6. Use **Open workflow** to go to the workflow's conversation, **Open run** to see the run in the Workflows run history, and **Refresh** to read the run again.

{% include media.html src="guides/view-workflow-activity-step-6.png"
                      alt="The Workflow activity page for a completed run, with the status, four figures, the timeline on the left and the selected activity's details on the right."
                      title="View workflow activity step 6"
                      capture="Capture the Workflow activity page for a completed run with several tool calls, with one card selected. Redact workflow names and tool arguments." %}

## Watch a run that is still going

While a run is running, or waiting for an approval or a Microsoft 365 sign-in, the page updates without you doing anything. New activities appear in the timeline, and the details follow the newest one.

- The timeline scrolls to the newest activity while you are at the bottom of it. If you scroll up to read, it leaves you where you are and follows again when you come back to the bottom.
- If you pick an earlier activity, the details stay on it until you pick the newest or choose **Refresh**.
- When the run finishes, fails or is cancelled the page stops listening and shows the final state.

## Cancel a run

While a run is live, **Cancel run** is in the header. Choose it and the page asks the server to stop the run. The status changes to **Cancelling** and then **Cancelled** once the run has stopped. A run that has already finished has no **Cancel run**. If the server refuses, the page says why and leaves the run as it was. If you use the keyboard, focus stays on **Cancel run** while it works, and if you are still on it when the run stops and the button goes away, focus moves to **Refresh**.

## Review a saved Microsoft 365 email or invitation

When a workflow prepares an email or a calendar invitation for review, the timeline has an activity for it in the **Microsoft Graph** lane, such as **Mail message review** or **Calendar invite delayed send**. Select it and its card appears in the details: the recipients, the time and the first lines of the content, with **Send** or **Send now**, **Cancel** and **Refresh status**.

- Opening the page, reading the card and waiting never send anything.
- **Send** and **Send now** send the version you reviewed. If the action changed in the meantime the server refuses it and the card tells you to review it again.
- **Cancel** stops a send that has not started. It does not recall a message that has gone.
- A cancelled action reads **Failed** on the timeline card, as it does on the classic page. The card beside it says **Cancelled**.

See [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }}) for who can send, and [Review approval requests]({{ '/guides/review-approval-requests/' | relative_url }}) for the same card in Approvals.

## Verify it worked

The page shows the run's name and a status that matches the Workflows run history. While the run is live, new activities appear without a refresh, and **Cancel run** is present. After the run finishes, **Cancel run** is gone and the status is final.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The page says "Open this page from a workflow conversation or a workflow run history entry." | It was opened without a run, workflow or conversation. | Open it from the **Activity** button, a run's **Open activity** button or the chat header icon. |
| "This workflow activity link is not valid." | The link carries a run, workflow, conversation or group id, or a scope, that the page cannot read. | Open the page again from the workflow instead of from the saved link. |
| "Workflow activity unavailable", followed by a sentence from the server | Workflows are turned off, you lack the app role, or the group is not assigned. | Ask an administrator for what the sentence names, then choose **Try again**. |
| "No activity yet" | The conversation has no run on record, or the run finished before activity was tracked. | Start the workflow. The page picks the run up when it begins. |
| There is no **Cancel run** | The run is not live. | None needed. A finished run cannot be cancelled. |
| The timeline stopped moving | The run settled, or is waiting on you. | Check the status. A run waiting for an approval or a sign-in needs you to act in Approvals or Settings. |
| A message about activity "no longer available" | The server stopped sharing the run, for example when access changed. | Choose **Refresh**. If it persists, reopen the page from the workflow. |

## Related

- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
- [Ask about workflow results]({{ '/guides/ask-about-workflow-results/' | relative_url }})
- [Review approval requests]({{ '/guides/review-approval-requests/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
