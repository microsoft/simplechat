# V2 Speech Resource ID Save Fix (0.261.397)

## Issue and root cause

The existing V2 **Knowledge > AI Voice Conversations > Speech resource** control
could build or accept a pasted Speech ARM resource ID, but **Save changes**
rejected the entire main settings draft with
`speech_service_resource_id cannot be changed through this endpoint.`

The field is a `resource-id-builder` component. The generic component guard in
`admin_settings_fields.py` rejects fields whose persistence belongs to another
API. Unlike those components, this builder edits a text setting that must be
persisted through `PATCH /api/v2/admin/settings`. Managed-identity synthesis
requires the saved ID to construct its `aad#<resource_id>#<token>` authorization
value.

## Implementation

Fixed in version: **0.261.397**.

`application/single_app/config.py` increments the application version from
`0.261.396` to `0.261.397`.

`application/single_app/admin_settings_fields.py` adds only
`speech_service_resource_id` to the existing delegated normalizers, reusing text
normalization to trim the built or pasted value. Empty values remain clearable,
consistent with existing Speech settings semantics. This is not a new ARM syntax
or Azure resource validation rule.

The field schema, Build button, route, authentication, secret redaction, and
Speech synthesis code are unchanged. Other component restrictions and protected
embedding settings remain enforced. The route still rejects an invalid draft
without partial writes, and the UI retains the full draft on failure.

The managed identity setup guide documents the V2 save workflow.

## Validation

`functional_tests/test_v2_admin_speech_resource_id_save.py` exercises the real
normalizer and real registered V2 PATCH/GET routes in fresh offline processes,
under normal and optimized Python. It covers built and padded pasted IDs,
companion settings, reload, clearing, unrelated component/protected-field
rejections, authentication, secret redaction, and persistence failure. The
settings persistence boundary is in memory; no Azure resources are contacted.

`ui_tests/test_v2_admin_speech_resource_id_save.py` uses the existing Playwright
harness with the built SPA, production schema, and real normalizer. It covers
Build-to-save, paste-to-save, reload, and retaining the complete draft for retry
after a rejected save.

Before the fix, the real route returned HTTP 400 without calling persistence;
the new normalization and Build-to-save tests reproduced the rejection.
After the fix, all seven focused functional cases and three browser cases pass.
The documentation surface inventory and site quality checks also pass; the
inventory is unchanged because no field or capability was added or renamed.

## Deployment and limitations

This is a repository fix, not a change to the running beta application. A later
application deployment containing **0.261.397** is needed to remove the live save
blocker. These tests do not validate live Azure Speech permissions or audio
synthesis. No live browser, existing admin draft, classic admin page, Azure
resources, roles, secrets, or backups are modified.
