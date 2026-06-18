# Deploy External Presidio DLP

SimpleChat can use Option C for richer DLP detection: call an external Presidio Analyzer-compatible HTTP endpoint from the server side while keeping Presidio out of the SimpleChat application image. SimpleChat does not embed Presidio packages, models, or recognizers; it sends text to an administrator-managed analyzer endpoint, receives spans, and applies its existing monitor, redact, or block behavior locally.

## Recommended Production Shape

Run the Presidio Analyzer-compatible service as sensitive internal infrastructure. The analyzer receives raw text before SimpleChat redacts it, so production deployments need both network and application controls.

Required controls:

- Use a private network path between SimpleChat and the analyzer.
- Require an API key header, usually `X-DLP-API-Key`, at a proxy, wrapper, gateway, or service boundary in front of the analyzer.
- Use HTTPS for every non-local endpoint.
- Do not expose a public unauthenticated Presidio Analyzer endpoint.
- Do not log raw request text, response bodies, snippets, or matched values in SimpleChat, the analyzer wrapper, reverse proxies, or platform diagnostics.
- Keep fail-closed scanner behavior enabled for protected upload and web-search paths when policy requires blocking on scanner errors.

## SimpleChat Settings

Configure these values in Admin Settings > Data Loss Prevention:

- Default Engine: `External Presidio Analyzer endpoint`
- Analyzer Endpoint: `https://<internal-presidio-host>/analyze`
- Allowed Private Hosts: `<internal-presidio-host>`
- Auth Header: `X-DLP-API-Key`
- Secret Env Var: `PRESIDIO_DLP_API_KEY`
- Timeout Seconds: `5`
- Score Threshold: `0.5`
- Entities: `CREDIT_CARD, EMAIL_ADDRESS, PHONE_NUMBER, US_SSN`

SimpleChat stores only the environment variable name in its admin settings, such as `PRESIDIO_DLP_API_KEY`. The API key value itself must live in the SimpleChat App Service application settings or in a Key Vault reference used by that App Service setting. Do not paste raw API key values into SimpleChat admin settings or Cosmos-backed configuration. Secret environment variable names are intentionally limited to blank, `PRESIDIO_DLP_API_KEY`, or names beginning with `DLP_PRESIDIO_`.

Endpoint URLs must use strict URL hygiene. Do not include usernames, passwords, fragments, or credential-like query parameters such as `key`, `api_key`, `secret`, `token`, `password`, `connection`, or `sig`. Public HTTPS endpoints are accepted after these checks. Private, loopback, link-local, or internal-style hosts must also appear in `Allowed Private Hosts` as comma- or newline-separated hostnames or IP addresses. SimpleChat disables HTTP redirects when calling the analyzer and treats redirect responses as analyzer errors.

## Local Docker Smoke Test

Run the stock Presidio Analyzer container locally:

```bash
docker run --rm -p 5002:3000 mcr.microsoft.com/presidio-analyzer:latest
```

Configure SimpleChat for a smoke test:

```text
Default Engine: External Presidio Analyzer endpoint
Analyzer Endpoint: http://localhost:5002/analyze
Allowed Private Hosts: localhost
Auth Header: X-DLP-API-Key
Secret Env Var: PRESIDIO_DLP_API_KEY
Score Threshold: 0.5
Entities: CREDIT_CARD, EMAIL_ADDRESS, PHONE_NUMBER, US_SSN
```

The stock local container does not require an API key. You can leave `PRESIDIO_DLP_API_KEY` unset for this local smoke path, or set it to any placeholder value while testing the SimpleChat configuration surface. Production deployments should add an authenticated proxy, wrapper, or service boundary before enabling the endpoint for protected traffic.

Test with harmless synthetic content such as `a@example.com`. In `redact` mode, SimpleChat should call the analyzer, receive entity spans, and replace the detected value before web-search egress or upload indexing. In `block` mode, the same finding should prevent the protected action.

## Separate Azure App Service

Deploy the Presidio Analyzer-compatible container as a separate Linux Web App for Containers. Restrict ingress with private endpoints, virtual network integration, and access restrictions so only the SimpleChat environment can reach it. Add the analyzer hostname or private IP to SimpleChat's `Allowed Private Hosts` setting. If the analyzer endpoint is reachable beyond localhost, place an API-key-validating proxy or wrapper in front of it and configure SimpleChat to send the configured auth header.

Use this shape when you want independent deployment and operational ownership for the analyzer while still running on App Service. Store the API key value as a SimpleChat App Service setting named by the SimpleChat admin setting, for example `PRESIDIO_DLP_API_KEY`, preferably backed by a Key Vault reference.

## App Service Sidecar

For deployments using App Service sidecar support, run the analyzer as a sidecar container next to SimpleChat and configure SimpleChat to call the sidecar endpoint over the local or private container network. Add the sidecar hostname, loopback host, or private IP to `Allowed Private Hosts`. This keeps Presidio dependencies out of the SimpleChat image while scaling the analyzer with the SimpleChat App Service instance count.

Even with a sidecar, avoid raw text logging and keep the analyzer endpoint unreachable from the public internet. If the sidecar is fronted by a local wrapper, validate the `X-DLP-API-Key` or equivalent header there.

## Azure Container Apps

For independent scaling, deploy the analyzer as an internal Azure Container Apps service. Configure SimpleChat to reach the internal ingress URL over private networking, add that internal host to `Allowed Private Hosts`, and require the API key header at the Container Apps ingress, gateway, or wrapper service.

This shape works well when analyzer CPU or model requirements scale differently from SimpleChat. Store the API key value in the SimpleChat App Service setting or Key Vault reference named by SimpleChat's `Secret Env Var` setting, not in the SimpleChat admin configuration.

## Security Notes

The analyzer receives raw user text, extracted document text, and selected metadata before SimpleChat applies redaction. Treat the endpoint as sensitive infrastructure with the same care as an internal document-processing service.

Do not log raw request bodies, response bodies, matched values, or analyzer explanations. SimpleChat's DLP telemetry and stored metadata should remain counts-only. If you add a gateway, proxy, or wrapper around Presidio Analyzer, disable body logging and scrub diagnostics before sending them to centralized logs.

Use `presidio_endpoint` only when the endpoint is private, authenticated, and operated by the same trust boundary that is allowed to process the source text. Keep regex DLP as the lightweight default and fallback path when the external analyzer is not configured.
