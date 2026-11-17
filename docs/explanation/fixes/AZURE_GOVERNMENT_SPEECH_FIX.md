# Azure Government Speech routing and failure reporting (0.261.450)

Fixed in version: **0.261.450**

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
fail explicitly in these clouds. The existing location and resource ID
requirements remain.

Public-cloud managed identity retains the region constructor. Key authentication
continues to use the configured endpoint and subscription key in all clouds.
Token audience selection in `config.py` is unchanged. For Government deployments,
configure `AZURE_ENVIRONMENT=usgovernment`, the resource's Government endpoint
(for example, `https://<resource-name>.cognitiveservices.azure.us`), matching
location such as `usgovvirginia`, resource ID, and identity permissions.

`application/single_app/route_backend_speech.py` uses thread-safe completion and
failure signals. Service-error cancellation and unexpected interruption raise
errors even after partial recognition; an incomplete 120-second recognition wait
raises a timeout. End-of-stream and normal session completion still preserve
recognized text, and true silence still follows the existing no-speech response.
The recognizer is stopped on start/wait failures and its callbacks are disconnected.
The route retains its safe generic HTTP 500 response and temporary-file cleanup.

Diagnostics use the existing `[SPEECH]` tag with application-owned `failure_code`
values `speech_sdk_canceled`, `speech_sdk_interrupted`, and `speech_sdk_timeout`.
They do not contain audio, transcript text, tokens, keys, or provider error details.
Raw cancellation/transcript debug output and route traceback printing are removed
from this path. Fast Transcription remains bypassed for Government/custom clouds.

## Offline validation

`functional_tests/test_government_speech.py` loads real application modules in
fresh offline processes. Native SDK configuration checks cover Government/custom
endpoint retention, authorization-token format, public-cloud region compatibility,
key authentication, and required fields. Simulated recognizer events cover normal
recognition, silence, end-of-stream, cancellation with/without partial text,
interruption, timeout with/without partial text, late failure, startup failure,
safe route responses, cleanup, and cloud-specific Fast Transcription selection.
The logger sanitizer is exercised to verify stable failure codes survive.

Related TTS voice fallback, prosody, and V2 Speech resource ID regressions are
retained. The document-module Cosmos inventory is refreshed and its existing
owner-runtime SDK evidence rerun: the Speech helper changes no storage owner,
import binding, point/query consumer, partition routing, or ETag handling.
The 45 affected representative SDK cases pass. The full inventory gate remains
blocked by 18 pre-existing stale reviews in `route_backend_orchestration.py`;
this change does not approve or alter those unrelated reviews.

Validation uses no live Azure services. Native Speech SDK configuration behavior
is checked with both the locally installed 1.47.0 and application's pinned 1.48.2.
This does not prove service availability, RBAC, network access, or successful
recognition/synthesis against a deployed Government resource; those still require
an authorized environment-specific smoke test.
