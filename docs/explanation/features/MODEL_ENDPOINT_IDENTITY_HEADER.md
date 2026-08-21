# Model Endpoint Identity Header

## Overview

Implemented in version: **0.250.203**

The Model Endpoint Identity Header feature lets admins send a stable, non-reversible user identity key with model endpoint requests. This is intended for Azure API Management (APIM) counters, quota policies, routing policies, and similar backend controls that need a consistent per-user key without exposing raw user identifiers.

## Dependencies

- Admin Settings > AI Models configuration
- Model endpoint runtime helpers
- Azure OpenAI/OpenAI-compatible endpoint clients
- Optional APIM or custom backend policy that reads the configured header

## Technical Specifications

### Settings

Global settings:

- `model_endpoint_identity_header_enabled`
- `model_endpoint_identity_header_name`
- `model_endpoint_identity_header_value_type`
- `model_endpoint_identity_header_hmac_secret`

Per-endpoint override:

```json
{
  "identity_header": {
    "mode": "inherit",
    "header_name": "",
    "value_type": ""
  }
}
```

Supported modes:

- `inherit`
- `enabled`
- `disabled`

Supported identity values:

- `user_oid`
- `user_oid_tenant_id`
- `user_upn`
- `user_upn_tenant_id`

The selected identity string is normalized and HMAC-SHA256 hashed before being added to the outbound model request header.

### Runtime Coverage

The header is applied to configured model endpoint calls and legacy GPT/APIM model calls used by chat, workflows, metadata extraction, conversation export summaries, document summarization, agent instruction drafting, and Smart HTTP large-content summarization.

### Header Guardrails

Header names are validated before use. Reserved authentication and protocol headers such as `authorization`, `api-key`, `x-api-key`, `ocp-apim-subscription-key`, `content-type`, and `host` are rejected so the identity header cannot override required service credentials or transport metadata.

## Usage Instructions

1. Open Admin Settings.
2. Go to AI Models > Model Endpoints.
3. Enable **Model Endpoint Identity Header**.
4. Choose a safe header name, such as `x-simplechat-identity-key`.
5. Choose the identity value used to derive the HMAC key.
6. Optionally edit individual model endpoints and set an Identity Header Override.
7. Configure APIM or backend policy logic to read the selected header.

If a background or workflow call has an owning user id, SimpleChat uses that owner identity. If the selected identity fields are unavailable, the header is omitted for that request.

## Testing and Validation

Functional coverage:

- `functional_tests/test_model_endpoint_identity_header.py`

UI coverage:

- `ui_tests/test_model_endpoint_request_uses_endpoint_id.py`

Validation confirms:

- Stable HMAC output for the same normalized identity.
- Raw UPN/OID/tenant values are not sent in the header value.
- Missing required identity fields omit the header.
- Global disablement and endpoint-level disablement omit the header.
- Endpoint-level enablement and identity value overrides work.
- Unsafe header names are rejected.
