# AI Connections Embeddings (v0.261.108)

## Overview

Text embeddings share the AI Connections registry used by chat and image generation.
An administrator publishes compatible embedding models and selects one global
default for document indexing, semantic retrieval, fact memory, and the default
Embedding Model action. Credentials remain on the connection, not in each consumer.

Implemented in version: **0.261.106**. The application version is recorded in
`application/single_app/config.py`.
Integration with the Custom endpoint/image foundation was implemented in **0.261.108**.

Dependencies are the existing OpenAI SDK, Azure Identity, scoped Key Vault helpers,
Azure AI Search, Cosmos DB, and the existing distributed Search write fence. No
retired Azure AI Inference SDK or browser runtime dependency is added.

## Supported operations

| Connection | Embedding operation | Important boundary |
| --- | --- | --- |
| Azure OpenAI | Versioned deployment embeddings or resource-level `/openai/v1/embeddings` | Imported deployment paths, API versions, and credentials remain unchanged |
| Azure API Management | The configured Azure-compatible operation and allowed key header | A gateway is never bypassed in favor of its presumed backend |
| Foundry | Explicit, supported resource-level OpenAI-compatible inference base | `/api/projects/<project>` is for project operations, not embeddings |
| OpenAI-compatible custom | `<configured-api-base>/embeddings`, API key/token authentication | Manual model entry; no Azure management discovery, native vendor API, or new chat/image adapter |

Canonical **Custom** OpenAI and Azure OpenAI connections also support embeddings
with API key or bearer authentication. They retain the shared provider's model-name
or deployment-name convention and its `auto`/`exact` URL policy. Custom chat/image
support, including their broader authentication options, remains independent;
OAuth2 and other Custom API types are not embedding adapters in this phase.

Existing `openai_compatible` embedding-only records retain their deployment
identifiers and exact base paths. Both Custom forms now use the common
DNS-pinned transport, certificate configuration, and administrator network policy.
Private networks and plaintext HTTP require the corresponding explicit permissions;
loopback, link-local, and metadata destinations remain blocked. Endpoint URLs must
not contain credentials, query parameters, or fragments.

The catalog describes models, not universal endpoint compatibility. For example,
Cohere embedding families require task-sensitive behavior on their native APIs.
Their presence in the catalog does not establish that a particular Foundry
deployment accepts the current OpenAI embeddings contract. Unsupported operation
requirements remain unavailable unless a verified compatible gateway handles them.
For a gateway that distinguishes document and query modes using input prefixes,
configure the corresponding prefixes and their translation on the gateway.
Declaring compatibility does not add native `input_type` fields to OpenAI requests.

The deprecated Azure Model Inference API and vendor-native APIs are outside this
release. See [Microsoft's endpoint guidance](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview#openai-sdk)
and [embedding API documentation](https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/embeddings).

## Configuration and model metadata

`embedding_model_selection` stores the same `{endpoint_id, model_id, provider}`
reference used by other capability defaults. It is independent of the chat
connections switch and image default. Personal and group chat connections are not
global embedding choices.

Connection-specific options live in `connection.operation_settings.embeddings`.
They select the `azure_openai` or `openai` operation, an optional explicit inference
endpoint, a dated API version for the versioned operation, and supported gateway
authentication behavior. They do not introduce another secret record.

Models use `supportsEmbeddings` and `enabled_capabilities`. An absent publication
list leaves supported operations unrestricted; an empty list publishes none.
Known embedding-only models do not appear as chat, image, or vision-analysis models.

The sourced catalog supplies dimension and input/batch policies for known models.
Unknown custom models require explicitly declared dimensions and maximum input
tokens. Optional `embedding_config` settings can describe model revision,
document/query prefixes, and supported dimension overrides. Declaring a model's
fixed dimension does not request unsupported resizing.

Maximum input size differs between the model family and its hosting API. In
particular, the Azure and Cohere sources list different context limits for Embed
v4. The application does not silently substitute the larger model-family limit
for an unverified hosting limit.

## Runtime behavior

`functions_embeddings.py` builds the registered client and validates actual output:
one finite numeric vector for each input, correct indexes and ordering, and exact
configured dimensions. It does not truncate, pad, or fabricate output vectors.
Inputs carry document/query purpose internally; unsupported vendor fields are not
sent to a standard OpenAI endpoint.

New configurations use a conservative UTF-8 byte bound for input and aggregate
batch budgets. This can reject text that a provider's tokenizer would accept;
split the text rather than increasing a limit beyond the documented deployment
contract. Imported legacy configurations retain their existing input behavior.

Single and batch callers retain the vector/optional-usage return contracts.
Provider usage remains unknown when omitted; vector provenance remains available
independently. Batch usage preserves the reported aggregate, including division
remainders. Rate-limit retries are bounded and exhaustion is an explicit error.

The default embedding action uses this shared runtime. An explicitly configured
action manifest retains its existing endpoint contract instead of silently using
the global document-search model.

## Configuration import

Startup imports configured legacy direct and APIM embedding routes independently
of the image import. It preserves the active model, credentials or secret
references, transport path, API version, and identity-header behavior. New imported
model records publish embeddings only.

Migration uses deterministic IDs, conservative connection reuse, credential
staging, and conditional settings writes. It does not call inference, change
dimensions, resize indexes, or regenerate vectors.

`ai_connections_embedding_migration_version` and its separate notice record the
handoff. On failure, legacy configuration remains available for recovery. After
a successful import or explicit shared-default save, clearing or invalidating
the selection never reactivates legacy settings.

The original settings remain recovery data. Obsolete writes to the legacy model
selector return a migration response instead of pretending to update the active
shared default.

## Vector compatibility and the rebuild boundary

Equal vector dimensions do not mean equal vector spaces. The durable
`embedding_vector_profile` identifies the configured model/deployment, effective
dimensions, and input semantics without including credentials. It survives a
cleared or unavailable default. Credential rotation does not create a new space.

Activating a different profile requires empty/recreated personal, group, and public
search indexes plus no remaining fact-memory vectors. A failed inspection is not
treated as an empty store. The distributed write fence publishes the active
profile through Cosmos conditional-write coordination. Writers and retrieval
pages validate against that state instead of trusting independently
session-consistent settings reads. Stale vectors cannot be saved under a new
profile.

The fence retains `embedding_vectors_written`, a conservative write-intent ledger.
Once set, a lagging empty-store response cannot authorize a model change. Legacy
history without a ledger remains unverified. Resetting this ledger is part of the
external rebuild procedure, not a model-picker override; unsuccessful or
indeterminate writes can require the same deliberate cleanup.

New search chunks and fact vectors carry `embedding_profile_id`. Existing untagged
vectors remain legacy/unverified under the unchanged legacy profile. Read-only
fact retrieval does not backfill or regenerate vectors. Retrieval cache identity
includes the embedding profile.

Coordination adds Cosmos conditional operations to cache reads, retrieval pages,
and vector writes. Account for that throughput and latency at production concurrency.
Pin deployment revisions: replacing weights behind an unchanged deployment without
updating its declared revision cannot be detected from configuration alone.

Search schemas ship with 1,536 dimensions. App-managed creation uses the effective
profile for both `embedding` and the defined `video_ocr_embedding` field; the latter
does not enable a new OCR-vector pipeline. Field maintenance adds missing
provenance fields but cannot resize an existing vector field.

Normal legacy indexing and retrieval retain their data-plane Search permissions.
Privileged maintenance or activation records schema observations in the profile;
runtime queries do not read index definitions on every search.

An indeterminate settings commit or profile publication leaves vector operations
blocked by a pending activation marker. Reload and explicitly save the intended
embedding default again to reconcile it. Do not delete the write gate or bypass
the profile check.

### Preparing an externally managed model change

This release does not include a bulk rebuild, populated-index adoption, shadow
index, or zero-downtime cutover workflow.

1. Preserve source documents, fact text, metadata, and backups. Confirm that every
   document to be rebuilt has a recoverable source; this is not guaranteed for
   historical uploads.
2. Upgrade and stop all app workers, ingestion, and fact backfill. Plan a maintenance
   window for retrieval.
3. Explicitly empty/recreate the three document indexes for the intended dimensions.
   Preserve fact text while deliberately removing incompatible fact vectors.
4. With workers stopped and writer/fence leases expired, set only
   `embedding_vectors_written` to `false` on the
   `data_management_search_write_gate_global` document in the Cosmos
   `data_management_jobs` container. Leave all other fields intact. If the gate
   does not exist, use index maintenance to establish it before scheduling the reset.
5. Restart workers and select the new model after schema and empty-store checks
   pass. The ledger reset does not bypass these checks.
6. Reprocess or re-upload documents and deliberately backfill fact vectors. Confirm
   coverage across personal, group, public, and video-derived text sources.

Deleting an index or removing vectors is an administrator-controlled external
operation, never an implicit effect of saving a default. A populated external
rebuild does not gain an unchecked "trust this data" override.

## APIs and implementation files

| Surface | Purpose |
| --- | --- |
| `GET/PUT /api/v2/admin/capability-models/embeddings` | Read or save the global embedding reference and its eligible choices |
| Existing admin `test-connection` route with `test_type: embedding` and `selection` | Probe real inference without changing a default or persisting vectors |
| `functions_ai_connections.py`, `functions_embedding_policy.py`, `functions_embedding_profile.py` | Pure capability, metadata, transport, and identity contracts |
| `functions_embeddings.py`, `functions_content.py` | Registered runtime and compatible single/batch entrypoints |
| `functions_embedding_compatibility.py` | Activation checks, index dimensions/provenance, and vector write boundaries |
| `functions_ai_connection_migration.py` | Independent legacy import and recovery |

## Coverage and limitations

Focused functional coverage exercises catalog eligibility, endpoint paths,
authentication, batch ordering/usage, malformed responses, retries, migration,
default APIs, and vector compatibility. Classic and React browser coverage
exercises publication, custom configuration, independent defaults, operation tests,
recovery notices, and rejected saves.

These offline contracts do not establish live provider readiness, regional
availability, authorization, quota, or model quality. An administrator's operation
test incurs inference but does not prove full context limits or compatibility with
historical vectors. No new model is silently selected when the active one fails.
