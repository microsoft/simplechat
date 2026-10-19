# Orchestration Request and Saved-Memory Resolution Fix

**Version: 0.261.349**

Fixed/Implemented in version: **0.261.349**

Tracking: [#1785](https://github.com/microsoft/simplechat/issues/1785).
The corresponding `application/single_app/config.py` update is
**0.261.348 -> 0.261.349**. No data migration, new setting, browser asset, or
deployment-configuration change is required.

## Issue and root cause

The FED-31 through FED-38 live-UI reports planned eight 10/20-turn conversations,
but all stopped on turn one. They exposed two application seams and separate
harness failures; they do not establish eight failures of long-context retention.

The early request resolver treated transformation words plus references such as
"this" or "above" as proof of a missing historical source. A noun such as "review"
could trigger that path even when the current message supplied all needed facts
in ordinary prose. The shortcut asked for source text without invoking the
contextual resolver; a later override could discard a valid new-topic decision.

Saved memory was loaded only after request resolution. When resolution asked
for a saved name or role, it returned before receiving the memory already
available to the main planner and composition. FED-37's observed identity
question is consistent with that gap; the original private model prompt and
exact selected memory records were not captured, so its precise cause remains
unproven.

Read-only Azure investigation found seven matching completed execution outcomes
and no failed HTTP requests/5xx in the supplied windows. FED-37 profile writes
succeeded, and a time-correlated resolver event reported clarification with no
history. Transport success, visible answers, and successful profile writes do
not prove correct memory selection or completion of later turns.

## Application changes

| File | Responsibility |
| --- | --- |
| `functions_orchestration_planner.py` | Uses the existing bounded semantic resolver for ambiguous first-turn source requests; supplies authorized memory and selected-reference metadata with explicit trust boundaries. |
| `route_backend_orchestration.py` | Authorizes and recalls memory before resolution, including clarification resumption; reuses or refreshes recall for planning and preserves publication checks. |
| `functions_orchestration_memory.py` | Retains audience/scope rules and adds safe memory inclusion/selection diagnostics. |
| `functions_fact_memory_context.py` | Reports unembedded and incompatible fact counts without changing ranking, caps, or normal-chat backfill. |
| `config.py` | Advances the application version to `0.261.349`. |

### Source sufficiency

The full current message, retained historical previews, selected-reference
metadata, and accepted clarification answers reach the resolver. A self-contained
request can be a new topic without historical message IDs. A genuinely missing
or ambiguous target still requires clarification; workspace/web search cannot
silently replace missing text.

Transformation requests without explicit retrieval or selected-source intent
retain their no-unrelated-retrieval restriction, even if a model inconsistently
requests retrieval. Explicit authorized source selections and retrieval requests
keep their existing precedence. Historical IDs, roles, full-source reopening,
revision checks, and execution budgets remain unchanged.

Ambiguous no-history transformations now need a resolution completion instead
of an immediate lexical question. The existing two-attempt, 1,200-output-token
resolution limit applies; no additional model loop was introduced. Ordinary
first-turn requests and simple acknowledgments retain their cheap paths.

### Memory lifecycle and isolation

The existing shared reader supplies at most the newest eight nonempty instruction
memories and four relevant embedded facts, with read-only value bounds of 2,000
characters. The initial recall query includes the original request and accepted
clarification values. The main planner reuses it when that effective query is
unchanged, rechecking access; a changed resolved request causes a deliberate
refresh. New submissions, accepted clarification continuations, and final
composition read current memory again.

Current user instructions take precedence. Saved facts are background, not
instructions, permission grants, historical message IDs, or synthetic accepted
answers. Saved preferences cannot override resolver policy or supply absent
document text. The resolver is instructed not to copy private memory into
external retrieval queries just because it is available.

Memory remains server-authorized and read-only:

- Personal scope must match the authenticated user; group scope requires current
  membership. Shared/hidden conversation audiences withhold personal and group
  memory. Audience changes invalidate reuse.
- Disabled memory performs no memory-store or embedding access. Empty memory
  remains distinct from unavailable search. Embedding failure may leave
  instruction memory available with `partial` status.
- Unembedded/incompatible facts are omitted, not backfilled or silently relabeled.
  Authorization/storage failures stop planning with a safe error.
- Run/pending-turn records retain audience and scope markers, not the raw memory
  prompt. Normal user messages, validated answers, and model-generated content
  continue to be stored through their existing contracts.

The instruction/fact caps and scope-wide recall are unchanged. Unique test aliases
do not create isolated storage namespaces; fixture selection pressure must not
be mistaken for proof of a specific contamination incident.

### Diagnostics

`[ORCHESTRATION_PLANNER]` reports the resolution stage/outcome, memory status,
context-included flag, accepted-answer count, and hashed conversation/turn IDs.
`[ORCHESTRATION]` reports available/selected instruction and fact counts,
unembedded/incompatible counts, recall mode, and the hashed conversation ID.

No memory values, full prompts, answers, credentials, or content hashes are logged
by these diagnostics. A context-included flag establishes delivery, not model
compliance. Available-minus-selected does not itself distinguish a cap from
irrelevance. See [logging tags](../../reference/logging-tags.md#request-resolution-memory-diagnostics).

## Harness-owner repair guidance

The reported harness files live in a separate checkout, not this worktree. No
external harness code was changed. Line references below belong to the submitted
reports and must be checked against the harness revision being repaired.

| Reports | Observed failure | Repair owner |
| --- | --- | --- |
| FED-31, 32, 34, 35, 36, 38 | Captured optimistic `message-pending-user-*` wrapper no longer exists after persistence. | Harness observation helper. |
| FED-33 | Valid supplied facts rejected because incidental literal wording was absent. | Harness assertion contract; answer discovery also needs correction. |
| FED-37 | Asked for a saved review name/role. | Application resolution/memory investigation, then genuine recall acceptance rerun. |

### Track the logical turn across persistence

`ui_tests/federal/long_conversation_models.py:354` (`execute_turn`), reached
through `execute_long_conversation:376`, `workflows.py:85`, and
`live_evidence_plugin.py:173`, requires the captured optimistic wrapper to remain.

`chatStore.ts` intentionally replaces a pending ID with the server message ID,
and `MessageList.tsx` derives the wrapper from that current ID. Do not retain or
delay temporary IDs, add arbitrary sleeps, or accept duplicate messages to make
the harness pass.

Capture the pre-send conversation state, submit once, and re-resolve the current
user turn using visible content and position, distinguishing repeated prompts.
Read its persisted rendered ID when available. A fast save may replace the
optimistic bubble before it can be observed. Submission, persistence, answer
completion, and reload durability are separate checkpoints.

Regression cases should include fast/slow acknowledgments, failed saves,
delayed answers, reconnect, repeated text, navigation, and reload. If visible
UI evidence cannot establish identity, propose a generic testability contract
separately rather than guess an ID or inspect internal state as UI evidence.

### Discover the current answer before checking its meaning

`long_conversation_models.py:348` calls `page_models.py:390` (`facts`). The
reported locator selects the first wrapper containing the exact `Show reasoning`
button. Reasoning is optional, and `.first` can select an earlier answer on a
later turn.

Find the assistant response belonging to the current submitted turn independently
of answer wording or reasoning controls. Then assert the required facts and
relationships. FED-33 preserved its review/program IDs, budget, readiness, and
owner without repeating "Civic Bridge"; absent incidental phrasing alone does
not demonstrate a memory defect.

Keep explicit requirements strict: exact saved prefixes/headings, identity-role
relationships, numeric values, updated identifiers, stale-value exclusions, and
source provenance. If literal display-name repetition is required, specify it
in the input and classify its absence as output-contract noncompliance.

### Do not hide recall failures or fixture interference

FED-37's clarification path includes `long_conversation_models.py:339,256` and
`page_models.py:503,449`, ending at `plan.synthetic_clarification_answered`.
Do not auto-answer a missing saved identity and then claim recall passed.
A separate continuation test may answer it, but must preserve the original
failed recall checkpoint.

Use a dedicated test profile and lifecycle-managed run-owned fixtures. Record
exact visible saved values/types/IDs and update times, selected scope, model,
mode, version/build, harness revision, and per-turn evidence. Never delete
unrelated memories. Capture submitted/answered/verified/reloaded turn counts
separately; dependent turns not reached are **not run**.

## Validation and limitations

`functional_tests/test_orchestration_request_memory_resolution.py` executes real
Flask planning, resolver, shared memory reader/store, and composition boundaries
with external model, embedding, storage, and network I/O controlled. It covers
inline-source paraphrases, history/new-topic separation, context supplied before
resolution, accepted-answer updates, unchanged/changed-query reads, fresh
composition, normal-reader parity, caps, unavailable embeddings, authorization,
group membership, audience changes, and private diagnostics.

Related suites retain missing-source questions, no-workspace fallback,
full-source fidelity, strict resolver validation/retries, normal-chat backfill,
and answer-time reauthorization. Deterministic replies verify context and state
transitions, not a live model's factual accuracy or obedience.

Local validation in an isolated environment with the repository-pinned Flask
and Werkzeug versions:

| Check | Result |
| --- | --- |
| Combined request/source, orchestration memory/context/HTTP/model-selection, normal-chat memory, and persistence suites | 320 passed, 83 subtests passed. |
| Changed orchestration owners, request-memory/source routes, and SDK response contracts with the Cosmos network guard | 98 passed. |
| Full reviewed Cosmos gate: `python scripts\check_cosmos_response_boundaries.py --run-contracts` | 1,143 passed, 244 subtests passed; 1,067 owners and 412 doubles have zero review gaps. |
| Blueprint policy inventory, unauthenticated contract, and route coverage scripts | 28 checks passed. |
| Documentation surface coverage and site quality scripts | 13 checks passed; generated surface inventory is current. |

The isolated environment also avoids the shared installation's incompatible
OpenSSL dependency. The full gate required restoring the repository-pinned
Cosmos SDK and missing YAMCS client there. No global Python packages or
application requirements were changed.

No production deployment or external harness repair was performed. The deployed
build was not independently pinned to a commit/digest. After harness repair and
an explicitly authorized deployment, rerun all eight full 10/20-turn sequences,
including mixed-mode transitions, midpoint/final reloads, and FED-38 updated-value
recall with stale-value exclusion. None of those previously unexecuted turns is
claimed to pass by this fix.
