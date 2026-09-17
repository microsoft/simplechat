# Explicit Workflow Data Flow

Implemented in version: **0.261.108**

The application version is tracked in `application/single_app/config.py`.

## Overview

An ordered workflow can select the final output of a specific earlier task instead
of relying on whichever reply happened immediately before it. Shared reference
documents supply reusable criteria separately from those task outputs. Optional
output requirements make missing or malformed deliverables visible rather than
inferring success from a model's prose.

This builds on the immutable result manifests described in
[Workflow Data Flow](WORKFLOW_DATA_FLOW.md). It does not add a parallel execution
engine, arbitrary scripts, task loops, a graph editor, or automatic checkpoint
resume.

## Definition and result versions

`definition_version: 2` identifies the authored workflow schema. It is distinct
from the React V2 interface and from the stored `workflow-result-v1` result
contract.

Existing V1 definitions retain their ordered-task behavior. A classic save cannot
convert an advanced definition back into a reduced list of instruction fields.
Unsupported definition versions are read-only, and the server rejects a downgrade.

Native updates echo `definition_revision` from the saved definition. That revision
fingerprints authored fields, not transient progress. Conditional writes protect
against another editor changing the definition while it is open. Runtime updates
also use conditional writes so a delayed progress update cannot restore old
instructions.

Editing an advanced workflow with an active run is rejected. Cancelling or
finishing the run does not discard the saved editor draft.

## Explicit task inputs

A task's `inputs` has three meanings:

| Value | Meaning |
| --- | --- |
| Omitted or `null` | Consume the preceding successful task's authoritative result, preserving the legacy default. |
| `[]` | Do not consume upstream task outputs. |
| A binding list | Consume exactly the named outputs selected in that list. |

A binding names an earlier task by stable `task_id`, not list position:

```json
{
  "inputs": [
    {
      "name": "inventory",
      "task_id": "extract",
      "output": "records",
      "required": true,
      "expected_kind": "records"
    }
  ]
}
```

The supported final output selectors are `authoritative`, `text`, `records`,
`json`, and `documents`. Presentation and diagnostic sections remain inspectable
results, but are not task-data binding choices.

Reordering a task never silently changes its producer. Forward, self, and missing
producer references fail definition validation. At execution, the loader uses
server-owned result references, verifies the actual representation, and preserves
the exact producer/output receipt with the consumer.

A required unavailable producer blocks the task. An optional missing producer or
named output is represented explicitly as unavailable. Permission errors and
invalid output are not converted into optional empty data.

## Shared reference documents

Workflow-level `reference_inputs` identify reusable documents such as policy or
evaluation criteria:

```json
{
  "reference_inputs": [
    {
      "id": "criteria",
      "name": "criteria",
      "document_id": "policy-document",
      "scope_type": "group",
      "scope_id": "workflow-group"
    }
  ]
}
```

Aliases begin with a letter and contain up to 64 letters, digits, underscores or
hyphens. Reference IDs and aliases must be unique.

Per-task `reference_ids` can select all shared references when omitted, none with
an empty list, or a subset of reference IDs. These references are separate from
the task's document action and from earlier task outputs.

Group workflow references belong to that workflow's group. Personal references
use the workflow owner's documents; an explicit group or public scope identifies
other authorized sources. A descriptor is not an authorization decision: save
and execution resolve the exact source through existing document-access helpers.

Before task execution, the run freezes the complete indexed text of references
used by its tasks and their source identities. Later uses recheck access even when reusing that frozen content.
Changed sources require a new run. Missing, partially available, or unreadable
indexed content fails explicitly; no excerpt is presented as the complete
reference.

References still count toward the actual model request budget. Attaching a large
reference does not increase the model's context capacity.

## Output requirements and honest status

An optional `output_contract` describes expected deliverables:

| Field | Purpose |
| --- | --- |
| `kind` | Require text, records, JSON, or per-document results; `any` leaves the representation unconstrained. |
| `schema` | Validate the complete final value against a supported JSON Schema subset. |
| `expected_count` | Require an exact collection size, including a legitimate zero-item result. |
| `identity_field` | Require a nonempty unique string/integer identifier on each record. |
| `require_complete_coverage` | Require explicit complete source-processing evidence. Missing evidence is not assumed complete. |
| `allow_partial` | Explicitly accept completed-but-incomplete data while retaining its limitations. The default is false. |

The schema supports types, object properties, required fields, additional
properties, items, numeric/string/array bounds, enums, and descriptive labels.
External references, regular expressions, and composition keywords are not
supported. Structural limits are 32 KiB per schema, 12 nesting levels, and 200
properties per object. These are definition-validation limits, not task-output
truncation.

Server-owned `workflow_validation` is separate from Analyze's producer validation.
It contains a status, eligibility, reason codes, and counts without copying
private output values into error messages.

| Status | Meaning |
| --- | --- |
| `not_requested` | No meaningful output requirements were configured. |
| `valid` | Configured structural/count/coverage requirements passed. |
| `invalid` | The output violates a requirement or producer validation failed. |
| `incomplete` | Required data or coverage is missing, unknown, or still pending. |
| `accepted_partial` | Completed partial data was explicitly accepted; limitations remain visible. |

Partial acceptance cannot make malformed data valid or bypass a pending producer.
Structural validity is not proof that a finding is factually correct.

The run outcome accounts for every task, not only the last successful reply.
Accepted partial results remain distinct as `completed_partial`; the presence of
the word "complete" in model text does not set a success state.

Result pages, task history, and workflow activity recheck contributing sources
through the shared source-authorized reader. Workflow lists redact cached
last-run text when its source access is lost. Older cached previews without a
bound `last_run_id` are omitted instead of guessing which run they describe.

Output validation happens after a task returns. It does not undo side effects
an agent already performed; pre-action approval and durable execution gates
remain a separate milestone.

## Native V2 editing and compatibility

Personal workflow editing lives at `/v2/workspace/workflows`. Group workflow
editing uses the selected group under `/v2/groups`, without changing the user's
active group setting behind the scenes.

The list editor exposes task order, runner selection, explicit prior-task inputs,
shared references, and optional output requirements. Existing File Sync, alert,
document-action, and publication settings that are outside the current editor
remain preserved.

Classic workflows remain runnable. Advanced definition editing belongs in V2;
both the interface and server protect against unsupported or stale saves.
The run inspector presents validation and consumption metadata separately from
execution state and loads result data only on request.

## Implementation and coverage

The new independent modules are:

- `functions_workflow_definitions.py`: versioning, aliases, scoped descriptors,
  ordering, input contracts, and the bounded schema subset.
- `functions_workflow_bindings.py`: authorized named reads and frozen reference
  loading through supplied shared loaders.
- `functions_workflow_validation.py`: deterministic requirement reports and
  aggregate outcomes.
- `functions_workflow_definition_store.py`: conditional definition/runtime writes.
- `functions_workflow_editor.py`: non-secret, scope-authorized runner choices.

Functional coverage includes nonadjacent producers, missing/forward bindings,
V1 downgrade prevention, stale edits, concurrent runtime updates, source
revocation/change, zero counts, duplicate identities, explicit partial
acceptance, and preservation of stricter producer validation.

The V2 editor uses locally bundled assets and existing Python Playwright
fixtures. No CDN, new graph runtime, or new test framework is required.
