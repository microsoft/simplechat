---
layout: page
title: "Running the Tests"
description: "How to set up, run and extend SimpleChat's functional, JavaScript and UI test suites, including in a fork."
section: "Contributing"
permalink: /contributing/testing/
---

Implemented in version: **0.261.489** (`application/single_app/config.py`).

SimpleChat ships three test suites. All of them can run on a developer machine
or in a fork's CI without access to the SimpleChat team's Azure resources.
Tests that do need a live deployment skip themselves and say what is missing.

| Suite | Location | Runner | Needs |
|---|---|---|---|
| Python functional tests | `functional_tests/test_*.py` | pytest | Python packages only |
| JavaScript functional tests | `functional_tests/test_*.js`, `test_*.mjs` | Node's built-in test runner | Node and `npm ci` in `application/v2_ui` |
| UI tests | `ui_tests/test_*.py` | pytest with Playwright | Chromium, the built v2 SPA, and for some tests a running SimpleChat |

## One-time setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r application/single_app/requirements.txt -r requirements-dev.txt
python -m playwright install chromium
```

```powershell
cd application/v2_ui
npm ci
npm run build
```

`npm ci` is needed by the JavaScript tests that load the v2 UI's TypeScript
sources. `npm run build` writes the v2 SPA to
`application/single_app/static/v2/` (git-ignored), which the v2 UI tests serve.

Two pytest plugins are optional but strongly recommended for the full functional
suite, which has tens of thousands of tests:

```powershell
pip install pytest-xdist pytest-timeout
```

They are not in `requirements-dev.txt` because new dependencies go through the
[dependency pinning](dependency-pinning.md) review.

## Running the suites

`scripts/run_tests.py` runs each suite with the flags it needs:

```powershell
python scripts/run_tests.py functional
```

```powershell
python scripts/run_tests.py js
```

```powershell
python scripts/run_tests.py ui
```

```powershell
python scripts/run_tests.py all
```

Arguments after `--` go to pytest (or to Node for `js`), for example
`python scripts/run_tests.py functional -- -k image_edit`. With pytest-xdist
installed the functional suite runs one test file per worker
(`-n auto --dist loadfile`).

Running a single file still works both ways:

```powershell
python -m pytest functional_tests/test_message_image_revisions.py -q
```

```powershell
python functional_tests/test_message_image_revisions.py
```

JavaScript test files are run with Node's test runner. Several evaluate ES
modules through `node:vm`, so always pass `--experimental-vm-modules`:

```powershell
node --experimental-vm-modules --test functional_tests/test_workflow_settings_client.js
```

## Tests that need a live deployment

Most functional tests import application modules through the offline seams in
`functional_tests/test_support/` (`app_stubs`, `offline_bootstrap`) and never
touch Azure. A few still import the real `config.py`, which constructs a Cosmos
DB client and contacts the account while doing so. Those files call
`require_live_cosmos(__file__)` from `test_support/live_services.py` and are
skipped unless a Cosmos DB account is configured, either in the environment or
in `application/single_app/.env` (or the file named by `SIMPLECHAT_ENV_FILE`),
exactly as the app itself reads it. Set `SIMPLECHAT_TESTS_OFFLINE=1` to skip them
even when a deployment is configured.

When no Cosmos DB account is configured at all, `functional_tests/conftest.py`
lets the real `config.py` import against an in-memory Cosmos client
(`test_support/offline_cosmos.py`), so tests that only need settings and
containers to exist still run. Tests that depend on real data cannot pass that
way and should call `require_live_cosmos(__file__)`.

UI tests come in two kinds:

* **Offline UI tests** start a local Flask app with stubbed services and drive it
  with Playwright. They need Chromium and the built v2 SPA, nothing else.
* **Live UI tests** drive a running SimpleChat and skip unless
  `SIMPLECHAT_UI_BASE_URL` is set. Most also need a signed-in Playwright storage
  state in `SIMPLECHAT_UI_STORAGE_STATE` (and `SIMPLECHAT_UI_ADMIN_STORAGE_STATE`
  for admin pages).

## Known failures

Some functional tests fell behind the application and have not been fixed yet.
They are listed in `functional_tests/known_failures.txt`, one per line, each with
a reason:

```text
test_example.py::test_old_wording   # source text check out of date
test_hangs.py                       # whole file: hangs without Cosmos DB
```

* A listed test runs as an expected failure (`xfailed`), so the suite passes
  while only listed tests fail and any new failure stands out.
* A listed test that passes fails the run (`XPASS(strict)`). Remove its line in
  the same change that fixed it. The list can only shrink.
* A listed test with subtests counts as failing while it or any of its subtests
  fails.
* A listed file (no `::`) is not collected. This is only for the few files that
  cannot be imported or that hang.
* JavaScript tests are listed as whole files (`test_example.mjs  # reason`).
  `scripts/run_tests.py js` reports a listed file that fails as `xfail` and one
  that passes as `XPASS`, which fails the run.
* Never list a test that a GitHub workflow runs, directly or through
  `scripts/check_cosmos_response_boundaries.py --run-contracts`. A listed test
  that passes in CI would fail the build as `XPASS(strict)`, and a listed file
  would silently stop running there.
* Never add a test to the list to get a change merged. Fix the test, or fix the
  application if the test found a real problem.

To work on the listed tests, run them normally with
`SIMPLECHAT_IGNORE_KNOWN_FAILURES=1`. The UI suite has no such list.

## Writing and updating tests

New tests follow the template in `CLAUDE.md`. In short:

* Name files `test_{feature_area}_{specific_test}.py` (or `.js`). Only
  `test_*.py` files are collected; one-off debugging scripts belong in a
  `debug_*.py` or `quick_*.py` file, which pytest ignores.
* Start each file with its filename comment, then a docstring with
  `Version:` (the release the file was last validated against) and
  `Implemented in:` (the release the feature or fix shipped in).
* Check behavior with `assert`. A pytest test that returns `False` fails
  (#1572), but returning a value is only for the `__main__` runner.
* **Never assert an exact application version.** A check such as
  `'VERSION = "0.241.042"' in config_text` fails on the next version bump, and
  on every bump a fork makes, although the feature it guards is still there.
  Use `assert_app_version_at_least("0.241.042")` or
  `app_version_is_at_least(...)` from `test_support/versioning.py`.
* Import application code through `test_support.app_stubs` or
  `test_support.offline_bootstrap`, not the real `config.py`. If a test truly
  needs live services, call `require_live_cosmos(__file__)` before the first
  application import.
* Stubs that a test file installs in `sys.modules` at import time are taken back
  after the file is collected and re-installed while that file's own tests run
  (`test_support/module_isolation.py`), so they can no longer break files that
  run after it. Prefer `unittest.mock.patch.dict(sys.modules, ...)` inside the
  test anyway. Set `SIMPLECHAT_TEST_MODULE_ISOLATION=0` to switch the isolation
  off while investigating an ordering problem.

`scripts/normalize_test_headers.py` checks and fixes file headers:

```powershell
python scripts/normalize_test_headers.py --check
```

```powershell
python scripts/normalize_test_headers.py --write --set-version
```

`--set-version` sets every file's `Version:` line to the current `config.py`
VERSION. Run it after the whole suite passes against a release, for example
after merging upstream changes into a fork. `Implemented in:` is never changed.

## Keeping a fork's tests green

After merging an upstream release into a fork, or after customizing SimpleChat:

1. Reinstall requirements and rerun `npm ci` and `npm run build` in
   `application/v2_ui`.
2. Run `python scripts/run_tests.py all`.
3. A failing test either found a real regression in your change, or asserts
   upstream behavior you changed on purpose. In the second case update the test
   to describe your behavior; do not delete it.
4. Run `python scripts/normalize_test_headers.py --write --set-version` once the
   suites pass, and commit the result with your version bump.
