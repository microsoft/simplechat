# V2 GPT-5.6 model tool and citation fixes (v0.261.389)

Fixed/Implemented in version: **0.261.389**, recorded in
`application/single_app/config.py`.

## Issue and root causes

Some GPT-5.6 agent paths already supplied reasoning None correctly, but direct
Semantic Kernel tabular calls bypassed that policy. Azure treats omitted effort
differently from explicit None when function tools are present. A positive effort
cannot be made compatible merely by dropping it or changing a dated API version.

The connection editor also allowed protocol labels to be mistaken for dated
Azure API versions. Separately, a model-emitted Unicode-bracket source ID did
not match V2's existing Source-prefix citation grammar, even with exact
authorized metadata present.

Generic source-coverage prose made these outcomes difficult to distinguish:
a search with no returned evidence, an inaccessible source, an incomplete
operation, and an unsupported model request are not the same condition.

## Technical changes

`model_tool_chat_completion.py` enforces the selected model budget/tool policy
at the actual SDK boundary. `functions_model_endpoint_runtime.py` and
`semantic_kernel_loader.py` use these typed SDK subclasses, retaining canonical
model identity and the selected request deployment. Existing Chat Completions
connections are not switched to Responses automatically.

`model_responses_chat.py` supplies the opt-in reasoning/tool translation.
The connection editor now exposes **Use Responses API**, stores the choice
separately from a normalized base, and recognizes pasted operation URLs.
The shared chat factories honor this choice in legacy chat and workflow/APIM
fallbacks as well as named connections, without changing gateway prefixes or
turning subscription keys into bearer tokens.
Private continuation state is excluded from public message serialization.
Configuration observation, generated-tabular budgets, and applicable
orchestration model snapshots recognize the selected API.

`functions_model_endpoint_validation.py`, model connection form logic, and
runtime checks distinguish v1 routes from dated-version connections.
Legacy global/APIM factories also select the versionless v1 SDK path while
retaining API-key or managed-identity authentication and deployment aliases.
`citations.ts` resolves alternate markers only from exact current-message
records, with inert unresolved presentation and literal-code protection.

`functions_evidence_status.py`, the mixed-source handoff, and verified retained
Search lineage supply bounded per-answer metadata. V2 `MessageList`,
`MessageInspector`, and `ConversationDrawer` render the compact status without
inventing a result from citation absence or another conversation's state.
Copy/export text preserves material limitations.

The tabular retry guard propagates deterministic configuration and screening
failures, and records schema/model phase timings using the existing logging tag.

## Before and after

| Before | After |
|---|---|
| A direct tabular call could send tools without required None. | Shared SDK policy supplies the supported unset/None behavior and rejects an explicitly incompatible effort. |
| A protocol label could reach a dated Azure query. | Save/runtime validation explains the mismatch; explicit v1 routes use the versionless client. |
| Raw Unicode source markers remained visible. | Exact recorded sources resolve to named V2 citations; unknown records remain explicitly unresolved. |
| Coverage was mostly prose and could be mistaken for a model setting. | Recorded document status is available separately, with source details and honest recovery suggestions. |
| A deterministic policy failure could enter generic analysis recovery. | The failure escapes the loop without pretending computation succeeded. |

## Validation and impact

Real SDK mock transports verify all three GPT-5.6 catalog variants, deployment
aliases, explicit None versus positive effort, Responses function continuation,
generation limits, streaming delivery, private state, safe failures, and
cancellation. Production-parser checks and rendered browser cases cover exact
source resolution, evidence-state distinctions, and conversation isolation.

These are application-contract regressions, not a live customer-model benchmark.
Existing working YAMCS, database, and other action plugins are not rewritten.
No new route, cloud resource, CDN asset, deployment change, or quota increase
is introduced.

See [V2 model tools and evidence status](../features/V2_MODEL_TOOLS_AND_EVIDENCE_STATUS.md)
for configuration, behavior, test files, and limitations.
