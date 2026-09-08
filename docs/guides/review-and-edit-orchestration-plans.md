---
layout: page
title: "Review and edit orchestration plans"
description: "Refine proposed work with the planner before running it."
section: "Guides"
audience: user
version: "0.261.104"
---

## Decide what should run

An orchestration plan explains how SimpleChat intends to answer your question.
Review it when you want to check its sources or cost before committing to that
work. Edit it when the approach needs another step, less research, or a different
focus.

Conversational plan editing was implemented in version **0.261.102**, recorded in
`application/single_app/config.py`. It is available in the V2 interface for plans
that have not started.

## Choose requirements, not permissions

Since **0.261.104**, every Orchestrate request reaches the planner, including
short questions. Selected supported tools, documents, and agents tell it what
the plan must use. Leaving Web Search or Deep Research unchecked does not
forbid those capabilities: the planner can choose them when they are enabled,
authorized, and useful for the task. Say "do not browse" when that is an actual
requirement.

Deep Research does not require selecting the Web button first. Its automatic
source discovery still depends on the administrator enabling Web Search.
Selected workspaces and document filters continue to bound document access.
Image generation has no orchestration adapter; use ordinary chat for that work.
If Image was already selected, Send and Enter pause for an explicit choice:
**Use regular Chat with Image**, or **Use Orchestrate without Image for this
message**. The second choice excludes Image only from that orchestration message
and preserves your ordinary-chat Image preference.

URL Access uses the full resolved message, including an attached prompt. Removing
the URL from the draft clears that now-ineligible selection; it does not clear
other selected requirements.

Research is not compulsory. The planner can answer directly when the available
context is enough. Capability lookup or model failures produce errors rather
than a replacement answer-only plan.

## Review versus Edit

**Review** opens the existing drawer. You can inspect steps and their rationales,
switch off non-answering steps, and remove documents from a step. These controls
only reduce the work already proposed.

**Edit** opens a full-screen preview with **Ask planner** and **History**. Use it
to discuss a change instead of asking a new question in the main conversation.
The planner creates a new version of the same plan.

If plans currently run immediately, choose Review or countdown approval before
asking your question, if your administrator permits that choice. A plan that has
already started cannot be edited.

## Refine the plan with the planner

1. Ask your question with orchestration enabled and wait for the proposed plan.
2. Select **Edit** beside Review, or open Edit from the plan drawer.
3. In **Ask planner**, describe what should change. For example: "Add a second
   document search focused on pricing" or "Remove the extra research and compare
   only the selected contracts."
4. Read the updated preview. Check the steps, source selections, assumptions,
   and any adjustments reported by the planner.
5. Continue refining the same plan, or select **Run** when the current version
   describes the work you want.

The planner may ask a clarifying question or explain why a requested capability
is unavailable. Answer within the editor to continue the change. A request to add
a feature does not enable that feature for the deployment or grant access to its
sources.

Editor exchanges do not create duplicate messages in your main conversation.
The eventual answer follows your accepted changes while the original question
remains intact.

If an accepted edit removes an originally selected operation or document, the
preview reports that change for review. It does not rewrite your standing
composer preferences.

## Understand reasoning adjustments

The reasoning picker uses the selected model's supported levels. For example,
GPT-5.6 Luna supports **None**, **Low**, **Medium**, **High**, and **XHigh**, not
Minimal. A previously saved Minimal choice becomes Low with a visible notice.
This also applies to older saved plans when edited or run.

**None** is an explicit level on models that support it. **Model default** means
the request omitted the effort parameter; it does not claim the provider chose
None or Low. If the provider rejects an otherwise supported effort, SimpleChat
can retry once using the model default and reports the adjustment. Other model
errors still stop the affected operation. Neither adjustment switches models
or approves a plan.

## Understand the countdown pause

Opening Edit stops any countdown and establishes a manual-approval hold. The
plan waits for an explicit **Run**, even if you close the editor without changing
anything or reload the conversation.

Closing the editor is not approval. A failed edit also does not cause the previous
plan to run automatically. If another tab already started the work before the
edit hold was acquired, the editor reports a conflict instead of pretending it
can modify that run.

## Return to an earlier version

Use **History** to inspect prior versions and restore one that better matches
your intent. Restoring creates a new current version; it does not delete later
history or reactivate an old execution.

Capabilities and source access are checked again. A version that depends on a
document or integration you can no longer use may not be restorable.

## Recover from a failed change

The last valid plan remains available when an instruction cannot be planned or
saved. Read the error and retry the change rather than sending the original
question again. If a clarification is no longer needed, cancel the proposed
change to return to the existing plan.

When another tab changes the plan, refresh the editor's current version before
continuing. An outdated approval cannot run a superseded plan.
If Cancel discovers a newer pending change, the editor shows that change without
cancelling it. Review it before explicitly choosing Cancel again.

## Related

- [Chat orchestration](https://github.com/microsoft/simplechat/blob/main/docs/explanation/features/CHAT_ORCHESTRATION.md)
- [Plan editing architecture](https://github.com/microsoft/simplechat/blob/main/docs/explanation/features/V2_ORCHESTRATION_PLAN_EDITING.md)
- [Orchestration settings]({{ '/admin/orchestration/' | relative_url }})
