# Model Catalog Publisher Key Setup Fix

**Version:** 0.261.473 (upgrade alert added in 0.261.474, secret-based signing in 0.261.475)

## Issue

Admin Settings > Model Catalog > Catalog updates showed:

> Publisher verification key is not configured. Install the trusted public key before
> publishing or importing packages.

Administrators had no way to act on this. The page also showed a second switch for the
same setting, labelled only with its key name (`enable_model_catalog_online_updates`), that
looked unrelated to **Allow online catalog update checks**.

## Root cause

- **The key was never bundled.** Signed packages are verified against public keys bundled
  in `static/json/model_catalog_trusted_keys.json`, so customers receive the key with an
  ordinary upgrade. The one-time publisher setup step that fills that file (export the
  Key Vault public key and commit it) had not been done, so the file shipped as `{}` and
  every deployment showed the warning. The warning wording told customers to install
  the key themselves, which they cannot do.
- **The duplicate switch** came from the V2 fallback scan, which draws a generic switch
  for every `enable_*` key that has no declared field. The Catalog updates card already
  owns this key and saves it through its own API with a concurrency check and audit event.

## Changes

| File | Change |
| --- | --- |
| `scripts/publish_model_catalog.py` | New `trust-key` command: reads the public half of a versioned Key Vault key, checks it is RSA of at least 3,072 bits, writes it under a key ID in the production or development trust map, re-verifies the map, and restores the file if verification fails. Refuses to reuse a key ID for new key material. |
| `admin_settings_fields.py` | `enable_model_catalog_online_updates` added to `SUPPRESSED_CAPABILITY_KEYS` with its reason. |
| `static/js/admin/model_catalog_updates.js`, `v2_ui/.../ModelCatalogUpdates.tsx` | Warning now says catalog updates are unavailable in this release, that the key ships inside SimpleChat, and that there is nothing to configure. |
| Docs | Publisher setup step 2, admin catalog page, V2 section links note. |

## Upgrade alert for deployments behind a key change (0.261.474)

Publisher keys are replaced only through an application release, so a deployment running
an older release cannot verify packages signed with a newer key. Previously that ended in a
generic "Unable to verify" failure.

- `model_catalog_package.py` adds `CatalogUpgradeRequired` (a `CatalogUpdateError`) with a
  `reason`: `publisher_key` (unknown key ID), `minimum_version` (catalog needs a newer app),
  or `format`. Its message tells the administrator to deploy the latest SimpleChat release
  and that the installed catalog keeps working.
- `CatalogUpdates.check()` records `{"status": "upgrade_required", "reason", "message",
  "downloadUrl", "minimumAppVersion"?}` as a completed check instead of a failure, so the
  alert persists across page loads.
- A release with no bundled key can now run **Check for updates** and upload a package; both
  report that an upgrade is needed instead of being disabled.
- Classic and V2 show **Upgrade SimpleChat to get catalog updates** with that message.
- Uploading a package signed with an unknown key returns the same explanation.

## Signing with an environment secret (0.261.475)

The publisher vault has public network access disabled by policy and no private endpoint,
so neither a workstation nor a GitHub-hosted runner can read or sign with a Key Vault key.

- `scripts/publish_model_catalog.py` adds `generate-key`: creates an RSA 3,072-bit pair,
  writes the private key to a new file outside the repository (refusing paths inside it and
  existing files), and adds the public key to the trust map, removing the private file if
  that fails.
- `sign_candidate()` signs with either the Key Vault key or the `CATALOG_SIGNING_KEY`
  secret, requiring exactly one, and checks the secret matches the trusted public key for
  `CATALOG_KEY_ID` before signing. Errors never echo the secret.
- `.github/workflows/publish-model-catalog.yml` accepts either configuration, refuses both,
  runs Azure login only when a vault URL is set, and passes the secret only to the signing
  step.

## Remaining publisher action

Code cannot create the publisher's signing key. Until a maintainer runs the setup in
`docs/explanation/features/SIGNED_MODEL_CATALOG_UPDATES.md` and commits the trust map,
the warning remains. With the Key Vault key created:

```
python scripts/publish_model_catalog.py trust-key --channel production --key-id <CATALOG_KEY_ID> --vault-key-url <CATALOG_VAULT_KEY_URL>
```

Commit the changed `model_catalog_trusted_keys.json`; the next release carries the key to
every deployment and the warning disappears after upgrade.

## Validation

- `functional_tests/test_model_catalog_publisher_key_setup.py`: key round-trip into the
  trust map, refusal of small keys and of a production key reused for development (map left
  unchanged), the suppression, and the new wording in both UIs.
- Existing `test_model_catalog_signed_updates.py`, `test_model_catalog_publication_lifecycle.py`,
  `test_model_catalog_api.py` and `test_v2_admin_capability_placement.py` pass.
