# Document Transformation Framework

Implemented in version: **0.261.321**

Related version update: `application/single_app/config.py`.

## Overview

SimpleChat can use an existing Word document or PowerPoint presentation as a
reference for a new file. A populated report or deck can supply the formatting
and reusable structures; a `.dotx` or `.potx` can supply an actual Office
template. Outputs are new `.docx` or `.pptx` conversation artifacts. The
reference is never overwritten.

Two tasks separate the user's intent:

| Task | Purpose |
| --- | --- |
| Create from reference | Prepare new content using the reference's formatting and structures. Existing example material is not treated as verified new information. |
| Refresh document content | Change selected content while leaving unrelated material alone. |

The framework favors a useful draft over an all-or-nothing document editor.
Missing facts and unsupported edits are disclosed. They do not prevent delivery
of the changes that can safely be applied, and they are never replaced with
invented facts.

## Architecture

The existing Gather / Reason / Render engine owns execution, model calls,
retained results, cancellation and artifact delivery. This feature adds
reference inspection and native-package editing, not another orchestration
engine.

1. **Gather:** `document_inspect` opens authorized reference bytes and retains
   a `document-inspection-v1` description of targets, reusable layouts and
   limitations. Other Gather tasks collect the requested information.
2. **Reason:** `document_create_from_reference` or `document_refresh` uses the
   existing composition service to prepare explicit edits. Its complete
   `structured-v1` output is named `transformation` and uses
   `document_transform_v1`.
3. **Render:** `render_file` consumes that output with the same profile, applies
   the edits to the inspected package and creates a downloadable artifact.
   Rendering does not call a model, gather facts or write missing content.

The compiler requires inspection to come from the actual inspection task, not
an arbitrary JSON object. Preparation must keep its exact source handle,
format and SHA-256. Rendering checks the retained inspection and the current
reference bytes again. A changed source requires a new preparation rather
than silently applying old targets to a different file.

### Shared service and adapters

| File | Responsibility |
| --- | --- |
| `functions_document_transform.py` | Versioned contracts, bounded package access, adapter dispatch, deterministic packing and truthful outcome reports. |
| `functions_document_transform_docx.py` | Word structure inspection and native Word edits. |
| `functions_document_transform_pptx.py` | PowerPoint structure inspection and native slide edits. |
| `functions_document_transform_sources.py` | Authorized document and same-conversation generated-artifact reference access. |
| `functions_orchestration_document_transform.py` | Inspection task and server-bound preparation checks. |
| `functions_orchestration_composition.py` | Existing model invocation and schema-correction path used by both preparation tools. |
| `functions_generated_office_adapters.py` | Transformation bridge in the shared file-export facade. |
| `functions_orchestration_rendering.py` | Per-file rendering, recovery and artifact delivery. |

Prepared operations are data, not executable rewrite instructions:
`replace_text`, `append_text`, `replace_image`, `clone` and `remove`.
Adapters decide which target types support each operation. Inspection target
IDs, rather than paragraph wording or a model-supplied XML path, identify the
content to change. Image replacement uses authorized asset tokens, not
filesystem paths or arbitrary URLs. Preparation can only name exact `asset:`
tokens supplied by its image inputs; missing assets remain unresolved.

### Preservation and limitations

Native edits retain the surrounding package instead of rebuilding the file
through a generic report or slide-deck profile. Embedded formatting and
unrelated parts remain available. This is not a promise of pixel-perfect
reflow: longer text may need manual layout adjustment, and complex Office
objects are not necessarily editable.

Word supports ordinary paragraphs, table-cell text, headers/footers and embedded
image positions. Simple body paragraphs and tables can be duplicated or removed.
Fields, content controls, revisions and other protected structures are preserved,
not filled as forms.

PowerPoint supports slide and layout reuse, text, table cells, embedded pictures
and speaker notes. A template with no slides can create slides from its layouts.
Charts, SmartArt, embedded objects and animations are preserved rather than
refreshed. Inspection supplies clone target mappings for editing newly copied
structures without matching repeated labels.

Unresolved refresh targets retain their existing content. In create mode,
unchanged reference examples are explicitly reported as reference material,
not newly verified content. The report distinguishes **applied**,
**unchanged**, **skipped** and **unresolved** outcomes, with warnings and the
resulting file's size. Exact output-integrity bindings remain private. Public
reports retain exact counts and bounded target-level details without exposing
source handles or digests; chat delivery and model-free recovery use these
committed outcomes.

An external Word template link is detached so the output does not need to
contact that location; embedded formatting remains available. Macro-enabled
files, unsafe active content, corrupt packages, revoked access, screening
restrictions and resource limits are not best-effort omissions. They stop
unsafe or unauthorized work.

## Use in chat

Enable Chat Orchestration and the required capabilities in
[Orchestration settings](../../admin/orchestration.md). When the capability
list is narrowed, include **Inspect reference document**, the appropriate
create/refresh task, **Create a file**, and any information-gathering tasks
the request needs. This feature does not add a separate `enable_*` setting.

Select or upload the reference and explain what should change. Examples:

> Use this deck's formatting to create a community-call presentation from
> these release notes. Keep its title and closing-slide styles.

> Refresh the dates and product changes in this presentation. Keep the
> introduction and closing slides unchanged.

> Use this Word report as the format for a new report about these findings.
> Leave missing figures unresolved rather than guessing.

After delivery, refer to the generated file in the same conversation:

> In the Word file you just generated, replace the executive summary with
> these findings and finish the unresolved table.

Each request creates another file. A file retry repeats the retained prepared
edits; it does not collect new information or change their content. Workspace
promotion remains a separate existing action. Ordinary chat exports and saved
workflow publication retain their existing contracts.

## Relationship to other formats

The lifecycle is shared; editing algorithms are format-specific.

| Format or workload | Already available | Additional transformation work |
| --- | --- | --- |
| JSON | Schema-shaped composition and structured JSON export. | Selected-path updates preserving an existing instance. |
| XML | Typed XML export; selected-XSD generation with final-byte validation in its existing paths. | Editing a supplied XML instance while preserving namespaces and untouched nodes. |
| CSV | Typed record export and tabular inspection, mapping and merging. | Preservation-specific row or dialect updates when those existing tools do not fit. |
| Excel | Record-oriented XLSX export and workbook merging. | Cell/range editing with formulas, named ranges and existing workbook formatting. |
| Word/PDF forms | Document processing and file generation are separate from form filling. | Named-field discovery, typed field values and format-specific form validation. |

These future adapters are not delivered by this release. PDF AcroForms,
scanned forms, spreadsheet cells and XML nodes need their own semantics, not a
universal Office document model. A later workflow task can call the same
service without widening the existing JSON-only exact saved-record
publication path.

## Testing and validation

Functional coverage lives in `functional_tests/test_document_transform_core.py`
and the Word, PowerPoint, source-intake, rendering and orchestration
transformation tests, plus `test_document_transform_harness.py`. It covers source identity, package preservation,
template content types, supported edits, incomplete useful drafts and
unauthorized or unsafe inputs. Orchestration tests use actual retained results
and composition with external I/O blocked. The headless harness also exercises
actual chat publication, model-free delivery recovery and a second transformation
of the newly committed file in the same conversation.

The implementation uses existing Office/XML dependencies; it does not require
desktop Word, PowerPoint, LibreOffice or browser automation in production.
Package reopening and content/style checks validate document structure, but
visual fit still depends on the reference design and the amount of replacement
content. Review the file and its outcome report before external distribution.

Related documentation:
[Create files with orchestration](../../guides/create-files-with-orchestration.md)
and [Generated File Export Framework](GENERATED_FILE_EXPORT_FRAMEWORK.md).
