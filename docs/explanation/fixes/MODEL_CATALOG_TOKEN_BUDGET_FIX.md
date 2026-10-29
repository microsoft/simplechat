# Verified model catalog and Microsoft 365 token budgets (v0.261.035)

Fixed/Implemented in version: **0.261.035**

Related version update: `application/single_app/config.py`, from `0.261.034`
to `0.261.035`. Refs #1493 and PR #1497.

## Issue and root cause

A Microsoft 365 file action could return `model_context_unavailable` even when
the user had a valid connection and the agent had the correct SharePoint action.
All 75 model catalog entries lacked numeric token limits. The agent loader also
discarded the selected model's configuration before the file runtime resolved
the budget using only a deployment-name string.

The previous resolver stopped at the first partial override and treated maximum
input and shared context as interchangeable. This could hide a missing value
that was available from the endpoint or catalog. Some agent generation settings
were applied to service objects that did not retain them, rather than being
bound to the actual Semantic Kernel request arguments.

## Catalog and configuration

The catalog now accounts for all existing models with source-linked numeric
values or explicit unknown, hosting-dependent, configuration-only, or
not-applicable dispositions. The model audit was verified on **2026-09-19**.
Provider/version/protocol profiles retain differences instead of assigning one
universal capacity to every deployment of a similarly named model.

For example, the exact `gpt-5.6-terra` specification documents **1,050,000 shared
context tokens, 922,000 maximum input tokens, and 128,000 maximum output tokens**.
Azure GPT-5 Pro and direct OpenAI GPT-5 Pro publish different output ceilings.
xAI's configurable 128,000-token API default is not a hard model maximum.
Non-text image/video models do not receive fabricated text-output limits.

Model Endpoints separates `contextWindow`, `inputTokenLimit`, and
`outputTokenLimit` from per-request Response Length. Blank overrides inherit.
`catalogModelId` maps a custom deployment name to an actual published model;
`modelVersion` selects applicable version-specific evidence. Custom endpoints
can explicitly declare verified capacities and output-accounting semantics.
Invalid values are rejected rather than silently truncated or replaced.

The catalog describes capacity, not a guarantee of cloud availability.
Commercial, Government, and custom clouds continue using their configured
endpoints and authentication. No new public-host fallback or permission is added.

## Runtime changes

`functions_model_capabilities.py` resolves each capacity independently and
produces an immutable, allowlisted `ModelTokenBudget`. It does not import
configuration, settings, logging, or cloud clients.
Generation-accounting provenance is separate from numeric-limit provenance, so
an explicit operator declaration is not presented as verified native behavior.
An unknown model does not acquire accounting semantics from its provider name.

`semantic_kernel_loader.py` carries the selected model and endpoint metadata into
both single-agent and specialist construction. `agent_logging_chat_completion.py`
keeps request settings isolated and verifies that the selected service matches
its budget. `functions_model_budget_runtime.py` sends one protocol-appropriate
generation parameter and preserves explicit reasoning settings.

Azure GPT-5.6 Chat Completions function tools require `reasoning_effort: none`.
When the caller has not chosen an effort, that documented tool-compatible value
is sent explicitly. An incompatible explicit choice produces a configuration
error; it is not silently changed and does not initiate sign-in.

The continuation journal counts current message/tool history and advertised
tool schemas, and binds budgets to asynchronous task context rather than a
mutable Flask `g` field shared by concurrent tasks. Cleanup restores the prior
context on completion, interruption, or error. Model-budget changes are included
in continuation fingerprints, so a paused request cannot silently resume under
different limits.

File retrieval and staged deeper analysis use the same budget semantics.
Independent input ceilings constrain input alone; shared-context constraints
also reserve generated output. Reasoning is included only according to the
actual provider/protocol contract. Deeper analysis removes tool access and sends
its bounded output cap through the same SDK settings adapter.
Its complete response must also fit the calling agent's remaining context.
Oversized findings remain in retained checkpoints instead of being silently
truncated or injected into an already full conversation.

The 12,000-token fast evidence window, sharing consent, identity checks,
retained source ranges, and no-replay guarantees remain in place. The tabular
consumer retains bounded legacy fallback behavior without confusing fallback
estimates or requested response length with verified model capacities.
For unknown accounting, tabular planning stays at or below its legacy
128,000-token input ceiling and 65,536-token request ceiling, tightened by
smaller verified or configured limits. It emits warning metadata and logging
and sends the bounded request cap to the provider. These are application
policies, not verified hidden-thinking limits; M365's stricter evidence gate
still requires a verified total-generation contract.

## Validation

The regression coverage uses the shipped catalog and resolver rather than
mocking successful capacity values:

- `test_model_token_budget_resolution.py`: strict numeric validation, independent
  precedence, exact identity/alias matching, scoped profiles, context boundaries,
  provider output accounting, immutable projections, and serialized SDK settings.
- `test_m365_catalog_budget_integration.py`: fresh-process application bootstrap,
  actual selected/default model loading, real agent continuation, SharePoint
  provider access with external Graph/model I/O replaced, and task isolation.
  Explicit checks also run under optimized Python.
- `test_m365_runtime_adapters.py`: real-catalog staged analysis with retained
  checkpoints and a real Semantic Kernel settings type.
- Existing retrieval, consent, continuation, streaming, cold-import, tabular,
  endpoint-normalization, and endpoint-editor UI suites cover compatibility.

Before the fix, a valid Terra deployment had no usable catalog budget and file
evidence failed before search. After the fix, its declared capacities and
selected overrides reach the actual request, with bounded retained evidence.
This does not force an LLM to call a tool when its instructions leave that choice
optional.

## Deployment and limitations

Deploy **0.261.035** to use the repair. No SDK upgrade, database migration,
Microsoft 365 permission change, or deployer version change is required.
The user manages deployment; local validation does not claim the live app has
already been updated.

After deployment, explicitly request a read-only SharePoint search and confirm
source excerpts/citations, not merely a generic answer. A reconnect is needed
only for an actual connection rejection.

Unpublished or conflicting capacity evidence remains explicit. Open-weight
configuration lengths are not automatically a host's supported serving limit.
Visible-only output caps cannot bound hidden reasoning. Multimodal history
without a verified token estimate requires a text-only conversation for file
evidence rather than pretending that URL/text lengths bound image or audio
tokens. Previously paused requests whose model-budget fingerprint changes must
start a new request; retained evidence is not deleted.
