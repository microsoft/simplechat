# V2 Context Usage

## Overview

The modern (V2) chat now shows how much of the selected model's context window the conversation
uses and what is using it.

- A **ring in the composer**, beside Attach and Send, shows the percentage used. Hovering names
  the numbers; selecting it opens the details.
- A **Context tab in the right-hand drawer**, beside Contents, Documents and Plan, shows the
  total, a breakdown by type, and the request size behind each reply.

Implemented in version **0.261.483**.

### Dependencies

None added. Sizes are estimated with `tiktoken`, which the application already requires, and the
model limits come from the existing model capability catalog and Model Endpoints settings.

## Technical specifications

### What is measured, and what is estimated

| Number | Source | Accuracy |
|---|---|---|
| Total for a reply | The provider's input count for the request (`metadata.token_usage.prompt_tokens`) | Exact, when the reply took one request |
| Split by type | The server sizes each message of the request just before it is sent | Estimated with the model's tokenizer |
| Limit | The model's context window less the space held back for the reply, capped by its input limit | From Model Endpoints or the capability catalog |

The provider reports one number per request. It does not say how much of it was messages, files
or search results, so the split is the server's own estimate of the same request. Where the
provider's total is larger than the estimate, the difference is shown as **Agent, tools and
overhead** (tool definitions, an agent's own instructions and request formatting). Where the
estimate runs high, the rows are scaled to the provider's total.

When an agent calls tools, a reply takes several requests and the provider's counts are added
together. That sum is spend, not the size of any one request, so the display uses the server's
estimate for that reply and marks it as estimated.

### Categories

| Category | What it holds |
|---|---|
| Messages | The recent user and assistant messages sent with the request |
| Summary of earlier messages | The short summary that stands in for older messages |
| Attached files | Files and images uploaded to the chat, itemized by file name |
| Workspace results | Document passages retrieved for the question |
| Web results | Web search results and pages read for URL access or deep research |
| Memory | Saved facts and instruction memories |
| Instructions | The system prompt and guidance added for the request |
| Agent, tools and overhead | What the provider counted beyond the listed text |

### How SimpleChat fills the context

SimpleChat does not send the whole conversation. Each request sends the most recent messages, up
to the **conversation history limit** in Admin Settings, and replaces older ones with a short
summary when that option is on. The context therefore does not grow with every turn; large
attached files and retrieved passages are what fill it. The Context tab states the limit that
applied and how many older messages were summarized or left out.

### Orchestration plans

A plan does not have one context window. It is many separate model requests (planning, each
model-backed step, the final answer), each with its own prompt, and with Auto routing the steps
can run on different models with different windows. None of those requests is the conversation's
context, and only the plan's answer text is carried into later chat requests.

A plan is therefore reported as **spend**, not as context:

- The ring ignores a plan's reply and keeps showing the last ordinary reply.
- **By turn** lists the plan with its total and, beneath it, what each model spent, how many
  steps ran on it, and which model planned and wrote the answer.
- The reply stores this as `metadata.usage_by_model`. Each request a step makes notes the model
  it ran on, so a step counts under the models that actually served it: an agent step under the
  agent's own configured model, and its delegates under theirs. Anything a step did not note
  counts under the model its approved binding names, or the answer model when it has none.
  Whatever the run spent beyond its steps, planning and composing the answer, counts under the
  answer model.

The window question a plan does have is per step: did any one request come close to the limit
of the model it ran on? Each step records its **largest single request** and that model's limit,
and the **Plan** tab shows it under the step, for example "Largest request: 82% of GPT-4o's
window (92K of 112K tokens)". It turns amber at 75% and red at 90%, like the ring. An agent
reports one total for however many requests it made, so an agent step names its model but shows
no largest request.

### Switching models

The ring measures against the model the next message will use. Each model in the picker carries
its limits, so choosing another model re-bases the ring immediately: the size is still the last
reply's, and the limit is the newly selected model's. The Context tab says so until the next
reply. While an agent is selected nothing is re-based, because an agent runs on its own model.

### Activity logs and Control Center

Plans used to be missing from usage reporting: the run kept its totals but wrote no
`token_usage` activity. A finished run now writes one `chat` token usage row **per model**, with
`additional_context.execution_path` set to `orchestration` along with the run, attempt, status,
step count and model roles. Existing token charts and filters by day, model, user, group and
public workspace include plans without change.

- The row id is derived from the run and the model, so redelivering or recovering the same run
  cannot count it twice.
- A run that is waiting for approval or input writes nothing until it finishes.
- A retry is a new run and is counted for what it spent itself; steps it reused report no usage.
- Failed and cancelled runs are logged, because the tokens were spent.

The request that summarizes older messages used to discard its usage. It now writes its own
`chat` row, marked `purpose: history_summary`, separate from the reply's row so the reply's
count stays the size of one request.

**Source filter.** Token usage from chat, plans and workflows all share the `chat` token type.
The dashboard's token filters and the activity logs' filters now include **Source** (Chat, Plan,
Workflow), sent as `token_source`. A chart filtered by source drills into activity logs with the
same filter. Plan rows are those marked `execution_path: orchestration`; workflow rows are those
that name a workflow or deliver a workflow's result; Chat is every other `chat` row. Embedding
and web search rows have their own token types and belong to no source.

### Architecture

1. Every chat path (standard, streaming, agent and kernel) calls
   `_prepare_conversation_context_for_invocation` in `route_backend_chats.py` immediately before
   the model call. That function now passes the final message list to
   `measure_context_usage` in `functions_context_usage.py`.
   The model's limits are worked out once, when the request resolves its selected model, from
   the records already in hand, and reused here; the display reads nothing further.
2. The result is stored as `context_usage` inside the reply's existing
   `metadata.history_context`, so it is saved with the reply and returned by the existing message
   and stream-completion responses. No route was added.
3. `contextUsage.ts` reads the latest active reply and combines the provider's count with the
   estimate. `ContextUsage.tsx` renders the composer ring, the header button and the drawer tab.

Stored shape:

```json
{
    "version": 1,
    "estimator": "o200k_base",
    "model": "gpt-4o",
    "estimated_total": 8123,
    "message_count": 9,
    "categories": { "messages": 2100, "files": 4800, "search": 900, "instructions": 323 },
    "counts": { "messages": 6, "files": 1, "search": 1, "instructions": 1 },
    "items": [{ "category": "files", "label": "Q3-forecast.xlsx", "size": 4800 }],
    "limits": { "window": 128000, "input_limit": 128000, "reply_reserve": 4096, "input_ceiling": 123904 }
}
```

Field names avoid the words "token" and "key" because several serializers in the application
treat such fields as credentials. File names are the only user content stored, at most twelve.

### File structure

| File | Purpose |
|---|---|
| `application/single_app/functions_context_usage.py` | Classifies and sizes the request; resolves model limits |
| `application/single_app/route_backend_chats.py` | Records the measurement on every model path |
| `application/single_app/functions_orchestration_usage.py` | Notes each request's model and size; splits a plan's usage by model and logs it |
| `application/single_app/functions_orchestration_execution.py` | Notes each prompt request; records and logs the split when a run is saved |
| `application/single_app/functions_orchestration_executor.py` | Keeps per-model usage and the largest request on each step |
| `application/single_app/functions_orchestration_adapters.py` | Notes the agent's and its delegates' models |
| `application/single_app/functions_orchestration_runs.py` | Shows the step's largest request to readers |
| `application/single_app/functions_chat_model_catalog.py` | Sends each selectable model's limits |
| `application/single_app/functions_control_center_dashboard.py` | Source filter, shared by the dashboard and activity logs |
| `application/single_app/functions_control_center_activity.py` | Applies the source filter to activity logs |
| `application/v2_ui/src/stores/contextUsageStore.ts` | The composer's selected model, for re-basing |
| `application/v2_ui/src/components/chat/OrchestrationRunView.tsx` | Largest-request line under each plan step |
| `application/v2_ui/src/components/controlCenter/DashboardSection.tsx` | Source filter on the dashboard |
| `application/v2_ui/src/components/controlCenter/activityLogs/ActivityFilterBar.tsx` | Token source filter on activity logs |
| `application/v2_ui/src/lib/contextUsage.ts` | Combines the provider's count with the estimate |
| `application/v2_ui/src/components/chat/ContextUsage.tsx` | Composer ring, header button, Context tab |
| `application/v2_ui/src/components/chat/ConversationDrawer.tsx` | Adds the Context tab |
| `application/v2_ui/src/pages/ChatPage.tsx` | Adds the header button |

## Usage instructions

No setting turns this on. The ring and the header button appear after the first reply in a
conversation.

- Hover the ring for the percentage and sizes. Select it, or the ring in the chat header, to open
  the Context tab.
- **By type** lists what the last request contained. **By turn** lists the request size behind
  each reply; selecting one scrolls to it.
- The ring turns amber at 75% and red at 90%, and the tab adds a notice.

For a percentage to appear, the model's limits must be known. Set **Context window** and
**Output limit** for the model in Model Endpoints, or use a deployment the capability catalog
recognizes. Without them the ring shows the size of the last request and no percentage.

With four tabs, the drawer shows a label only on the open tab; the others show their icon and are
named on hover and to assistive technology.

## Testing and validation

- `functional_tests/test_context_usage_measurement.py` covers classification, totals, itemized
  files, odd message shapes, the character fallback when no tokenizer vocabulary can be loaded,
  limit resolution, and that every model path records the measurement.
- `functional_tests/test_v2_context_usage_logic.mjs` runs the real V2 helpers: provider count
  versus estimate, the overhead row, scaling, multi-request replies, replies saved before this
  feature, replaced attempts, the warning levels, the by-turn list and number formatting.

- `functional_tests/test_orchestration_plan_token_usage_logging.py` covers the per-model split
  adding up to the run's total, steps bound to different models, agent steps counted under the
  agent's model, unbound and reused steps, per-step observations and the largest request, the
  activity rows and their idempotency ids, waiting runs, and a failing log store.
- `functional_tests/test_token_usage_source_filter.py` covers the source predicates, the
  dashboard and activity log filters, refusal of unknown sources, and the summary request's
  usage being read and logged on every path that can summarize.

### Limitations

- The split is an estimate. Models that are not OpenAI models are sized with the `o200k_base`
  tokenizer, which is close but not exact. If no tokenizer vocabulary can be loaded (for example
  on a network that cannot reach its host), sizes fall back to four characters per token and the
  failure is remembered so chat requests are not delayed again.
- Images sent to a vision model are not sized; only their text description is.
- Replies saved before 0.261.483 show a total only, with no split and no percentage.
- A custom deployment name the catalog does not recognize has no percentage until its limits are
  set in Model Endpoints.
- An agent step shows no largest request, because an agent reports one total for all the
  requests it made.
- Requests a plan step makes through its planner client, rather than its prompt invoker or an
  agent, are not counted by the run at all. This predates this feature.
- Plans finished before 0.261.483 are not added to the activity logs retroactively, and their
  steps show no largest request.
- Small helper calls in chat other than the older-message summary (the search-query summary and
  source review planning) still record no usage.
- Re-basing needs the selected model's limits. A custom deployment with none keeps the last
  reply's limit.
- Generating an image is not a chat request and does not change the ring.
- The tab reports usage. It does not yet remove a file from the context or summarize on request.
- The classic interface is unchanged.
