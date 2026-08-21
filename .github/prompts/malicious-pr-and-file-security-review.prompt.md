---
description: "Use when: reviewing a SimpleChat pull request, commit diff, branch diff, or explicit file set for malicious code, hidden security issues, obfuscation, unauthorized external connections, malware-like behavior, data exfiltration, dependency pinning, or newly released package risk."
name: "Malicious PR And File Security Review"
argument-hint: "PR number/URL, base/head refs, commit range, explicit file paths, scan only, dependency gate only, or fix findings"
agent: "agent"
---

# Malicious PR And File Security Review

Review a SimpleChat pull request, commit range, branch diff, or explicit file set for intentionally harmful behavior, hidden security issues, supply-chain risk, obfuscation, external network egress, data exfiltration, dependency policy violations, and contributor trickery.

This prompt is for adversarial review. Assume benign explanations are possible, but do not give suspicious code the benefit of the doubt without evidence. The default output is a findings report, not edits. Only modify files if the user explicitly asks to remediate findings.

## Scope Inputs

The user may provide any of these targets:

- A GitHub PR number or URL.
- Base and head refs, such as `upstream/Development...feature-branch`.
- A commit range.
- A list of explicit files.
- A pasted diff.

If the target is ambiguous, use the safest local interpretation and state it. If no target is provided, review the current working tree and branch diff against the repository's normal PR target, `Development`.

## Operating Rules

- Work in the SimpleChat repository root.
- Treat this as a security review with hostile-change assumptions.
- Do not revert unrelated user changes.
- Do not run untrusted code, install new packages, execute changed scripts, start services, or run package lifecycle hooks from the reviewed change unless the user explicitly approves after seeing the risk.
- Prefer read-only inspection, static search, metadata review, and existing repo checkers.
- If registry, GitHub, or network access is unavailable, report which checks could not be completed and whether that blocks approval.
- If the user asks for `scan only`, `review only`, or `report only`, do not edit files.
- If findings are remediated, keep fixes focused and rerun the relevant checks.

## Baseline Discovery

1. Confirm repository, branch, status, and target scope:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short
git remote -v
```

2. If reviewing a PR and GitHub CLI is available, capture PR metadata and files:

```powershell
gh pr view <pr-number-or-url> --json number,title,author,baseRefName,headRefName,commits,files,additions,deletions,reviews,statusCheckRollup
gh pr diff <pr-number-or-url> --name-only
gh pr diff <pr-number-or-url>
```

3. If reviewing local refs, identify changed files and patch content:

```powershell
git fetch --all --prune
git diff --name-status <base>...<head>
git diff --stat <base>...<head>
git diff --find-renames --find-copies <base>...<head>
```

4. If reviewing explicit files, inspect each file and, when possible, compare it to the base branch:

```powershell
git diff -- <file1> <file2>
git diff <base>...HEAD -- <file1> <file2>
```

5. Classify changed files before deep review:

- Application runtime: `application/single_app/**`.
- Browser runtime: templates, static JavaScript, CSS, workers, WASM, fonts, vendored assets.
- Routes/auth/security: Flask routes, decorators, role checks, CSRF, CSP, settings sanitization.
- Dependency manifests: `requirements*.txt`, `package.json`, lockfiles, Dockerfiles, GitHub Actions, installer scripts.
- Infrastructure/deployment: `deployers/**`, Bicep, Terraform, PowerShell, Azure CLI scripts, `azd` hooks.
- Tests and validation: functional tests, UI tests, route policy tests, security scanners, CI workflows.
- Documentation or prompts that may influence operational behavior.

## Dependency Gate

Apply this policy to new or changed dependencies in any ecosystem, and especially to Python requirements files:

- Dependencies must be exactly pinned. Reject ranges such as `>=`, `>`, `<`, `<=`, `~=`, `^`, `~`, `*`, npm dist-tags such as `latest`, unversioned entries, and floating Docker tags unless the repository already has a reviewed exception.
- Python direct dependencies in `requirements*.txt` must use `package==version`.
- Reject editable installs, local paths, direct URLs, Git URLs, untrusted package indexes, `--extra-index-url`, and `--trusted-host` unless explicitly justified and reviewed.
- Reject any new or changed package version released less than seven full days before the review date.
- If the release date cannot be verified from a trusted registry or lockfile metadata, mark the dependency as `Needs investigation` or `Blocker`, depending on whether it is production-reachable.
- Treat pre-release, yanked, typosquatting-suspect, abandoned, newly transferred, or dependency-confusion-risk packages as suspicious even when older than seven days.

Find changed dependency manifests:

```powershell
git diff --name-only <base>...<head> | Select-String -Pattern "requirements.*\.txt$|package\.json$|package-lock\.json$|npm-shrinkwrap\.json$|pnpm-lock\.yaml$|yarn\.lock$|pyproject\.toml$|poetry\.lock$|Pipfile$|Pipfile\.lock$|Dockerfile$|\.github/workflows/|deployers/"
```

Find unsafe Python requirement forms:

```powershell
rg -n "^\s*(-e\s+|--extra-index-url|--index-url|--trusted-host|https?://|git\+|file:|[A-Za-z0-9_.-]+\s*(>=|>|<=|<|~=|!=)|[A-Za-z0-9_.-]+\s*$)" -g "requirements*.txt"
```

Verify Python package release dates through PyPI when network access is available:

```powershell
$reviewDate = Get-Date
$package = "<package-name>"
$version = "<version>"
$metadata = Invoke-RestMethod "https://pypi.org/pypi/$package/$version/json"
$uploads = $metadata.urls | Select-Object -ExpandProperty upload_time_iso_8601
$oldestUpload = ($uploads | ForEach-Object { [datetime]$_ } | Sort-Object | Select-Object -First 1)
$age = $reviewDate - $oldestUpload
$age.TotalDays
```

Verify npm package release dates when JavaScript dependencies changed:

```powershell
npm view <package>@<version> time --json
```

For Docker images, GitHub Actions, Terraform providers, Bicep modules, PowerShell modules, browser libraries, and other dependency ecosystems, verify exact pinning and release age from the relevant trusted registry when possible. Prefer immutable digests, commit SHAs, or exact versions over tags.

## High-Risk Search Patterns

Run targeted searches over changed files first, then broaden if suspicious patterns appear.

### External Connections And Egress

Look for new or changed code that connects to public or unexpected endpoints, sends telemetry, calls webhooks, opens sockets, uses DNS as a channel, or loads remote assets:

```powershell
rg -n -i "https?://|webhook|telemetry|analytics|beacon|sendBeacon|fetch\(|XMLHttpRequest|WebSocket|EventSource|requests\.|httpx\.|aiohttp|urllib|socket\.|smtplib|ftplib|paramiko|scp|Invoke-WebRequest|Invoke-RestMethod|curl|wget|nslookup|Resolve-DnsName|cdn\.|unpkg|jsdelivr|cdnjs|esm\.sh|skypack" <changed-paths>
```

Review whether the endpoint is expected, configurable, documented, local-only where required, and not receiving secrets, prompts, files, embeddings, tokens, cookies, settings, logs, or user data.

### Secret, Credential, And Data Exfiltration Sources

Look for code that reads sensitive values and pairs them with network, logging, serialization, or process execution sinks:

```powershell
rg -n -i "api[_-]?key|secret|password|passwd|pwd|token|bearer|credential|connection[_ -]?string|client[_-]?secret|private[_-]?key|account[_-]?key|sas[_-]?token|Authorization|Cookie|get_settings\(|os\.environ|process\.env|localStorage|sessionStorage|document\.cookie|id_rsa|\.env|MSAL|OPENAI|COSMOS|SEARCH|BLOB|STORAGE|KEYVAULT|GRAPH" <changed-paths>
```

Review logs, errors, exports, traces, activity records, plugin calls, prompt construction, browser storage, hidden inputs, generated artifacts, and test fixtures for accidental or intentional disclosure.

### Obfuscation, Stealth, And Hidden Payloads

Look for code designed to hide intent or evade review:

```powershell
rg -n -i "base64|b64decode|atob\(|fromCharCode|charCodeAt|unescape\(|decodeURIComponent|zlib|gzip|brotli|marshal|pickle|loads\(|exec\(|eval\(|compile\(|new Function|Function\(|importlib|__import__|getattr\(|setattr\(|globals\(\)|locals\(\)|Reflection|Add-Type|EncodedCommand|FromBase64String|IEX|Invoke-Expression|Start-Process|hidden|homoglyph|bidi|unicode" <changed-paths>
```

Also inspect:

- Very long strings, high-entropy blobs, minified code, generated code, binary artifacts, unexpected images/documents, source maps, compressed archives, and vendored files.
- Unicode bidirectional controls, zero-width characters, homoglyph identifiers, trailing code after comments, misleading filenames, and whitespace-only changes.
- Renames, copied files, or large deletions that may hide a small malicious change.

Useful checks:

```powershell
git diff --check <base>...<head>
git diff --word-diff=color <base>...<head> -- <suspicious-file>
rg -n --pcre2 "[\x{202A}-\x{202E}\x{2066}-\x{2069}\x{200B}\x{200C}\x{200D}\x{FEFF}]" <changed-paths>
```

### Dynamic Execution, Persistence, And System Access

Look for code that executes commands, changes the host, installs software, persists tasks, or reaches local files unexpectedly:

```powershell
rg -n -i "subprocess|os\.system|popen|shell=True|pty|spawn|execFile|child_process|ProcessStartInfo|Start-Process|New-Service|schtasks|crontab|systemctl|chmod|chown|icacls|reg add|Set-ItemProperty|pip install|npm install|postinstall|preinstall|setup.py|pyproject.toml|entry_points|ctypes|cffi|ffi|DllImport|LoadLibrary|unsafe" <changed-paths>
```

Do not execute changed lifecycle scripts or installers as part of the review.

### Security Control Tampering

Look for changes that weaken existing controls, create blind spots, or make malicious behavior harder to detect:

```powershell
rg -n -i "login_required|admin_required|user_required|swagger_route|get_auth_security|csrf|Content-Security-Policy|sanitize_settings_for_user|escapeHtml|DOMPurify|innerHTML|outerHTML|insertAdjacentHTML|eval\(|debug\s*=\s*True|verify\s*=\s*False|ssl|cert|validate|allowlist|denylist|permission|role|policy|redact|mask|log_event|audit|telemetry|traceback|try:|except Exception|pass|skip|xfail|disable|noqa|type:\s*ignore|pragma" <changed-paths>
```

Pay special attention to:

- Removed route decorators, Blueprint auth policies, role checks, CSRF checks, CSP restrictions, XSS sanitization, settings sanitization, or secret redaction.
- Test changes that reduce coverage, skip security tests, weaken assertions, or alter fixtures to hide failures.
- CI changes that remove scanners, lower permissions boundaries, expose tokens to pull_request contexts, add untrusted actions, or run contributor code with secrets.
- Logging changes that suppress errors, hide audit trails, or send sensitive telemetry externally.

### AI, Plugin, And Agent-Specific Risks

Review SimpleChat AI surfaces for prompt, tool, and data exfiltration risks:

- New tools, plugins, OpenAPI specs, external action endpoints, or agent instructions that can send prompts, chat history, uploaded documents, embeddings, citations, settings, or user identity outside approved services.
- Prompt-injection pathways that bypass workspace isolation or role checks.
- Hidden system prompt changes, model endpoint changes, unreviewed fallback models, or external model providers.
- Changes to document ingestion, search indexing, citations, file sync, public workspaces, or group workspace boundaries that could leak documents across users or workspaces.

## Manual Review Checklist

Review each changed file with these questions:

- What new trust boundary is crossed?
- What data can leave the process, browser, container, tenant, subscription, or repository?
- Does the code read secrets, environment variables, settings, tokens, cookies, prompts, uploaded files, generated files, or private documents?
- Is any new external host, package registry, CDN, model endpoint, webhook, telemetry sink, storage account, or database introduced?
- Are dependencies pinned exactly and older than seven full days?
- Can the change run during install, import, test, build, deploy, startup, request handling, browser load, or CI before a human notices?
- Does the change weaken authentication, authorization, CSRF, CSP, XSS defenses, settings sanitization, redaction, audit logging, route policy tests, or deployment security?
- Is code intentionally hard to read through obfuscation, indirection, hidden Unicode, minification, misleading names, dead code, broad exception swallowing, or noisy unrelated churn?
- Are new binaries, archives, generated assets, vendored libraries, certificates, keys, models, or serialized files justified and inspectable?
- Could this change behave differently in CI, production, Azure, a container, Windows, Linux, or when environment variables are present?

## Triage

Group findings by severity:

- `Critical`: Clear credential exfiltration, malware-like behavior, unauthorized external egress of sensitive data, install-time execution from an untrusted dependency, active security control bypass, CI secret exposure to untrusted code, malicious obfuscation with reachable execution, or a dependency policy violation in production code.
- `Important`: Suspicious external endpoint, newly introduced broad system/process access, weakened auth or sanitization, risky package provenance, unverified package release age, unsafe CI permissions, or hidden behavior that could plausibly expose data.
- `Moderate`: Exact risk depends on configuration or reachability, suspicious but non-production dependency change, stale/binary/opaque vendor asset, broad logging, broad exception swallowing, or weakened tests without a direct exploit path.
- `Low`: Review hygiene concerns, false positives, documentation-only external links, unreachable code, or already-reviewed exceptions.

For every finding, include:

- Severity and verdict: `Blocker`, `Needs investigation`, or `Acceptable with notes`.
- File and relevant symbol or changed hunk.
- Evidence from diff, file contents, registry metadata, command output, or repo policy.
- Source data involved and sink or execution path.
- Reachability: install time, import time, build time, CI, browser load, request path, admin-only, test-only, deployer-only, or unreachable.
- Why benign explanations are insufficient or what evidence would clear the concern.
- Recommended action.
- Minimum validation after remediation.

## Validation

Use existing repo checks when they match the changed surface. Do not execute untrusted changed code just to validate it.

Run static or deterministic checks such as:

```powershell
git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check
python scripts/check_xss_sinks.py --full-file <changed-browser-or-rendering-files>
python scripts/check_broken_access_control.py --full-file <changed-python-auth-files>
python scripts/check_swagger_routes.py <changed-route-files>
```

For changed Python files that are not suspicious lifecycle/install code, run syntax checks:

```powershell
python -m py_compile <changed-python-files>
```

For changed JavaScript files, run parse checks:

```powershell
node --check <changed-js-files>
```

If dependencies changed, validate pinning and release age from trusted registries. If package install, build, or lifecycle execution is required to test, stop and ask before running it.

## Output Expectations

Return findings first, ordered by severity. Include:

- Review target and base/head or file scope.
- Changed-file summary grouped by risk area.
- Dependency policy result, including exact pins, release-age checks, package sources, and any unverified packages.
- External hosts, URLs, registries, CDNs, webhooks, model endpoints, or telemetry sinks introduced or modified.
- Obfuscation, hidden Unicode, binary, generated, vendored, or minified artifacts reviewed.
- Security controls weakened, removed, or confirmed unchanged.
- Commands and tools run, with pass/fail/skipped status.
- False positives and reviewed exceptions.
- Final verdict: `Block`, `Needs investigation`, or `No malicious indicators found in reviewed scope`.

Do not claim the code is safe. Say only what was reviewed, what evidence was found, what could not be checked, and what risk remains.