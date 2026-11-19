---
layout: page
title: "Dependency Pinning"
description: "How to maintain explicit dependency graphs and verify the age of newly selected releases."
section: "Contributing"
permalink: /contributing/dependency-pinning/
---

Implemented in version: **0.261.454** (`application/single_app/config.py`).
Current integration version: **0.261.460**.

## Selection policy

Retain existing exact versions and lock resolutions unless a compatibility
repair requires changing them. Every newly selected release, including a
transitive dependency, must have been published for at least **14 full days**.
Existing exact pins are grandfathered; their age is not a reason to downgrade.
When integrating an existing security pin from Development, retain that version
and record its immutable baseline commit in `inherited_from` selection evidence.
The audit checks the baseline content and exact reference rather than inventing
an older publication timestamp.

Only SimpleChat's own application image in its Azure Container Registry may
use `latest`. Third-party images, devcontainer features, installed tools, and
other dependencies must not use that alias. Preserve the application's
versioned output tags as well.

## Python environments

Install through the existing requirements files: their `-c` directives consume
the committed transitive constraints. Linux and Windows resolution are recorded
separately where necessary. Catalog and isolated build constraints support
Python 3.11 and 3.12; application/development/UI constraints target Python 3.12.
These locks do not claim support for other interpreter/platform combinations.

Bootstrap the exact installer and consume isolated build constraints too:

```powershell
python -m pip install pip==26.0.1
python -m pip install --build-constraint docker-customization/requirements-build.lock.txt -r application/single_app/requirements.txt -r requirements-dev.txt
python -m pip check
```

For intentional maintenance, install the pinned resolver requirements, then
regenerate against authoritative release metadata:

```powershell
python -m pip install -r scripts/requirements-dependency-locks.txt
python scripts/lock_python_dependencies.py --uv uv
```

The generator keeps existing constraint selections by default, releasing only
an obsolete constraint for an explicitly changed direct pin. During a merge,
both parents supply the existing exact-version baseline. `--upgrade`
explicitly permits new selections, still subject to release-age checks.
`--profile` limits regeneration to one environment. A trusted `--index-url`
or local `--find-links` cache may be supplied; do not disable TLS validation
to work around package transport failures.

Review the `.lock.txt` and corresponding `.lock.json` together. Evidence
records input hashes, lock hashes, authoritative PyPI publication timestamps,
and grandfathered exact pins. Hashes normalize text line endings so Windows
checkout conversion does not invalidate unchanged evidence.

## npm, Ruby, and Terraform

Use `npm ci` with committed manifests/locks. The catalog SDK bootstrap verifies
that the generated compiler install command agrees with its committed graph,
then executes the compiler's install offline. A compiler SDK version change
must be reviewed rather than silently replacing the lock.

```powershell
python scripts/lock_npm_tooling.py
gh aw compile --no-logo --no-check-update refresh-model-catalog
```

The npm generator checks registry publication timestamps for all selected
packages and writes `package-lock.evidence.json`. The authored workflow is
`refresh-model-catalog.md`; regenerate its `.lock.yml`, not just the generated
file. Existing application/browser-test npm locks retain their resolutions.

`docs/Gemfile` uses exact versions from `Gemfile.lock`; use its recorded Bundler
version and frozen installation. Terraform's CLI and provider constraints in
`deployers/terraform/main.tf` match the committed provider lock. Do not run
dependency-upgrade commands as part of ordinary builds.

## Images, OS packages, and downloaded artifacts

Container bases use immutable SHA-256 digests with readable release tags where
available. `scripts/dependency-selections.json` records verified distribution
publication evidence for newly selected images/runtimes and the Simba archive.
OCI build timestamps alone are not registry publication timestamps.

`docker-customization/azurelinux-packages.lock.json` contains the exact RPM
URLs, SHA-256 checksums, publication timestamps, and base-image identity for
the main image's common and optional Chromium closures.
`install_locked_rpms.py` verifies downloads before invoking `tdnf` with every
repository disabled. No package-resolution fallback is permitted.

To regenerate that lock, run `scripts/lock_azurelinux_packages.py` **inside
the exact builder image recorded in the lock**, with the repository mounted as
`/workspace` and that directory selected as the working directory. It resolves
against tdnf's 14-day snapshot, verifies signed-repository metadata and package
checksums, and models common packages before Chromium. Review the closure and
rebuild both enabled/disabled browser configurations.

The devcontainer base and Databricks customization use Ubuntu/Debian snapshots
at `20261104T000000Z`. Only expired snapshot `Valid-Until` checks are disabled;
archive signature verification remains enabled. Advance snapshots only
deliberately, preserving the 14-day minimum.

The Databricks Dockerfile is a caller-supplied application template. Its build
context must now provide `requirements.txt`, its complete
`requirements.lock.txt`, and `requirements-build.lock.txt` (the repository's
generated build constraints can be copied). Driver version changes also
require an independently verified archive SHA-256. The template's existing
Python 3.13 copy-path inconsistency is not repaired by dependency pinning.

## Auditing and honest limits

```powershell
python scripts/check_dependency_pins.py
python -m pytest -q -p no:cacheprovider functional_tests/test_dependency_pin_audit.py functional_tests/test_registry_destination.py
```

The audit reports active manifests, installer wiring, release evidence, image
digests, workflow selectors, and ecosystem lock drift. It is not a substitute
for clean installs, `pip check`, real builds, or owner-runtime tests.

Devcontainer feature/tool/editor closure remains unresolved and deliberately
fails the audit. Feature installers may introduce implicit GitHub CLI
dependencies, unpinned pip/pipx tooling, editor extensions, or additional OS
repositories. Pinning only their OCI artifact would create a false guarantee.

Versioned GitHub-hosted runner labels still receive vendor-managed image
updates. Preinstalled tools and externally managed Azure services are not made
byte-immutable by a runtime selector or client-library lock. A fully immutable
runner or retained private package infrastructure requires a separate
infrastructure decision.
