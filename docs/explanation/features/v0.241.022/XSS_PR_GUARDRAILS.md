# XSS PR Guardrails

Fixed/Implemented in version: **0.241.021**

## Overview

This feature adds a prevention-focused XSS guardrail for pull requests into Development. It is designed to catch new browser-side sink regressions before they merge, especially when code arrives from contributors who are not using the local Copilot or CLAUDE instruction set.

The guardrail also covers the V2 React/TypeScript UI in `application/v2_ui/src`, and it runs on pull requests into the V2 branch `paullizer-react-v2-ui` until that branch merges into Development. See [V2 React/TypeScript Coverage](#v2-reacttypescript-coverage).

## Scope

This change affects:

- the repository instruction set in `.github/instructions/xss-prevention.instructions.md`
- the changed-file checker in `scripts/check_xss_sinks.py`
- the Development pull-request workflow in `.github/workflows/xss-sink-check.yml`
- the on-demand whole-file scan in `.github/workflows/xss-full-scan.yml`
- the guardrail regression test in `functional_tests/test_xss_guardrails_checker.py`
- the full-audit prompt in `.github/prompts/xss-full-audit-and-remediation.prompt.md`

## Technical Details

### GitHub Instruction

The new instruction file documents the repo's preferred safe browser-rendering patterns:

- `createElement(...)`
- `textContent`
- `setAttribute(...)`
- `dataset`
- `addEventListener(...)`
- `DOMPurify.sanitize(marked.parse(...))`

It also explicitly blocks the sink patterns that caused the recurring XSS findings:

- dynamic `innerHTML`, `outerHTML`, `insertAdjacentHTML`, and jQuery `.html(...)`
- inline event handlers such as `onclick`, `onerror`, and `onload`
- dynamic interpolation into `href`, `src`, `title`, `style`, and `data-*`
- `javascript:` URLs
- `Markup(...)` in Python on untrusted content
- Jinja `|safe` on untrusted content
- `marked.parse(...)` rendered without DOMPurify

### Changed-File Checker

`scripts/check_xss_sinks.py` follows the same custom-checker model already used for Swagger route validation in this repository.

Key behaviors:

- Scans only supported source files: `.js`, `.html`, and `.py`, plus the TypeScript-family files `.ts`, `.tsx`, `.jsx`, and `.mjs` described below
- Skips vendored browser assets, such as the classic OpenLayers and SimpleMDE copies and the V2 libraries under `application/v2_ui/public/vendor/`
- Supports pull-request diff mode through `--base-sha` and `--head-sha`
- Limits checks to added lines in CI when revision metadata is provided
- Emits GitHub Actions error annotations for each blocking issue
- Allows a narrow reviewed escape hatch with the suppression token `xss-check: ignore`

### PR Workflow

`.github/workflows/xss-sink-check.yml` adds a Development pull-request gate with two layers:

- a blocking `xss-sink-check` job that scans changed application files
- a non-blocking guardrail self-test step that runs when the checker, workflow, instruction, or feature doc changes

This keeps the primary PR gate fast while still validating the guardrail itself when the guardrail code changes.

The workflow also runs on pull requests into `paullizer-react-v2-ui`. That trigger is marked temporary in the workflow file and should be removed when the V2 branch merges into Development.

## Local Usage

Run the checker against full files from the repository root:

```powershell
python scripts/check_xss_sinks.py --full-file application/single_app/static/js/chat/chat-messages.js
python scripts/check_xss_sinks.py --full-file application/v2_ui/src/components/chat/CitationChip.tsx
```

Check only the lines a branch added, the way the pull-request workflow does:

```powershell
python scripts/check_xss_sinks.py --base-sha origin/paullizer-react-v2-ui --head-sha HEAD <changed files>
```

Run the guardrail self-test:

```powershell
python functional_tests/test_xss_guardrails_checker.py
```

## Reviewed Exceptions

If a reviewed legacy exception is unavoidable, add the suppression token near the specific line and include a justification comment:

```text
xss-check: ignore
```

That token should remain rare. New rendering code should use the safe DOM patterns instead.

## V2 React/TypeScript Coverage

V2 coverage was added for GitHub issue #1571 while the application was at version **0.261.203**. It is a tooling-only change, so the application version did not change.

### Why V2 needs its own rules

The V2 UI in `application/v2_ui/src` is React 18 with TypeScript. React escapes JSX text and attribute strings, so most of the string-to-HTML sinks the classic rules look for do not appear there. React 18 does not close every path, though:

- It still renders `javascript:` URLs in `href`, `src`, `action`, `formAction` and `xlinkHref`, with only a development warning. React 19 blocks them; React 18 does not.
- `dangerouslySetInnerHTML` inserts its value as raw HTML.
- Refs and browser APIs (`innerHTML`, `insertAdjacentHTML`, `DOMParser`, `window.open`, `location`) bypass React entirely.
- `react-markdown` is safe on its defaults, but `rehype-raw`, `allowDangerousHtml` or a pass-through `urlTransform` turns raw HTML or unfiltered URLs back on.

The classic regexes also match JSX text, comments and type annotations as if they were code, so the TypeScript-family files get a separate pipeline.

### File types

| Files | How they are checked |
|---|---|
| `.js`, `.html`, `.py` | The existing regex checks, unchanged. |
| `.tsx`, `.jsx` | The TypeScript pipeline with JSX enabled. |
| `.ts`, `.mjs` | The TypeScript pipeline with JSX disabled, so `<T>` generics and comparisons are not read as tags. |
| `.d.ts`, `.d.mts`, `.d.cts` | Skipped. Declaration files hold types only. |
| `application/v2_ui/public/vendor/` | Skipped. These are vendored minified builds of Chart.js, DOMPurify, KaTeX and Mermaid. |

The V2 build output in `application/single_app/static/v2` is not tracked, so it is never scanned.

### How the TypeScript pipeline reads code

The checker lexes each file once. It separates comments, string and template literals, regular-expression literals, JSX text and JSX expression containers from code, and each rule matches against code only. As a result, comments, JSX text, string contents and type annotations do not produce findings, and `as` casts, non-null assertions (`value!`), generics, optional chaining and multi-line JSX attributes are handled.

The checker has no type information and does not follow values across files. It decides whether a value is safe from its local shape: literals, template-literal prefixes, helper names, reviewed builders, guards, and the local bindings it can resolve in the same file. When it cannot resolve a value, it reports the finding rather than assuming the value is safe.

### Rules

Every TypeScript-family finding starts with its rule id, for example `[ts-jsx-url-attribute]`.

| Rule id | What it flags | What it accepts |
|---|---|---|
| `ts-dangerous-inner-html` | `dangerouslySetInnerHTML`, as a JSX prop or an object key, whose `__html` is not sanitized. | `DOMPurify.sanitize(...)`, another `*purify*.sanitize(...)`, `sanitize*(...)` or `escape*Html(...)` result, inline, through a local `const`, or from a `useMemo(...)` whose every return is sanitized. Static strings. |
| `ts-html-sink` | `innerHTML`/`outerHTML` assignments, `insertAdjacentHTML`, `document.write`, `createContextualFragment`, and `DOMParser.parseFromString` output that is inserted into the page. | The same sanitized or static values. |
| `ts-code-eval` | `eval(...)`, `Function(...)` with or without `new`, and `setTimeout`/`setInterval` whose first argument is a string literal. | Function arguments to timers. |
| `ts-javascript-url` | A `javascript:` URL inside a string or template literal. | A literal that is exactly `javascript:`, such as an entry in a scheme blocklist. Comments and JSX text. |
| `ts-jsx-url-attribute` | Dynamic `href`, `xlinkHref`, `formAction` and `srcDoc` props; `action` on `<form>`; `src` on `<iframe>`, `<frame>`, `<script>` and `<embed>`; `data` on `<object>`; and `to` on `Link`, `NavLink` and `Navigate`. | See [Accepted URL sources](#accepted-url-sources). `srcDoc` must be sanitized HTML. |
| `ts-navigation-sink` | `window.open(...)`, `location.assign(...)`, `location.replace(...)`, `location.href = ...` and `location = ...` with a dynamic value. | Accepted URL sources, and a statement guard that dominates the call. |
| `ts-markdown-raw-html` | Any reference to `rehype-raw` (or `rehypeRaw`); `allowDangerousHtml` set to anything but `false`; a `urlTransform` that is not `defaultUrlTransform` or a `sanitize*`, `safe*` or `normalize*` function; and the older `transformLinkUri`/`transformImageUri` options when they are `null` or return their input unchanged. | `allowDangerousHtml={false}`, `defaultUrlTransform`, and sanitizing transforms. |
| `ts-dom-url-property` | Dynamic values assigned to `.href`, `.src`, `.action`, `.formAction` and `.srcdoc`, and `setAttribute`/`setAttributeNS` with `href`, `src`, `action`, `formaction`, `srcdoc` or `xlink:href`. | Accepted URL sources and statement guards. |
| `ts-inline-event-handler` | Inline handler attributes in generated HTML strings, `.onclick = '...'`-style string handlers and `setAttribute('on...', ...)`, as in the classic rules. | Function handlers. |
| `ts-attribute-interpolation` | Interpolated `href`, `src`, `title`, `style` and `data-*` attributes inside HTML strings, as in the classic rules. | The classic allowlist. |
| `ts-marked-parse` | `marked.parse(...)` without `DOMPurify.sanitize(...)` nearby, as in the classic rules. | Sanitized output. |

`<img src>` and other media sources are not script sinks, so they are not flagged. For DOM `.src` assignments the checker uses the receiver name: `previewImage.src` is treated as media, while any receiver whose name mentions a frame, script, embed, object or worker stays strict, even when it also sounds like media. A `.action` assignment is only checked when the receiver's name mentions a form, or when the receiver is a call or index result such as `document.forms[0]`, because `.action` is also a common data field.

### Accepted URL sources

A URL value passes when the checker can show that it is one of the following:

- A complete string literal. A literal `javascript:` URL is reported by `ts-javascript-url` instead.
- A template literal or `+` concatenation whose literal head is `/`, `#`, `?`, `./`, `../`, a relative path segment such as `chat/`, or one of `http:`, `https:`, `mailto:`, `tel:` and `data:image/`. A value that starts with an interpolation passes only when that value is itself an accepted URL source.
- `URL.createObjectURL(...)` for link-level sinks, `canvas.toDataURL(...)`, and the V2 `apiUrl(...)` helper.
- `location.href`, `location.origin`, `location.pathname`, `location.search`, `location.hash`, `import.meta.env` values, and upper-case constants such as `VENDOR_PATHS.mermaid`, which are treated as reviewed configuration.
- A call to a reviewed builder in `TS_SAME_ORIGIN_URL_BUILDERS` (same-origin paths with encoded segments) or `TS_HREF_URL_BUILDERS` (a fixed `mailto:` URL, link-level sinks only) in `scripts/check_xss_sinks.py`. Add a builder there only after reviewing that it cannot return a script URL.
- A call to a helper whose name matches `sanitize*Url`, `normalize*Url` or `safe*Url` (also `Href`, `Src` and `Uri` endings), or a `useMemo(...)` value whose every `return` is an accepted source. Other local functions are not followed.
- A value guarded by `isSafeOriginHref(value)`, a scheme regular expression such as `/^https?:/i.test(value)`, or `value.startsWith('https://')`. The guard can be part of the same expression (`guard ? value : undefined`, `guard && value`) or, for navigation and DOM sinks, an enclosing `if`, an `else` of a negated guard, or an earlier `if (!guard) return;` (also `throw`, `continue` and `break`) in the same or an enclosing block.
- A local binding that resolves to one of these. For `useState` values, every setter call must pass an accepted value; a setter that is handed to another component, or called with an updater function, makes the value unresolvable.

`<iframe>`, `<frame>`, `<script>`, `<embed>` and `<object>` sources, and DOM `.src` assignments that are not media, use a stricter level. A path that starts with a bare `/` must continue with an `encodeURIComponent(...)` segment, `//` and `/\` prefixes are rejected, an absolute URL passes only with a pinned host such as `https://www.youtube.com/`, and `URL.createObjectURL(...)` and the `mailto:` builder are not accepted.

Statement guards are deliberately narrow. The checker does not accept a guard combined with `||`, a guard that only exits in an `else if` branch or a `switch` case, a guard in a sibling block, or a value that is rebound or reassigned after the guard.

### Suppressions in TypeScript-family files

The suppression token `xss-check: ignore` works in TypeScript-family files too, but it counts only when a justification follows it on the same line. It can sit on any line of the finding or up to four lines above it:

```tsx
{/* xss-check: ignore reviewed: value is restricted to https URLs before it is stored */}
<a href={agent.homepage}>Homepage</a>
```

A token without a justification does not suppress anything, and the finding says that the reason is missing.

### Workflows

These pull-request workflows run on pull requests into `paullizer-react-v2-ui` as well as their existing branches:

- `xss-sink-check.yml`, whose `paths` filter and changed-file list now include `application/**/*.ts`, `application/**/*.tsx`, `application/**/*.jsx` and `application/**/*.mjs`
- `broken-access-control-check.yml`
- `swagger-route-check.yml`
- `python-syntax-check.yml`
- `malicious-pr-security-review.yml`
- `codeql.yml`, on both `push` and `pull_request`

Each V2 entry carries a `# Temporary` comment. Remove the entries when `paullizer-react-v2-ui` merges into Development. Recent pull requests from the fork `paullizer/simplechat` into Development ran all six workflows successfully, including the CodeQL upload, so they work for the cross-repository pull requests V2 usually receives. `release-notes-check.yml` stays Development-only.

`.github/workflows/xss-full-scan.yml` runs the checker over whole files on demand (`workflow_dispatch`). Its inputs choose the target paths (default `application`), whether findings fail the run, and whether to run the guardrail self-test first. The report is uploaded as the `xss-full-scan-report` artifact. GitHub only offers a `workflow_dispatch` workflow after the file exists on the default branch, so until then run the same scan locally. The full file list is longer than the 32,767-character limit Windows puts on a command line, so pass it in batches:

```powershell
$xssFiles = @(git ls-files "application/**/*.js" "application/**/*.html" "application/**/*.py" "application/**/*.ts" "application/**/*.tsx" "application/**/*.jsx" "application/**/*.mjs")
for ($i = 0; $i -lt $xssFiles.Count; $i += 200) {
    python scripts/check_xss_sinks.py --full-file $xssFiles[$i..([Math]::Min($i + 199, $xssFiles.Count - 1))]
}
```

A full scan of the application reports findings in the classic `.js`, `.html` and `.py` files that predate the V2 coverage, so the workflow's `fail_on_findings` input defaults to `false`. Narrow `target_paths` before turning it on.

### Baseline

A full-mode run over the tracked V2 source reports 28 findings. Every one has been reviewed and is safe; none is an exploitable XSS. The per-finding reasons, the before-and-after tuning counts and the lexing audit are in [XSS_PR_GUARDRAILS_V2_BASELINE_TRIAGE.md](XSS_PR_GUARDRAILS_V2_BASELINE_TRIAGE.md).

The pull-request check only reports added lines, so these existing findings do not fail pull requests unless the flagged lines change.

### Known limitations

- No type information. A timer call is only flagged when its first argument is a string literal, and a value's safety is judged from its local shape.
- No cross-file flow. A component that forwards a URL prop into a sink is flagged at the sink, and the value has to be traced through its callers by hand. Function parameters are treated as unresolved.
- Helper names are trusted. A function named like `sanitizeUrl`, or an upper-case constant, is accepted without inspecting its body or value, so a misnamed helper or constant would hide a finding.
- `//` is accepted in link-level sinks. A protocol-relative URL cannot run script, so it is an open-redirect concern rather than an XSS concern.
- jQuery `.html(...)` is not checked in TypeScript-family files; the V2 source does not use jQuery.
- `.js` files keep the classic checks even inside `application/v2_ui/`.

## Benefits

- Prevents common XSS sink regressions before merge
- Gives non-local contributors a CI guardrail instead of relying only on editor instructions
- Reinforces the safe rendering patterns already used in the hardened chat, workspace, and Control Center flows
- Keeps the first pass lightweight without introducing a full frontend lint stack

## Validation

Validation completed with:

- `python functional_tests/test_xss_guardrails_checker.py`
- targeted diagnostics on `scripts/check_xss_sinks.py`
- review of the Development PR workflow wiring in `.github/workflows/xss-sink-check.yml`

The V2 coverage added these checks to the same self-test, which runs under both `python` and `python -O`:

- a flagged case and an accepted case for each of the 11 TypeScript rules
- TypeScript syntax that must not be misread: type annotations, comments, strings, JSX comments, `as` casts, non-null assertions, generics, optional chaining and multi-line JSX attributes
- each precision refinement: form receivers, statement guards, `useState` setters, block scoping, reviewed builders and media receivers
- the file-type routing, including skipped declaration files and the V2 vendor directory, and classic `.js` output without rule ids
- justified, bare and out-of-range suppression tokens
- changed-line filtering in memory and against a real temporary Git repository, where diff mode reports only the added line and full mode reports every finding
- the workflow, instruction, prompt and documentation wiring for the new file types and the temporary V2 triggers

The checker's output for existing `.js`, `.html` and `.py` files is unchanged. A full-file run over all 2,881 tracked classic files produced the same findings before and after the V2 change, except for 26 findings in two vendored V2 libraries under `application/v2_ui/public/vendor/`, which the checker now skips.