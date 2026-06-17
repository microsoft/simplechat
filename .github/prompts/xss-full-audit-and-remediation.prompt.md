---
description: "Use when: running a full SimpleChat cross-site scripting/XSS audit across all browser rendering surfaces, creating a remediation plan, fixing risky sinks, and validating locally."
name: "XSS Full Audit And Remediation"
argument-hint: "Optional: target paths, scan only, fix findings, include guardrail checker updates, or stop after plan"
agent: "agent"
---

# XSS Full Audit And Remediation

Run a full local SimpleChat XSS audit and remediation workflow. This is broader than the GitHub Actions PR check in [.github/workflows/xss-sink-check.yml](../workflows/xss-sink-check.yml): the action checks changed application lines, while this prompt should inspect the whole browser-rendering surface and produce a plan to fix real risks.

Use the repository guardrails in [.github/instructions/xss-prevention.instructions.md](../instructions/xss-prevention.instructions.md), [.github/instructions/local_browser_assets.instructions.md](../instructions/local_browser_assets.instructions.md), and the deterministic checker in [scripts/check_xss_sinks.py](../../scripts/check_xss_sinks.py). Prefer the repo's existing rendering helpers and Bootstrap patterns over new abstractions.

## Operating Rules

- Work in the SimpleChat repository root.
- Treat JavaScript, HTML/Jinja, and Python routes/helpers that send data to the browser as the audit surface.
- Do not revert unrelated user changes.
- Start with a concise plan and keep it updated as findings are triaged and fixed.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If the user asks to fix findings, make focused changes by feature/file area and verify each batch.
- Use `xss-check: ignore` only for a reviewed exception with a nearby justification. Prefer safer rendering code.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Identify tracked application files in scope:

```powershell
$xssFiles = git ls-files "application/**/*.js" "application/**/*.html" "application/**/*.py"
```

3. Run the deterministic checker in full-file mode, saving the output if it is large:

```powershell
python scripts/check_xss_sinks.py --full-file $xssFiles
```

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

Avoid broad mechanical rewrites. Preserve behavior, accessibility, Bootstrap state classes, and local asset references.

## Verification

After each remediation batch, run the narrowest reliable checks first, then broaden before final reporting:

- `node --check <changed-js-file>` for changed JavaScript files.
- `python -m py_compile <changed-python-file>` for changed Python files.
- Relevant functional or UI tests for the edited workflow.
- `python scripts/check_xss_sinks.py --full-file <changed-files>` for edited application JS/HTML/Python files.
- Full audit rerun before completion when the user asked for a complete fix pass:

```powershell
$xssFiles = git ls-files "application/**/*.js" "application/**/*.html" "application/**/*.py"
python scripts/check_xss_sinks.py --full-file $xssFiles
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