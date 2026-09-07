# Model Capability Catalog

## Overview

SimpleChat needs to know what each model can do in order to decide whether to offer
it as a vision model, whether it can be given tools, whether it can stream, and
whether it uses reasoning-style request parameters.

Those answers used to be derived by pattern-matching the model's name. That works
for well-known Azure OpenAI deployments and fails for everything else. A model
reached through a Custom endpoint — an on-premises gateway, a customer's own
fine-tune, or a provider SimpleChat has not shipped support for — was named
whatever the customer chose to name it, so every capability question silently
returned the wrong answer.

The model capability catalog makes those answers data-driven, and lets an
administrator override them per model or per endpoint.

**Implemented in version: 0.261.014**

## Dependencies

- `jsonschema` (already a SimpleChat dependency) for catalog validation in tests.
- No new runtime dependencies. The resolver uses only the standard library so it
  can sit below the settings, logging, and route layers without import cycles.

## Architecture

### Resolution order

Every capability question resolves through this chain, stopping at the first
source that gives a definite answer:

1. **Per-model override** — a `capabilities` map on the model record.
2. **Endpoint override** — a `capabilities` map on the endpoint record.
3. **Catalog entry** — the matching record in `model_capabilities.json`.
4. **Name heuristic** — the original pattern matching, kept as a last resort so
   models absent from the catalog behave exactly as they did before.

This ordering means the catalog can be wrong or incomplete without blocking an
administrator, and an unknown model degrades to previous behaviour rather than to
"no capabilities".

### Catalog matching

A model record is matched to a catalog record by normalized identifier. The
model's `modelName`, `displayName`, `deploymentName`, `deployment`, and `name`
fields are each compared against the catalog record's `id`, `displayName`, and
`aliases`.

Two rules keep matching honest:

**`family` is never used for matching.** It is a grouping attribute, and members
of one family disagree on capabilities. The `phi-4` family contains both the
multimodal and the text-only Phi models; each `gpt-5.x` family contains a
non-vision `-chat` member. Matching on family would let a model inherit a
sibling's capabilities.

**A longer identifier prefix wins, and a version continuation is not a prefix
match.** A deployment named `gpt-5.6-sol-eastus` resolves to `gpt-5.6-sol`, and
`gpt-5.1-chat-v2` resolves to `gpt-5.1-chat` rather than the shorter and
differently capable `gpt-5.1`. Because identifier normalization turns `.` into
`-`, `gpt-5.3` would otherwise look like a variant of `gpt-5`; a remainder that
starts with a digit is treated as a different version, not a variant, so that
match is rejected.

## Configuration

### Catalog file

`application/single_app/static/json/model_capabilities.json`

```json
{
  "schemaVersion": 2,
  "capabilityFields": { "...": "description of each flag" },
  "models": [
    {
      "id": "gemini-3.8-flash",
      "provider": "google",
      "displayName": "Gemini 3.8 Flash",
      "aliases": [],
      "family": "gemini-3.8",
      "lifecycle": "current",
      "releaseDate": null,
      "capabilities": {
        "processesText": true,
        "generatesText": true,
        "processesImages": true,
        "generatesImages": false,
        "processesAudio": true,
        "generatesAudio": false,
        "processesVideo": true,
        "generatesVideo": false,
        "processesBinaryFiles": true,
        "optimizedForCoding": true,
        "toolCalling": true,
        "structuredOutput": true,
        "supportsStreaming": true,
        "reasoning": true
      },
      "notes": ["..."],
      "sourceIds": ["google-gemini-api"]
    }
  ]
}
```

The catalog is validated against
`application/single_app/static/json/schemas/model_capabilities.schema.json`.
Every capability flag is required on every record, so a model can never be
silently missing an answer.

### Capability flags

| Flag | Meaning |
|---|---|
| `processesText` / `generatesText` | Accepts text input / produces text output |
| `processesImages` / `generatesImages` | Accepts image input / produces image output |
| `processesAudio` / `generatesAudio` | Accepts audio input / produces audio output |
| `processesVideo` / `generatesVideo` | Accepts video input / produces video output |
| `processesBinaryFiles` | Accepts uploaded files or binary document payloads |
| `optimizedForCoding` | Documented or positioned for coding and agentic software tasks |
| `toolCalling` | Supports function/tool calling or the provider equivalent |
| `structuredOutput` | Supports JSON-schema or equivalent constrained output |
| `supportsStreaming` | Supports incremental token streaming for chat responses |
| `reasoning` | Performs extended reasoning or thinking before responding |

### Overriding a capability

To describe a model the catalog does not know about, add a `capabilities` map to
the model record on the endpoint. Only the flags you specify are overridden;
everything else continues to resolve through the chain.

```json
{
  "id": "corp-llm",
  "modelName": "corp-llm-v2",
  "enabled": true,
  "capabilities": {
    "processesImages": false,
    "toolCalling": true,
    "supportsStreaming": false
  }
}
```

An endpoint-level `capabilities` map applies the same way to every model on that
endpoint, and is outranked by a per-model map.

## Usage

```python
from functions_model_capabilities import (
    is_vision_capable_model,
    is_reasoning_model,
    supports_streaming,
    supports_tool_calling,
    resolve_model_capabilities,
    resolve_model_output_token_limit,
)

is_vision_capable_model(model_record, endpoint_record)
supports_streaming(model_record, endpoint_record)      # unknown models default to True
supports_tool_calling(model_record, endpoint_record)   # unknown models default to True
resolve_model_capabilities(model_record, endpoint_record)  # every flag at once
```

`supports_streaming` and `supports_tool_calling` default to `True` for unknown
models, so an undescribed model is not needlessly downgraded. `is_vision_capable_model`
defaults to `False`, matching the previous behaviour of the vision model selector.

## Maintaining the catalog

The catalog is a maintained JSON file rather than an admin-managed surface. To add
a model, add a record and run the coverage test. There is deliberately no admin UI
for it yet; administrators who need a one-off answer use the per-model override
above instead.

Google coverage was added in this version and includes the generally available
Gemini chat tiers that expose `generateContent` and `streamGenerateContent`.

## Testing and validation

`functional_tests/test_model_capability_catalog_resolution.py` covers:

- the shipped catalog validating against its JSON schema, with unique model ids;
- family isolation — every member of a family whose members disagree on vision
  resolving to its own value, and a bare family name matching no specific model;
- longest-prefix matching, including the version-continuation rejection;
- override precedence for per-model and endpoint-level overrides;
- heuristic fallback for models absent from the catalog;
- Google models resolving from the catalog rather than the name heuristics.

## Known limitations

- The catalog carries no token-limit fields yet. `resolve_model_token_limits`
  reads `inputTokenLimit` and `outputTokenLimit` when present and returns `None`
  otherwise, so callers must supply their own default.
- `reasoning` records whether a model performs extended reasoning. It is
  deliberately not yet wired to the request-parameter switch that chooses between
  `max_tokens` and `max_completion_tokens`, because that choice depends on the
  wire protocol rather than the model.
- Capability overrides are read from the endpoint and model records but are not
  yet editable in the Admin Settings endpoint editor.
