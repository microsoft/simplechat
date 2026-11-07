---
description: "Use when: running a full SimpleChat cross-site scripting/XSS audit across all browser rendering surfaces, creating a remediation plan, fixing risky sinks, and validating locally."
name: "XSS Full Audit And Remediation"
argument-hint: "Optional: target paths, scan only, fix findings, include guardrail checker updates, or stop after plan"
agent: "agent"
---

# XSS Full Audit And Remediation

Run a full local SimpleChat XSS audit and remediation workflow. This is broader than the GitHub Actions PR check in [.github/workflows/xss-sink-check.yml](../workflows/xss-sink-check.yml): the action checks changed application lines, while this prompt should inspect the whole browser-rendering surface and produce a plan to fix real risks. The on-demand [.github/workflows/xss-full-scan.yml](../workflows/xss-full-scan.yml) workflow runs the same checker over whole files and is a useful first pass, but it does not replace the manual review below.

Use the repository guardrails in [.github/instructions/xss-prevention.instructions.md](../instructions/xss-prevention.instructions.md), [.github/instructions/local_browser_assets.instructions.md](../instructions/local_browser_assets.instructions.md), and the deterministic checker in [scripts/check_xss_sinks.py](../../scripts/check_xss_sinks.py). Prefer the repo's existing rendering helpers and Bootstrap patterns over new abstractions.

## Operating Rules

- Work in the SimpleChat repository root.
- Treat JavaScript, HTML/Jinja, and Python routes/helpers that send data to the browser as the audit surface.
- On branches that contain the V2 React UI, also treat the TypeScript source in `application/v2_ui/src` (`.ts`, `.tsx`, `.jsx`, `.mjs`) as audit surface. Skip vendored minified libraries under `application/v2_ui/public/vendor/`; the checker skips them too.
- Do not revert unrelated user changes.
- Start with a concise plan and keep it updated as findings are triaged and fixed.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If the user asks to fix findings, make focused changes by feature/file area and verify each batch.
- Use `xss-check: ignore` only for a reviewed exception with a nearby justification. Prefer safer rendering code.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Identify tracked application files in scope:

```powershell
$xssFiles = @(git ls-files "application/**/*.js" "application/**/*.html" "application/**/*.py" "application/**/*.ts" "application/**/*.tsx" "application/**/*.jsx" "application/**/*.mjs")
```

3. Run the deterministic checker in full-file mode, saving the output if it is large. The full file list is longer than the 32,767-character limit Windows puts on a command line, so pass it in batches, and read every batch's output rather than only the last exit code:

```powershell
for ($i = 0; $i -lt $xssFiles.Count; $i += 200) {
    python scripts/check_xss_sinks.py --full-file $xssFiles[$i..([Math]::Min($i + 199, $xssFiles.Count - 1))]
}
```

TypeScript-family findings start with a rule id such as `[ts-jsx-url-attribute]`. The reviewed V2 baseline, with the reason each finding is safe, is in [docs/explanation/features/v0.241.022/XSS_PR_GUARDRAILS_V2_BASELINE_TRIAGE.md](../../docs/explanation/features/v0.241.022/XSS_PR_GUARDRAILS_V2_BASELINE_TRIAGE.md). Compare against it so already-reviewed sites are not re-triaged from scratch, but re-check any baseline site whose code has changed.

4. Run the guardrail self-test when the checker, workflow, XSS instructions, or this prompt are part of the work:

```powershell
python functional_tests/test_xss_guardrails_checker.py
```

5. Independently search for browser execution and HTML-rendering sinks that need human review:

```powershell
rg -n "innerHTML|outerHTML|insertAdjacentHTML|\.html\(|onclick=|onerror=|onload=|javascript:|\|safe\b|Markup\(|marked\.parse|dangerouslySetInnerHTML|setAttribute\(\s*['\"]on" application
```

6. Search for dynamic template interpolation into rendered markup:

```powershell
rg -n "`[^`]*\$\{|href=.*\$\{|src=.*\$\{|title=.*\$\{|style=.*\$\{|data-[A-Za-z0-9_-]+=.*\$\{" application/single_app/static application/single_app/templates
```

7. When `application/v2_ui/src` exists, search it for React and DOM sinks that bypass JSX escaping:

```powershell
rg -n "dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser|eval\(|new Function|javascript:|rehype-raw|allowDangerousHtml|urlTransform" application/v2_ui/src
rg -n "(href|src|action|formAction|srcDoc|xlinkHref|to)=\{|window\.open\(|location\.(href|assign|replace)|\.setAttribute\(" application/v2_ui/src
```

If shell quoting gets in the way, use equivalent `rg` searches or the VS Code search tool, but preserve the same coverage.

## Manual Audit Checklist

For each finding or suspicious sink, determine whether untrusted data can reach it. Treat these values as untrusted unless proven otherwise:

- User names, emails, IDs, workspace/group names, agent names, tags, filenames, document titles, descriptions, and settings-derived display values.
- API responses from Cosmos DB, Azure AI Search, Microsoft Graph, plugins/tools, file processing, or model output.
- Markdown, rich text, uploaded text, generated summaries, citation snippets, errors, and logs shown in the browser.

Review these sink categories:

- Dynamic `innerHTML`, `outerHTML`, `insertAdjacentHTML`, jQuery `.html(...)`, and `dangerouslySetInnerHTML`.
- Inline event handlers in templates or JavaScript-created markup.
- `javascript:` URLs and dynamic `href` or `src` values without explicit URL normalization.
- Dynamic interpolation into `title`, `style`, or `data-*` attributes in HTML strings.
- `marked.parse(...)` output rendered without `DOMPurify.sanitize(...)`.
- Python `Markup(...)` and Jinja `|safe` on values that can contain user, model, file, or service-provided content.
- Static HTML shell exceptions that are no longer static because they interpolate runtime data.

For the V2 React UI, also review these sink categories. React 18 escapes JSX text children and attribute strings, but it does not block `javascript:` URLs in URL props (it only warns in development), and it never inspects values that go straight to the DOM:

- `dangerouslySetInnerHTML` whose `__html` is not `DOMPurify.sanitize(...)` output, or whose renderer (KaTeX, Mermaid) runs without its safe mode (`trust: false`, `securityLevel: 'strict'`).
- `innerHTML`/`outerHTML` assignments through refs, `insertAdjacentHTML`, `document.write`, `createContextualFragment`, and `DOMParser` output appended to the page.
- `eval`, `new Function`, and string arguments to `setTimeout`/`setInterval`.
- Dynamic `href`, `src`, `action`, `formAction`, `srcDoc` and `xlinkHref` props, and router `to` props on `Link`, `NavLink` and `Navigate`, that are not a literal, a same-origin path, a reviewed URL builder, a `sanitize*Url`/`normalize*Url` helper, or guarded by `isSafeOriginHref(...)` or an `http(s)` scheme test.
- Navigation sinks: `window.open(...)`, `location.href = ...`, `location = ...`, and `location.assign(...)`/`location.replace(...)` with a dynamic value.
- DOM URL properties such as `element.href`, `element.src`, `form.action`, `frame.srcdoc`, and `setAttribute('href' | 'src' | 'action' | 'srcdoc', ...)`.
- `react-markdown` options that re-enable raw HTML or unfiltered URLs: `rehype-raw`, `allowDangerousHtml`, or a `urlTransform` that returns its input unchanged.
- Props that forward a URL into one of these sinks from another component. The checker sees only the file with the sink, so trace the value back through its callers.

## Triage And Plan

Group findings before editing:

- `Critical`: Untrusted content can execute script or inject event handlers/URLs in reachable browser flows.
- `Important`: Untrusted content reaches HTML sinks or unsafe markdown rendering, but exploitability depends on stored data or role-specific access.
- `Moderate`: Inline handlers, dynamic attributes, or legacy HTML shell patterns that are risky but likely constrained.
- `Low`: Static-only shell code, false positives, or reviewed sanitizer boundaries that should be documented or covered by tests.

For each group, record:

- File and function/component.
- Source of untrusted data.
- Sink and why the existing boundary is insufficient.
- Remediation approach.
- Minimum validation or regression test.

Then propose a repair order that starts with high-confidence, high-impact fixes and keeps each batch small enough to review.

## Remediation Patterns

Use these fixes by default:

- Build DOM nodes with `document.createElement(...)` and set untrusted text with `textContent`.
- Attach behavior with `addEventListener(...)`, not inline handler attributes.
- Assign inert values through `dataset` or `setAttribute(...)` only after validating the attribute context.
- Normalize dynamic links with an existing URL sanitizer or a small local helper before assigning `href` or `src`.
- Render markdown as `DOMPurify.sanitize(marked.parse(...))` before assigning to an HTML sink.
- Keep static modal/card/table shells fully static, then populate untrusted fields with DOM APIs.
- Remove unnecessary `Markup(...)` and Jinja `|safe`; if HTML is required, make the sanitizer boundary explicit and covered by tests.

For V2 React components:

- Render untrusted text as JSX children instead of building HTML strings.
- Keep `dangerouslySetInnerHTML` only for sanitizer output: `{{ __html: DOMPurify.sanitize(html) }}` or a clearly named sanitized `const`.
- Build same-origin links from a literal path and `encodeURIComponent(...)` segments, or use an existing reviewed URL builder. Guard external links with `isSafeOriginHref(...)` or an explicit `http(s)` scheme test before they reach `href`, `window.open`, or `location`.
- Keep `react-markdown` on its defaults: no `rehype-raw`, no `allowDangerousHtml`, and the default URL transform.

Avoid broad mechanical rewrites. Preserve behavior, accessibility, Bootstrap state classes, and local asset references.

## Verification

After each remediation batch, run the narrowest reliable checks first, then broaden before final reporting:

- `node --check <changed-js-file>` for changed JavaScript files.
- `npm --prefix application/v2_ui run typecheck` for changed V2 TypeScript files.
- `python -m py_compile <changed-python-file>` for changed Python files.
- Relevant functional or UI tests for the edited workflow.
- `python scripts/check_xss_sinks.py --full-file <changed-files>` for edited application JS/HTML/Python/TypeScript files.
- Full audit rerun before completion when the user asked for a complete fix pass, in batches as in Baseline Discovery:

```powershell
$xssFiles = @(git ls-files "application/**/*.js" "application/**/*.html" "application/**/*.py" "application/**/*.ts" "application/**/*.tsx" "application/**/*.jsx" "application/**/*.mjs")
for ($i = 0; $i -lt $xssFiles.Count; $i += 200) {
    python scripts/check_xss_sinks.py --full-file $xssFiles[$i..([Math]::Min($i + 199, $xssFiles.Count - 1))]
}
```

- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

When complete, report:

- Scope scanned and whether this was full-repo, target-path, scan-only, or remediation mode.
- Findings grouped by severity, including false positives and reviewed exceptions.
- Files changed and the rendering safety pattern used.
- Validation commands run and pass/fail status.
- Remaining risks, tests that were skipped, and any follow-up that needs a product or security decision.