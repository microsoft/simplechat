---
layout: page
title: "Read and discuss saved Analyze results"
description: "Read the answer first, browse saved findings and evidence, and ask follow-up questions without requesting another source pass."
section: "Guides"
audience: user
version: "0.261.113"
---

## What this does

Analyze reviews selected documents according to your question and saves the
accepted findings for later review. Both classic chat and React V2 keep the
readable answer in the conversation, with a compact **Saved analysis** section
under it. A supporting file becoming ready does not replace that answer.

Implemented in version: **0.261.109**. Application version alignment is tracked in
`application/single_app/config.py`.

## Start with the question, not a report schema

An ordinary request such as “Explain the risks in these documents” uses narrative
defaults: flexible findings, supporting evidence, and readable prose. You do not
need to define columns, invent scores, or complete a configuration interview for
that request. State the goal and any important constraints; clarification is only
needed when missing information materially changes the task.

Use the existing source-selection and Analyze flow:

- In classic chat, choose the documents in **Grounded Search** and select
  **Analyze** in **Action**, rather than **Search**.
- In React V2, **Documents** selects context. When an **Orchestrate** plan includes
  Analyze, use the existing plan-review and approval controls; the saved-result
  view appears with its answer. **Documents** is not a separate Analyze button.

Since **0.261.113**, pinning documents does not also require a Search step. Ask
for Analyze in the message and review the proposed operation. All selected
documents must still be accounted for; an explicit Search selection remains a
requirement rather than being silently replaced by Analyze.

Source access, supported documents, and your deployment's existing Analyze limits
still apply. See [Chat controls]({{ '/reference/chat-controls/#saved-analyze-results-both-interfaces' | relative_url }})
and [Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

## Read the overview, then the saved findings

The assistant's answer is the readable overview. It can explain the main themes
without displaying every saved finding. Do not treat that overview, or a file
preview, as the complete set of records.

1. Read the answer and the validation notice under **Saved analysis**.
2. Expand **Findings and limitations** to load a page of accepted findings.
3. Use **Next findings** and **Previous findings** to move through the saved set.
   Pages contain up to **25 complete records**; the last page may be shorter.
4. Compare the displayed count with the total. For example,
   `Showing 1–25 of 60 records` means that 35 records are on other pages.

A closed findings section reports zero records displayed, not zero records saved.
Source counts are separate: the sources represented on one page can be fewer than
the sources in the saved analysis. One source can contribute several findings.
Neither count proves that every possible issue was discovered.

**Downloads** contains the existing generated-file cards and their format-specific
download actions, such as **Download CSV**, when an output is available. Downloads
are optional supporting outputs, not a prerequisite for reading or discussing the
findings.

Downloads check current artifact and source access before returning the file.
If a download fails, the conversation remains open and the download button becomes
available again. Refresh the conversation before retrying a stale or unavailable
file. A preview opening successfully does not establish that a download will work.

In React V2 on a narrow screen, **Expand navigation** opens the rail over the chat
instead of narrowing the report. Collapse it, press Escape, or select the shaded
backdrop to return to the report. Wide tables scroll inside their own container.

## Inspect evidence and limitations

Expand **Evidence for finding …** beside a finding; the label includes that
finding's identifier. Saved passages can include a filename, page or page range,
and chunk location when those details were saved. A finding without supporting
passages says **No supporting passage saved for this finding.**

The **Limitations and validation issues** section appears when the saved result
includes those notices. Read it alongside the findings, particularly when the
analysis is incomplete.

| Notice | How to interpret it |
| --- | --- |
| **Structural checks passed.** | Structural checks completed successfully. This is not independent factual verification or proof that the findings are exhaustive. |
| **Partial analysis** | Only accepted findings are included. Counts and totals describe this saved subset; some work or checks remain unresolved. |
| **Validation pending** | The saved findings are not yet a validated final result. Execution finishing does not mean validation has finished. |
| **Validation failed** | The saved findings must not be treated as a validated final result. |
| **Not validated** | No completed validation is claimed. |

Findings remain model judgments. Inspecting a saved quotation helps you understand
its support; it does not reread the original source or independently verify the
conclusion.

For an audit, **View diagnostics (JSON)** opens the separately saved processing
data in a new tab. It is not the final findings or a readable report. The response
is bounded; `next_offset` identifies another byte page when the audit is larger
than one response. Ordinary reading and follow-up questions do not use this data.

## Ask about the saved analysis

1. Select **Ask about this analysis** on the result you want to discuss.
2. Check the composer notice:

   > Saved analysis selected. Explaining the saved analysis — not running a new pass over the original sources.

3. Ask a follow-up, such as “Explain the finding on the second page” or “Which
   findings need an owner's attention?”

While that notice is present, the message asks the model or selected agent to
explain the saved analysis. It does not request another document Analyze/Search
pass or an Orchestrate source-retrieval run. The explanation is not a claim that
the original sources were checked again, including for changes since the analysis.

A newly completed result can be selected automatically for the next ordinary
follow-up. The notice makes that selection visible; check it before sending,
especially after reopening a conversation.

To leave saved-analysis context, use the notice's close button, whose accessible
label is **Remove saved analysis context**. Starting or changing conversations,
or explicitly choosing a new source action, also clears the selection. A message
feed refresh does not undo a removal or new source choice made in that open
conversation.

If you need a fresh source review, choose the sources and Analyze flow explicitly
instead of asking through the saved-analysis notice.

## Understand unavailable and stale results

Saved Analyze results produced by this feature require current access to every
contributing source for new reads or reuse. Keeping access to the conversation
alone is not sufficient. If access to any contributing source is lost, the entire
original saved result becomes unavailable, including its evidence, saved
explanations derived from it, and original exports. A mixed-source result is not
silently reduced to the sources you can still access.

**Already explicitly published workspace copies are different:** they remain
separate documents governed by the destination workspace's permissions and
lifecycle. Losing access to an original contributing source does not replace
those destination permissions. Saving a result in its originating chat is not
workspace publication. Bytes already delivered or downloaded cannot be recalled.

An unavailable or stale notice is not an empty successful analysis:

- **Saved analysis unavailable** can indicate removal or changed access. Result
  reading, **Ask about this analysis**, and original result export controls are
  unavailable. A sign-in notice asks you to sign in again before checking access.
- **Saved analysis is stale or has changed** asks you to reopen the conversation
  to use its current saved result, rather than silently switching results.
- **Retry findings** or **Retry evidence** appears after a temporary loading
  failure. These actions retry reading saved data, not analyzing the sources again.

## Validation scope

Local functional and browser-fixture coverage is separate from live acceptance.
Use a matching backend and V2 build, a new conversation, and currently authorized
sources when evaluating a deployment. Reopening an old conversation does not
re-analyze its documents or retrofit new saved-result metadata.
