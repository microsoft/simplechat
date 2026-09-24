---
layout: page
title: "Create files with orchestration"
description: "Plan several files from the same retained results and recover an individual output."
section: "Guides"
audience: user
version: "0.261.135"
---

## Availability

This guide describes contract-v2 Gather / Reason / Render plans for the
orchestration harness preview, integrated in version **0.261.127**, recorded in
`application/single_app/config.py`. Retained-result foundations arrived in
**0.261.125** and the shared renderer in **0.261.126**.

An administrator must enable orchestration and its harness preview, and the
server must admit the supported runtime. This release supplies that runtime;
both settings remain off by default. Existing saved plans keep their original
contract. Ordinary chat exports, standalone Analyze/Compare and workflow output
settings are separate and keep their existing behavior.

See [orchestration settings](../admin/orchestration.md) for rollout and permissions.

## Ask for the result and its representations

Describe the work once, then name the files you need. For example:

> Analyze the selected contracts. Prepare a table of findings and one report.
> Give me the findings as CSV, and the same report as Word and PDF.
> Do not browse the web.

The intended plan retains the findings and prepared report so each file can use
the same completed work. It should not analyze the contracts again merely to
produce the second document format.

You can also request source-free content:

> Prepare a sample configuration with the fields I specify, then save the same
> structured configuration as JSON and YAML.

Such a plan does not need a search task or invented document sources. Likewise,
selected documents do not require a redundant search when the requested analysis
can use them directly.

## Check that the plan delivers what you asked for

Since **0.261.135**, a plan lists what you asked to receive before its steps. The
approval card and the plan panel show it under **You asked for**, with the step that
produces each item. Use it to confirm the plan will create a real file: a file is
created only by a Render task, and text or a table in the chat answer is not a file.

If something you asked for cannot be produced here, it stays on the list marked
**Not available**, with the reason the server reports, for example "This file format
is not available for this plan." The rest of the plan still runs, and the answer says
once, in its **Delivery notes**, what was not delivered. A plan is never approved on
the promise of a file that no task creates.

## Ask for images in a report or deck

Ask for the images in the same request, for example:

> Create a Word file for my report on the first three presidents, with an image of
> each president.

When image generation is enabled, the plan generates each image you asked for as its
own task, writes the report with each image where it belongs, and renders the Word
document with the images embedded. Approving the plan is your consent to generate them;
in Run automatically mode, your request is. The images also appear inline in the chat
answer, where you can view and edit them as usual. DOCX, PDF, and PowerPoint files embed
images; CSV, XLSX, JSON, YAML, XML, Markdown, and text files do not.

Generated images are AI illustrations, captioned as such, not photographs. Web search
returns text and links only, so a report links authentic sources rather than copying
their pictures. A plan generates at most four images; when you ask for more, the rest are
listed as not available. Images the planner only suggests stay approval cards, which
never appear in a file.

If an image cannot be generated, the report and file are still produced without it, the
run is reported as incomplete, and the delivery notes say how many images were created.

## Review the file tasks before running

Use the [plan review and editor](review-and-edit-orchestration-plans.md) to check
what will be computed and what will be exported.

**Gather** acquires inputs. **Reason** produces reusable findings, records, text
or other prepared content. **Render** creates the requested files. These labels
describe purpose rather than three compulsory consecutive stages.

Check each **Planned file** against your request: its name, format and source
result should be clear. Several file tasks may use the same named result.
Retained results and planned files are not download links or proof of completion.
In the new contract, analysis or composition without an explicit Render task
does not automatically attach a file.

For a table, specify the columns and their order when that matters. Nested data
cannot be silently flattened into CSV. If the available findings do not already
have the required table shape, ask for a Reason task that prepares it explicitly.

To change a format, filename, column selection or prepared content, request a
validated plan revision. A file retry repeats the approved representation;
it is not an editor for the file's contents.

## Choose a compatible format

The server's shared file-format reference is authoritative. Not every retained
result can be rendered directly into every format.

| Requested format | Appropriate prepared input |
| --- | --- |
| CSV | Complete records with an explicit ordered selection of scalar columns. Spreadsheet-like formulas are protected as data. |
| XLSX | Complete typed records with explicit columns and a sheet name. Strings are not treated as executable formulas. |
| JSON | Complete records or a structured value, including nested objects and arrays. |
| YAML or YML | Complete records or a structured value using the declared safe serialization profile. YML is an extension alias. |
| XML | Complete records or a structured value using the typed XML representation. This is not automatic generation of an arbitrary requested XML schema. |
| Markdown | Prepared Markdown, without a second writing pass during export. |
| TXT | Prepared plain text rather than an implicit conversion of another document format. |
| Word (DOCX) or PDF | Prepared text or Markdown report content. Both formats can reuse the same report result. |
| PowerPoint (PPTX) | A prepared slide deck with explicit slide content and layout. Writing the slides belongs in Reason, not in the binary renderer or retry. |

Rich document and slide features are limited to the supported profiles and
authorized assets. A request that needs another data shape or exceeds an output
limit should be revised, not silently truncated or changed to a different format.
The renderer cannot turn a preview, incomplete source coverage or pending
computation into a complete exported dataset.

## Follow each file independently

A run can finish one file while another waits for computation or a retry. Use
the current per-file state rather than a sentence in the answer to decide
whether a file exists.

Only a committed, currently authorized output has an available artifact link.
Successful siblings are independent: a PDF failure does not discard a completed
CSV or Word file.

If the browser loses the live stream, reopen the existing conversation or run.
The saved output state is the authority; sending the same request again is not
necessary merely to check progress.

## Recover a failed file

Retryable file failures allow **three automatic attempts in total**: the initial
attempt and two retries. Scheduled retry timing is recorded by the server;
refreshing the browser does not restart the budget.

After automatic attempts are exhausted, **Retry file** is available only when
the server permits a separate manual attempt. It targets that one output and
reuses its retained inputs. Completed reasoning and successful sibling files
should not run again.

If retry admission cannot be confirmed, retry the same action rather than
creating a new orchestration request. The interface retains the submission
identity needed to reconcile an uncertain response.

Retrying cannot repair an unsupported format, invalid data or revoked source
access. Restore the required access or revise the plan when its requirements
have changed. An authorization or storage outage is not proof that a previously
committed file has disappeared; current access must be verified before it is
offered again.

## Understand retained results and access

Retained task results carry data between steps and permit explicit reuse in the
same owner's conversation. They are not a new cross-conversation memory library,
and their reuse does not require saving every result into Fact Memory.

The saved material consists of task outputs such as evidence, findings, tables
and drafts, not a transcript of private model reasoning. A small displayed
preview is separate from the complete retained data used by a renderer.

Current source access and content-screening restrictions still apply when a
result is reused, rendered or downloaded. Keeping a snapshot does not preserve
permission after access is revoked. Deleting a conversation also invalidates
its retained results and private output access.

Files are private conversation artifacts by default, not automatically indexed
workspace documents. Workspace publication, external delivery, workflow
integration and audio generation are not part of this harness tranche.
