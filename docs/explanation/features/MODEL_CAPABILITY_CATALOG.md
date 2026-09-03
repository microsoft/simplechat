# Model Capability Catalog

## Overview

SimpleChat uses the model catalog to distinguish what a model can do from how
much input and generation its documented contract permits. This matters when
retrieval, file analysis, or tabular processing must leave room for a response:
a shared context window is not an independent input allowance, and a requested
response length is not the model's maximum output.

**Implemented in version: 0.261.035**

- Application version owner: `application\single_app\config.py`.
- Catalog data contract: **schemaVersion 3**.
- Primary-source verification date: **2026-09-19**.
- Related work: issue **#1493**, PR **#1497**.
- The original qualitative capability resolver shipped in **0.261.014**.

All **75 existing model IDs** have an explicit token-limit disposition. An
unknown limit is a researched result, not zero, unlimited capacity, or permission
to borrow a sibling model's limit. Existing IDs, qualitative flags, display
metadata, and legacy aliases are retained.

## Dependencies and files

| File or dependency | Purpose |
|---|---|
| `application\single_app\static\json\model_capabilities.json` | Maintained model records, public sources, evidence, and conditional profiles |
| `application\single_app\static\json\schemas\model_capabilities.schema.json` | Strict Draft 2020-12 data contract |
| `application\single_app\functions_model_capabilities.py` | Dependency-light capability and capacity resolution |
| `functional_tests\test_model_capability_catalog_resolution.py` | Schema validation and qualitative resolver compatibility |
| `functional_tests\test_model_catalog_token_evidence.py` | Exact-ID audit, provenance, profile, and rejection regressions |
| `jsonschema` | Existing test dependency; no network lookup of schemas or sources is required |

The catalog is a local static JSON asset. Maintaining evidence does not add a
browser dependency, new API endpoint, or a provider documentation fetch to normal
application requests or CI.

## Qualitative capability resolution

Qualitative answers retain their original precedence:

1. A model's `capabilities` override.
2. An endpoint's `capabilities` override.
3. The catalog record.
4. The existing name heuristic for an otherwise unknown model.

Only explicitly supplied flags override lower levels. Unknown models still
default to supporting tools and streaming; unknown vision support defaults to
false.

### Qualitative matching is not numeric identity

The qualitative resolver compares normalized `modelName`, `displayName`,
`deploymentName`, `deployment`, and `name` against catalog IDs, display names,
and legacy `aliases`. Its longest-prefix matching continues to support deployment
suffixes such as `gpt-5.6-sol-eastus`. A numeric version continuation is not a
deployment suffix, and `family` is never a model identity.

Numeric capacity matching must instead use the exact provider model identity
or a first-party `verifiedAliases` entry, with the selected host, protocol, and
version. It must not trust every legacy alias, a user-edited display label,
a family, or a deployment-name prefix.

For example:

- `gpt-5.6` is a verified alias of **Sol**, not Terra or Luna.
- `chat-latest` is verified; `gpt-5.5-instant` branding is not a verified
  callable ID.
- `gemini-3.1-pro` is not a verified synonym for `gemini-3.1-pro-preview`.
- `grok-build-latest` targets **Grok 4.5**, not Build 0.1.
- `grok-voice-latest` currently targets **2.0**, not both voice 1.0 and 2.0.

Unverified legacy aliases remain in `aliases` for compatibility. Their exclusion
from `verifiedAliases` does not establish that a provider rejects them; it means
they are not evidence for numeric capacity.

`gpt-chat-latest` is a logical cross-provider catalog ID, not a universal API
request name. Azure uses `gpt-chat-latest`; native OpenAI uses `chat-latest`.
The native root evidence explicitly names the latter, while Azure capacities
require the version profiles. Keep the selected provider's actual request model
ID; do not send a budget's canonical catalog ID as a replacement API model name.
The cross-provider correspondence does not establish that OpenAI accepts the
literal Azure ID.

### Capability flags

| Flag | Meaning |
|---|---|
| `processesText` / `generatesText` | Accepts text / produces text |
| `processesImages` / `generatesImages` | Accepts images / produces images |
| `processesAudio` / `generatesAudio` | Accepts audio / produces audio |
| `processesVideo` / `generatesVideo` | Accepts video / produces video |
| `processesBinaryFiles` | Accepts uploaded files or binary document payloads |
| `optimizedForCoding` | Documented for coding or agentic software tasks |
| `toolCalling` | Supports function or tool calling |
| `structuredOutput` | Supports constrained structured output |
| `supportsStreaming` | Supports incremental chat response delivery |
| `reasoning` | Performs extended reasoning or thinking |

All flags are required in a catalog record. A capability flag alone does not
prove compatible request parameters, entitlement, or support for every API.

## Token-capacity contract

### Separate quantities and applicability

Root capacity fields describe the **publisher-native specification**, or a
publisher checkpoint for open-weight models. They are not blanket claims about
Azure, Vertex, custom gateways, or sovereign-cloud deployments.

| Field | Meaning |
|---|---|
| `contextWindow` | Shared prompt-plus-generation capacity |
| `inputTokenLimit` | A separately documented maximum input |
| `outputTokenLimit` | Documented maximum generation, not an adjustable default |
| `tokenLimitsApplicability` | `text`, `non-text`, or `unknown` |
| `outputTokenAccounting` | `total_generation`, `visible_only`, or `unknown` for native output-cap semantics |
| `verifiedAliases` | First-party verified identifiers eligible for numeric matching |
| `tokenLimitProfiles` | Host-, protocol-, or exact-version-specific overrides |

Every model explicitly contains all three capacity fields. Each is a positive
integer or `null`, with evidence explaining its disposition. Boolean, fractional,
integral-float, non-finite, string, zero, and negative capacities are rejected by
the offline validator. JSON Schema treats some integral floats as integers, so
the test validator also checks the actual parsed Python type.

Never derive an independent input maximum by subtracting maximum output from
context. Never add independent input and output maxima to invent a shared
window. Independent maxima need not be simultaneously consumable: a request
must satisfy every applicable shared and independent constraint.

Response Length and request output parameters describe the **requested
generation allowance**. They must remain separate from these provider
capacities. A provider can publish shared context without publishing a hard
output maximum; that does not turn an adjustable output default into evidence
of a maximum.

### Per-field evidence

`tokenLimitEvidence` contains an entry for each capacity field. The catalog also
records evidence for `outputTokenAccounting`. Each evidence entry has:

| Key | Meaning |
|---|---|
| `status` | One of the five dispositions below |
| `sourceIds` | Nonempty references to entries in the catalog's public `sources` registry |
| `verifiedAt` | Date the cited evidence was checked |
| `note` | Exact-model interpretation, uncertainty, and relevant conditions |

| Status | Data representation and interpretation |
|---|---|
| `verified` | A documented numeric capacity, or verified accounting semantics |
| `unknown` | `null`; no independent capacity was verified |
| `hosting-dependent` | `null`; the selected host or serving contract must supply the answer |
| `not-applicable` | `null`; the text-generation quantity does not apply to the modality |
| `configuration-only` | `null`; an architectural/configuration value is recorded in the note, not promoted into usable serving capacity |

Source records identify a publisher, title, public HTTPS URL, and verification
date. Mutable checkpoint configurations are pinned to a commit revision.
Historical Claude sources also retain `archivedFrom`, identifying the original
Anthropic-authored page rather than treating an archive as a third-party
specification.

For example, the token-related portion of Terra's native record includes:

```json
{
  "id": "gpt-5.6-terra",
  "contextWindow": 1050000,
  "inputTokenLimit": 922000,
  "outputTokenLimit": 128000,
  "tokenLimitsApplicability": "text",
  "outputTokenAccounting": "total_generation",
  "verifiedAliases": [],
  "tokenLimitEvidence": {
    "contextWindow": {
      "status": "verified",
      "sourceIds": ["openai-spec-gpt-5.6-terra"],
      "verifiedAt": "2026-09-19",
      "note": "The exact Terra specification documents 1,050,000 shared-context tokens."
    },
    "inputTokenLimit": {
      "status": "verified",
      "sourceIds": ["openai-spec-gpt-5.6-terra"],
      "verifiedAt": "2026-09-19",
      "note": "The exact Terra specification independently documents 922,000 maximum input tokens."
    },
    "outputTokenLimit": {
      "status": "verified",
      "sourceIds": ["openai-spec-gpt-5.6-terra"],
      "verifiedAt": "2026-09-19",
      "note": "The exact Terra specification documents 128,000 maximum output tokens."
    },
    "outputTokenAccounting": {
      "status": "verified",
      "sourceIds": ["openai-reasoning"],
      "verifiedAt": "2026-09-19",
      "note": "The generation ceiling includes reasoning and visible output."
    }
  }
}
```

This is a capacity fragment, not a complete catalog record; identity metadata,
qualitative flags, the source registry, and Azure qualifications remain in the
full catalog.

### Conditional profiles

A profile has an `id`, a `provider`, optional `protocol` and `modelVersions`,
the fields it overrides, and evidence for **each overridden field**. Provider
values are `azure`, `openai`, `anthropic`, `google`, `vertex`, `xai`, and
`publisher`. Supported protocol selectors are `chat_completions`, `responses`,
`messages`, and `generate_content`.

The optional profile field `toolReasoningEfforts` is a nonempty, unique list of
verified request effort strings allowed **when function tools are present**.
It requires its own `tokenLimitEvidence` entry. It is a validation constraint,
not a default or permission to change the requested effort. An omitted field
means no additional catalog restriction was verified; the string `"none"`
is an explicit supported setting, not an omitted setting or JSON `null`.

Profile interpretation is deterministic:

1. Match the selected provider and any supplied protocol/exact-version selectors.
2. Apply a generic host profile before more specific matching profiles.
3. Specificity is the number of qualified dimensions: protocol and model version.
4. Omitted fields inherit; **an explicit `null` clears an inherited capacity**.
5. Equally specific profiles must not overlap for the same selection. The
   offline integrity test rejects ambiguity, duplicate IDs, and dangling evidence.

`modelVersions` contains exact versions, never prefix rules or an assumption
that every future release has the newest documented limits.

Profiles can additionally declare `effectiveContextWindow`: a host/protocol
combined ceiling distinct from advertised context. Azure GPT-5.5 Responses has
an **approximately 922,000-token combined ceiling**, while advertised context
remains **1,050,000**. Its evidence preserves the approximation, incomplete
response behavior, and need for a runtime counting/protocol margin. The integer
does not assert an exact all-host capacity.

## Verified coverage and important qualifications

| Publisher | Existing IDs | Scope of recorded evidence |
|---|---:|---|
| OpenAI | 25 | Native limits plus Azure and exact-version profiles |
| Anthropic | 17 | Shared context and ordinary synchronous Messages output |
| Google | 10 | Independent Gemini API limits; Vertex context for nine models |
| Meta | 6 | Exact publisher checkpoints and unresolved CodeLlama configuration |
| Microsoft | 6 | Pinned Phi checkpoints and configuration-only MAI evidence |
| xAI | 11 | Six text contexts, four non-text outputs, one unresolved voice budget |
| **Total** | **75** | Every field has an explicit disposition |

### OpenAI and Azure

- **Sol, Terra, and Luna:** each exact model is verified at **1,050,000 context /
  922,000 input / 128,000 output**. These values are not family guesses.
- **GPT-5 Pro:** native OpenAI output is **272,000**; Azure output is **128,000**.
- **Latest chat:** Azure versions `2026-05-05`, `2026-05-28`, and `2026-06-24`
  have **128,000 / 111,616 / 16,384**. Version `2026-08-06` has
  **400,000 / 272,000 / 128,000**.
- **Unknown Azure latest-chat version:** a generic profile explicitly clears
  all three inherited native capacities. Only an audited version or verified
  deployment override can supply them.
- **Historical Azure chat IDs:** `gpt-5.3-chat`, `gpt-5.2-chat`, `gpt-5.1-chat`,
  and `gpt-5-chat` retain verified historical Azure profiles. Native root fields
  remain hosting-dependent because direct OpenAI uses distinct `*-chat-latest`
  IDs; the catalog does not invent a cross-provider alias.
- Azure-only independent input values are not copied into native OpenAI entries
  whose direct specification only verifies context and output.
- The exact native OpenAI specifications independently publish **272,000 input**
  for GPT-5.4 Mini/Nano, GPT-5.3 Codex, GPT-5.2 Codex, and GPT-5/Codex/Mini/Nano.
  Those entries cite the explicit official Markdown input field; they are not
  context-minus-output calculations. GPT-5.5, GPT-5.4/Pro, GPT-5.2, GPT-5.1 and
  its listed Codex variants, and GPT-5 Pro keep their unverified native input
  fields unknown even when Azure documents an input ceiling.
- Azure GPT-5.6 function tools through Chat Completions require explicit
  `reasoning_effort: none`, or a supported Responses integration. The exact
  Sol, Terra, and Luna records express this as `toolReasoningEfforts: ["none"]`
  in their `azure` / `chat_completions` profiles, with official Azure model and
  reasoning sources. Consumers validate this data rather than hardcoding a
  model-family rule. These profiles retain `total_generation` accounting and
  do not impose the tool-effort condition on direct OpenAI or Responses.
  Their compatible tool-effort rule is not version-gated: legacy saved rows
  with an omitted, null, or empty `modelVersion` still resolve `["none"]` for
  these exact model IDs. This does not relax latest-chat's separate requirement
  for an audited Azure version before supplying its differing capacities.

### Anthropic

Claude context is shared; independent input limits remain `null`. The ordinary
Messages output ceiling includes thinking. Do not reserve that thinking again
or substitute the **300,000-output Message Batches beta** for chat capacity.

Historical snapshots retain their own **32,000**, **64,000**, or **8,192** output
limits with archived first-party evidence. Sonnet 3.7's historical extended-output
beta and Sonnet 4/4.5's conditional hosted 1M context are not promoted into
standard defaults. Retirement notes name the **Claude API**, not every host.

Six historically verified aliases retain their exact archived targets, including
`claude-3-5-sonnet-latest` mapping to the **20241022** snapshot, not 20240620.
Those historical mappings do not assert present availability. Dateless Claude
IDs from generation 4.6 onward are canonical snapshots; no invented dated
aliases are added. Archived context/thinking documentation confirms that
Messages `max_tokens` includes thinking, rather than only the visible summary.

### Gemini API and Vertex

Gemini API input is **1,048,576**, and output is **65,536** for the nine current
or preview entries. Historical Gemini 2.0 Flash output is **8,192**. A separate
native shared-context integer is not inferred from those independent fields.

Vertex profiles record **1,048,576 shared context** and **65,536 maximum output**
for the first nine models, with canonical Google Cloud model-page references.
Gemini 2.0 has no invented shared-context profile and retains its native
**2026-06-01** shutdown evidence. Vertex's **2026-10-20** date for the Gemini 2.5
models is host-scoped; the checked native Gemini API source had no announced
shutdown date for those models.

Google output accounting remains **unknown** in the endpoint-agnostic roots and
the `generate_content` Vertex profiles. The checked thinking guide explicitly
includes thought tokens in **Interactions** `max_output_tokens`; it does not
independently establish equivalent `generateContent` `maxOutputTokens` accounting
or OpenAI-compatible `chat_completions` accounting, nor historical Gemini 2.0
accounting. The generic Models API output-limit description is insufficient
evidence to broaden that statement.

The completed narrow review also checked the exact GenerateContent parameter
reference, native OpenAI-compatibility guide and pinned first-party quickstart,
Vertex inference/parameter/compatibility references, and current and archived
thinking guides. GenerateContent's response-candidate wording does not explicitly
identify whether hidden thoughts consume the cap. Separate usage counters do not
establish which counters it bounds. Qualitative advice about reserving token
output and compatibility parameter aliases likewise do not supply an exact
thinking-inclusion contract. These checked sources are retained in the registry;
the result remains a researched unknown, not evidence that either API excludes
thinking.

This is an evidence limitation, not a claim that `generateContent` behaves
differently. No Interactions protocol or runtime integration is added here.
Capacity-aware consumers must obtain verified selected-endpoint accounting
rather than silently treating these numeric output maxima as total-generation
request reserves.

An operator can explicitly declare an independently verified accounting contract
for the selected model/endpoint and protocol. Such an override is configuration,
not a newly verified native fact: it must leave the catalog's unknown disposition
unchanged, remain isolated from other callers, and be identified as an override
in tests and provenance. An accounting override does not create an undocumented
shared-context capacity.

### Open-weight checkpoints

Llama Scout's **10,485,760**, Maverick's **1,048,576**, and the listed Llama 3.x
models' **131,072** windows come from the exact publisher registry. Phi records
use their own pinned configurations; mini-reasoning no longer cites
mini-instruct as its specification. Microsoft repository revisions were resolved
during implementation, and both the configuration and model card were fetched
at each immutable revision; these pins do not depend on assuming an earlier
mutable `main` read was immutable.

Independent input and hard output maxima remain unknown or hosting-dependent.
Example generation settings do not prove hosted limits.

- CodeLlama's **4,096** configuration value conflicts with the card's 16K
  fine-tuning wording. It stays in a `configuration-only` note, not usable context.
- MAI-DS-R1's **163,840** configuration value likewise lacks a verified supported
  serving-context contract. It does not inherit DeepSeek's hosted limits.

### xAI text, media, and voice

The six exact text-model context windows are preserved. Their hard output maxima
remain unknown: **128,000 is an adjustable API default**, not a maximum.

Responses caps total generation, including reasoning. Chat Completions'
documented cap covers visible output and excludes reasoning/function calls.
Separate profiles preserve that distinction; an OpenAI-compatible parameter
name is not sufficient evidence for total-generation accounting.

Four image/video models have `non-text` applicability and `not-applicable`
text-output limits. Their prompt/context limits remain unknown. Image counts,
video duration, and resolution notes are native media constraints, not token
budgets. Voice context/input/text-output ceilings remain explicitly unknown.

The xAI alias lists record the first-party documentation snapshot on
**2026-09-19**, including documented reasoning/non-reasoning beta mappings,
Build 0.1's code-fast aliases, and dated media snapshots. In particular,
`grok-imagine-image-quality-latest` is verified, while
`grok-imagine-image-latest` and `grok-imagine-video-latest` remain unverified.
Rolling and beta labels are not permanent equivalence claims. Voice latest's
switch to 2.0 is dated **2026-08-05**; 1.0 remains a historical model, not an
alias of current latest. Legacy qualitative `aliases` are unchanged.

## Configuration and usage

The catalog is maintained in the repository, not edited through a catalog
administration page. For a deployment, first establish its actual provider model,
version, and selected protocol. A friendly deployment name alone is not proof
that a published capacity applies.

When a selected endpoint has a verified custom serving contract, keep its
capacity overrides separate from Response Length. Resolve each capacity
independently through the selected model override, endpoint override, and
applicable catalog evidence; a partial override must not hide unrelated fields.
Unknown or configuration-only evidence requires verification, not a copied
family capacity.

Qualitative overrides continue to use a partial `capabilities` map:

```json
{
  "modelName": "corp-llm-v2",
  "capabilities": {
    "processesImages": false,
    "toolCalling": true,
    "supportsStreaming": false
  }
}
```

Callers can continue using `is_vision_capable_model`, `supports_tool_calling`,
`supports_streaming`, and `resolve_model_capabilities` with the selected model
and endpoint records. Capacity consumers additionally need the selected
identity/profile and the actual generation allowance; the catalog does not
replace runtime counting or prove that a deployment is available.

### Runtime budget result

`resolve_model_token_budget(...)` returns a frozen `ModelTokenBudget`. For
example, an explicitly selected Azure Terra Chat Completions deployment resolves
its provider-specific tool constraint along with its capacities:

```python
from functions_model_capabilities import resolve_model_token_budget

budget = resolve_model_token_budget(
    {"modelName": "gpt-5.6-terra"},
    provider="azure",
    protocol="chat_completions",
    request_output_limit=4096,
)
```

The result keeps `context_window`, `input_limit`, `output_limit`,
`effective_context_window`, and `request_output_limit` separate. It also carries
`output_accounting`, the immutable `tool_reasoning_efforts` tuple, applicability,
model/provider/protocol/version identity, and provenance. This example has
`tool_reasoning_efforts == ("none",)`; the caller must validate an explicit
request setting rather than silently supplying or removing it.

Native OpenAI, Azure, and Anthropic profiles use `total_generation` accounting.
xAI Chat Completions retains its `visible_only` override. Google independent
limits and Vertex shared context remain separately scoped; the result does not
invent shared capacity for Gemini 2.0 or infer total-generation accounting from
Interactions-only evidence. With unverified accounting, the shared strict
`ModelTokenBudget.remaining_input()` calculation reports
`model_generation_unbounded` until the selected endpoint has a verified contract.
The old tuple helper remains a compatibility interface, not the complete
contract for new capacity-aware consumers.

Tabular planning has a separate, explicitly labeled conservative legacy policy
for unknown accounting: a **128,000-token input-planning ceiling** and a request
policy no greater than **65,536 tokens**, subject to tighter applicable limits.
Warnings and policy flags identify this fallback, while raw `output_accounting`
remains `unknown`. These are planning controls, not verified provider capacities
or proof of bounded hidden thinking. The policy does not relax errors for
`visible_only` accounting or non-text models.

## Maintenance and validation

For a catalog change:

1. Keep the exact model identity and qualitative compatibility unless a reviewed
   correction requires a behavioral change.
2. Verify each capacity independently against its exact primary source.
3. Record unknowns, configuration-only evidence, host scope, and lifecycle scope.
4. Add source registry entries, verification dates, and pinned revisions where
   applicable. A source ID must resolve both from the model and its evidence.
5. Add verified aliases only with first-party identity evidence.
6. Update the explicit per-ID audit expectations and relevant profile tests.

Run the focused offline suites:

```powershell
python -m pytest -q `
    .\functional_tests\test_model_capability_catalog_resolution.py `
    .\functional_tests\test_model_catalog_token_evidence.py
python .\functional_tests\test_model_capability_catalog_resolution.py
python .\functional_tests\test_model_catalog_token_evidence.py
python -O .\functional_tests\test_model_capability_catalog_resolution.py
python -O .\functional_tests\test_model_catalog_token_evidence.py
```

Coverage includes all 75 dispositions, source integrity, true positive integers,
missing/contradictory evidence, retired snapshots, configuration-only values,
non-text applicability, aliases, conditional profile ambiguity, and evidenced
tool-effort constraints. Real-catalog resolver checks verify the frozen budget
result, exact Azure/protocol scope, and distinct output accounting. The exact
Azure `2026-07-09` model version retains its tool-effort constraint even with
partial model-capacity overrides. `unittest`
assertions propagate failures under both standalone execution and pytest,
including optimized Python; tests do not catch a failure and return `False`.

## Limitations

- A dated specification is not a guarantee of current deployment availability,
  regional entitlement, or identical limits in another host/cloud.
- Historical and unverified aliases are retained only for qualitative
  compatibility, not numeric capacity.
- Approximations, hidden reasoning, and multimodal tokenization still require
  conservative runtime accounting.
- Catalog validation does not itself qualify an agent's selected endpoint,
  API compatibility, retrieval budget, or live provider request.
