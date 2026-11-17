# Azure Government Speech routing and failure reporting (0.261.065)

Fixed in version: **0.261.065**

Tracking issue: [#1946](https://github.com/microsoft/simplechat/issues/1946).
Application version: `application/single_app/config.py`.

## Issue and root cause

Managed-identity text-to-speech configuration previously used only the configured
region and ignored the endpoint. The Speech SDK region constructor does not
retain the resource-specific Government endpoint. This affects the shared
configuration used for voice discovery and synthesis. Microsoft requires
[endpoint-based SDK construction in sovereign clouds](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/sovereign-clouds).

Separately, chat Speech SDK recognition marked a canceled session complete without
propagating service errors. Failed sessions could appear to be silence or return
only the text recognized before the failure. Reaching the recognition deadline
also returned whatever partial results were available.

These are code-level findings, not a confirmed diagnosis of a customer's incident.
No customer logs, credentials, deployed version, authentication mode, or failing
workflow were available.

## Changes and compatibility

`application/single_app/functions_documents.py` constructs managed-identity
synthesis configuration from the supplied endpoint for `AZURE_ENVIRONMENT` values
`usgovernment` and `custom`. It then assigns the existing
`aad#<resource-id>#<access-token>` authorization value, because the SDK rejects
passing `auth_token` together with `endpoint` in its constructor. Missing endpoints
fail explicitly in these clouds. Existing location and resource ID requirements
remain. Public-cloud managed identity retains the region constructor. Key
authentication continues to use the endpoint and subscription key in all clouds.
Token audience selection in `config.py` is unchanged.

`application/single_app/route_backend_speech.py` retains main's inline SDK
transcription path, with thread-safe completion and failure signals. Service-error
cancellation and unexpected interruption raise errors even after partial
recognition; an incomplete 120-second recognition wait raises a timeout.
End-of-stream and normal completion preserve recognized text; true silence keeps
the existing no-speech response. The recognizer is stopped on start/wait failures
and callbacks are disconnected. The route returns a generic HTTP 500 response
instead of raw exceptions, and retains temporary-file cleanup.

Diagnostics use the existing `[SPEECH]` tag with application-owned reason values
`speech_sdk_canceled`, `speech_sdk_interrupted`, and `speech_sdk_timeout`.
Main's logger retains these under its existing allowlisted `reason` field;
Development's newer `failure_code` sanitizer support is not imported.
No audio, transcript text, tokens, keys, or provider error details are logged by
the modified cancellation/error path. Raw cancellation/transcript debug output
and route traceback printing are removed.

This is a narrow port of Development commit
`467921145f593b8704618e02fc8912e0a6528211`, not a Development merge.
Main's chat dictation remains SDK-only in all clouds; no Fast Transcription
selection behavior is introduced. Main has no Cosmos response-boundary inventory
machinery, and the fix changes no Cosmos ownership or response handling.

## Validation

`functional_tests/test_government_speech.py` loads real application modules in
fresh offline processes. Native SDK configuration checks cover Government/custom
endpoint retention, authorization-token format, public-cloud region compatibility,
key authentication, and required fields. Simulated recognizer events exercise
the real route for normal recognition, silence, end-of-stream, cancellation
with/without partial text, interruption, timeout with/without partial text,
late failure, startup failure, safe responses, and resource cleanup.
The logger sanitizer verifies that stable reason codes survive.

The two fresh-process Speech regression probes pass with native Speech SDK
1.47.0. Swagger validation, all 12 route-policy checks, Python compilation,
whitespace validation, and all 13 documentation coverage/quality checks pass.
The broader audio fallback suite has six passing tests and two existing failures:
its exact application/deployer version assertions expect `0.250.011` and
`1.0.21`, respectively. Both failures also reproduce against unchanged main
(`0.261.064` / `1.0.32`); this Speech fix does not alter those unrelated tests.

Validation uses no live Azure services. Offline checks cannot establish resource
availability, RBAC, network access, or successful recognition/synthesis against
a deployed Government resource; those require an authorized deployment-specific
smoke test. No Azure deployment or merge is part of this fix.
