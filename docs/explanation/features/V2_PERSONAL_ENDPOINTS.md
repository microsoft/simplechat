# V2 Personal Endpoint Editor

## Overview

Implemented in version: **0.261.315**, tracked in
`application/single_app/config.py`. Refs
[issue #1722, row 6](https://github.com/microsoft/simplechat/issues/1722).

The personal **Endpoints** section now creates and edits connections natively
instead of sending users to the classic workspace. It reuses
`ModelConnectionsManager` through a personal adapter, preserving the established
admin/group forms without exposing their privileged API operations.

Dependencies are the existing personal-endpoint feature/governance gates,
supported resource credentials, and the V2 build. No new settings, routes,
frontend dependencies, external browser assets, or deployment version are added.

## Architecture and API contract

`pages/workspace/EndpointsSection.tsx` supplies a stable
`createPersonalModelConnectionsAdapter` from `lib/modelConnections.ts`.

| Operation | Personal route and shape |
| --- | --- |
| List | `GET /api/user/model-endpoints`: sanitized `endpoints` and public `custom_api_types` registry descriptors. |
| Create | `POST /api/user/model-endpoints`: one connection payload. |
| Read/edit | `GET/PATCH /api/user/model-endpoints/<endpoint_id>`: one endpoint; edits never replace the collection. |
| Toggle | Per-item `PATCH` with only `{enabled}`. |
| Delete | Per-item `DELETE`, without a body. |
| Discovery | `POST /api/user/models/fetch`. |
| Chat test | `POST /api/user/models/test-model`. |

Malformed envelopes/records fail visibly rather than falling back to empty
lists or apparent success. IDs are validated and URL-encoded. Personal scope
has neither the group's revisions nor `endpoint_actions`; it does not invent
a conditional-write protocol. Existing server ownership and governance checks
remain authoritative.

`route_backend_models.py` adds only safe provider registry descriptors to the
list response. Stored secrets and Key Vault references remain sanitized.
The adapter hides tenant connection tests, capability inference tests, global
defaults/migrations, and network-policy editing. The public model catalogue
picker still reads `GET /api/models/catalog`.

## Saved configuration and credential boundaries

Existing personal discovery/tests deliberately resolve saved connection/auth
details. Tests also require the stored enabled model. The editor disables
discovery/chat tests whenever its serialized draft differs from that saved
binding, and guards handlers with the same save-first explanation. Discovered
changes also require saving. Unsaved new connections retain existing transient
request support without weakening application-identity restrictions.

`has_api_key`, `has_client_secret`, and `has_bearer_token` flags explain
stored credentials. Blank fields are omitted from saves; explicit replacements
go through the existing normalization/Key Vault helpers. No draft is written
to browser storage. Save, discovery, and inference success remain distinct.

## Advanced metadata and icons

`lib/connectionMetadata.ts` and
`components/workspace/ConnectionMetadataFields.tsx` add personal-only endpoint
defaults and model overrides for `contextWindow`, `inputTokenLimit`,
`outputTokenLimit`, `tokenLimitProvider`, and `outputTokenAccounting`.
Model overrides also include `catalogModelId` and `modelVersion`.
Descriptions, optional `responseLength`, and icons are editable.

Positive safe integers are required for capacities/response length. Cleared
overrides serialize as explicit `null`; capacity inheritance is independent
per field. The backend removes a cleared response length. Independent maxima
are not rejected merely because their sum exceeds context capacity.

`lib/resourceIcons.ts` extracts the agent editor's existing local icon loading
and raster resizing. PNG/JPEG images are bounded to 128 pixels per dimension
and 350000 characters. Bootstrap classes are validated; remote images and
SVG are not accepted. Upload failures are announced, saving waits for resizing,
and unmounted drafts cannot be overwritten by late image results.

## Usage

See [Connect personal models in V2](../../guides/personal-model-endpoints.md)
for provider/auth configuration, manual and discovered models, save-first tests,
capacity inheritance, icon selection, and troubleshooting.

## Testing and limitations

`functional_tests/test_v2_personal_endpoints_api.py` runs the registered personal
routes offline, including sanitization, credentials, null clears, ownership,
governance, deletion, and saved/transient test semantics.
`functional_tests/test_v2_personal_endpoints_logic.mjs` executes the production
adapter, serializers, numeric validation, icon checks, and saved-binding gate.

`ui_tests/test_v2_personal_endpoints.py` drives the built SPA through a closed
workspace fixture backed by the same real Flask route harness. It covers
provider/auth creation, advanced edits/reopening, discovery, chat tests, icons,
failures, denied sections, keyboard focus, both themes, and mobile/desktop
overflow. Shared group/admin/agent suites cover the reused seams.

### Validation results

The production build/typecheck, 63 personal/group/admin/shared-icon browser
cases, 81 executable TypeScript checks, and targeted real-route regressions
passed. Route policy coverage, documentation coverage/site quality, and the
changed production files' XSS sink checks also passed.

The broader existing workspace-authoring suite retained 11 action-related
failures; all 11 reproduced against an isolated unchanged-HEAD production
bundle. The existing full-app capacity test retained two failures because its
offline admin-page render attempted a release-update network request; both
also reproduced on unchanged HEAD. Those pre-existing failures are not claimed
as fixed or as passing coverage for this feature.

The tests do not qualify live Azure inference, root/separately hosted routing,
or Teams. Companion [issue #1723](https://github.com/microsoft/simplechat/issues/1723)
owns legacy/root routing and New UI only policy. Personal saves still lack
optimistic revisions; this change does not claim protection against concurrent
edits to the same endpoint. Image and embedding inference tests remain
administrator-only.
