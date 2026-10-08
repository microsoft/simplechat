# Shared Custom Endpoint CA Bundles

## Overview and dependencies

Fixed/Implemented in version: **0.261.052**, tracked in
`application/single_app/config.py`.

Administrators can upload named PEM certificate-authority bundles rather than
mounting the same certificate file in every application worker. Certificates
use the dedicated private `model-endpoint-ca-bundles` container in the existing
application Blob account; metadata and reference reservations use the existing
Cosmos `settings` container. Configure the application's Blob account access
using its existing key or managed-identity settings. **Enhanced Citations does
not need to be enabled.** No storage resource is provisioned by a local test.

## Architecture and trust

- Uploads accept PEM CA certificates only: maximum 1 MiB and 64 certificates.
  Private keys, mixed content, leaf certificates, and duplicate certificates
  are rejected before publication.
- Friendly names, SHA-256 fingerprints, validity dates, revisions, and recent
  audit history are visible to administrators. Workspace choices expose only
  approved bundle names/IDs, revision, expiry, and certificate count.
- Endpoint `connection.ca_bundle_mode` is `inherit`, `public`, or `bundle`.
  Bundle mode requires a stable `connection.ca_bundle_id`.
- Existing endpoints without these fields retain their prior global CA-path
  behavior. New editor configurations default to public roots. Nothing
  automatically migrates existing paths or widens trust.
- A selected bundle **replaces**, rather than appends to, public trust roots.
  TLS hostname verification remains enabled, and ambient certificate variables
  remain ignored. mTLS certificate/key paths remain separate and are preserved
  by editor saves; private keys are never uploaded here.
- Runtime verifies stored bytes against their digest. An unavailable, corrupt,
  or deleted bundle fails explicitly; public-root fallback is never used.
  Revision-aware caching refreshes new sync/async requests and route identities.
  Requests already in flight may complete using their original TLS context.
- Endpoint saves reserve bundle references before conditional persistence.
  Deletion checks saved references using captured Cosmos session tokens and
  rejects in-progress saves. An expired reservation is fenced before recovery,
  so a late writer cannot resurrect a deleted trust reference.

## API and files

Admin-only management:

- `GET|POST /api/model-ca-bundles`
- `PUT|DELETE /api/model-ca-bundles/<bundle_id>`; replacement/deletion requires
  the displayed `expected_revision`

Scope-authorized choices:

- `GET /api/models/ca-bundle-options`
- `GET /api/user/models/ca-bundle-options`
- `GET /api/group/models/ca-bundle-options`

Personal/group flags, governance, current group membership, and existing
Blueprint login/user policies apply before the choice inventory is read.

Implementation: `model_endpoint_ca_bundles.py`,
`route_backend_model_ca_bundles.py`, the settings/runtime owners, shared
`static/js/model_ca_bundles.js`, and
`static/js/admin/model_ca_bundle_manager.js`.

## Usage

Open **Model Endpoints -> Advanced network and certificate trust -> Manage shared
CA bundles**. Upload a friendly name and a PEM CA file. Select the bundle in an
authorized endpoint editor's **Certificate trust** control and save the endpoint
(and the main settings form for a global endpoint).

Use **Edit / replace** to rename or supply a new PEM file. Endpoint references
keep the same bundle ID. The server checks revisions to prevent stale replacement.
Expiry is displayed; this feature does not make an expired certificate valid.

Change all referencing endpoints before deleting a bundle. The server rechecks
references even if the displayed inventory is old. Failed deletion remains
recoverable with **Retry deletion** rather than silently reporting success.

## Validation, operations, and limitations

Coverage includes bounded PEM parsing, integrity, private-container enforcement,
cross-worker revision refresh, reference/deletion races, abandoned-writer fencing,
real cold Blueprint authorization, and browser upload/rename/delete workflows.
See `functional_tests/test_model_endpoint_ca_bundles.py`,
`functional_tests/test_model_ca_bundle_routes_integration.py`, and
`ui_tests/test_model_ca_bundle_manager.py`.

Immutable prior certificate objects are retained until bundle deletion for
replacement history. Recent metadata audit history is bounded to 50 events;
production event retention follows the configured logging policy. Back up both
Cosmos metadata and the dedicated Blob container together. Metadata is kept
below Cosmos item-size limits, with an explicit error if its reference inventory
reaches the safe bound. Live storage permissions, platform networking, disaster
recovery, and deployed scale-out still require environment validation.
