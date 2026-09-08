# Shared AI Connections Framework (v0.261.102)

## Overview

AI Connections reuses the existing `model_endpoints` registry for chat and image
generation. Administrators configure a resource and its authentication once, publish
appropriate models, and choose a separate default for each task. An image-only resource
can remain separate from the chat resource without needing a second endpoint manager.

Implemented in version: **0.261.102**. Application versioning remains in
`application/single_app/config.py`.

Associated issue: [#1436 — Unify AI connections and fix GPT image generation](https://github.com/microsoft/simplechat/issues/1436).

**Dependencies:** the existing model catalog and endpoint normalization, application
settings cache and Cosmos DB settings document, scoped Key Vault helpers when secret
storage is enabled, and operation-specific clients for an existing supported deployment.
Connection discovery and inference require their respective Azure permissions.

Only `chat` and `image_generation` are registered product capabilities in this release.
Embeddings, transcription, speech, computer use, and other integrations are deferred;
their existing configuration is neither migrated nor replaced. No provider family or
unfinished capability control is added.

## Architecture and persisted data

| Layer | Responsibility | Contract |
| --- | --- | --- |
| Connection | Resource address, provider, authentication, identity-header policy, and transport options | Existing `model_endpoints` records and stable connection IDs |
| Model | Deployment identity, technical support, enabled state, and publication policy | Models remain inside their owning connection; equal deployment names on different connections are distinct |
| Capability definition | Required support, feature gate, selection key, and supported operation routes | `CapabilityDefinition` in `functions_ai_connections.py` |
| Binding | Resolve an authorized stored reference to one connection and model | Server-only `ModelBinding`; no connection data is supplied by the picker |
| Client adapter | Build the appropriate client and request for one operation | Capability client-factory registry, rather than a universal inference payload |

Defaults are references, not copies of endpoints or credentials:

```json
{
  "endpoint_id": "creative-connection-id",
  "model_id": "illustration-model-id",
  "provider": "aoai"
}
```

Chat keeps `default_model_selection`. Images use
`image_generation_model_selection`. Resolving either reference finds the exact stored
connection/model pair and derives the provider from that connection. A caller cannot
redirect it by supplying another provider, endpoint URL, or credential.

Operation-specific options live under
`connection.operation_settings.<capability>`. For example, the image import retains
its API version and APIM transport information under
`connection.operation_settings.image_generation`. This does not replace the connection's
chat API version or introduce another credential record.

Version defaults belong to the operation adapter, not the generic connection.
New shared Images configurations use their own default rather than inheriting
chat or legacy root versions; explicit imported image versions are retained.
See [Image API versions](IMAGE_GENERATION_RESPONSES_MODELS.md#image-api-versions)
for the shared, imported, legacy, and Responses contracts.

The image adapter recognizes `api_version` for the Images operation, `is_apim`, and
`auth_header` for key-based gateway/provider authentication. Its optional
`image_deployment` is an explicitly stored backing-image binding used with Responses,
not another model picker. It is sent as `x-ms-oai-image-generation-deployment`;
without it, backend routing is left to the provider. Only retain a binding verified
against existing deployment/provider configuration, never invent a name or select
an arbitrary image model from the registry.

## Technical support, publication, and readiness

These are different questions and must remain separate:

1. **Technical support:** does the model have an implemented operation through this
   provider? `resolve_model_capability()` returns `supported`, `source`, `reason`, and
   `api`.
2. **Publication:** has the administrator made that supported operation available?
   The connection and model must be enabled, and any model-specific publication list
   must include the operation.
3. **Service readiness:** does the deployed resource currently accept the request?
   Permissions, API Management operations, service availability, quota, and image-tool
   access are checked by actual operation requests, not established by catalog metadata.

| Model field | Meaning |
| --- | --- |
| `supportsChat` | Optional boolean declaration of text-chat support |
| `supportsImageGeneration` | Optional boolean declaration of image-generation support, not proof that the service is currently usable |
| `image_generation_api` | Optional compatible image-operation route: `images` or `responses`; this is metadata, not a mandatory administrator API-mode choice |
| `enabled_capabilities` | Publication list containing implemented capability keys. An absent list imposes no task-specific restriction on technically supported operations; an empty list publishes none |
| `capability_status` | Computed, non-secret projection for consumers. Incoming values are discarded during normalization, not trusted as capability declarations |

The computed status describes technical support and model-level availability. Eligible
picker choices additionally require an enabled connection. Neither status is a live
health check. A transient provider error or content refusal must not change capability
metadata or silently replace a default.

Known direct image models are not chat models. Unknown legacy chat deployments remain
usable unless authoritative support information excludes them; an unknown name does
not establish new image-generation support. Image input/vision and image output are
also separate: vision analysis needs image input **and text output**, not merely an
ability to produce a picture.

Image-tool catalog lookup accepts exact catalog IDs, declared aliases, and valid
`YYYY-MM-DD` snapshots of those identifiers. An arbitrary `gpt-4o-*` variant does
not inherit image-tool support from the `gpt-4o` prefix. The separate legacy
vision/name heuristic remains available for image-input classification; it does
not establish image output support.

The image capability is restricted to existing `aoai`, `aifoundry`, and `new_foundry`
connection types with a compatible implemented operation. Being a model in one of
those providers, supporting generic tools, or belonging to a GPT family does not by
itself establish image-generation support.

## Capability and client contracts

`CapabilityDefinition` records `key`, `label`, `selection_key`, `catalog_flag`,
`supported_providers`, `feature_flag`, and `api_routes`. Its optional
`support_resolver(model, provider)` describes technical support when a catalog flag
alone is insufficient. Set this callable on the definition passed to
`register_capability()`; it is separate from the client factory.

Provider restrictions are checked before invoking the resolver. It can return:

- A boolean, normalized into a support description with source `provider`.
- A mapping with a boolean `supported` and optional `source`, `reason`, and `api`
  fields. These fields are included in public capability descriptions, so they must
  be safe for users and contain no secrets or internal diagnostics.

Registration rejects a non-callable resolver. Resolution rejects results that are
neither booleans nor mappings with a boolean `supported`. The resolver describes
technical eligibility only: publication, feature gates, and live service readiness
remain separate.

`register_capability(definition, client_factory=None)` registers an implemented
operation. Client factories can also be attached with
`register_capability_client_factory()`. `create_capability_client()` requires the
capability's feature gate and a registered factory before constructing its client.
These registrations are application code, not extensible request payloads.

`resolve_capability_binding()` produces a normalized `ModelBinding` containing the
capability, selection, connection, and model. The binding is **server-only**: its
connection can contain authentication configuration and must never be serialized to
the browser. Picker APIs use explicit non-secret projections instead.

The leaf framework has no Flask, settings-store, Azure, or SDK imports. Catalog
filtering and reference validation can therefore be tested without initializing
provider clients.

## File structure

Unless qualified, these files are under `application/single_app/`.

| File | Responsibility |
| --- | --- |
| `functions_ai_connections.py` | Capability definitions, publication rules, safe catalogs, binding validation, and client-factory registration |
| `functions_model_capabilities.py`, `static/json/model_capabilities.json` | Existing shared model catalog and capability evidence |
| `functions_settings.py` | Endpoint/model normalization and non-secret frontend projections |
| `functions_ai_connection_migration.py` | Pure import planning plus startup persistence, scoped credential conversion, and ETag retries |
| `functions_keyvault.py` | Existing scoped secret references plus opt-in staging for new import credentials |
| `app.py` | Initialize the import between settings-cache initialization and model-client setup |
| `route_backend_v2.py` | Capability-default HTTP API and revalidation when global connections change |
| `functions_image_generation.py`, `functions_image_api_route.py` | Registered image client, operation routing, request construction, and result validation |

## Administrator default API

Authenticated administrators use:

| Method and path | Behavior |
| --- | --- |
| `GET /api/v2/admin/capability-models/<capability>` | Read the resolved default, eligible global choices, feature state, and notices; does not import or persist settings |
| `PUT /api/v2/admin/capability-models/<capability>` | Validate and store a global default reference; return the same read contract |

For the image default, `<capability>` is `image_generation`:

```json
{
  "selection": {
    "endpoint_id": "creative-connection-id",
    "model_id": "illustration-model-id",
    "provider": "aoai"
  }
}
```

To clear it, send `selection` with empty `endpoint_id`, `model_id`, and `provider`
strings. Clearing is an explicit state, not a request to choose a fallback.

| Response field | Meaning |
| --- | --- |
| `capability` | Registered operation key |
| `selection` | Resolved reference, or the empty reference |
| `choices` | Eligible global model choices, sorted by connection/model labels and stable IDs |
| `reason` | Safe explanation for an unavailable or invalidated default, or `null` |
| `enabled` | The operation's feature gate, not provider health |
| `migration` | Image-import notice, when present; otherwise `null` |

Each choice includes `endpoint_id`, `model_id`, `provider`, `connection_name`,
`label`, `deployment_name`, and a `capability` support description. It contains
neither credentials nor internal endpoint URLs. Labels help administrators recognize
models; IDs prevent same-named deployments from being confused.

Malformed, partial, unavailable, incompatible, and non-global selections are rejected
with `400`. Unimplemented capability keys return `404`; unavailable settings return
`503`; a failed settings write returns `500`, not a successful save. Both routes retain
login, administrator, and Swagger security decorators.

Images can be configured while `enable_image_generation` is off; saving the reference
does not turn the feature on. A nonempty chat default still requires
`enable_multi_model_endpoints`. The existing `/api/v2/admin/default-model` contract
and `default_model_selection` remain compatible.

### Legacy image catalog handoff

Before import completes and while no shared image selection has been saved,
`GET` and `PUT /api/v2/admin/model-selection/image` retain their legacy catalog
behavior. After import or an explicit shared selection, including an intentional
clear, the legacy image catalog returns **HTTP 409**:

```json
{
  "error": "Image models are now selected through AI Connections.",
  "code": "image_catalog_migrated"
}
```

This prevents an older client from receiving a successful response for a write to
image settings that no longer control generation. Integrations must use
`GET`/`PUT /api/v2/admin/capability-models/image_generation` and its `selection`
reference instead of retrying a legacy catalog write.

The legacy embedding endpoint,
`GET`/`PUT /api/v2/admin/model-selection/embedding`, is unchanged.

## Automatic legacy image import

Application initialization runs the import after the settings cache is initialized
and before model clients use the final settings. Default/catalog GET requests remain
read-only.

1. Read authoritative settings. Import configured direct and APIM image routes,
   retaining the formerly active route and deployment as the image default. Empty
   configurations do not create empty connections.
2. Reuse a connection only when resource identity, provider, authentication, and
   relevant transport/identity policy are compatible. Otherwise use a separate
   connection with deterministic migration IDs. A matching display or deployment
   name alone is not enough.
3. Preserve deployment metadata, authentication, image API version, and APIM route
   information. Newly imported model records initially publish
   `image_generation` only, even when the model can also chat. Existing reused
   model publication is not broadened by the import.
4. Resolve legacy Key Vault references through their original allowed context,
   then stage new endpoint credentials through the existing global endpoint-secret
   helper before committing settings. Do not reinterpret a legacy settings-secret
   name as an endpoint secret.
5. Commit connections, image selection, and
   `ai_connections_image_migration_version` together with an ETag-conditional
   settings write. On a concurrent update, reread and rebuild, with bounded retries
   rather than an unconditional overwrite.
6. Refresh the settings cache after success. Keep original legacy values as backup;
   do not delete working credentials or enable chat connections or images as an
   incidental upgrade side effect.

The current migration version is `1`. The completion check accepts that or a newer
integer marker and does not downgrade it. An already recorded shared image selection,
including an empty one, is respected rather than replaced by a legacy selection.

A compatible reused connection retains its connection ID and existing model IDs.
If its active legacy model has no ID, the migration uses that deployment name as
the model ID; a missing provider is filled with `aoai` for the legacy Azure image
connection. This preserves a usable reference without adding another copy of the
deployment. Reuse still requires an existing connection ID.

If import fails, initialization retains legacy image operation and adds an actionable
`ai_connections_image_migration_notice`. Correct the reported settings or permissions
and restart to retry. `[AI_CONNECTIONS]` logs identify import and default-update events
without publishing credentials.

After successful import **or an explicit shared-default save**, the shared reference
is authoritative. Clearing it, deleting its model, or disabling its connection must
not reactivate the old image configuration. Connection writes revalidate the image
default and record an invalidation notice; no alternate model is silently selected.

### Credential staging during concurrent imports

A settings ETag protects the settings document, not a preceding Key Vault write.
If competing importers wrote the same secret name, a worker that later lost the
settings race could still replace the credential used by the winner.

The import opts into
`keyvault_model_endpoint_save_helper(..., stage_new_secrets=True)`. New credentials
receive unique staged secret names while retaining the connection owner, source,
and scope. Existing valid references can be reused. A losing importer therefore
cannot overwrite the winning importer's credential before detecting an ETag conflict.

Cleanup targets only stages known to be uncommitted, such as prepared credentials
from a rejected conditional write or a preparation failure. If a write's outcome
is indeterminate, credentials are retained rather than risking deletion of a secret
that the settings store may already reference.

Staging is opt-in for the import. It introduces no new stored-reference format and
does not change ordinary endpoint saves or key-rotation semantics for other callers.

## Security and compatibility boundaries

- Global image defaults are administered centrally. Personal/group chat connection
  ownership, membership, governance, and feature gates remain in force; this release
  does not add personal/group image defaults or new access rights.
- Capability projections filter a consumer's view without removing image models from
  the source registry. Text consumers must enforce chat eligibility at selection and
  execution boundaries, not just hide incompatible choices in the browser.
- Connection secrets are managed through existing scoped helpers. Updating a shared
  connection avoids a second copied credential in the task default.
- Image use is independent of the irreversible **Use AI Connections for chat** switch.
  Existing image connections must survive a later chat migration; that migration
  considers chat-eligible records rather than treating any nonempty registry as a
  configured chat source.
- Generated-image storage, proposal approval, regeneration, and existing masked-edit
  restrictions remain part of the image workflow, not new connection capabilities.

## Adding a future capability

An extension needs more than a new key in the registry:

1. Supply a definition, selection setting, technical support evidence, provider
   restrictions, and the intended feature gate. Use an optional `support_resolver`
   for non-catalog metadata instead of adding another special case to the core.
2. Implement and register a server-side client factory and operation adapter that
   reuse connection authentication and operation settings.
3. Validate selections against the authorized scope, publication policy, and required
   model capability at both catalog and runtime boundaries.
4. Add the task's actual UI and default-selection workflow; do not add placeholders
   before the adapter exists.
5. Cover binding, unavailable defaults, authorization, request/response handling, and
   persistence failures with targeted tests. Update the relevant settings/feature
   documentation and generated application-surface inventory when the UI changes.

Registration does not provision resources, add providers, or implement embeddings,
speech, transcription, or computer use automatically.

For example, a future adapter could describe service-provided voices through a
resolver rather than a text-model catalog flag. This is an extension example, not
a shipped voice integration: the active product capabilities remain chat and image
generation, and their existing configuration boundaries are unchanged.

## Testing and validation

| Coverage | Regression suite |
| --- | --- |
| Capability support, publication, projections, normalized references, and extension contracts | `functional_tests/test_ai_connections_capabilities.py` |
| Stable import identities, active direct/APIM selection, conservative reuse, legacy preservation, ETag conflicts, and explicit clears | `functional_tests/test_ai_connection_image_migration.py` |
| Unique scoped credential stages, interleaved import workers, and compatibility of ordinary secret saves | `functional_tests/test_ai_connection_credential_staging.py` |
| HTTP default reads/writes, independent task defaults, duplicate deployment names, safe payloads, authorization, invalid references, and failed saves | `functional_tests/test_ai_connection_defaults_api.py` |
| Existing chat-default and endpoint-management compatibility | `functional_tests/test_v2_admin_default_model_api.py`, `functional_tests/test_v2_admin_model_endpoints_api.py` |

The default API tests use Werkzeug `Client` to send real WSGI HTTP requests through
isolated registered route handlers, with settings and external dependencies isolated.
They test HTTP behavior, not live Azure availability.

The credential-staging suite runs the real secret-save helper with an in-memory
vault and interleaved settings writers. It checks that a losing importer cannot
overwrite or delete the winning credential without contacting Azure Key Vault.

The extension regression registers a test-only non-catalog operation with its own
support resolver and client factory, exercising shared HTTP/default binding and
factory reuse. The dummy operation is removed during test cleanup; it does not
publish a new product capability.

Image/client, text-consumer, and Classic/V2 UI regressions complement these contract
tests. This coverage description is not a claim of a completed live-provider run.
Deployment discovery performs no paid image generation; an explicit image request is
needed to verify image readiness and can incur provider charges.

Azure Responses availability, image-tool access, gateway operations, and any required
backing image deployment/default are deployment-specific. Do not infer them from a
successful text response, invent a backing deployment, or provision a resource as a
fallback.

## Related

- [Configure AI connections](../../guides/configure-ai-connections.md)
- [AI Models settings](../../admin/ai-models.md)
- [Image generation through Responses-capable models](IMAGE_GENERATION_RESPONSES_MODELS.md)
- [GPT chat model image-generation fix](../fixes/GPT_CHAT_MODEL_IMAGE_GENERATION_FIX.md)
