# GenAI.mil Custom Model Profile

## Overview and dependencies

Fixed/Implemented in version: **0.261.052**, tracked in
`application/single_app/config.py`.

The named **GenAI.mil** Custom profile uses the existing protected
OpenAI-compatible Chat Completions adapter. It does not introduce a new wire
protocol or infer support from a model's vendor name.

The implementation follows the user-supplied API/Swagger contract recorded in
[the routing specification](./CUSTOM_ENDPOINTS_PER_MODEL_ROUTING_SPEC.md#genaimil-provider-profile).
Its referenced portal documentation has not been live-verified here. Local mock
validation is **not** service certification or authorization to send data.

## Contract and safety

- Default base: `https://api.genai.mil/v1`.
- Inference: `POST /v1/chat/completions`, streamed or non-streamed.
- Discovery: protected backend `GET /v1/models`; credentials never go to a
  browser-side discovery request.
- Authentication: scoped key using `Authorization: Bearer`. Azure identity and
  OAuth2 are not GenAI.mil profile authentication mechanisms.
- Wire fields: `model`, `messages`, optional `temperature`, `max_tokens`, and
  `stream`. SDK generation ceilings are translated to `max_tokens`; unrelated
  SDK defaults are not forwarded.
- Text system/user/assistant messages only. Tools, function calling, vision,
  audio, structured output, Messages, and Responses are rejected. Catalog or
  user capability overrides cannot opt them in.
- Exact discovered model IDs remain case-sensitive. Manual entry is available;
  catalog names do not prove a key can access a model.
- Changing a configured API origin requires explicit destination approval and
  freshly entered credentials. A stored key is never silently reused at another
  origin. The same scope, governance, Key Vault, DNS pinning, redirect, and TLS
  controls continue to apply.
- `usage: null` stays unavailable (`token_usage: null`), not measured zero.
  Real reported zero usage remains distinguishable.

## Error handling and costs

401 requests user action to unlock/review the key using the fixed approved
portal link. Provider-supplied unlock URLs are never fetched or displayed.
403 means model permission denied, 404 unavailable/not enabled, 429 rate limited,
and 502 upstream failure.

Automatic SDK retries are disabled for this profile. Numeric `Retry-After` is
reported to the user; there is no unbounded backoff or replay of partially
consumed streams. Async cancellation is preserved and owned streams can be
closed. Provider bodies and echoed keys are excluded from GenAI.mil diagnostic
logs; safe status/type and correlation references remain available.

Requests and live connection tests can incur provider token costs. Use approved
synthetic content for initial acceptance.

## Configuration workflow

Choose **Custom**, then **Custom profile -> GenAI.mil** in a global, personal,
or group endpoint editor. A blank API base receives the default; existing URLs
and entered model identifiers are not overwritten.

Enter the scoped key through the existing secret flow. Use **Fetch Models** to
load the permitted inventory or add a model manually. Each row uses OpenAI
Chat Completions. Preview, save, and test a nonproduction endpoint before
explicitly enabling it. Global changes also require the main settings save.

For a different approved HTTPS origin, re-enter the key and select the origin
approval checkbox. Product support does not establish approval for that host,
data classification, or operating environment.

## API, implementation, and validation

Uses the existing scoped fetch/test/save routes:
`/api/models/fetch`, `/api/user/models/fetch`, `/api/group/models/fetch`, and
their existing test-model/model-endpoint counterparts.

Contract/approval policy: `model_endpoint_profiles.py`. Discovery:
`functions_genai_mil.py`. Runtime/stream handling:
`functions_model_endpoint_runtime.py` and `model_endpoint_clients.py`.
Nullable usage: `model_endpoint_usage.py`.

Tests: `functional_tests/test_genai_mil_profile.py`,
`functional_tests/test_model_ca_bundle_routes_integration.py`, and the
GenAI.mil cases in `ui_tests/test_model_endpoint_capacity_editor.py`.

Local validation uses mocked external HTTP/storage and actual adapters,
authorization boundaries, and browser assets. An authorized tester still needs
to verify live key lifecycle, available models, deployment networking, and
service responses. No agents are opted into the new per-model routing.
