---
layout: page
title: "Screen and review workspace documents"
description: "Inspect sensitive or manipulative extracted content, keep it out of knowledge use, and release only a reviewed version."
section: "Guides"
audience: user
version: "0.261.108"
---

## What this does

Content screening checks workspace knowledge for configured PII, patterns, values, and optional model-evaluated criteria. A finding holds the whole document so a clean early page cannot be used while another page awaits review.

**Implemented in version: 0.261.106**, tracked in `application\single_app\config.py`.

Use it when a document might contain sensitive data or instructions aimed at an AI rather than a human reader. Text can enter extraction even when its appearance makes it hard to notice in the original.

## Configure an appropriate baseline

An administrator must configure Enhanced Citations and its storage account before enabling screening. The capability is off by default.

Open **Admin Settings > Security > Content Screening**. This is a separate tab from Content Safety in both the classic and V2 interfaces. You can prepare the policy before configuring Enhanced Citations; an unmet storage prerequisite does not hide the editor.

Add or edit the rules, enable **Baseline policy enabled**, then select **Save screening policy**. That save is separate from the application's enrollment switch. After Enhanced Citations is configured, enable new scans; V2 calls this **Screen workspace content before publication** and persists it with **Save changes**. You do not need to enable Azure AI Content Safety.

Choose baseline checks that reflect the information your organization actually needs to control. A policy that treats every email address as unacceptable can create a large review queue for otherwise ordinary public documents. Use representative allowed examples and known matches when testing the rules.

### Choose deterministic rules

Both interfaces offer **Add literal rule**, **Add regex rule**, and **Add PII rule**. Custom rules start with a blank name and match configuration; choose the values, pattern, or built-in PII detector you actually need. Literal and regex rules support case-sensitive and whole-word matching.

For a starting set, use **Starter rule pack** and **Add starter pack**. The four shared packs cover structured PII, confidentiality markings, credentials, and prompt/source-ranking manipulation. Existing starter rules are not duplicated or reset when you add the same pack again. You can edit their severity, match configuration, or enabled state.

These checks run in code and do not call a model. Selecting an email pattern does not send the document to an AI service or identify every kind of personal information.

### Add contextual AI checks only when needed

For contextual checks, first select **Enable AI checks**, then choose one approved **Scanner model** and describe the criterion precisely. **AI starter criteria** can provide a starting instruction. A useful instruction distinguishes an instruction to manipulate source priority from an ordinary discussion of prompt injection. The content being inspected is sent to that selected model, so review its approved data routing first.

The scanner, criteria, and window controls are disabled while AI checks are off. Their saved values remain available when you turn AI checks back on; turning the switch off does not clear them. This controls screening inference only, not extraction, embeddings, or other uses of models.

### Delegate model permissions without enabling inference

Administrators use **Models workspaces may use** to permit models for optional workspace checks. Checking several models here does not run several scanners, and the permission list can be configured while baseline AI checks are off. The baseline's saved scanner is permitted automatically and is marked separately from explicit permissions.

Workspace managers can add local rules and instructions without disabling the required administrator baseline. A workspace's **Enable AI checks** switch controls only its own additional check. Required administrator AI checks still run when local AI additions are off.

Read **Configured screening checks** before saving. It shows enabled deterministic and AI checks in the draft, including inherited requirements for a workspace. If the administrator baseline is disabled, local additions are inactive too. The summary is not the separate enrollment switch and does not change an existing document hold.

**Policy-editor alignment implemented in version: 0.261.108**, tracked in `application\single_app\config.py`.

## Inspect existing knowledge

Choose the documents or workspaces to inspect. Only administrators can start an all-workspace scan across private and shared scopes.

Use the workload/progress view to distinguish queued, running, completed, flagged, incomplete, and failed documents. Queued documents remain in their previous state until their scan starts. Started documents remain held if a check cannot finish.

Do not interpret a completed enumeration or a model timeout as evidence that every document passed. Correct the reported source, model, policy, or storage problem and resume or retry the work. Cancelling a job does not release documents that are already held.

## Review a finding

Open content review from the document's status or the relevant review request. A reviewer must be the personal owner or hold an Owner, Admin, or DocumentManager role in the owning group/public workspace. These reviewers can review their own uploads.

Inspect the rule, explanation, complete coverage status, and source location. The extracted text is the relevant evidence for an instruction hidden by visual formatting. An ordinary document list or notification deliberately does not show the sensitive excerpt.

A displayed page number represents a real source mapping. A segment, transcript range, or table coordinate is not a PDF page. If the original source is unavailable, consider that limitation before deciding whether an indexed-text snapshot is enough for your policy.

## Choose the outcome

| Outcome | Use it when |
| --- | --- |
| Approve with flags | The content is acceptable in context and you want that acceptance and warning to remain visible. Record a meaningful reason. |
| Remove a page or segment | The whole unit should not become knowledge. Confirm which other mapped content is affected. |
| Remove a span or change/clear data | Only a precise line, text span, or cell needs to be removed. Review the candidate diff rather than assuming every occurrence was changed. |
| Keep held or reject | The document should not be used and you are not ready to release a replacement. |
| Delete | The document and its retained/derived content are no longer needed. A storage failure can leave deletion pending rather than pretending cleanup succeeded. |

For remediation, preview the proposed changes, create the candidate, and let its required checks complete. Approve the clean candidate explicitly. If findings remain, either remediate further or accept them with a retained flag.

Refresh after a conflict. An old browser tab cannot authorize a replacement uploaded or edited after that tab loaded.

## Understand the download

A clean text or structured-data derivative is the approved replacement. It is not a layout-preserving edit of the original PDF or Office file.

After remediation, the original stays restricted to reviewers; ordinary citations and native data tools must use the approved representation. Removing a line from extracted knowledge while leaving the original exposed as a normal download is not the intended workflow.

Review original files as potentially untrusted content. Do not follow links or instructions in the document simply because they appeared in a review view.

## Common problems

| Symptom | Meaning and response |
| --- | --- |
| The model did not return a valid result | The scan is incomplete or failed. Retry after correcting the model/configuration; do not treat it as a clean scan. |
| Enabling screening is rejected | Save an enabled baseline containing a rule or model check, and configure Enhanced Citations storage. The error beside the screening switch identifies a missing prerequisite. |
| Admin Settings reports that the write failed | The change was not saved. Keep the draft or reload the current settings before retrying; do not assume the displayed draft is persisted. |
| A retry looks clean but the document is still held | A previous finding still needs a human decision. |
| The document has a warning after approval | It was approved with flags; the warning is intentional. |
| An original is missing | Source-backed inspection or re-extraction may be unavailable. A table schema summary does not cover the underlying cell data. |
| Scanning was disabled but a document is still held | Disabling future scans does not approve existing held content. |
| An older attachment or tool result is unavailable in conversation history | Its source is held, or that old result cannot prove it used the currently approved revision. Complete review and run a new query against the approved document. |
| Another person cannot open the evidence | Review access is scoped. Administrative scan permission or ordinary shared-read access is not sufficient. |

## Related

- [Security settings]({{ '/admin/security/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Review approval requests]({{ '/guides/review-approval-requests/' | relative_url }})
- [Framework specification]({{ '/explanation/features/CONTENT_SCREENING_FRAMEWORK/' | relative_url }})
