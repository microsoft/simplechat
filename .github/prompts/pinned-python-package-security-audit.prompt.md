---
description: "Use when: auditing SimpleChat pinned Python requirements, third-party package source or wheels, dependency advisories, transitive dependencies, supply-chain risk, hashes, licenses, or package update safety."
name: "Pinned Python Package Security Audit"
argument-hint: "Target requirements file, package names, direct pins only, include transitive deps, source review, scan only, or upgrade plan"
agent: "agent"
---

# Pinned Python Package Security Audit

Audit SimpleChat pinned Python dependencies for known vulnerabilities, supply-chain risk, package metadata issues, risky install/runtime behavior, and source-level concerns. This prompt covers direct pins in every `requirements.txt` and, when available, the transitive packages resolved in the local Python environment.

Primary requirement files in this repo include [application/single_app/requirements.txt](../../application/single_app/requirements.txt), [application/external_apps/bulkloader/requirements.txt](../../application/external_apps/bulkloader/requirements.txt), [application/external_apps/databaseseeder/requirements.txt](../../application/external_apps/databaseseeder/requirements.txt), [deployers/bicep/requirements.txt](../../deployers/bicep/requirements.txt), and [ui_tests/requirements.txt](../../ui_tests/requirements.txt).

## What Is Possible

You can inspect Python packages in several useful ways:

- Direct pins: parse every `requirements.txt` entry pinned with `==`.
- Installed packages: use the repo virtualenv to inspect installed package metadata and transitive dependencies.
- Advisories: run tools such as `pip-audit` or `pip index versions` if they are available and network access is allowed.
- Source/wheel review: download packages with `pip download --no-deps` into a temporary audit folder, extract wheels or source distributions, and review package code and metadata.
- Import-path review: inspect locally installed package files under `site-packages` when downloads are unavailable.

This does not prove a package is safe. Treat it as a practical, evidence-based review that combines advisories, provenance, install behavior, risky code patterns, and SimpleChat usage.

## Operating Rules

- Work in the SimpleChat repository root.
- Do not modify dependency versions unless the user explicitly asks for an upgrade plan or remediation.
- Do not install new audit tools without telling the user what is needed and why.
- Do not vendor or edit third-party Python package source in the app unless the user explicitly requests that path.
- Do not revert unrelated user changes.
- If the user asks for `scan only` or `report only`, do not edit files.
- Store temporary downloaded package archives under `artifacts/security/python-package-audit/` if downloads are needed, and keep generated artifacts out of commits unless the user asks to keep them.

## Baseline Discovery

1. Confirm the repo root, current branch, concise `git status --short`, and active Python path:

```powershell
$py = if (Test-Path ".venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
& $py --version
& $py -m pip --version
```

2. Inventory requirement files and pinned direct dependencies:

```powershell
rg --files -g "requirements*.txt"
rg -n "^[A-Za-z0-9_.-]+==[^\s#]+" -g "requirements*.txt"
```

3. Check for unpinned, editable, URL, path, extra-index, or trusted-host entries:

```powershell
rg -n "^\s*(-e\s+|--extra-index-url|--index-url|--trusted-host|https?://|git\+|file:|[A-Za-z0-9_.-]+\s*(>=|>|<=|<|~=|!=)|[A-Za-z0-9_.-]+\s*$)" -g "requirements*.txt"
```

4. Capture installed dependency metadata when a local environment is available:

```powershell
& $py -m pip list --format=json
& $py -m pip check
& $py -m pip inspect --local --verbose
```

5. Run advisory scanning if available:

```powershell
& $py -m pip_audit -r application/single_app/requirements.txt
```

If `pip_audit` is unavailable, report that gap and use metadata/source review instead. Do not install it unless the user approves or explicitly asked for full advisory tooling.

6. Download package archives for source/wheel review when network access is available and the user requested source review:

```powershell
New-Item -ItemType Directory -Force artifacts/security/python-package-audit | Out-Null
& $py -m pip download --no-deps --dest artifacts/security/python-package-audit -r application/single_app/requirements.txt
```

Repeat for other requirements files as needed. If downloads fail because of network, index, or platform constraints, inspect installed `site-packages` metadata instead.

## Manual Audit Checklist

Review these areas:

- Known vulnerability advisories, severity, affected versions, fixed versions, and whether SimpleChat uses the vulnerable feature.
- Package provenance: expected package name, publisher/maintainer reputation, project URL, license, release recency, typosquatting risk, beta/pre-release status, and sudden ownership changes when metadata is available.
- Requirement hygiene: all direct dependencies pinned, no URL/path/editable installs unless reviewed, no untrusted indexes, no missing hashes if the team wants reproducible supply-chain hardening.
- Transitive dependencies: installed versions, dependency conflicts from `pip check`, duplicate packages across app/deployer/UI environments, and packages pulled in by large frameworks.
- Install-time behavior: `setup.py`, `pyproject.toml`, build backends, custom install commands, native extensions, binary wheels, post-install scripts, and generated code.
- Runtime risky patterns in package code, prioritized by packages that process untrusted files, network data, auth, cryptography, serialization, HTML/markdown, browser automation, or cloud credentials.
- Source patterns to review in downloaded or installed packages: `eval`, `exec`, `compile`, `pickle`, `marshal`, `yaml.load`, `subprocess`, `os.system`, `shell=True`, `ctypes`, `cffi`, dynamic imports, network calls at import time, telemetry, environment-variable scraping, credential file reads, temporary file handling, archive extraction, and unsafe XML/HTML parsing.
- SimpleChat usage of the package: whether the package is imported in production, admin-only, deployer-only, tests-only, optional, or unused.
- License or compliance risks if the package is newly introduced or materially changed.

Useful searches for extracted or installed package source:

```powershell
rg -n "eval\(|exec\(|compile\(|pickle|marshal|yaml\.load|subprocess|os\.system|shell=True|ctypes|cffi|requests\.|urllib|socket|open\(|tempfile|zipfile|tarfile|extractall|fromstring|innerHTML|telemetry|analytics|credential|token|password|secret" artifacts/security/python-package-audit
```

If reviewing installed packages, replace the path with the relevant `site-packages` package directory.

## Triage And Plan

Group findings before editing:

- `Critical`: Known actively exploited vulnerability, malicious package indicators, credential exfiltration risk, unsafe install-time execution, or vulnerable code reachable through SimpleChat with untrusted input.
- `Important`: High-severity advisory, risky parser/network/auth behavior reachable by SimpleChat, suspicious package provenance, or missing fixed-version path.
- `Moderate`: Stale or beta package, broad risky primitives not clearly reachable, missing hashes, dependency conflicts, native binary opacity, or license/compliance concerns.
- `Low`: False positives, dev/test-only issues, unreachable vulnerable features, or informational hygiene improvements.

For each finding, record:

- Package name and version.
- Requirement file or transitive dependency path.
- Evidence source: advisory, metadata, source file, wheel contents, SimpleChat import/use, or command output.
- Reachability in SimpleChat.
- Impact.
- Recommended action: pin upgrade, replace package, configuration change, code usage change, add hash, monitor, or accept risk.
- Minimum validation after a change.

## Remediation And Upgrade Planning

If the user asks for remediation:

- Prefer patch or minor upgrades that fix advisories without broad behavior changes.
- Check release notes for packages that process files, auth, cloud credentials, markdown/HTML, browser automation, or networking.
- Update all relevant requirements files when the same package is pinned in multiple environments.
- Run `pip check`, import smoke tests, and relevant functional/UI tests after upgrades.
- For production packages, run focused app checks that cover the package’s real use.
- Consider adding hashes only as a deliberate supply-chain hardening task because it changes dependency maintenance workflow.

## Verification

After dependency changes, run the narrowest reliable checks:

- `& $py -m pip check`.
- `& $py -m py_compile <changed-python-files>` when app code changed.
- Import smoke tests for upgraded packages.
- Relevant functional tests under `functional_tests/`.
- Relevant UI tests for Playwright/browser package changes.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

Return findings first, ordered by severity. Include direct and transitive scope, requirement files reviewed, tools run, package source or wheel paths inspected, vulnerabilities or risky patterns found, false positives, recommended upgrades, skipped checks, and remaining risks.