# Orchestration Conversation Context Fix

**Fixed in version: 0.261.096**

## Issue

V2 orchestration could lose the subject of a follow-up. After discussing wineries
on a Medford-to-Crescent-City trip and narrowing the location to Grants Pass,
"which are open on Wednesdays" could become a generic search for "open on
Wednesdays". The answer then asked the user to identify the businesses again.

## Root cause

The planning route accepted optional browser `recent_messages`, but the V2
controller did not send them and the server did not load the stored conversation.
Candidate retrieval also ran before any conversational interpretation.

The existing run ledger summarized activities, not the assistant's actual answers.
Even if history had been supplied, the old conversation signal builder retained
only 300-character prefixes. Execution was another request and received neither
that history nor a durable contextual interpretation.

A related clarification handoff sent the user's answer without the matching
elicitation schema, so the server could not validate and incorporate it.

## Changes

| Component | Change |
| --- | --- |
| `functions_orchestration_context.py` | Normalizes eligible stored messages, respects masking and current block revisions, bounds snapshots, and verifies source fingerprints before reuse. |

Before a runnable plan exists, the validated clarification chain and original
snapshot are retained in a private `pending_turn` record in the existing run
container. These records are excluded from run listings, numbering, and execution.
Updates use the observed record version so a delayed model response cannot overwrite
a newer answer. The pending state is removed after a runnable plan is saved.

Clarification chains are limited to 12 answers and 32 KiB of answer data; a complete
pending record is limited to 64 KiB. Exceeding a limit produces an error rather
than silently discarding earlier answers. Subsequent answers are validated against
the server's saved question, not a replacement schema from the browser.py` | Normalizes eligible stored messages, respects masking and current block revisions, bounds snapshots, and verifies source fingerprints before reuse. |
| `functions_orchestration_planner.py` | Resolves follow-ups before retrieval, distinguishes new topics and transformations, and requires self-contained queries and tasks. |
| `route_backend_orchestration.py` | Loads history from an owned conversation partition, persists the interpreted turn, reuses its user-message ID, and reloads the same context for execution. |
| `functions_orchestration_runs.py` | Saves run context and bounded private pending-turn state, preserving answers across successive clarifications without creating phantom runs. |
| `functions_orchestration_executor.py` | Carries conversation context alongside evidence and revalidates it before final synthesis, including respond-only runs. |
| `functions_orchestration_adapters.py` | Uses contextualized task defaults and supplies relevant conversation text to analysis, agents, and final answers. |
| `orchestrationController.ts`, `orchestration.ts` | Send the matching clarification with its response, preserve the original turn, and stop a cancelled clarification without starting another plan. |
| `application\single_app\config.py` | Advances the application patch version to `0.261.096`. |

The behavior is shared by Auto, countdown, and manual approval. Browser pagination,
navigation, or clearing local message state cannot replace the server's history.
Later messages do not enter an already approved run. Changes to referenced messages
or their visibility require a new plan rather than replaying stale text.

### Context is not source evidence

An earlier answer can identify which wineries the user means or provide text to
reformat. It does not prove their opening hours. The resolver supplies meaning and
constraints; knowledge steps still obtain factual evidence, and final synthesis
must describe missing information rather than invent it.

The run ledger remains a separate activity summary. Disabling it does not disable
recent conversation history. Repeating a search can be appropriate when an earlier
run did not obtain the newly requested fact.
Entries derived from masked or inactive turns are omitted from the model's ledger
so their summaries and clarification answers do not reintroduce hidden text.

### Bounds and access

Orchestration uses `conversation_history_limit`, rounded up to an even message
count, with a hard maximum of 50 messages and a 16 KiB serialized snapshot budget.
The normal setting default is 10; a missing setting falls back to six. Zero disables
historical messages. Older content is removed first; an oversized remaining message
retains bounded beginning/end text with an explicit truncation marker.

Only eligible user and assistant text is included. System/tool records, hidden
generated artifacts, inactive attempts, masked text, and binary content are not
replayed. Conversation ownership is checked before message reads. Snapshot IDs are
not permission grants, and document, workspace, role, and capability checks remain
in effect.

Historical links are usable only when the request refers to an eligible user-authored
message containing them. Links in validated, accepted clarification values also
count as user input. Rewritten text, question text, declined answers, and
assistant-suggested URLs cannot authorize a page read. Internal history snapshots
are omitted from the run-list response.

## Validation

The following suites exercise the fix without accessing production data:

- `functional_tests\test_orchestration_conversation_context.py`: bounds, Unicode,
  masking, source changes, request resolution, URL provenance, analysis adapters,
  and synthesis prompt roles.
- `functional_tests\test_orchestration_conversation_context_routes.py`: real
  Flask HTTP/SSE planning and execution with controlled external boundaries,
  all approval modes, clarified requests, retries, source cutoffs, stale plans,
  ownership failures, successive clarifications, pending-state isolation, and older
  pending records.
- `ui_tests\test_v2_orchestration_conversation_context.py`: the shipped controller
  and cards, accepting/declining/cancelling clarifications, approval modes, and
  navigation without retargeting a pending run.

The deterministic functional and browser scenarios pass, along with the affected
orchestration contracts, route-policy coverage, and V2 TypeScript check. These
results establish context transport and lifecycle behavior; controlled completions
do not establish the factual accuracy of a live model or current business hours.

One older assertion in `ui_tests\test_v2_orchestration_plan_card.py` expects a
completed card to retain "view"/"done" text. It fails identically against the
unchanged baseline because the component intentionally hides completed inline
cards. That unrelated assertion and the existing display behavior are unchanged.

## Limitations

This change does not introduce rolling summaries or memory across conversations.
References outside the retained window may still need clarification. Substantive
messages with usable history add a small resolution completion; first turns
without history and simple acknowledgments skip it.

Older pending records can reconstruct history only when their saved user-message
cutoff remains available. That reconstructed snapshot is frozen for execution and
revalidated before synthesis just like a newly created plan. Otherwise the user
must create a new plan. Completed historical runs remain readable.

## Related

- [Chat orchestration](../features/CHAT_ORCHESTRATION.md)
- [Orchestration settings](../../admin/orchestration.md)
- [Chat settings](../../admin/chat.md)
