---
layout: page
title: "Signed model catalog updates"
description: "Publish reviewed model metadata through an approval-gated signing workflow and install compatible revisions independently of application deployment."
version: "0.261.428"
---

# Signed model catalog updates

Implemented in version: **0.261.425**.
The application version is tracked in `application/single_app/config.py`.
The standard online-access switch in classic and V2 was added in **0.261.426**.
Isolated development signing, Staging promotion evidence, and weekly review PRs
were implemented in **0.261.428**. Channel-aware bundles require that application
version or newer.

## Purpose and dependencies

Catalog publication is separate from application deployment. The publisher maintains
the existing model JSON, while administrators install a verified snapshot into their
deployment. A snapshot can change capabilities, evidence, selection descriptions,
and supported token/operation policies. It cannot implement a new provider protocol
or a catalog schema the installed application does not support.

The application uses its local JSON schema, `jsonschema`, and `cryptography`.
The publisher additionally needs Azure Key Vault Keys, a GitHub Actions identity,
and protected GitHub environments described below. Customer
installations do not need signing credentials or access to the publisher's vault.

## Publisher setup

Complete this once before the first publication. No publisher key or Azure
permissions are provisioned by this feature; both committed trust maps start empty.
Do not distribute a private key or put a development key in the production map.

1. Create a publisher-controlled RSA signing key of at least 3,072 bits in Azure
   Key Vault. Keep the private key in the vault. Choose a specific key version.
2. Export only its public key in PEM SubjectPublicKeyInfo format. Add that PEM
   string under a stable key ID in
   `application/single_app/static/json/model_catalog_trusted_keys.json`.
   Review and ship this trust-anchor change in the initial application upgrade.
3. Configure a publisher Azure identity for the GitHub workflow using OIDC.
   Read the repository's actual subject customization with
   `gh api repos/microsoft/simplechat/actions/oidc/customization/sub`; use the
   emitted subject, including repository/owner IDs and environment context where
   configured, rather than assuming a repository-name subject template.
   Restrict federation to the official publisher environment. Give the identity
   only the required key metadata/read and signing permissions.
4. Create the GitHub environment **model-catalog-publishing** and configure
   **required reviewers**. Restrict its deployment branch to `main`. Naming an
   environment in YAML alone does not require approval: the publisher script checks
   that a required-reviewer rule actually exists and fails if it cannot confirm it.
5. Add environment variables `CATALOG_AZURE_CLIENT_ID`,
   `CATALOG_AZURE_TENANT_ID`, `CATALOG_AZURE_SUBSCRIPTION_ID`,
   `CATALOG_VAULT_KEY_URL`, and `CATALOG_KEY_ID`. The key URL must identify the
   same key version whose public key is trusted. These identifiers are not
   private key material.
6. Permit the protected job's GitHub token to publish Git data on the dedicated
   `model-catalog` branch. Ensure repository/organization rules allow this
   narrowly scoped publishing operation. The workflow never pushes to `main`.
7. Create a **separate** development RSA key and signing identity. Put only its
   public key in `model_catalog_development_trusted_keys.json` beside the
   production map. Use different key IDs and actual key material; the verifier
   rejects overlapping IDs and reused public keys in the development map.
   Configure the same five variable names in **model-catalog-development**,
   using the development identity/key, required reviewers, and a deployment-branch
   restriction to `Development`. Neither identity should be able to sign with
   the other channel's key.
8. Create **model-catalog-validation** with required reviewers and restrict it to
   `Staging`. This environment needs no Azure identity or signing permission.
   Restrict direct writes/force pushes to the `model-catalog`,
   `model-catalog-development`, and `model-catalog-validation` data branches to
   their intended publishing jobs using repository rules. Protect source and
   workflow changes through normal repository review.
9. Exercise a real approved signing/publication run before declaring the channel
   operational. Local fixtures do not establish that federation, required reviewers,
   vault permissions, network access, and branch rules are correctly configured.

The publisher's Key Vault belongs to the publisher, not each customer deployment.
GitHub environment approval controls use of the signing identity; source review
controls which catalog changes can reach the publisher workflow.

## Everyday publishing workflow

1. You or Copilot updates
   `application/single_app/static/json/model_capabilities.json` in a normal PR.
   Preserve independent source-review dates; publishing a package is not a new
   factual audit.
2. Increment the positive integer `revision` in `model-catalog/release.json`.
   Set `minimumAppVersion` to the oldest application that supports the package's
   technical metadata. This revision is independent of the application version.
3. Reviewed changes first merge into **Development**, following the repository's
   **Development → Staging → main** promotion flow. **Publish model catalog**
   prepares the exact source payload and manifest, with commit and hash in its
   summary. Approve **model-catalog-development** to sign and publish a
   development-only package. The workflow also attaches the signed file as an
   Actions artifact for convenient offline-upload testing.
4. Test that package on an isolated development deployment as described below.
   Promote the source into **Staging**. Its publishing run waits for
   **model-catalog-validation** approval. The reviewer must confirm that the
   signed upload, opt-in online check, preview, apply, runtime use, and rollback
   were exercised against the candidate. Approval is a human test attestation;
   the workflow does not pretend to deploy or inspect an unspecified live app.
5. After approval, Staging runs the offline channel/promotion regression suite,
   verifies the signed development revision against its exact source, and records
   the payload hash, package digest, Staging commit and Actions run ID on the
   validation data branch. A failed test writes no record. Existing records
   cannot be replaced. The complete validation workflow must succeed.
6. Promote **Staging** into **main** and approve
   **model-catalog-publishing** after reviewing the prepared production candidate.
   Before production signing, the script requires the same revision, payload,
   schema and minimum application version as the signed development package,
   its matching validation record, and a successful Staging workflow run.
   It independently fetches the catalog at that Staging commit and compares the
   exact bytes. Missing, changed, failed or pending evidence blocks publication.
7. The signing job checks out that exact source commit, retrieves the prepared
   artifact, and uses OIDC to authenticate. Key Vault signs a SHA-256 digest of
   the manifest using RS256. The private key never leaves the vault.
8. The job verifies the completed bundle using the same pinned public-key verifier
   as the application, commits its dated/versioned package, and advances the
   discovery pointer on the dedicated publication branch. Both become visible
   through one final branch update. Signing or verification failure leaves the
   previous published pointer intact.

Publication is serialized. A stale/repeated run cannot replace an existing revision
or move the latest pointer backward. Generated data lives on a separate branch,
so it neither retriggers catalog publication nor the existing main-branch Docker
image build. The initial reviewed source merge may still trigger that existing
Docker build; catalog publication itself does not depend on it.

Once its workflow definition is on default `main`, **Publish model catalog**
also supports manual dispatch on `Development`, `Staging`, or `main`.
Before that, the initial Development push can test publication and its failed
jobs can be rerun after fixing configuration. Feature
branches and forks cannot publish. Successful immutable publications/validation
records are not overwritten on retry; make a new revision for a new candidate.
An application-only promotion without catalog-path changes need not republish.

The output is one portable JSON bundle containing base64-encoded catalog bytes,
the exact signed manifest bytes, and the signature. Administrators can download
that file from the `model-catalog` branch for offline upload; they must not edit or
reformat its embedded contents.

## Development deployment and test feed

On an isolated test deployment, set the server process environment variable
`MODEL_CATALOG_CHANNEL=development` **before starting both web and scheduler
processes**. Use separate Cosmos application settings/data from production.
Do not change a production instance to development mode or share its active
catalog pointers with a test instance. Restart test processes after changing this
startup policy.

The default is `production`. The variable accepts only `production` or
`development`, never a URL, key, or branch supplied by the administrator UI.
The development mode reads only the development public-key map and the fixed feed:

`https://raw.githubusercontent.com/microsoft/simplechat/model-catalog-development/model-catalog/latest.json`

The same admin interface displays this actual URL before online opt-in. Test
offline upload with the signed Actions artifact as well as online discovery.
Both paths still require explicit Preview and Apply. Verify a model resolver or
chat sees the new metadata, and exercise rollback. A signed `channel` manifest
field prevents a development bundle from being installed in production even if
someone accidentally copies a development public key into the production map.
Production clients never query the development feed by default.

Revision-specific pointers under `model-catalog/revisions/<revision>.json`
identify immutable package commits. Promotion uses these, not whichever
development revision happens to be latest when main is approved. Production
re-signs the tested payload with its own key; it does not reuse the development
signature. Publication timestamps and source merge commits may legitimately
differ between channels.

## Weekly model discovery and review PRs

`.github/workflows/refresh-model-catalog.md` is a GitHub Agentic Workflow compiled
with **gh-aw v1.2.2** into its committed `.lock.yml`. The schedule is **Monday
09:23 UTC**, with manual dispatch available. GitHub schedules execute only once
the workflow exists on default `main`; its checkout and PR target remain
`Development`. Manual dispatch also requires the workflow to exist on default
`main`. To test research before that first main promotion, a push changing the
research workflow source/lock on `Development` is an additional trigger, subject
to the same explicit enable variable. Catalog-only merges do not trigger another
research run.

The publisher must explicitly set the repository Actions variable
`ENABLE_MODEL_CATALOG_REFRESH=true` to permit research runs. Enable the
organization's Copilot-in-Actions inference policy for the workflow's
`copilot-requests: write` permission; this uses the publisher's GitHub inference
entitlement, not customer application credentials. Missing access is a workflow
failure, not an empty successful research result. No account, token, repository
policy or paid entitlement is provisioned automatically.

The Copilot SDK engine can fetch public pages within an explicit provider-domain
allowlist. It begins with provider-wide model indexes and release/deprecation
pages, compares their exact IDs with the current catalog, then reads first-party
model documentation/cards for changed or new candidates. It does not rely only
on the existing model-specific source URLs. Model availability listings are
discovery leads, not proof of capacities, protocols, reasoning effort, image
generation or embedding support. Unreachable indexes and incomplete evidence
must be disclosed; discovery is not guaranteed exhaustive.

Official pricing can be researched for the PR evidence, with host/provider,
region where relevant, currency, billing units, input/output/cached-input rates,
discount qualifications, source URL and review/effective dates. **The current
catalog schema has no structured pricing fields**. This workflow does not add
them, change runtime pricing, or treat published list prices as negotiated tenant
rates. Unknown prices remain unknown, and pricing-only observations do not
justify a fabricated catalog update.

The researcher has read-only GitHub access and no Azure signing identity.
Separate safe-output jobs may create **one draft PR into Development**, bounded
to the catalog, release metadata, VERSION, release notes and this feature page.
The agent cannot change workflow files or public trust anchors through that
output. It must preserve IDs and historical evidence, validate schema/identities,
include sources and before/after claims, and follow the PR template. Existing
open catalog PRs suppress duplicate proposals. No supported change means no PR;
there is no date-only refresh, automatic merge, signature or activation.

GitHub does not trigger ordinary PR CI from a default `GITHUB_TOKEN` push.
Configure the optional **GH_AW_CI_TRIGGER_TOKEN** secret, restricted to this
repository with only the permissions needed to push the framework's extra empty
commit, if those PRs should automatically start normal CI. The token stays in the
deterministic safe-output job, outside the researcher. Without it, a maintainer
must trigger the applicable checks or push a reviewed commit before merging;
a created PR is not evidence that CI ran.

After editing the workflow source, regenerate and commit the lock:

```powershell
gh extension install github/gh-aw --pin v1.2.2
gh aw compile refresh-model-catalog --no-check-update --no-logo
```

The publication-contract CI job runs isolated channel/promotion tests and verifies
that recompilation leaves the committed lock unchanged. Compiled action/container
dependencies are pinned. The workflow's fixed weekly time intentionally avoids
the top of the hour; its compiler's suggestion to use a fuzzy schedule is advisory.

## Runtime and API

The fixed discovery endpoint is
`https://raw.githubusercontent.com/microsoft/simplechat/model-catalog/model-catalog/latest.json`.
Its closed JSON shape contains `commit` and `filename`. The application constructs
an immutable raw-content URL under the same official repository; discovery cannot
introduce an arbitrary destination or a replacement verification key.

`GET /api/admin/model-catalog/updates` returns explicit status metadata, not raw
application settings. Its admin-authenticated `POST` operations are `online`,
`check`, `upload`, `preview`, `apply`, `rollback-preview`, and `rollback`.
Mutating online policy or activating a revision requires the current settings ETag.

Verified immutable bundles are stored as dedicated Cosmos settings-container
records. The settings document carries active and previous digest references.
Activation uses the shared fenced settings store, so derived settings-version
caches notice the change. Process caches hold only verified immutable snapshots,
not an authoritative active-pointer snapshot.

The low-level model resolver obtains snapshots through an injected provider.
It does not import Flask, settings, logging, Azure configuration, or storage owners.
Web requests and scheduler slices pin their effective catalog lazily; background
chat workers carry the request's pinned revision into their own execution scope.
New scopes resolve the shared active revision. If none is configured, the shipped file remains
the baseline. An unreadable active package is an explicit failure, not a silent
fallback to different limits or model behavior.

## Verification, recovery, and trust limits

Verification checks the trusted signing-key ID and fixed algorithm, signature,
exact payload hash and size, package/application/schema compatibility, model
identity collisions, channel isolation, and evidence references. Local schemas are used; uploaded
schema URLs are not fetched. Downloads reject redirects and have timeout and
decoded-size bounds. Online access defaults off and is enforced on the server.

SHA-256 detects content changes; a signature additionally authenticates the
publisher key. Neither proves the catalog's factual claims, guarantees that the
host serves the newest package, nor protects against compromise of the authorized
signing workflow. Older revisions cannot be installed through normal apply;
rollback is explicit, conditional, and checked against current links and identities.

To rotate keys, ship the replacement public key in an application release before
publishing packages signed by the replacement private key. Retain the old public
key while old rollback packages remain supported. There is no trust-on-first-use
or automatic key replacement from the download location.

## Validation and limitations

`functional_tests/test_model_catalog_signed_updates.py` uses real RSA signatures,
network-blocked imports, the installed Cosmos SDK mapping type, independent worker
stores, Redis and non-Redis activation, replay/conflict checks, and offline API
contracts. `ui_tests/test_model_catalog_update_controls.py` exercises classic and
React V2 controls through the existing Azure Playwright/local Chromium fixture.
`functional_tests/test_model_catalog_publication_lifecycle.py` verifies separate
keys/channels, branch/environment policies, exact tested-payload promotion,
failed/pending/wrong workflow rejection, fixed feeds, and bounded review-only
weekly proposals. It requires only the publisher/test requirements and runs
without cloud configuration.

Adding the weekly workflow does not itself research or expand the committed source
inventory; only a configured run can propose a reviewed change. Personal
and group links are protected conservatively by blocking model-ID removal rather
than claiming to enumerate all tenants' connection inventories. Staged packages
remain immutable storage records; this version does not provide a package-history
deletion interface. A live publisher run requires the one-time setup above.
