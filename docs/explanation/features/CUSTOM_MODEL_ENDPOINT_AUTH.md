# Custom Model Endpoint Authentication

## Overview

A Custom model endpoint has to authenticate to whatever it is pointed at. The
first implementation supported exactly one scheme — an API key, sent in whichever
header the built-in providers happened to use — which covers OpenAI and Anthropic
and nothing else.

That left three common cases unreachable: a gateway that reads the key from a
different header, a corporate gateway that issues short-lived OAuth2 tokens, and
an appliance that requires a client certificate.

**Implemented in version: 0.261.017**

## Schemes

| Scheme | `auth.type` | Use it for |
|---|---|---|
| API key | `api_key` | Any provider or gateway that reads a static key from a header |
| Bearer token | `bearer` | A long-lived token issued out of band |
| OAuth2 client credentials | `oauth2_client_credentials` | A gateway that issues short-lived tokens |

mTLS is deliberately **not** a scheme. A client certificate combines with any of
the above, so it is configured on the connection rather than the auth block.

## API key

The header name and value prefix are both configurable, which is what lets one
scheme cover every convention:

| Provider | Header | Prefix | Result |
|---|---|---|---|
| OpenAI | `Authorization` | `Bearer` | `Authorization: Bearer sk-...` |
| Anthropic | `x-api-key` | none | `x-api-key: sk-ant-...` |
| Google | `x-goog-api-key` | none | `x-goog-api-key: AIza...` |
| Custom gateway | anything | anything | `X-Corp-Key: Token abc123` |

Each registered provider supplies its own default, so nothing needs configuring
for the common case. Override `auth.api_key_header` and `auth.api_key_prefix`
only when a gateway differs.

An override that names a header but no prefix means exactly that — the provider's
default prefix is not silently reapplied.

## Bearer token

```json
{ "type": "bearer", "bearer_token": "..." }
```

Sent as `Authorization: Bearer <token>`.

## OAuth2 client credentials

```json
{
  "type": "oauth2_client_credentials",
  "token_url": "https://auth.example.com/oauth2/token",
  "client_id": "...",
  "client_secret": "...",
  "scope": "inference.read"
}
```

Behaviour worth knowing:

- **Tokens are cached** per token URL, client ID, and scope, and refreshed 60
  seconds before expiry so a token cannot lapse part-way through a request. A
  response without `expires_in` is treated as one hour.
- **The token endpoint is policy checked.** It is a different host from the
  inference endpoint, so it is validated against the same outbound rules. A token
  URL pointing at a cloud metadata address is refused, exactly as an inference
  endpoint would be. Without this, the token URL would be an unchecked outbound
  request target.
- **The token endpoint is fetched with an ordinary client**, not the no-redirect
  pinned transport used for inference, because token endpoints commonly redirect.
- **Failures are sanitized.** A token endpoint's error body frequently echoes the
  client ID or secret, so the browser sees a generic message with a correlation
  id while the real response is recorded server-side with credentials redacted.

## mTLS client certificates

Set these on the endpoint's `connection`:

```json
{
  "client_cert_path": "/etc/ssl/certs/client.pem",
  "client_key_path": "/etc/ssl/private/client.key"
}
```

A single combined PEM may be supplied through `client_cert_path` alone.

**Certificates are referenced by path, never by value.** A private key pasted into
a settings field would be written to the configuration database and replicated
wherever that database goes. Mounting the key into the deployment and naming its
path keeps the key material out of application storage entirely.

A certificate that cannot be loaded fails the request rather than silently
continuing without one.

## What has not changed

- Custom endpoints still refuse managed identity and service principal
  authentication; those are for Azure-hosted providers.
- The outbound protections are unchanged. Every scheme runs over the same
  validated-DNS, no-redirect transport described in the on-premises documentation.

## Testing and validation

`functional_tests/test_custom_model_endpoint_auth.py` covers:

- API key header customization across four conventions, plus the per-provider
  defaults declared by the registry;
- bearer and API key credential resolution, including which schemes need an
  explicit header and which ride on the SDK's own credential argument;
- OAuth2 tokens being fetched once, served from cache on the second call, and
  refetched after the cache is cleared, with the request payload asserted;
- a failing token endpoint leaking neither its error body nor the client details,
  while still offering a correlation id;
- a token endpoint pointing at a cloud metadata address being refused;
- unsupported and incomplete auth configurations being rejected;
- mTLS certificates resolving by path only, with the module asserted to offer no
  way to supply key material inline.

## Known limitations

- OAuth2 supports the client credentials grant only. Authorization code and
  on-behalf-of flows are not implemented.
- The token cache is per process. A multi-worker deployment fetches one token per
  worker, which is correct but not maximally efficient.
- Client certificate paths are not yet editable in the endpoint editor UI; they
  are set on the endpoint's connection record.
