# Shared PR check remediation

Version: **0.261.400**, tracked in `application/single_app/config.py`.

Fixed/Implemented in version: **0.261.399**; current-base integration and
authorized staging CI setup in **0.261.400**.

## Issue and root causes

The check rollups on closed PRs #1867 through #1874 repeated a few shared
failures rather than identifying a separate defect in every PR.

- Advanced CodeQL uploads were rejected because repository Default setup was
  also enabled. The three failed language jobs were processing failures, not
  three independently confirmed vulnerabilities.
- The Windows Cosmos contract command expanded every selector into the process
  command line. The baseline's 183 targets produced 35,103 characters, exceeding
  the 32,767-character Windows limit.
- Three headless citation cases expected the old document-only behavior for a
  selected Search `evidence` output. The intentional 0.261.365 implementation
  already preserved its verified passage citations.
- The credential reconstruction probe counted calls on the upstream Semantic
  Kernel math class, but SimpleChat's loader instantiates its overriding local
  plugin. Actual completed work was therefore counted as zero.
- The legacy recovery fixture returned raw SDK `CosmosDict` responses to a
  domain callback requiring a plain dictionary. Strict retained-producer
  validation correctly refused those records before adapters ran.

The retired Azure tenant was a separate live-environment problem. It does not
explain these network-blocked fixture failures or the GitHub CodeQL
configuration conflict.

## Technical changes

### Portable contract runner

`scripts/check_cosmos_response_boundaries.py` writes the complete selection to a
temporary UTF-8 pytest argument file and invokes pytest in a fresh subprocess.
The file is closed before the child reads it and removed after completion or a
launch error. Node IDs, environment inheritance, child exit codes and the
pre-collection network guard are preserved.

Pytest argument files are supported by the existing pinned version. No
dependency update or in-process pytest workaround is needed.
`functional_tests/test_cosmos_contract_runner.py` covers selections beyond the
Windows limit, spaces, exact selected node IDs, real guarded collection,
nonzero child status, launch failure and cleanup. It is included in the core
contract selection; no existing evidence targets or exemptions were removed.

The existing scanner's self-inventoried synthetic fixtures remain unchanged.
No legacy baseline or inventory classification was expanded to accommodate the
new runner tests.

The complete successful Windows run took 23 minutes 28 seconds for pytest,
longer than the previous 20-minute job budget. The dedicated contract job now
has a bounded 30-minute budget so successful continuation coverage is not cut
short. Tokenizer assets are still prepared before network blocking, and no
test selectors or guards were removed.

### Citation and credential fixture alignment

`functional_tests/test_orchestration_harness_execution.py` now verifies the exact
two retained chunks, page numbers and evidence IDs for Search evidence, together
with saved-message, completion-frame, cache and used-document agreement.
Source-free/no-response behavior, sibling exclusion, current access checks and
delivery-only refresh remain covered. The feature description in
`CHAT_ORCHESTRATION.md` now describes the already implemented behavior.

`functional_tests/test_action_credentials_chat_reconstruction.py` instruments
`semantic_kernel_plugins.math_plugin.MathPlugin`, records successful real
results, and checks the initial result is exactly `"5"`. Its continuation
privacy, configuration-mutation, streaming, persistence/publication-failure and
duplicate-execution checks are unchanged.

`functional_tests/test_orchestration_dependency_recovery.py` normalizes point
and returned-write responses at its transport-to-domain fixture boundary using
`normalize_cosmos_document`. The container still returns the installed SDK's
`CosmosDict`; ETags and all record fields survive. The product's strict
dictionary, ownership, producer and recovery validators were not relaxed.

### Coverage-preserving CodeQL preparation

`.github/workflows/codeql.yml` adds `main` and `Staging` push/PR coverage while
retaining `Development`, the temporary V2 branch, all three languages and
`+security-and-quality`. A weekly default-branch schedule is included.
Configuration regressions live in
`functional_tests/test_codeql_workflow_configuration.py`.

This source change is not proof of a completed live cutover. The updated
workflow must be present on the relevant branches before disabling
repository-wide Default setup. Scheduled workflows run from the default branch;
an edit only on the feature branch cannot restore that scheduled coverage.
Do not suppress upload errors, reduce queries, or disable current scanning to
make a feature-branch check appear successful.

### Existing-staging validation and local configuration

`.github/workflows/staging-ui-smoke.yml` now validates an existing deployment
without running `azd`, restoring deployment secrets, or provisioning resources.
It requires an explicit HTTPS staging URL and application authentication,
retains OIDC and both existing authenticated smoke paths, verifies TLS, and
labels authentication redirects as reachability rather than application health.

The selected target is
`https://simplechat-2026stage-app.azurewebsites.net/`. Beta remains manual-only.
There is no inferred deployment name or automatic beta fallback.

`STAGING_UI_VALIDATION.md` documents the current workflow; the older versioned
guide is explicitly historical. The local guide and `example.env` distinguish
the app's tenant/client/secret, the independent Flask signing secret, and the
separate Actions identity. The template now includes the existing runtime
setting `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET`.

Initial source validation changed no Azure configuration. The subsequent
authorized staging-only authentication setup is recorded below. No application
deployment was performed. The unchanged standalone deployment bootstrap is not
part of the validation-only path.

## Validation

The following **0.261.399 pre-integration** results were obtained locally and on
GitHub's `ubuntu-latest` runner, with external network access blocked where
application owners execute. They do not establish success on the later merge
context; current-base review is recorded below.

| Selection | Result |
|---|---|
| Portable runner regressions | 3 passed in normal Python; 3 passed in optimized Python |
| Complete credential reconstruction file | 24 passed |
| Citation delivery matrix and dedicated Search citation suites | 40 passed |
| Recovery fixture, checkpoint-child citations and saved Compose permission | 16 passed |
| Selected saved-composition continuation and scheduler replay checks | 4 passed |
| CodeQL and staging/local configuration regressions | 11 passed |
| Existing dotenv-profile regressions | 3 passed |
| Documentation surface coverage | 7/7 checks passed |
| Documentation site quality | 6/6 checks passed |
| Actionlint 1.7.12 on all three changed workflows | Passed |
| Complete reviewed Cosmos contract command on Windows | 1,881 passed; 416 subtests passed; 1,086 owners and 423 doubles with zero review gaps |
| Live Ubuntu Cosmos contract workflow | 1,881 passed; 416 subtests passed; the same owners/doubles with zero review gaps |

The [successful Linux run](https://github.com/microsoft/simplechat/actions/runs/41901934773)
used published feature SHA `f263fa8172d50a1d6f08dc9da51ba9c438c86697`.
Pytest took 20 minutes 11 seconds and the complete job took 23 minutes 31 seconds,
confirming that the old 20-minute job limit was insufficient for the successful
suite. The 30-minute budget remains bounded. This was the isolated,
network-blocked contract workflow, not a staging deployment or live chat test.

Primary commands:

```powershell
python .\scripts\check_cosmos_response_boundaries.py --run-contracts
python -m pytest .\functional_tests\test_cosmos_contract_runner.py -q
python -O -m pytest .\functional_tests\test_cosmos_contract_runner.py -q
python -m pytest .\functional_tests\test_codeql_workflow_configuration.py .\functional_tests\test_staging_ui_cicd_workflow.py -q
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
```

For affected application selections, set `PYTHONPATH` to the application and
functional-test directories and retain `-p test_support.cosmos_network_guard`.
Targeted success is not a substitute for the complete gate or live tenant
verification.

## Initial live-transition findings

The read-only preflight found the GitHub `Staging` Environment still referenced
the retired tenant and deployment. A subsequent check after repository access
was restored confirmed that its configured tenant and base URL still do not
match the verified staging app. The corrected staging hostname is reachable and
redirects to the replacement tenant, but this is not authenticated application
validation.

A subsequent read-only ARM check confirmed that `simplechat-2026stage-app` is
running in `simplechat-2026stage-rg`. Its hosted tenant/client settings and
managed identity match the replacement tenant. The earlier resource-access
blocker is resolved; no tenant setting needed to be changed on that app.

At the initial checkpoint, no Playwright resource was found
across the four accessible enabled subscriptions, and the staging App Service
has no CI bearer-authentication, caller-allowlist or required-role overrides
configured. CI bearer authentication defaults to disabled. An approved
authenticated browser credential was not available to this run.

Its inspected sign-in registration has no registered identifier URI, and its
`Admin` role permits users, not application callers. Neither inspected hosted
registration has a local loopback redirect. Do not invent replacement
audience/workload values, reuse a hosted registration for localhost without
checking its redirects, or grant new access under the validation-only approval.
Creating the missing CI/browser infrastructure or enabling CI sign-in requires
specific approval beyond the then-current no-Azure-changes boundary. The owner
subsequently authorized staging-only access/configuration changes; the current
setup below replaces these initial blockers without a paid browser resource.

Before changing live GitHub Environment values, first activate the
validation-only workflow and confirm no older deploying run is active. Only
then apply a coherent, verified set of new-tenant values. New identities, role
grants, stored browser credentials, resource creation and Azure setting changes
require separate approval.

The CodeQL Default-to-Advanced switch likewise remains a coordinated
post-promotion operation. Neither old closed-PR statuses nor local configuration
tests establish that these live transitions have completed.

The CodeQL check still finds the old Development-only triggers on
`main` and `Staging`, with no schedule there, and Default setup remains enabled.
The updated source coverage must be promoted before disabling Default setup.

The earlier GitHub authorization blocker is resolved. After the owner restored
permissions, the current CLI credential was verified with repository admin,
maintain and push access, and reading the CodeQL administrative configuration
succeeded. No additional GitHub permission is currently needed. The remaining
GitHub step is publication/promotion of the prepared changes, followed by the
coverage-preserving settings cutover and fresh CI runs. Publishing an isolated
feature branch for contract verification does not promote the workflows or
authorize a merge or application deployment. No automatic account switch or
token-permission expansion was performed.

At that checkpoint, the older deployment-capable workflow was enabled with no
run in progress. It has since been explicitly disabled before configuring
replacement-tenant validation access; its old deployment secrets were not
refreshed.

A push-trigger audit also found that `Development` and `Staging` publish
`simple-chat-dev:latest` to two configured container registries, while `main`
publishes `simple-chat:latest`. A workflow-only promotion can therefore still
publish images. Protected-branch activation needs a separately approved,
deployment-suppressed cutover that preserves required validation and branch
flow. No release workflow was paused and no protected branch was changed for
the feature-branch verification.

Release-note and GitHub issue-publishing updates were not approved at the
source-validation checkpoint and remain unchanged. No issue or pull request was
created at that checkpoint.

## Current-base integration and authorized staging setup

The target branch advanced through two other merges while
[#1877](https://github.com/microsoft/simplechat/pull/1877) was being opened.
The incoming Excel change already failed its own inventory check with
75 storage-owner review gaps. These were separate from the repaired Windows
transport and original credential/citation runtime failures.

The feature branch was merged with target
`0ee8893cb38e647640626d5a4a201bfe6bb19d35` without rewriting published history.
Both lines had independently selected version 0.261.399, so the final
integration advances `config.py` to **0.261.400**.

### Renewed storage-owner review

| Module | Affected owners | Review outcome |
|---|---:|---|
| `functions_documents.py` | 45 | Native Excel extraction/import wiring changes the module fingerprint. Direct Cosmos operations and the existing Mapping/ETag consumers are unchanged. |
| `route_backend_chats.py` | 30 | All module fingerprints change; two chat handlers also gain native-inspection routing predicates. Their Cosmos point/query/batch operations and retry/history consumers remain unchanged. |

All ten existing affected-owner evidence selectors plus the incoming Excel and
available-information regression files passed: **105 tests**, with network
access blocked. The evidence exercises installed-SDK point responses, ordinary
query rows, conditional writes, processing guards, personal/group/public scope
and real chat recovery entry points.

The 75 entries retain their specific consumer classifications and existing
runtime evidence. Native ingestion and native report/search routing selectors
are added to the three directly affected review records. Runtime targets grow
from **185 to 187**; none are removed. The inventory reports **1,086 owners,
423 doubles and zero review gaps**. No legacy-double, source-only-owner or
compatibility-seam baseline was expanded or reset.

This is representative owner-runtime coverage, not a claim that every branch
of all 75 functions is exhaustively tested. Current complete-gate and live-run
evidence belongs in the PR validation record; the earlier 1,881-test runs above
remain explicitly scoped to their original feature baseline.

### Staging-only CI access

The owner explicitly authorized Azure/GitHub permissions and Environment
configuration for `https://simplechat-2026stage-app.azurewebsites.net/`.
The older deploying workflow was disabled, with no active run, before access
was configured. A separate **Staging-Validation** GitHub Environment avoids
reactivating the retired deployment context.

The new dedicated workload uses GitHub Environment-bound federation, has no
client secret, and holds only the staging application's **User** role. Its
registered API audience matches the existing bearer validator. The staging
endpoint is enabled with that exact caller allowlist and required User role;
App Service Easy Auth remains enabled. No Admin role, Azure RBAC grant, browser
workspace, beta configuration or production configuration is added.

Both existing smoke paths now run Chromium directly on the GitHub runner.
Azure login permits no-subscription access because application authentication
does not require deployment permissions. Authenticated traces and browser
state are excluded from artifact upload; only failure PNGs are published.
Generated local browser dependencies/reports are ignored rather than committed.

See [Existing staging UI validation](../features/STAGING_UI_VALIDATION.md)
for the four required Environment values, supported authentication paths and
the distinction between testing an existing app and deploying PR source.
Configuration success alone is not reported as an authenticated smoke pass.

### Remaining CodeQL activation boundary

Repository administration is working. Normal protected-branch promotion still
requires a controlled CI-only cutover, because push-triggered publishers can
update latest container tags even when application source is unchanged.
Specific permission for that protected-branch promotion/publisher pause was
requested but no affirmative response was available. Default setup therefore
remains enabled until the prepared Advanced coverage reaches the relevant
branches; its upload conflict is not hidden or reported as resolved.

## Future phase work

### A. Security-alert remediation

Refresh the stale CodeQL baseline after scanning works, classify actual current
source-to-sink findings, and fix verified critical/high issues before medium
issues. The recorded 3,320 alerts across 82 families include quality notes and
stale results, not 3,320 confirmed current vulnerabilities. No bulk dismissal,
query reduction or broad security refactoring is included in this change.

The separate default-branch Dependabot queue contains 100 open alerts:
7 critical, 52 high, 39 medium and 2 low. Patch metadata exists for 99 alerts.
The manifests account for 94 application-requirements alerts, four dev-
requirements alerts, one Playwright npm-lock alert and one documentation Ruby-
lock alert. Compare the exact current feature-branch pins and affected runtime
paths before treating default-branch reports as current defects or applying
upgrades. No dependency pins were changed in this remediation; the browser-test
package manifest only adds its runner-local command.

### B. Broader runtime correctness and test integrity

Review unrelated assertion side effects, unsafe initialization, incorrect calls,
resource/error handling and obsolete harness expectations in a separately
approved phase. This includes the historical maintenance fake-config lead when
not required by the current gate.

A supplemental run also exposed an unchanged exact capability-list expectation
in `test_orchestration_dependency_allowlist.py::test_registry_metadata_expresses_roles_without_phases_or_a_terminal_step`.
It describes an older catalog and is not reported as passing or silently
reclassified as one of the repaired continuation failures.

### C. Import structure and remaining quality

Review cyclic/polluting imports and remaining unused-code/query families by
proven dependency cluster. Preserve registration, cache/bootstrap ownership,
scheduler wiring and real cold-import behavior. Broad import cleanup is not
part of these focused CI repairs.

## Impact

No database migration, historical-run rewrite, new application capability switch,
browser runtime dependency or deployer change is included. The application
version is **0.261.400**; `deployers/version.txt` is unchanged because no file
under `deployers/` was modified.
