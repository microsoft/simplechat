# Brotli Runtime Security Fix

Version: **0.261.455**, tracked in `application/single_app/config.py`.

Fixed/Implemented in version: **0.261.453**. Deployer version: **1.0.38**.

## Issue and root cause

SimpleChat's Python Playwright dependency includes its own Node executable.
The former `playwright==1.58.0` pin bundled Node 24.13.0, which predates the
Brotli decoder fix described in
[Node's October security advisory](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases).
Updating a machine's system Node does not replace this embedded executable.

The frontend Docker build, staging UI workflow, and optional standalone frontend
App Service also selected the unsupported Node 20 release line. The Docker
frontend builder is separate from the production Python image; its Node
executable is not copied into that image. Playwright's Node executable is.

The public Brotli issue is CVE-2026-111497. A notification without a CVE or
affected-resource inventory cannot establish that it describes this exact
advisory or that a SimpleChat execution path is exploitable. These updates
remove the identified old runtime selections without claiming such proof.

## Changes

| Component | New baseline | Files |
| --- | --- | --- |
| Production and Python test browser driver | Playwright 1.65.1, bundling Node 26.13.1 | `application/single_app/requirements.txt`, `ui_tests/requirements.txt` |
| Node native runtime | Install and copy Azure Linux `libgcc-atomic` independently of the Chromium build option | `application/single_app/Dockerfile` |
| Frontend build | Azure Linux Node 24.22.3 image, tag `24.22.3-1-azl3.0.20261116` | `application/single_app/Dockerfile` |
| Staging UI test runner | Node 24.22.3 | `.github/workflows/staging-ui-smoke.yml` |
| Optional standalone frontend host | Platform-maintained `NODE|24-lts` | `deployers/bicep/modules/v2FrontendAppService.bicep`, regenerated `deployers/bicep/main.json` |

These versions also include
[Node's November security updates](https://nodejs.org/en/blog/vulnerability/november-2026-security-releases),
rather than stopping at the October Brotli fix. The regression test therefore
uses the November floors: Node 22.23.5, 24.22.3, and 26.13.1 for those respective
reviewed release lines.

Flask remains the production application server. The default same-origin V2
deployment, optional-host default, Chromium build opt-out, URL access controls,
and browser launch settings are unchanged. No workstation tools or existing
Azure resources are patched by these source changes.

## Compatibility considerations

Playwright 1.65.1 requires Python 3.10 or later; the production image and staging
workflow use Python 3.12. The existing pytest/plugin requirements permit the new
Playwright version. The frontend and JavaScript test packages' declared Node
engine ranges permit Node 24, so they are not upgraded as part of this fix.

The final pin is 1.65.1 rather than the initially proposed 1.65.2 because the
local package source offered 1.65.1. Both upstream releases specify Node
26.13.1; the actual installed Windows and Linux executables were also checked.
The selected release meets the same November security floor without a system
Node override.

The embedded Node 26 driver and the independent Node 24 build/hosting processes
do not need matching major versions. Likewise, the Python and JavaScript browser
test runners each need the browser revision selected by their own Playwright
package. Reusing an arbitrary browser executable between versions is not a
compatibility check.

[Playwright's release notes](https://playwright.dev/python/docs/release-notes)
describe changes to inert-element actions, accessible names, cookie matching,
and headless clipboard handling. Relevant SimpleChat checks include mobile
drawers/dialogs, browser clipboard uploads, authenticated request setup, and
Source Review's rendered-page and Load More workflows.

Azure Linux is not an officially supported Playwright browser distribution.
SimpleChat's existing packaging copies browser libraries and fonts into its
distroless image, so the upgraded Chromium and Node must be checked in that
final image as the non-root runtime user. A successful Windows browser test or
Python dependency install does not establish Linux container compatibility.

The image checks exposed a real compatibility issue with the Node 26 upgrade:
the Chromium-disabled image could not start the driver because
`libatomic.so.1` was missing. The normal browser package installation happened
to supply that library, hiding the problem in the default image. The Dockerfile
now installs `libgcc-atomic` and copies its shared library outside the Chromium
condition. The opt-out still omits Chromium and its browser-only dependencies.

The optional Azure-hosted Python test fixture is also distinct from the
[officially documented Workspaces runners](https://learn.microsoft.com/en-us/azure/app-testing/playwright-workspaces/resource-limits-quotas-capacity).
Keep local Python validation separate from the supported JavaScript service
runner; do not infer remote-service compatibility from a local pass.

## Applying the fix

1. Rebuild the application image with refreshed bases and the updated
   requirements. The existing Docker build installs the Chromium revision
   belonging to the Python package. Preserve sandbox settings and run the
   resulting browser check under the image's configured non-root user.
2. Deploy the new image using the deployment process for the installation.
   Existing images do not acquire a new Python wheel, embedded Node, or
   Chromium merely because this repository changed.
3. For non-container installations, install the updated requirements and run
   `python -m playwright install chromium` in that same Python environment.
4. If separate frontend hosting is enabled, verify Node 24 LTS availability in
   the target cloud/region before applying the updated deployment template.
   Verify the actual host's Node patch level; `24-lts` is maintained by Azure
   and is not an exact patch pin.
5. Verify the actual Playwright driver, including any
   `PLAYWRIGHT_NODEJS_PATH` override. An override can otherwise select a
   vulnerable system executable despite an upgraded wheel.

To print the effective Python driver's Node version without bootstrapping Flask:

```powershell
python -c "from playwright._impl._driver import compute_driver_executable; import subprocess; node, _ = compute_driver_executable(); subprocess.run([node, '--version'], check=True)"
```

The helper is a Playwright internal API used here for operator verification, not
an application dependency. For the standard wheel without an override, expect
Node 26.13.1.

## Validation

`functional_tests/test_brotli_runtime_security.py` checks the installed Python
package against the app/test pins, executes the bundled and effective Node
drivers, rejects old/unreviewed runtime versions, and checks build/CI settings
and Bicep/generated ARM agreement. Runtime assertions are not replaced with
source-only checks when an old local package is installed.

Existing Source Review, Chromium build-option, staging-workflow, and relevant
browser interaction tests provide compatibility coverage. Full dependency,
browser, and final-image validation results must be recorded before treating a
deployed installation as remediated.

### Results and deployment limits

The implementation was checked with the following results:

| Check | Result |
| --- | --- |
| V2 production build using Node 24.22.3 | Passed: TypeScript and Vite completed. |
| Actual pinned Azure Linux Node image | Passed: the image executable reports Node 24.22.3. |
| Docker frontend build stage | Passed: `docker build --pull --progress plain --target v2uibuilder --tag simplechat-brotli-v2-validation:0.261.453 --file application\single_app\Dockerfile .` completed. The resulting image reports Node 24.22.3 and contains the built SPA. This does not validate the final Python image. |
| Full local production Docker build | Passed with default Chromium and FFmpeg options, using the local-only package-source overrides described below. Image: `simplechat-brotli-validation:0.261.453`. |
| Chromium opt-out Docker build | Passed with `INSTALL_PLAYWRIGHT_CHROMIUM=false`. Image: `simplechat-brotli-validation:0.261.453-no-chromium`. Node starts successfully, and the matching Chromium executable is absent. |
| Final-image browser smoke | Passed as UID 65532: Playwright 1.65.1, bundled Node 26.13.1, and Chromium 158.0.8127.18. Verified actual DOM input, button interaction, and PNG rendering without external requests or privileged container flags. |
| Clean application dependency consistency | `python3 -m pip --no-cache-dir check` reported no broken requirements in both final images. |
| Runtime regression file in Linux images | All 15 checks passed in each final image, including the Chromium-disabled image that previously failed to load Node. Test tooling was installed only in temporary test containers, not the application images. |
| Independent JavaScript runner on Node 24.22.3 | Passed: test discovery and a local Chromium 148.0.7778.96 click/DOM smoke. No staging request was made. |
| Bicep regeneration using 0.44.1 | Passed: only the optional-host runtime and generated template hashes changed. Existing nullable-resource/type warnings remain. |
| Upgraded Python compatibility suite | 92 passed with Playwright 1.65.1: complete runtime regression coverage, Source Review, Chromium build-option/deployer contracts, and the three custom local UI suites. No runtime tests were excluded. |
| Documentation site quality | All six checks passed. |
| Custom local UI harnesses | All 46 mobile-navigation, orchestration-retry, and clipboard-upload checks passed on upgraded Playwright. These exercise real components and production CSS with synthetic HTTP boundaries, without live staging/model calls. They are included in the 92-test total above. |

The targeted host command, using an environment with the updated requirements,
was:

```powershell
python -m pytest functional_tests\test_brotli_runtime_security.py functional_tests\test_source_review_security.py functional_tests\test_source_review_deep_traversal.py functional_tests\test_deep_research_chromium_build_opt_out.py functional_tests\test_deployer_version_tracking.py ui_tests\test_v2_mobile_navigation.py ui_tests\test_v2_orchestration_planning_retry.py ui_tests\test_v2_chat_clipboard_uploads.py -q -p no:cacheprovider
```

### Local-only package-source setup

Initial direct-public-index builds failed during TLS negotiation with
`files.pythonhosted.org`. Local verification then used the workstation's
existing machine-wide pip configuration, mounted as a BuildKit secret.
The dependency-install instruction was overridden in a Dockerfile supplied
through standard input, not by adding machine-specific settings to repository
files.

A transient feed response also failed pip's wheel hash check. A fresh copy of
the same pinned urllib3 wheel was checked against its authoritative PyPI
SHA-256 digest and mounted for the local build, with the digest checked again
inside the build. No TLS or artifact-integrity checks were disabled.

The repository's `docker-customization/pip.conf` remains unchanged. The final
images were checked for local pip configuration; it was not retained.

Live Azure authentication, remote Workspaces execution, and the optional
App Service host were not exercised. Existing deployed images and hosts still
need the normal deployment and runtime-verification steps above.

Two unrelated baseline checks were not changed: the staging
workflow test expects a 30-minute Cosmos job while the checked-in workflow uses
45, and the shared-source test treats the existing `static/v2` build-output
exclusion as an excluded source directory. Neither unrelated expectation was
changed by this fix.
