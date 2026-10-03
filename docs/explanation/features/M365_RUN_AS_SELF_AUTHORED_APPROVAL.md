# Microsoft 365 Run As Approval For A Revision You Saved (v0.261.229)

## Overview

A workflow that runs as someone's connected Microsoft 365 account needs that
person's **Run as** approval, because the workflow acts as them while they
aren't watching. Before this release the approval was tied to an exact
workflow revision and conversation audience. Every edit made a new revision, so
the Run as user had to approve the workflow again after each change, even
when they made the change themselves. Adding a participant to the
conversation asked them again too.

Since this release, a revision the Run as user saved runs as them without a
separate approval. Their save counts as their review of the whole revision,
including earlier edits by others. SimpleChat records an approved, audited
authorization for that exact revision and connection, sends no notification,
and never shows it as pending. The first run of a workflow they saved doesn't
wait either.

Approval is still required when someone else is responsible for what runs:
someone else saved the current revision, or changed an agent or action it
uses after the Run as user's save. Audience changes never ask again. Explicit
decisions still win: a denial or cancellation stops its run, and a revoked
authorization is not silently re-created for the same revision.

Implemented in version: **0.261.229**, tracked in
`application/single_app/config.py`. This is the Run as part of #1621.

Dependencies:

- The Microsoft 365 approval service (`functions_m365_approvals.py`) and its
  `m365_workflow_run_as` records in the approvals container.
- The workflow execution boundary (`functions_m365_execution.py`) and runtime
  (`functions_m365_runtime.py`), which prepare a binding before any Microsoft
  365 operation of a run.
- Server-stamped `modified_by` and `modified_at` on workflows, agents and
  actions.

No setting, container, route or index is added.

## How a run is authorized

### A revision the Run as user saved

A revision is self-authored when all of these hold:

- the workflow's `modified_by` is its `m365_run_as_user_id`;
- that account is the run's data user;
- every agent and action the revision runs was last changed by the Run as
  user, or was last changed at or before the Run as user's save of the
  workflow (`modified_at`).

The binding is then created, or reused, as an approved record marked
`self_authored: true` for that exact revision: the execution fingerprint, the
Microsoft 365 connection id and the connection generation. A later run of the
same revision on the same connection reuses it.

### Someone else's revision

When someone else saved the current revision, or `modified_by` is missing, the
Run as user approves it as before. The run waits on a pending
`m365_workflow_run_as` approval, and the user is notified. These still ask
again:

- a later edit by someone else, which is a new revision;
- an agent or action the revision runs, changed by someone else after the Run
  as user's save, even when the workflow itself is unchanged;
- a new connection id or connection generation for the Run as account. The
  generation increments when the account reconnects or disconnects
  (`functions_m365_connections.py`).

A revision the Run as user saved is authorized again, without asking, for a new
connection or generation.

### Audience changes

The binding records the conversation's `audience_version`, but
`ensure_workflow_binding` and `validate_workflow_binding` no longer compare it.
Adding or removing participants never asks for Run as again.

Unchanged by this release:

- source-sharing approvals (`m365_source_sharing`, `authorize_sources`,
  `effective_sharing_grant`), which still follow the audience of each request;
- the runtime checks that stop a run or a prepared delivery when the audience
  changes while it is in progress (`validate_m365_workflow_execution`,
  `validate_m365_approval_decision` and the pending delivery context).

### Explicit decisions still win

- A denial or cancellation recorded for a run still stops that run with
  `m365_workflow_declined`, even after the Run as user saves the revision. A
  new run is authorized normally.
- Revoking a binding in Profile revokes every approved binding for the same
  workflow revision, including copies approved for earlier audiences. A
  revision with a revoked binding is never self-authored again: its next run
  waits for an ordinary approval. Approving it, or saving a new revision, lets
  the workflow run again.

## Technical specifications

### Where authorship comes from

`modified_by` is written by the server from the authenticated actor, never
from a payload:

| Save path | Actor |
| --- | --- |
| `POST /api/user/workflows` (`save_personal_workflow`) | The signed-in user |
| `POST /api/group/workflows` (`save_group_workflow`) | The signed-in group member |
| Workflows created from chat proposals (`create_personal_workflow_if_absent`) | The requester who accepted |
| AI assist | Saves through the routes above; the assistant writes nothing |
| The SimpleChat agent action's workflow creation (`create_personal_workflow_for_current_user`) | The signed-in user |
| The Data Management Cosmos DB editor | The editing administrator (see below) |

`build_personal_workflow_document` and `build_group_workflow_document` build the
stored document field by field, so a `modified_by` in a payload is ignored. A
structured (version 3) payload lists it among the server-managed fields.
Runtime progress updates (`update_workflow_runtime_record`) can't change it.

Agents and actions record `modified_by` and `modified_at` the same way.
`workflow_m365_manifests` copies each selected agent's and Microsoft 365 action's
authorship into `m365_revision_authorship` on the workflow it hands to the
binding. That field is outside `workflow_execution_fingerprint`, so saving an
agent without changing it doesn't change the revision.

### Raw administrator edits

The Data Management Cosmos DB editor can edit workflows, agents and actions
directly. When it saves a changed record in one of those containers, it now
records the administrator as `modified_by`, and the edit time as
`modified_at`, through `attribute_raw_authored_record_edit`. A raw edit
therefore never keeps a previous author, and never makes changed content run as
that author without their approval. The activity log still lists exactly the
paths the administrator changed.

Data Management backups, restores and migrations keep the recorded authorship.
They never transfer Run as approvals or Microsoft 365 connections, so the Run as
user must connect in the target environment before any run.

### The self-authored binding

The record keeps the shape `/api/m365/bindings` and Approvals already read:

| Field | Value |
| --- | --- |
| `request_type` | `m365_workflow_run_as` |
| `status` | `approved` from creation |
| `self_authored` | `true` |
| `approved_by_id` | The Run as user |
| `requester_id` | The run's actor |
| `binding` | The workflow id, fingerprint, connection id and generation, sources, conversation, recorded audience and review |
| `decision_event_id` | The id of its audit event |
| `execution_status` | `not_required` |
| `continuation_status` | `delivered`, so the continuation outbox never picks it up |
| `notification_status` | `not_required` |
| `expires_at` | Not set; nothing is requested |

The record and its append-only audit event, `self_authored_approved`, are
written in one transactional batch in the Run as user's partition. Two runs
that race to record the same revision converge on one record. The record's
`reason` explains that the user saved the revision and that revoking it makes
the revision wait for their approval.

### Revocation

`revoke_workflow_binding` revokes the chosen binding first, then every other
approved binding with the same workflow id and fingerprint. Two checks keep the
revocation in force when it overlaps a run:

- `ensure_workflow_binding` reuses an approved binding of a revoked revision
  only when it is an ordinary approval granted after the latest revocation. A
  run that finds any other approved copy, such as one an interrupted revocation
  missed, revokes it. The copy is then neither reused nor returned by
  `_create_request` as an existing approval.
- `_create_self_authored_binding` writes its record and then looks for a
  revocation of the revision. Because a revocation also writes before it looks
  for copies, either the revocation finds the new record or the new record finds
  the revocation. When it finds one, it revokes its own record and the run
  waits for an ordinary approval.

Revoking a copy that changed after it was read is retried up to three times.

### Interfaces

| Function | Change |
| --- | --- |
| `workflow_revision_self_authored(workflow, user_id, components)` | New, pure. Fails closed on missing or unreadable authorship. |
| `workflow_saved_by_run_as(workflow, user_id)` | New, pure. The workflow-level check the proposal card uses. |
| `M365ApprovalService.ensure_workflow_binding(..., self_authored=False)` | New keyword. Stops comparing `audience_version`, prefers an approved binding over a pending one, creates the self-authored binding, and revokes approved copies a revocation missed. |
| `M365ApprovalService.validate_workflow_binding` | Stops comparing `audience_version`. |
| `M365ApprovalService.revoke_workflow_binding` | Also revokes the revision's other approved bindings. |
| `prepare_m365_workflow_binding` | Decides `self_authored` from the stored workflow and its recorded authorship. |

### Interface text

- **Workflow proposal card (V2).** The status route's `m365.approval_state`
  adds `self_authored`. Before Create it is reported for a workflow that runs as
  the requester; after Create, when the stored workflow's `modified_by` and Run
  as account are both the requester. The card then says the workflow needs no
  separate Run as approval and waits only if someone else changes it or an agent
  it uses, instead of claiming that its first run waits.
- **Workflow editor (V2).** **Saving requires re-approving Run as** no longer
  appears when the draft runs as the signed-in user. The AI assistant's
  `run_as_reapproval` warning follows the same rule.
- **Run as field (V2 and classic).** The help text explains that the selected
  person approves revisions someone else saved, and that a revision they saved
  needs no separate approval.
- **Profile and Approvals (classic).** A self-authored binding reads
  "Decision: approved automatically because you saved this workflow revision
  yourself." It can still be revoked.

## Usage

There is nothing to turn on.

- **Run as users** save their own workflows and run them. Profile lists each
  automatic authorization under the workflow authorizations, where it can be
  revoked.
- **Group members who edit a workflow that runs as someone else** see
  **Saving requires re-approving Run as** before saving. The Run as user
  approves the new revision from Approvals.
- **Administrators** who edit workflow, agent or action records with the
  Cosmos DB editor become their last author, so affected workflows ask their
  Run as users before running as them again.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_m365_run_as_self_authored.py` | A self-authored first run and the Run as user's own edits are approved, audited and silent; someone else's revision, a missing `modified_by`, a later edit by someone else, and agents or actions changed after the save ask; connection id and generation changes; audience changes; denials, cancellations and revocations, including a revocation that races a new binding or is interrupted; the runtime's authorship plumbing; save routes record the signed-in actor; raw edits name the administrator. |
| `functional_tests/test_m365_approvals_execution.py` | An approved binding stays valid after an audience change. |
| `functional_tests/test_orchestration_workflow_proposal_routes.py`, `test_orchestration_workflow_proposal_done_when.py` | `approval_state` before and after Create. |
| `functional_tests/test_workflow_assist_scenarios.py`, `test_workflow_assist_dry_run_parity.py`, `test_workflow_assist_candidate_parity.py`, `test_v2_workflow_change_tracking.py` | The assistant's warning and the editor's note agree, for your own and someone else's Run as account. |
| `ui_tests/test_v2_orchestration_workflow_proposal_card.py` | The card's Run as line for every approval state. |
| `ui_tests/test_v2_workflow_change_tracking.py`, `ui_tests/test_v2_workflow_ask_ai.py` | The Run as note and warning in the browser. |
| `ui_tests/test_m365_lifecycle_and_approvals.py` | A self-authored binding in Profile, the Approvals list and the saved decision. |

Known limitations:

- The proposal card judges a created workflow from its own `modified_by` only.
  If someone else later changes an agent the workflow uses, the card still says
  no separate approval is needed until a run waits, when it shows the waiting
  state.
- An agent or action with no readable change time counts as changed after the
  save, so its workflows ask for approval. Saving the workflow again records a
  newer save time, but a component with no timestamp still asks.
- Authorship times come from the app servers' clocks, so an agent edit within
  clock skew of the Run as user's save counts as reviewed by that save.
- Revocation and approval times also come from those clocks. An approval
  granted within clock skew after a revocation can count as granted before it,
  and the run then asks once more.
