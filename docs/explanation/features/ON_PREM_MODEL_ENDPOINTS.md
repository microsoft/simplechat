# On-Premises Custom Model Endpoints

## Overview

SimpleChat can reach a model API running inside your own network — an on-premises
gateway, a self-hosted vLLM or LiteLLM deployment, or an air-gapped inference
appliance — through a Custom model endpoint.

That path exists because not every deployment can send prompts to a public cloud
API. It is off by default, because pointing an application at arbitrary internal
addresses is exactly the shape of a server-side request forgery, so each relaxation
is a deliberate administrator decision.

**Implemented in version: 0.261.019**

## What was blocking on-premises use

The gate for private hosts existed but did not permit the two address forms
on-premises deployments actually use:

| Endpoint | Before | After (gate enabled) |
|---|---|---|
| `https://10.20.30.40/v1` | Rejected | Accepted |
| `https://10.20.30.40:8443/v1` | Rejected | Accepted |
| `https://llm-gateway/v1` | Rejected | Accepted |
| `https://llm.corp.internal/v1` | Rejected | Accepted |
| `http://llm.corp.example.com/v1` | Rejected | Accepted with the second gate |

Both rejections also used the same message — that the URL had to be a fully
qualified domain name "not an IP address" — which was simply wrong for a short
host name, and did not say which setting would allow it.

Even once an address was accepted, TLS made the connection impossible. The
outbound transport trusts only certifi's public roots and deliberately ignores
`SSL_CERT_FILE` and `SSL_CERT_DIR`, so a gateway presenting an internally issued
certificate could never be validated.

## Settings

| Setting | Default | Effect |
|---|---|---|
| `allow_private_custom_model_endpoints` | off | Permits IP addresses, short host names, and hosts resolving to private ranges |
| `allow_insecure_custom_model_endpoints` | off | Permits plaintext `http://`. Requires the private-hosts gate as well |
| `custom_model_endpoint_ca_bundle_path` | empty | Path to a PEM bundle used to validate Custom endpoint certificates |

All three are on the **Model Endpoints** admin tab.

## What stays blocked

Enabling every gate does not disable the outbound protections. These are always
refused, because they are the targets that make request forgery useful:

- Loopback addresses, including `127.0.0.1` and `localhost`
- Link-local addresses
- Cloud instance metadata endpoints — `169.254.169.254`, `168.63.129.16`,
  `metadata.google.internal`, `metadata.azure.com`, `instance-data.ec2.internal`
- Multicast, reserved, and unspecified addresses
- URLs carrying embedded credentials, a query string, or a fragment
- UNIX domain sockets
- HTTP redirects

Address validation also runs again at connection time, on the addresses the
connection actually uses, so a DNS answer that changes between configuration and
request cannot redirect the connection.

## Trusting an internal certificate authority

Set **Custom endpoint CA bundle path** to a PEM file readable by the application:

```
/etc/ssl/certs/internal-ca.pem
```

Two properties are deliberate:

- **Ambient environment variables are still ignored.** Setting `SSL_CERT_FILE` in
  the environment does not change what SimpleChat trusts. Widening trust is a
  configuration decision, recorded in settings, not an ambient one.
- **A bundle that cannot be loaded is an error.** A missing or unreadable file
  fails the request rather than silently falling back to public roots, so a
  typo cannot quietly downgrade what is being validated.

## Plaintext HTTP

`allow_insecure_custom_model_endpoints` permits `http://` endpoints, and requires
the private-hosts gate as well.

Prompts, responses, and the API key all travel unencrypted. This exists for
isolated networks where TLS genuinely cannot be terminated; prefer the CA bundle
setting and keep TLS wherever it is possible.

## Configuring before connectivity exists

Saving an endpoint no longer requires the host name to resolve from the
application tier. Configuration can be seeded, scripted, or restored from backup
before the network path exists.

Only name resolution is tolerated at save time. A policy violation — a blocked
address, a bad scheme, embedded credentials — is still refused when saving, and
the connection-time check is unchanged, so nothing is skipped.

## Testing and validation

`functional_tests/test_custom_model_endpoint_on_prem.py` covers:

- default-deny behaviour with the gate off, across five address forms;
- acceptance of IP literals, ports, short host names, and `.internal` names with
  the gate on;
- plaintext HTTP requiring its own second gate rather than riding on the first;
- loopback, link-local, and cloud metadata staying blocked with every gate on;
- the short-host-name rejection message no longer claiming the URL is an IP
  address, and naming the setting that would allow it;
- the CA bundle being honoured explicitly, ambient environment variables still
  being ignored, and a missing bundle failing rather than falling back;
- save-time tolerance of an unresolvable name, while a policy violation is still
  refused and reported as a policy violation rather than a resolution failure.

## Known limitations

- **Egress proxies are not supported.** This is deliberate rather than
  incomplete. With an HTTP proxy the client issues `CONNECT host:443` and the
  *proxy* resolves DNS, so connection-time address pinning would provide no
  protection at all. Supporting a proxy means replacing that control with an
  administrator-managed host allowlist, which is a security decision rather than
  a plumbing change, so the proxy is refused instead of silently unprotected.
- Client certificate authentication (mTLS) to the endpoint is not yet supported;
  the CA bundle setting validates the server, not the client.
