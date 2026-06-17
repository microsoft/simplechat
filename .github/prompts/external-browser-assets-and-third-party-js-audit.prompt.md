---
description: "Use when: auditing SimpleChat browser runtime assets, CDN references, CSP, vendored third-party JavaScript, worker/font/WASM companion assets, or local-only frontend dependency security."
name: "External Browser Assets And Third Party JS Audit"
argument-hint: "Target paths, changed files, asset names, vendor folders, CSP review, scan only, or fix findings"
agent: "agent"
---

# External Browser Assets And Third Party JS Audit

Audit SimpleChat browser runtime assets to ensure all JavaScript and JavaScript-required companion assets are copied locally, served locally, pinned, compatible with CSP, and reviewed with the same security care as first-party JavaScript.

Use the repository guardrails in [.github/instructions/local_browser_assets.instructions.md](../instructions/local_browser_assets.instructions.md), [.github/instructions/xss-prevention.instructions.md](../instructions/xss-prevention.instructions.md), [.github/instructions/javascript-lang.instructions.md](../instructions/javascript-lang.instructions.md), [.github/instructions/html-lang.instructions.md](../instructions/html-lang.instructions.md), and [.github/copilot-instructions.md](../copilot-instructions.md). Do not add CDN-hosted browser runtime JavaScript or dynamic public-Internet imports.

## Operating Rules

- Work in the SimpleChat repository root.
- Treat third-party browser JavaScript as part of the application attack surface, even when it is vendored locally.
- Do not revert unrelated user changes.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If fixing findings, vendor pinned local assets under `application/single_app/static/`, preserve license/attribution files, and keep CSP local-only.
- Do not loosen CSP to permit public CDN runtime code.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Find external browser runtime references:

```powershell
rg -n -i "https?://|//cdn|cdn\.jsdelivr|unpkg|cdnjs|esm\.sh|skypack|code\.jquery|stackpath|fonts\.googleapis|fonts\.gstatic|import\(|new Worker\(|workerSrc|wasm|sourceMappingURL|integrity=|crossorigin=" application/single_app/templates application/single_app/static application/single_app/*.py
```

3. Inventory local vendor assets:

```powershell
Get-ChildItem -Recurse application/single_app/static | Where-Object { $_.FullName -match "vendor|lib|third|openlayers|dompurify|marked|simplemde|bootstrap|jquery|chart|map|wasm|worker" } | Select-Object FullName
```

If PowerShell output is too noisy, use `rg --files application/single_app/static` and filter manually.

4. Search CSP and security-header definitions:

```powershell
rg -n "Content-Security-Policy|script-src|style-src|connect-src|img-src|font-src|worker-src|frame-src|unsafe-inline|unsafe-eval|nonce|hash" application deployers docs .github
```

5. Search for third-party JavaScript sinks using the same XSS lens as first-party code:

```powershell
rg -n "innerHTML|outerHTML|insertAdjacentHTML|\.html\(|eval\(|new Function\(|document\.write|setAttribute\(\s*['\"]on|javascript:|postMessage|addEventListener\(\s*['\"]message|localStorage|sessionStorage" application/single_app/static
```

6. Run the deterministic XSS checker against changed or target JavaScript and template files where useful:

```powershell
python scripts/check_xss_sinks.py --full-file <changed-or-target-browser-files>
```

## Manual Audit Checklist

Review these areas:

- `<script>`, `<link>`, `import(...)`, module imports, import maps, workers, service workers, source maps, WASM files, dictionaries, fonts, maps, spell-check dictionaries, and plugin-managed fallback downloads.
- Library configuration that fetches companion assets from public URLs at runtime.
- CSP headers that allow CDN script/style/font/worker sources, `unsafe-eval`, broad wildcards, or broad data/blob allowances without a clear need.
- Local vendor folders for version pinning, provenance notes, license/attribution files, minified and unminified copies, and update process clarity.
- Vendored third-party JavaScript sinks that handle SimpleChat-controlled or user-controlled data.
- Third-party library use of `innerHTML`, URL handling, markdown rendering, postMessage, workers, dynamic code execution, prototype modification, global object writes, storage, and network calls.
- Whether a third-party asset has known security advisories, stale versions, abandoned maintainers, or safer local alternatives.
- Whether vendored code is modified locally, and whether local modifications are documented enough to rebase safely during future upgrades.

## Triage And Plan

Group findings before editing:

- `Critical`: Browser runtime JavaScript executes from a public CDN, remote dynamic import, remote worker, or compromised CSP path in a reachable application page.
- `Important`: Vendored third-party JavaScript contains risky sinks reachable with untrusted SimpleChat data, or CSP is loosened enough to bypass local-only controls.
- `Moderate`: Companion assets load remotely, version/provenance is unclear, licenses are missing, source maps leak unexpected code, or a library auto-downloads optional assets.
- `Low`: Documentation-only external URLs, static user-clickable links, reviewed exceptions, or false positives.

For each finding, record:

- File and asset reference.
- Asset source and whether it is first-party or third-party.
- Runtime behavior and data trust boundary.
- CSP impact.
- Remediation approach.
- Minimum regression test or static check.

## Remediation Patterns

Use these fixes by default:

- Copy pinned browser runtime assets into `application/single_app/static/js/<vendor>/` or `application/single_app/static/css/<vendor>/`.
- Reference assets through local Flask static paths such as `url_for('static', filename='...')`.
- Keep required worker, WASM, font, dictionary, source map, CSS, and plugin assets local too.
- Disable third-party library defaults that fetch remote companion assets unless the local equivalent is configured.
- Keep CSP `script-src` and `style-src` aligned with local assets and avoid CDN allowlists.
- Review third-party JavaScript sinks with the same checklist used for first-party XSS review.
- Document vendored asset version, source URL, license, integrity/hash where practical, and local patches if any.
- Add or update a functional test or static checker when fixing a remote asset dependency.

## Verification

After fixing, run the narrowest reliable checks:

- `node --check <changed-js-file>` for changed JavaScript files.
- `python scripts/check_xss_sinks.py --full-file <changed application JS/HTML/Python files>` when rendering surfaces changed.
- Targeted `rg` searches for external URLs and CSP changes.
- Relevant UI tests when a page’s assets or behavior changed.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

Return findings first, ordered by severity. Include the list of local third-party browser libraries reviewed, any remote runtime assets found, CSP changes, vendored asset provenance gaps, validation commands run, skipped checks, and remaining risks.