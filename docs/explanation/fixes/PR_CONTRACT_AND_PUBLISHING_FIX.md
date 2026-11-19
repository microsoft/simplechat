# Development PR contracts and reproducible dependency installation

Version: **0.261.460**, tracked in `application/single_app/config.py`.

Fixed/Implemented in version: **0.261.454**.

## Issue and root causes

Development's Cosmos inventory rejected 31 stale owner reviews before running
the runtime contracts. A module-wide AST change invalidates every owner review
in that module, even when the owner's implementation is unchanged. Thirty
affected owners were unchanged; `orchestration_plan` only stopped binding an
unused local while retaining its export catalog in the context.

The Development image publisher built successfully but could not resolve one
configured registry hostname from its GitHub-hosted runner. Its other
destination succeeded. This is a separate configuration/network failure, not
evidence of a Docker compilation failure.

Dependency installation also had floating image/runtime selectors and
transitive resolutions. An exact direct requirement alone does not pin the
packages that requirement installs.

The credential import-graph guard additionally exposed a reverse dependency
from execution context through action-usage reporting into initialized
application owners. Deferred imports did not remove that cycle.

## Changes and impact

`functional_tests/cosmos_response_boundaries.json` renews the 31 owner reviews
after examining their consumers and existing real-owner runtime evidence.
SDK response contracts, module fingerprints, network blocking, classifications,
and required runtime evidence remain enforced.

`action_usage_context.py` now owns the shared task-local identity below both
`agent_execution_context.py` and `action_usage.py`. Existing reporting imports
remain compatible. Fresh normal/optimized probes in both import orders verify
shared identity, nested workflow preservation, copy isolation, exception
cleanup, and absence of configuration/credential-owner bootstrap.

The shared AST-extraction test harness now supplies the real exception-outcome,
deadline, and copied-worker-context dependencies used by the production
workflow runner. Handoff tests pass their existing fixture settings into
sequence execution instead of replacing them with an empty dictionary.
Production policy checks and timeout behavior are not bypassed.

`docker_image_publish_dev.yml` checks destination DNS and TCP port 443 before
login/build and separates building, tagging, and pushing. Both destinations,
versioned tags, and the application's ACR `latest` tag remain. A failed
versioned push stops the subsequent `latest` push. Diagnostics do not print the
registry hostname or underlying exception.

Consumed Python constraints now cover application/development/UI, catalog,
deployer, external-app, resolver, and isolated build dependencies. Tooling npm
locks cover the generated catalog SDK and devcontainer CLI. Image digests,
workflow runtimes/runners, Ruby declarations, and Terraform constraints are
explicit. The main image installs checksum-verified RPM closures with package
repositories disabled. Ubuntu/Debian package installs use frozen signed
snapshots; signature checking remains enabled.
The Azure Linux builder installs its pinned pip under `/build-assets/pip`
instead of uninstalling or overwriting RPM-managed Python packages. Only the
dependency-install command selects that build tool through `PYTHONPATH`.

See the [dependency maintenance guide]({{ '/contributing/dependency-pinning/' | relative_url }})
for regeneration commands, release-age evidence, and limitations.
Deployer changes are tracked separately as `deployers/version.txt` **1.0.39**.

## Development integration

The conflict resolution preserves Development's Node **24.22.3** builder and
Playwright **1.65.1** security updates. The Node image additionally uses its
verified MCR manifest digest. These existing exact versions are inherited
from Development, not newly selected older releases to satisfy the age policy.
The selection ledger records the immutable source commit; the audit verifies
that commit contains the inherited pin.

The application lock is regenerated for both supported platforms, changing
only the Playwright package version while retaining other constraint versions.
The resolver drops an obsolete constraint only when an explicit direct pin
changes, and recognizes pins from both merge parents. The common RPM profile
includes `libgcc-atomic`, so the Playwright Node driver retains its required
library even when Chromium is disabled, without adding floating package installs.

The five conflicting user-route review fingerprints retain Development's
reviewed module identity and its added owner-runtime evidence. The application
version advances beyond Development to **0.261.460**.

The newly inherited browser-assets workflow uses the same exact Python, patched
Node, and runner versions as the other pinned jobs, and installs the declared UI
test requirements through the shared constraints.

After integration, the locked Windows environment passed `pip check` and **52
focused tests** covering pin/registry safeguards, patched runtime execution,
and dependency compatibility. Another **70 tests** passed with networking
blocked, covering merged user-route Cosmos evidence and credential/workflow
regressions. The real patched Node TypeScript/Vite Docker
stage also built successfully. Documentation coverage and site quality passed
**7/7** and **6/6** checks respectively. The inventory still reports **1,107
owners, 433 doubles, and zero review gaps**. The dependency audit now inspects
**46 surfaces** and retains only its documented devcontainer closure finding.

The merged production Python builder also completed using a temporary context
that routes pip through the approved Microsoft mirror; no repository feed or
TLS settings were changed. Its Linux `pip check` passed. A nonroot distroless
probe with networking and Chromium disabled executed Playwright **1.65.1**'s
bundled Node **26.13.1**, found the copied `libatomic`, loaded the ODBC driver,
and loaded the TLS trust store successfully.

## Validation and remaining work

`functional_tests/test_dependency_pin_audit.py` and
`functional_tests/test_registry_destination.py` cover incomplete locks,
cross-platform markers, portable evidence hashes, release-age boundaries,
artifact tampering, ecosystem lock drift, destination checks, and actual Bash
push-failure propagation: **31 tests passed**.

The pinned Node image completed the real TypeScript/Vite application build.
The actual Azure Linux builder completed with the isolated installer. Both
checksum-locked OS package profiles installed with repositories disabled.
The frozen documentation build and Terraform validation also passed.

Credential-bootstrap regressions passed **13 tests**, including the fresh
normal/optimized import probes. Workflow refusal, durable runtime, and handoff
regressions passed **61 tests** with the network guard enabled. Catalog
publication contracts passed **50 tests on each clean locked Python 3.11 and
3.12 environment**, with `pip check`. The generated catalog workflow also
matches recompilation from LF-normalized source.

A clean Windows application/development/UI installation succeeded fully
offline, including source builds with the pinned build constraints. Its
`pip check` and **four compatibility tests** passed. Downloaded inputs were
checked against authoritative PyPI hashes without disabling TLS.
Clean isolated Linux and fully offline Windows installations for the deployer
and combined external-app inputs also passed `pip check` and their real
dependency imports.

A distroless runtime-closure probe with optional browser/audio installation
disabled passed 19 package imports, configured ODBC driver discovery, and TLS
trust-store loading as UID 65532 with networking disabled. This probe reuses
the production dependency-copy steps, not the unrelated SPA/OneNote stages.
The enabled variant also completed the production Chromium/audio installation
steps: real Chromium rendered an offline page and the copied FFmpeg executable
ran successfully, again as UID 65532 with networking disabled.

Before the Development integration, the locked Linux prerequisite suite passed **53 tests**. The complete
network-blocked Cosmos contract gate then passed **2,378 tests and 471
subtests**, with **1,107 owners, 433 doubles, and zero review gaps**.
No test deadlines or strict response validators were relaxed. These full-gate
results describe the pre-integration snapshot, not the subsequently merged tree.

Publishing remains externally blocked until an administrator verifies
`ACR_LOGIN_SERVER` and the registry's DNS/network access from the selected
runner, then authorizes and completes a publish to **both** destinations.
No replacement hostname, secret change, registry change, or publishing run is
implied by these repository changes.

The dependency audit intentionally continues to report unresolved devcontainer
feature/tool/editor installation inputs; digest-pinning a feature alone does
not pin everything its installer downloads. This is not a completed
repository-wide pinning claim. The available package API access also returned
HTTP 403 for exact feature publication metadata; source commit dates were not
substituted for artifact publication dates.
