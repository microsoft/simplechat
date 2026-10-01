---
layout: page
title: "Ask about workflow results"
description: "Ask chat about what one of your finished workflow runs found, without running the workflow again."
section: "Guides"
audience: user
version: "0.261.213"
---

## What this does

Every run of a workflow saves what it found. This guide shows you how to ask chat
about the stored result of one finished run of one of your personal workflows.
The answer uses only that run's saved output: the workflow isn't run again, and
nothing else is searched.

Implemented in version: **0.261.213**. Application version alignment is tracked in
`application/single_app/config.py`.

## Why you would use this

By the time you read a scheduled workflow's result, such as a weekly digest, the
work is already done. Asking chat about it lets you pull out what matters to
you, for example "Which of these items need a decision this week?", without
copying the output into chat or waiting for another run. Every answer names the
run it came from, so you always know which result it describes.

## Before you start

- Use the V2 interface. Classic chat has no **Ask in chat** or **Ask about
  this** button.
- Your administrator must turn on **Enable Personal Workflows** and **Use
  Workflow Results In Chat**. When **Require WorkflowUser App Role** is on, you
  also need the `WorkflowUser` role. See
  [Workflow settings]({{ '/admin/workflow/' | relative_url }}).
- The workflow must be one of your personal workflows, and the run must have
  completed, fully or partially. Group workflows aren't supported yet.

## Ask about a run from its history

1. In V2, open **My Workspace** and choose **Workflows**.
2. On the workflow's row, select the arrow, **Show run history**. It lists the
   workflow's 10 most recent runs.
3. On a run that completed, choose **Ask in chat**. Runs that completed
   partially offer it too. Runs that failed, were cancelled or are still running
   don't.
4. A new chat opens. While the run's result is checked, the composer shows
   **Opening the workflow result…**, and you can't send until it's ready.
5. Check the notice in the composer. It names the run you're asking about, for
   example:

   > Answering from the Weekly digest run of Mon, Jun 2, 9:02 AM — not re-running the workflow

6. Ask your question, such as "What changed since last week?" or "Which items
   need a decision?".

{% include media.html src="guides/ask-about-workflow-results-notice.png"
                      alt="A new V2 chat with the workflow result notice in the composer naming the Weekly digest run, its remove button, and the Ask about the workflow results placeholder."
                      title="A workflow run selected in the composer"
                      capture="Capture a new V2 chat opened with Ask in chat, showing the notice that names the run and the Ask about the workflow results placeholder. Use realistic sample workflow names." %}

## Ask about a run from a workflow alert

When a workflow alert is about a completed run of one of your personal
workflows, including one that completed partially, the full alert has an **Ask
about this** button. Choosing it closes the alert and opens a new chat about
that run's stored result, just as **Ask in chat** does. The alert stays unread
in the bell, so you can still mark it read or dismiss it afterwards. See
[Manage notifications]({{ '/guides/manage-notifications/' | relative_url }}).

Alerts for group workflows, alerts that don't name a run, and alerts about a run
that failed or was cancelled don't offer it.

## Keep asking in the same chat

Each answer ends with a line that names the run, for example:

> _This answer uses the stored result of the Weekly digest run of Mon Jun 2, 2025, 9:02 AM CDT. The workflow was not re-run._

Your next question in the same chat is about the same run. When you reopen the
chat later, the notice comes back as long as the chat's last message is still
an answer about the run.

The notice goes away when you choose **Remove workflow result context**, choose
documents or another source, upload a file, turn on **Orchestrate**, or start
another chat. Your next question is then an ordinary chat question.

## Verify it worked

- The answer ends with the line that names the run and says the workflow was not
  re-run.
- The workflow's run history shows no new run.
- The answer has no document or web citations, because it used only the run's
  stored result.

## What the answer can see

- **Only that run's stored result.** The workflow isn't run again, so the answer
  doesn't know about anything that has changed since the run.
- **The main output of the run's tasks.** Each task that succeeded contributes
  its main output, starting with the last task's, up to 8 outputs and about
  48 KB in total. When the result is larger, the answer sees only part of it,
  and the line at the end says so.
- **Saved analyses.** When the run includes an Analyze task, the answer explains
  its saved analysis, as **Ask about this analysis** does in
  [Read and discuss saved Analyze results]({{ '/guides/analyze-results/' | relative_url }}).
  When the run also has other outputs, only its saved analyses are used, and the
  line at the end says so.
- **Nothing it's told to do.** The run's output is treated as information to
  answer from, never as instructions. Text in a result that asks the assistant to
  do something isn't followed.

## Understand unavailable answers

The run's result is checked again every time you ask about it, and every time a
chat that used it is opened in V2.

- **The result changed.** If the run's stored result is different from the one
  you selected, you're told "This workflow run's result has changed since it was
  selected. Select the run again to ask about its current result." Nothing is
  answered from the new result until you select the run again.
- **The run is gone, or you lost access.** If the run was deleted, or you can no
  longer open a document its tasks used, the notice is removed and a message
  says the result is unavailable.
- **Earlier answers are hidden too.** Once the result is unavailable to you,
  every answer that used it shows "This answer is unavailable because access to
  the workflow result it used could not be confirmed." Your questions stay. Later
  answers in the same chat that could draw on those answers are hidden as well,
  even ones you asked after removing the notice.
- **Private chats only.** Answers about a workflow result, called Follow up
  answers, stay in your own private chats. Once a chat is shared or converted to
  a collaboration, its Follow up answers are hidden for everyone, you included.
  The original chat's stored messages are unchanged. The collaboration's copies
  are stored with these answers withheld, and the chat's saved summary is
  cleared on both chats.

## Limitations

- **Personal workflows only.** Group workflows aren't supported yet.
- **Structured workflows aren't supported yet.** Runs of a workflow converted
  with **Enable structured control flow** don't offer **Ask in chat**. Runs from
  before the conversion still show it, but asking about them says this kind of
  workflow isn't supported yet.
- **No Retry or Edit.** Retrying or editing a question about a workflow result,
  or its answer, isn't supported, and the server refuses it. Ask the question
  again instead.
- **No files.** An answer is text only. It can't turn the result into a file,
  such as a CSV.
- **Orchestrate doesn't read workflow results yet.** Turning on **Orchestrate**
  removes the notice, and when Orchestrate reads the chat's history it skips
  Follow up answers and later answers that could draw on them.
- **No retention setting.** A run's result stays available until the run is
  deleted.
- **Turning the feature off doesn't hide earlier answers.** If your
  administrator turns off **Use Workflow Results In Chat**, or you lose the
  `WorkflowUser` role, you can't ask new questions about a workflow result, but
  earlier answers stay visible while their result is still available to you.
- **Classic chat** has no buttons for this, and it doesn't hide an answer whose
  result is no longer available: when you open the chat in classic, you still
  see it. A few other reads that only you can reach work the same way, such as a
  chat summary you generate for the chat. Open the chat in V2 to see which
  answers are still available.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A run has no **Ask in chat** | The run didn't complete, the workflow belongs to a group or is a structured workflow, or the feature is off | Choose a completed run of a personal workflow. If no run offers it, ask your administrator about **Use Workflow Results In Chat**. |
| "Asking about the results of this kind of workflow isn't supported yet." | The workflow is a structured workflow. You chose **Ask about this** on its alert, or **Ask in chat** on a run from before it was converted. | Read the run's result in its run history. From an alert, open the alert again from the bell and choose **Open workflow**. |
| "This workflow run has no stored result to ask about. Older runs keep previews only." | The run finished before its tasks stored full results | Run the workflow again, then ask about the new run. |
| "Workflow results can only be used in your own private chats." | The chat is shared or was converted to a collaboration | Start a new chat with **Ask in chat**. |
| "The workflow result and this chat's history don't fit the selected model." | The result and the conversation are too long for the model's context window | Select a model with a larger context window, or start a new chat. |
| "The selected model or agent couldn't answer from this workflow result with its tools turned off." | The selected agent can't answer without its tools | Select a model or a local chat agent, then ask again. |
| "The workflow result couldn't be read right now. Try again in a moment." | A temporary storage problem | Send the question again. The notice stays selected. |

## Related

- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
- [Read and discuss saved Analyze results]({{ '/guides/analyze-results/' | relative_url }})
- [Chat interface controls]({{ '/reference/chat-controls/' | relative_url }}#workflow-results-in-chat-v2-interface)
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
