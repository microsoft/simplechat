---
layout: page
title: "Answer an agent's follow-up questions"
description: "Give missing facts in a focused interview, review the complete set, and continue saved work."
section: "Guides"
audience: user
version: "0.261.411"
---

## Give the facts that change the answer

An orchestration planner or local agent can pause when a missing fact prevents it
from completing your task. For example, a review may need the policy to apply or
the actual period to compare. Related questions can arrive as one set instead of
separate chat turns.

Fixed/Implemented in version: **0.261.411**
(`application/single_app/config.py`).

This experience is for V2 chat and local agents. Foundry-backed agents and the
classic interface keep their existing follow-up behavior.

## Choose, customize, and review

Choose a suggested answer or **Write my own** if the question offers it. A round
selection marker means one answer; checkboxes allow several. A custom answer can
replace a single suggestion or accompany selected answers in a multi-select
question. Closed choices deliberately do not offer custom values.

Use **Next** and **Back** to work through the set. **Add context or a file** opens
the richer input when an explanation, saved prompt, or source is useful. For a
file question, pick or upload a real accessible file rather than entering its
filename as if that granted access.

At **Review answers**, check the complete set and use **Edit** beside an answer
that needs changing. **Use these answers** submits once. Moving between questions
does not call the model or send partial answers.

## Decide not to answer

**Continue without answers** declines the set and does not send its draft text.
The assistant may be unable to complete the task without the missing fact.
**Cancel** abandons the request, without undoing completed work. Minimizing local
agent questions only hides the interview; **Show questions** opens it again.

Answering a question is not approval to send an email, modify a service, or run a
proposed plan. Those actions still follow the deployment's own review and
authorization rules.

## Return to a paused task

Reopen the original conversation to recover a pending question. Unsent drafts
are kept in this tab's memory while navigating questions or switching
conversations, not in persistent browser storage; refreshing can lose draft text.

If answers were saved but continuation did not start, use **Continue saved work**.
If the request is already continuing, refresh its saved status instead of sending
the original task again. A changed agent, revoked source permission, or uncertain
tool outcome can prevent safe continuation. SimpleChat reports that condition
rather than automatically repeating completed actions.

While a standalone agent continues, the composer's **Stop** targets that saved
request. After reopening the conversation, **Stop saved work** requests the same
cancellation. Actions that already completed are not undone. A continuing
orchestration run uses its existing run-level Stop control.

See [Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }})
for the separate plan-approval step.
