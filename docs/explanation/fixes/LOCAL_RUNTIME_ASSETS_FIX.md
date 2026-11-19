# Local runtime assets fix (0.261.456)

## Issue and root cause

**Fixed in version: 0.261.456**, recorded in `application/single_app/config.py`.

The application already served its main browser libraries locally, but the
local-only rule was not enforced across every repository-owned browser surface.
Seven standalone table fixtures contained 21 CDN references, and two Python
generators could recreate CDN-backed pages. The docs layout retained an optional
Google Analytics script loader. The locally vendored Teams SDK also fetched its
trusted-domain JSON from Microsoft's CDN.

Existing tests checked selected CDN hostnames. They could miss another external
host, conditional documentation markup, or a library's computed companion fetch.

## Changes and impact

The seven HTML fixtures and both generators now reference repository copies of
Bootstrap 5.3.3, Marked 15.0.7 and DOMPurify 3.4.14. The sanitizer comes from the
existing V2 vendor directory, not the older classic-client copy. Relative paths
resolve from the generated HTML's directory; the generators already place output
beside their own Python files rather than in the caller's working directory.
The fixture demonstration styles and conversion algorithms are unchanged.

`docs/_layouts/default.html` no longer includes the optional remote Google
Analytics loader or its initialization. Setting `google_analytics` does not
reintroduce remote JavaScript.

The Teams SDK remains version 2.19.0. Its single domain-list fetch now uses
`/static/js/teams-2.19.0/validDomains.json`. The snapshot is identical to the
SDK's embedded 35-domain list, rather than a live CDN response. Its existing
origin matching and embedded-list fallback are preserved. Future upstream
domain additions require an intentional reviewed update; they no longer
silently change the trusted hosts at runtime.

The application CSP explicitly declares `worker-src 'self'`. Script, style
and font external origins remain self-only. API connectivity, token exchange,
package installation, lockfiles, build dependencies, map data, user links and
user-supplied media are unchanged. No new routes or settings are introduced.

## Enforcement and vendoring

Run the shared checker from the repository root:

```powershell
python scripts\check_browser_assets.py
npm --prefix application\v2_ui run build
python scripts\check_browser_assets.py --require-v2-build
```

`scripts/check_browser_assets.py` checks asset tags, import maps, module/worker
loaders, CSS imports and font URLs, source-map URLs, simple computed targets,
and Python-generated HTML. Its diagnostics include the file and line.
Normal Vite package imports remain build dependencies. Local CSS/font companions
must exist, including the complete vendored KaTeX font set.
UI harness bundles may be absent before their tests compile the adjacent
`harness_entry.tsx`; those sources are scanned as well. In-memory UI fixtures
still receive external-loader checks without requiring their virtual routes
to exist on disk.

`functional_tests/browser_asset_inventory.json` records local dependencies,
attribution and patch provenance. It pins 27 existing minified source
distributions by SHA-256. A changed or new minified distribution requires
renewed review, because identifier reuse makes cross-scope string resolution
unreliable in a static pattern checker. Built V2 output is checked but is not
committed or assigned source-distribution hashes.

For an update, obtain the intended pinned upstream distribution, retain its
required attribution, review its executable and companion loaders, and update
only the reviewed inventory entries. Reapply the documented Teams URL patch if
needed. Verify the SDK snapshot against the embedded list and inspect any
intentional domain changes. Do not refresh hashes merely to dismiss a failure.

Local-only references to optional development source maps are retained even
where the upstream map was not vendored. They do not redirect to remote maps.

`.github/workflows/browser-assets-check.yml` builds V2 and requires compiled
output, runs the shared guard and its contracts, and exercises the real vendored
libraries in Chromium. It does not change dependency manifests or publishing
workflows.

The workflow runs on relevant pull requests targeting `Development`, on every
push to `Development` (including merges, without a path filter), and manually
through `workflow_dispatch`. Each run checks remote runtime-asset references,
required local companions and reviewed vendor hashes after building V2.
Normal package installation and external data APIs remain allowed.

The post-merge scan detects a regression after it lands. To block a pull request
before merging, require the `browser-assets` job from the **Local browser assets**
workflow in the repository's branch protection or ruleset. This change does not
modify repository protection settings.

## Validation and limitations

The regression suites are `functional_tests/test_browser_assets.py` and
`ui_tests/test_local_runtime_assets.py`, with the existing V2, documentation,
OpenLayers and Teams checks integrated.

Browser tests execute real local chart, diagram, math, map, editor, Swagger and
documentation vendor libraries. They load KaTeX fonts and a real Prism worker,
test every changed standalone fixture's local parser/sanitizer, and verify
external data APIs still work using controlled responses. Teams tests exercise
real SDK initialization for approved, wildcard and government hosts and reject
a lookalike origin, including missing/malformed local-metadata fallback.

The scanner is not an interprocedural JavaScript analysis or a vulnerability
assessment. Hash checks enforce review of minified changes; they do not prove
that a library is secure. Browser coverage is representative and isolated:
it does not claim that every authenticated production workflow was exercised.
The standalone fixtures' pre-existing conversion demonstrations are not repaired
by this change; the tests verify asset loading and rendering with the real
local parser and sanitizer.

The pre-change functional baseline had three failures: a stale exact-version
assertion in the OpenLayers asset test and two unrelated rich-rendering
expectations. Only the directly related version assertion is changed here,
to use the shared minimum-version helper.

### Results

- `npm --prefix application\v2_ui run build`: passed.
- `python scripts\check_browser_assets.py --require-v2-build`: passed with
  zero findings across source trees and compiled V2 output.
- Integrated browser-asset, V2, documentation and OpenLayers functional suites:
  50 passed. The repository-scan test was deselected in that run because the
  preceding CLI command independently exercised the same full scan and inventory.
- Real-browser local-runtime and existing Teams login suites: 26 passed;
  OpenLayers and three applicable Teams SSO contracts also passed in that run.
- First-party changed-file XSS sink validation, Teams SDK JavaScript syntax,
  workflow YAML parsing and whitespace checks: passed.

Two additional historical Teams SSO tests fail independently of this change:
one requires the obsolete exact application version `0.242.072`, and another
reads the removed `docs/how-to/teams_app.md` path. They are left unchanged,
as are the two pre-existing rich-rendering expectations above.

A production Jekyll build was not completed: the pinned Ruby gems were not
installed, and an isolated frozen dependency restoration did not finish.
Documentation source checks and real local documentation-library loading passed;
these results do not claim a successful production documentation build.
