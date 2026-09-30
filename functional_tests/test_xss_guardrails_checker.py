#!/usr/bin/env python3
# test_xss_guardrails_checker.py
"""
Functional test for XSS PR guardrail checker.
Version: 0.261.203
Implemented in: 0.241.021
V2 React/TypeScript coverage added in: 0.261.203 (#1571)

This test ensures the changed-file XSS checker flags the repo's target sink
patterns, allows the approved safe rendering patterns, and stays wired into
the repo instruction, PR workflow, and full-audit prompt. It also covers the
React/TypeScript rules for the V2 UI (.ts, .tsx, .jsx, .mjs): one flagged and
one allowed case per rule, the precision tuning, the justified suppression
token, and diff-only reporting. The TypeScript checks raise explicitly so they
still run under python -O.
"""

import contextlib
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_xss_sinks.py'
WORKFLOW_FILE = ROOT_DIR / '.github' / 'workflows' / 'xss-sink-check.yml'
INSTRUCTION_FILE = ROOT_DIR / '.github' / 'instructions' / 'xss-prevention.instructions.md'
FULL_AUDIT_PROMPT_FILE = ROOT_DIR / '.github' / 'prompts' / 'xss-full-audit-and-remediation.prompt.md'
FEATURE_DOC = ROOT_DIR / 'docs' / 'explanation' / 'features' / 'v0.241.022' / 'XSS_PR_GUARDRAILS.md'
CONFIG_FILE = ROOT_DIR / 'application' / 'single_app' / 'config.py'


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding='utf-8')


def load_checker_module():
    """Import the checker module from disk without touching sys.path."""
    spec = importlib.util.spec_from_file_location('check_xss_sinks', CHECKER_FILE)
    assert spec is not None and spec.loader is not None, 'Expected a module spec for check_xss_sinks.py'
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_config_version() -> str:
    """Extract the current application version from config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def issue_messages(module, file_name: str, source_text: str) -> list[str]:
    """Return the issue messages emitted for one in-memory source string."""
    issues = module.inspect_source(Path(file_name), source_text)
    return [issue.message for issue in issues]


WORKFLOWS_DIR = ROOT_DIR / '.github' / 'workflows'
V2_BRANCH = 'paullizer-react-v2-ui'
TS_RULE_PREFIX_RE = re.compile(r'\[([\w-]+)\]')


def require(condition: bool, message: str) -> None:
    """Raise AssertionError explicitly so the check still runs under python -O."""
    if not condition:
        raise AssertionError(message)


def ts_rule_ids(module, file_name: str, source_text: str, changed_lines: set[int] | None = None) -> list[str]:
    """Return the sorted TypeScript rule ids reported for one in-memory source string."""
    issues = module.inspect_source(Path(file_name), source_text, changed_lines=changed_lines)
    rule_ids = []
    for issue in issues:
        match = TS_RULE_PREFIX_RE.match(issue.message)
        rule_ids.append(match.group(1) if match else 'untagged')
    return sorted(rule_ids)


def require_ts_cases(module, cases: list[tuple[str, str, list[str]]]) -> None:
    """Check (file name, source, expected rule ids) cases and report every mismatch together."""
    known_rules = set(module.TS_RULE_IDS)
    failures = []
    for file_name, source_text, expected in cases:
        unknown = [rule for rule in expected if rule not in known_rules]
        require(not unknown, f'{file_name}: unknown rule ids in expectation {unknown}')
        actual = ts_rule_ids(module, file_name, source_text)
        if actual != sorted(expected):
            failures.append(f'{file_name}: expected {sorted(expected)}, got {actual}')
    require(not failures, 'TypeScript rule mismatches:\n' + '\n'.join(failures))


def remove_tree(path: Path) -> None:
    """Delete a temporary tree, including read-only git object files on Windows."""
    for child in path.rglob('*'):
        try:
            os.chmod(child, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            # Best effort only: rmtree below ignores errors, so a file left read-only just stays behind.
            pass
    shutil.rmtree(path, ignore_errors=True)


def test_checker_flags_dynamic_html_sinks_and_attribute_interpolation() -> None:
    """Verify dynamic HTML sinks and attribute interpolation are rejected."""
    module = load_checker_module()

    js_source = """
const row = document.createElement('tr');
row.innerHTML = `<td data-user-name="${userName}">${userName}</td>`;
""".strip()
    messages = issue_messages(module, 'sample.js', js_source)

    assert any('innerHTML/outerHTML' in message for message in messages), messages
    assert any('data-* attributes' in message for message in messages), messages


def test_checker_flags_marked_parse_inline_handlers_and_server_side_bypasses() -> None:
    """Verify the checker covers client and server bypass markers."""
    module = load_checker_module()

    js_source = """
const html = marked.parse(markdown);
button.setAttribute('onclick', 'runDanger()');
const rowHtml = `<button onclick="runDanger('${userName}')">Run</button>`;
""".strip()
    js_messages = issue_messages(module, 'sample.js', js_source)
    assert any('DOMPurify.sanitize' in message for message in js_messages), js_messages
    assert any('inline event-handler APIs' in message for message in js_messages), js_messages

    py_source = """
from markupsafe import Markup
safe_markup = Markup(user_supplied_html)
""".strip()
    py_messages = issue_messages(module, 'sample.py', py_source)
    assert any('Markup(...)' in message for message in py_messages), py_messages

    html_source = """
<div>{{ user_bio|safe }}</div>
""".strip()
    html_messages = issue_messages(module, 'sample.html', html_source)
    assert any("Jinja '|safe'" in message for message in html_messages), html_messages


def test_checker_allows_safe_dom_patterns_static_shells_and_reviewed_suppressions() -> None:
    """Verify the checker allows the repo's preferred safe rendering patterns."""
    module = load_checker_module()

    safe_js_source = """
const row = document.createElement('tr');
const nameCell = document.createElement('td');
nameCell.textContent = userName;
const actionButton = document.createElement('button');
actionButton.dataset.userName = userName;
actionButton.addEventListener('click', handleClick);
modal.innerHTML = '<div class="modal"><h5 class="modal-title"></h5></div>';
const renderedHtml = DOMPurify.sanitize(marked.parse(markdown));
const escapedName = escapeHtml(userName);
row.innerHTML = `<td title="${escapeHtml(userName)}" data-user-name="${escapedName}">${escapeHtml(userName)}</td>`;
document.querySelector(`[data-user-id="${userId}"]`);
""".strip()
    assert issue_messages(module, 'safe.js', safe_js_source) == []

    suppressed_js_source = """
// xss-check: ignore reviewed legacy shell with static allowlist
container.innerHTML = htmlFromReviewedBoundary;
""".strip()
    assert issue_messages(module, 'suppressed.js', suppressed_js_source) == []


def test_checker_assets_and_version_are_wired_into_repo() -> None:
    """Verify the new workflow, instruction, prompt, doc, and version bump landed together."""
    assert CHECKER_FILE.exists(), f'Expected checker script at {CHECKER_FILE}'
    assert WORKFLOW_FILE.exists(), f'Expected workflow file at {WORKFLOW_FILE}'
    assert INSTRUCTION_FILE.exists(), f'Expected instruction file at {INSTRUCTION_FILE}'
    assert FULL_AUDIT_PROMPT_FILE.exists(), f'Expected full-audit prompt at {FULL_AUDIT_PROMPT_FILE}'
    assert FEATURE_DOC.exists(), f'Expected feature document at {FEATURE_DOC}'
    assert_app_version_at_least("0.250.004")

    workflow_source = read_text(WORKFLOW_FILE)
    assert 'scripts/check_xss_sinks.py' in workflow_source
    assert 'functional_tests/test_xss_guardrails_checker.py' in workflow_source
    assert '.github/prompts/xss-full-audit-and-remediation.prompt.md' in workflow_source

    instruction_source = read_text(INSTRUCTION_FILE)
    assert 'xss-check: ignore' in instruction_source
    assert 'innerHTML' in instruction_source
    assert 'DOMPurify.sanitize' in instruction_source

    feature_doc_source = read_text(FEATURE_DOC)
    assert 'Fixed/Implemented in version: **0.241.021**' in feature_doc_source
    assert 'scripts/check_xss_sinks.py' in feature_doc_source
    assert '.github/workflows/xss-sink-check.yml' in feature_doc_source

    prompt_source = read_text(FULL_AUDIT_PROMPT_FILE)
    assert 'python scripts/check_xss_sinks.py --full-file' in prompt_source
    assert 'rg -n "innerHTML|outerHTML|insertAdjacentHTML' in prompt_source
    assert 'DOMPurify.sanitize(marked.parse' in prompt_source


R1 = 'ts-dangerous-inner-html'
R2 = 'ts-html-sink'
R3 = 'ts-code-eval'
R4 = 'ts-javascript-url'
R5 = 'ts-jsx-url-attribute'
R6 = 'ts-navigation-sink'
R7 = 'ts-markdown-raw-html'
R8 = 'ts-dom-url-property'
R9 = 'ts-inline-event-handler'
R10 = 'ts-attribute-interpolation'
R11 = 'ts-marked-parse'

TS_RULE_CASES = [
    # R1: dangerouslySetInnerHTML needs a sanitized __html value.
    ('r1-flag.tsx', 'export const A = ({ html }: { html: string }) => <div dangerouslySetInnerHTML={{ __html: html }} />;\n', [R1]),
    ('r1-allow.tsx', "import DOMPurify from 'dompurify';\nexport const A = ({ html }: { html: string }) => <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }} />;\n", []),
    ('r1-allow-const.tsx', "import DOMPurify from 'dompurify';\nconst clean = DOMPurify.sanitize(window.name);\nexport const A = () => <div dangerouslySetInnerHTML={{ __html: clean }} />;\n", []),
    # R2: DOM HTML sinks and DOMParser output inserted into the page.
    ('r2-flag-inner.ts', 'export function f(el: HTMLElement, html: string) { el.innerHTML = html; }\n', [R2]),
    ('r2-flag-adjacent.ts', "export function f(el: HTMLElement, html: string) { el.insertAdjacentHTML('beforeend', html); }\n", [R2]),
    ('r2-flag-write.ts', 'export function f(html: string) { document.write(html); }\n', [R2]),
    ('r2-flag-fragment.ts', 'export function f(range: Range, html: string) { return range.createContextualFragment(html); }\n', [R2]),
    ('r2-flag-parser.ts', "export function f(el: HTMLElement, html: string) {\n  const doc = new DOMParser().parseFromString(html, 'text/html');\n  el.appendChild(doc.body.firstChild!);\n}\n", [R2]),
    ('r2-allow-static.ts', "export function f(el: HTMLElement) { el.innerHTML = ''; }\n", []),
    ('r2-allow-sanitized.ts', "import DOMPurify from 'dompurify';\nexport function f(el: HTMLElement, html: string) { el.innerHTML = DOMPurify.sanitize(html); }\n", []),
    ('r2-allow-parser-text.ts', "export function f(html: string) {\n  const doc = new DOMParser().parseFromString(html, 'text/html');\n  return doc.body.textContent ?? '';\n}\n", []),
    # R3: string-to-code execution.
    ('r3-flag-eval.ts', 'export const run = (code: string) => eval(code);\n', [R3]),
    ('r3-flag-function.ts', "export const make = (body: string) => new Function('value', body);\n", [R3]),
    ('r3-flag-timer.ts', "setTimeout('refresh()', 10);\n", [R3]),
    ('r3-allow.ts', 'const evaluate = (value: number) => value * 2;\nsetTimeout(() => evaluate(1), 10);\nsetInterval(refresh, 1000);\n', []),
    # R4: javascript: URL literals.
    ('r4-flag.tsx', 'export const A = () => <a href="javascript:void(0)">x</a>;\n', [R4]),
    ('r4-allow-text.tsx', 'export const A = () => <p>Never use javascript: links</p>;\n', []),
    ('r4-allow-denylist.ts', "const BLOCKED_SCHEMES = ['javascript:', 'data:'];\nexport default BLOCKED_SCHEMES;\n", []),
    # R5: dynamic JSX URL attributes.
    ('r5-flag-href.tsx', 'export const A = ({ url }: { url: string }) => <a href={url}>x</a>;\n', [R5]),
    ('r5-flag-form.tsx', 'export const A = ({ url }: { url: string }) => <form action={url}><button formAction={url}>Go</button></form>;\n', [R5, R5]),
    ('r5-flag-srcdoc.tsx', 'export const A = ({ html }: { html: string }) => <iframe srcDoc={html} />;\n', [R5]),
    ('r5-flag-xlink.tsx', 'export const A = ({ url }: { url: string }) => <svg><use xlinkHref={url} /></svg>;\n', [R5]),
    ('r5-flag-router.tsx', "import { Link } from 'react-router-dom';\nexport const A = ({ url }: { url: string }) => <Link to={url}>x</Link>;\n", [R5]),
    ('r5-flag-guard-mismatch.tsx', 'export const A = ({ url, other }: { url: string; other: string }) => <a href={isSafeOriginHref(url) ? other : undefined}>x</a>;\n', [R5]),
    ('r5-flag-iframe-path.tsx', 'export const A = ({ path }: { path: string }) => <iframe src={`/${path}`} />;\n', [R5]),
    ('r5-flag-iframe-host.tsx', 'export const A = ({ host }: { host: string }) => <iframe src={`https://${host}/`} />;\n', [R5]),
    ('r5-allow-path.tsx', 'export const A = ({ id }: { id: string }) => <a href={`/chat/${encodeURIComponent(id)}`}>x</a>;\n', []),
    ('r5-allow-guard.tsx', 'export const A = ({ url }: { url: string }) => <a href={isSafeOriginHref(url) ? url : undefined}>x</a>;\n', []),
    ('r5-allow-helper.tsx', "import { sanitizeHttpUrl } from './urls';\nexport const A = ({ url }: { url: string }) => <a href={sanitizeHttpUrl(url)}>x</a>;\n", []),
    ('r5-allow-router.tsx', "import { Link } from 'react-router-dom';\nexport const A = ({ id }: { id: string }) => <Link to={`/workspace/${encodeURIComponent(id)}`}>x</Link>;\n", []),
    ('r5-allow-img.tsx', 'export const A = ({ src }: { src: string }) => <img src={src} alt="" />;\n', []),
    ('r5-allow-iframe-pinned.tsx', 'export const A = ({ id }: { id: string }) => <iframe src={`https://www.youtube.com/embed/${id}`} />;\n', []),
    # R6: navigation sinks.
    ('r6-flag-href.ts', 'export function go(url: string) { window.location.href = url; }\n', [R6]),
    ('r6-flag-open.ts', "export function go(url: string) { window.open(url, '_blank'); }\n", [R6]),
    ('r6-flag-methods.ts', 'export function go(url: string) {\n  window.location.assign(url);\n  window.location.replace(url);\n}\n', [R6, R6]),
    ('r6-flag-location.ts', 'export function go(url: string) { window.location = url; }\n', [R6]),
    ('r6-allow.ts', "export function go() { window.location.href = '/home'; window.open('/help', '_blank'); }\n", []),
    # R7: markdown raw HTML and URL-transform options.
    ('r7-flag-plugin.tsx', "import rehypeRaw from 'rehype-raw';\n", [R7]),
    ('r7-flag-transform.tsx', 'export const A = () => <ReactMarkdown urlTransform={(url) => url}>x</ReactMarkdown>;\n', [R7]),
    ('r7-flag-option.ts', 'export const options = { allowDangerousHtml: true };\n', [R7]),
    ('r7-allow-comment.tsx', '// Never add rehype-raw here.\nexport const x = 1;\n', []),
    ('r7-allow-off.tsx', "export const A = () => <ReactMarkdown skipHtml>{'x'}</ReactMarkdown>;\nexport const options = { allowDangerousHtml: false };\n", []),
    # R8: DOM URL properties and setAttribute.
    ('r8-flag-href.ts', 'export function f(a: HTMLAnchorElement, url: string) { a.href = url; }\n', [R8]),
    ('r8-flag-script.ts', "export function f(src: string) { const script = document.createElement('script'); script.src = src; }\n", [R8]),
    ('r8-flag-attribute.ts', "export function f(el: Element, url: string) { el.setAttribute('href', url); }\n", [R8]),
    ('r8-flag-form.ts', 'export function f(form: HTMLFormElement, url: string) { form.action = url; }\n', [R8]),
    ('r8-allow-blob.ts', 'export function f(a: HTMLAnchorElement, blob: Blob) { a.href = URL.createObjectURL(blob); }\n', []),
    ('r8-allow-media.ts', 'export function f(image: HTMLImageElement, url: string) { image.src = url; }\n', []),
    ('r8-allow-path.ts', 'export function f(a: HTMLAnchorElement, id: string) { a.href = `/files/${encodeURIComponent(id)}`; }\n', []),
    ('r8-flag-srcdoc.ts', 'export function f(frame: HTMLIFrameElement, html: string) { frame.srcdoc = html; }\n', [R8]),
    ('r8-allow-srcdoc.ts', "import DOMPurify from 'dompurify';\nexport function f(frame: HTMLIFrameElement, html: string) { frame.srcdoc = DOMPurify.sanitize(html); }\n", []),
    # R9-R11: the legacy string-HTML patterns, applied to code rather than comments.
    ('r9-flag-markup.ts', 'export const row = (id: string) => `<button onclick="run(${id})">Run</button>`;\n', [R9]),
    ('r9-flag-api.ts', "export function f(el: Element, handler: string) { el.setAttribute('onclick', handler); }\n", [R9]),
    ('r9-allow.tsx', "export function f(el: Element, handler: () => void) { el.addEventListener('click', handler); }\nexport const A = ({ run }: { run: () => void }) => <button onClick={() => run()}>Run</button>;\n", []),
    ('r10-flag.ts', 'export const link = (target: string) => `<a href="${target}">Open</a>`;\n', [R10]),
    ('r10-allow.ts', 'export const link = (id: string) => `<a href="/chat/${encodeURIComponent(id)}">Open</a>`;\n', []),
    ('r11-flag.ts', "import { marked } from 'marked';\nexport const render = (text: string) => marked.parse(text);\n", [R11]),
    ('r11-allow.ts', "import DOMPurify from 'dompurify';\nimport { marked } from 'marked';\nexport const render = (text: string) => DOMPurify.sanitize(marked.parse(text) as string);\n", []),
]


def test_typescript_rules_flag_unsafe_and_allow_safe_patterns() -> None:
    """Verify each React/TypeScript rule flags its unsafe form and allows its safe form."""
    module = load_checker_module()
    covered = {rule for _, _, expected in TS_RULE_CASES for rule in expected}
    require(covered == set(module.TS_RULE_IDS), f'Expected a flagged case for every rule, got {sorted(covered)}')
    require_ts_cases(module, TS_RULE_CASES)


TS_SYNTAX_CASES = [
    # Type-only code, comments and plain strings are not code sinks.
    ('syntax-types.tsx', 'export type Props = { href: string; dangerouslySetInnerHTML?: { __html: string } };\nexport interface LinkProps { href?: string; src?: string }\nlet html: TrustedHTML | string;\n', []),
    ('syntax-comments.ts', '// el.innerHTML = html;\n/* window.location.href = url; */\nexport const x = 1;\n', []),
    ('syntax-strings.ts', "export const help = 'Set el.innerHTML = value only after sanitizing';\n", []),
    ('syntax-jsx-comment.tsx', 'export const A = () => <div>{/* <a href={url}>old link</a> */}</div>;\n', []),
    # Casts, non-null assertions, generics, optional chaining and expression containers.
    ('syntax-cast-flag.tsx', 'export const A = ({ url }: { url: unknown }) => <a href={url as string}>x</a>;\n', [R5]),
    ('syntax-cast-allow.tsx', "import { sanitizeUrl } from './urls';\nexport const A = ({ raw }: { raw: string }) => <a href={sanitizeUrl(raw) as string}>x</a>;\n", []),
    ('syntax-non-null.ts', 'export function go(url?: string) { window.open(url!); }\n', [R6]),
    ('syntax-generic.tsx', 'const cache = new Map<string, string>();\nconst pick = <T,>(value: T): T => value;\nexport const A = ({ url }: { url: string }) => <a href={pick(url)}>x</a>;\n', [R5]),
    ('syntax-optional-chain.ts', 'export function go(link?: { url: string }) { window.open(link?.url); }\n', [R6]),
    ('syntax-optional-allow.tsx', "export const A = ({ item }: { item?: { id: string } }) => <a href={item?.id ? `/items/${encodeURIComponent(item.id)}` : '/'}>x</a>;\n", []),
    ('syntax-container.tsx', 'export const A = ({ url }: { url: string }) => <a href={ /* reviewed later */ url }>x</a>;\n', [R5]),
    ('syntax-multiline.tsx', 'export const A = ({ url }: { url: string }) => (\n  <a\n    className="link"\n    href={\n      url\n    }\n  >\n    x\n  </a>\n);\n', [R5]),
]

TS_TUNING_CASES = [
    # T1: `.action` is only a form URL on form-like receivers or call/index results.
    ('t1-allow-data-field.ts', 'export function f(transaction: { action: string }, value: string) { transaction.action = value; }\n', []),
    ('t1-flag-forms-index.ts', 'export function f(value: string) { document.forms[0].action = value; }\n', [R8]),
    ('t1-flag-set-attribute.ts', "export function f(el: Element, value: string) { el.setAttribute('action', value); }\n", [R8]),
    # T2: statement guards that dominate the sink.
    ('t2-allow-braceless.ts', 'export function go(u: string) { if (isSafeOriginHref(u)) window.open(u); }\n', []),
    ('t2-allow-block.ts', "export function go(u: string) { if (isSafeOriginHref(u)) { window.open(u, '_blank'); } }\n", []),
    ('t2-allow-early-return.ts', 'export function go(u: string) { if (!isSafeOriginHref(u)) return; window.location.assign(u); }\n', []),
    ('t2-allow-early-return-block.ts', 'export function go(u: string) { if (!isSafeOriginHref(u)) { return; } window.open(u); }\n', []),
    ('t2-allow-negated-else.ts', "export function go(u: string) { if (!isSafeOriginHref(u)) { console.warn('blocked'); } else { window.open(u); } }\n", []),
    ('t2-allow-scheme-regex.ts', 'const SAFE_SCHEME = /^https?:\\/\\//i;\nexport function go(u: string) { if (!SAFE_SCHEME.test(u)) return; window.open(u); }\n', []),
    ('t2-allow-loop-continue.ts', 'export function openAll(urls: string[]) { for (const u of urls) { if (!isSafeOriginHref(u)) continue; window.open(u); } }\n', []),
    ('t2-allow-dom-property.ts', 'export function f(a: HTMLAnchorElement, u: string) { if (isSafeOriginHref(u)) { a.href = u; } }\n', []),
    ('t2-flag-positive-else.ts', "export function go(u: string) { if (isSafeOriginHref(u)) { console.info('ok'); } else { window.open(u); } }\n", [R6]),
    ('t2-flag-no-exit.ts', "export function go(u: string) { if (!isSafeOriginHref(u)) { console.warn('blocked'); } window.open(u); }\n", [R6]),
    ('t2-flag-or.ts', 'export function go(u: string, force: boolean) { if (isSafeOriginHref(u) || force) { window.open(u); } }\n', [R6]),
    ('t2-flag-reassigned.ts', 'export function go(input: string) { let u = input; if (!isSafeOriginHref(u)) return; u = input.trim(); window.open(u); }\n', [R6]),
    ('t2-flag-shadowed.ts', 'export function go(u: string, list: string[]) { if (!isSafeOriginHref(u)) return; list.forEach((u) => window.open(u)); }\n', [R6]),
    ('t2-flag-sibling-block.ts', 'export function go(u: string, ok: boolean) { if (ok) { if (!isSafeOriginHref(u)) return; } window.open(u); }\n', [R6]),
    ('t2-flag-else-if.ts', "export function go(u: string, mode: string) { if (mode === 'x') { console.info(mode); } else if (!isSafeOriginHref(u)) return; window.open(u); }\n", [R6]),
    ('t2-flag-switch.ts', "export function go(u: string, mode: string) { switch (mode) { case 'a': if (!isSafeOriginHref(u)) break; case 'b': window.open(u); } }\n", [R6]),
    # T3: useState values follow every setter call.
    ('t3-allow-setter.tsx', "import { useCallback, useState } from 'react';\nexport function A({ raw }: { raw: string }) {\n  const [url, setUrl] = useState<string>('');\n  const apply = useCallback(() => setUrl(sanitizeUrl(raw)), [raw, setUrl]);\n  return <a href={url} onClick={apply}>x</a>;\n}\n", []),
    ('t3-flag-setter-value.tsx', "import { useEffect, useState } from 'react';\nexport function A({ raw }: { raw: string }) {\n  const [url, setUrl] = useState('');\n  useEffect(() => { setUrl(raw); }, [raw]);\n  return <a href={url}>x</a>;\n}\n", [R5]),
    ('t3-flag-setter-escapes.tsx', "import { useState } from 'react';\nexport function A() {\n  const [url, setUrl] = useState('');\n  return <><Picker onPick={setUrl} /><a href={url}>x</a></>;\n}\n", [R5]),
    ('t3-flag-updater.tsx', "import { useState } from 'react';\nexport function A({ raw }: { raw: string }) {\n  const [url, setUrl] = useState('');\n  const extend = () => setUrl((current) => current || raw);\n  return <a href={url} onClick={extend}>x</a>;\n}\n", [R5]),
    # T4: names resolve in the innermost block that declares them.
    ('t4-allow-local.ts', 'export function download(blob: Blob, a: HTMLAnchorElement) {\n  const url = URL.createObjectURL(blob);\n  a.href = url;\n}\nexport function describe(url: string) {\n  return url.length;\n}\n', []),
    ('t4-allow-inner-safe.ts', "export function go(a: HTMLAnchorElement, raw: string) {\n  const url = raw;\n  {\n    const url = '/home';\n    a.href = url;\n  }\n  return url;\n}\n", []),
    ('t4-flag-parameter-shadow.ts', "const url = '/home';\nexport function go(a: HTMLAnchorElement, url: string) {\n  a.href = url;\n}\n", [R8]),
    ('t4-flag-inner-shadow.ts', "export function go(a: HTMLAnchorElement, raw: string) {\n  const url = '/home';\n  {\n    const url = raw;\n    a.href = url;\n  }\n}\n", [R8]),
    ('t4-flag-imported.ts', "import { target } from './config';\nexport function go(a: HTMLAnchorElement) { a.href = target; }\n", [R8]),
    ('t4-flag-unbound.ts', 'export function go(a: HTMLAnchorElement) { a.href = someGlobal; }\n', [R8]),
    ('t4-flag-var-hoisting.ts', "const url = '/home';\nexport function go(a: HTMLAnchorElement, raw: string) {\n  if (raw) {\n    var url = raw;\n  }\n  a.href = url;\n}\n", [R8]),
    # T6/T7: reviewed builders and receiver-name hints for DOM src.
    ('t6-allow-vendor-script.ts', "export function load() {\n  const script = document.createElement('script');\n  script.src = vendorUrl(VENDOR_PATHS.mermaid);\n}\n", []),
    ('t7-flag-preview-frame.ts', 'export function f(previewFrame: HTMLIFrameElement, value: string) { previewFrame.src = value; }\n', [R8]),
    ('t7-allow-preview-image.ts', 'export function f(previewImage: HTMLImageElement, value: string) { previewImage.src = value; }\n', []),
]


def test_typescript_rules_handle_typescript_syntax() -> None:
    """Verify casts, generics, optional chaining, comments and type-only code are handled."""
    module = load_checker_module()
    require_ts_cases(module, TS_SYNTAX_CASES)


def test_typescript_precision_tuning_keeps_real_findings() -> None:
    """Verify the precision tuning approves proven-safe forms and still reports near misses."""
    module = load_checker_module()
    require_ts_cases(module, TS_TUNING_CASES)


def test_typescript_file_types_route_to_the_right_rules() -> None:
    """Verify .ts/.tsx/.jsx/.mjs use the TypeScript rules and .js/.html/.py keep the legacy rules."""
    module = load_checker_module()
    require_ts_cases(module, [
        ('route.jsx', 'export const A = ({ url }) => <a href={url}>x</a>;\n', [R5]),
        ('route.mjs', 'export const between = (a, b, c) => a < b && b > c;\nexport function go(url) { window.open(url); }\n', [R6]),
        ('route.ts', 'export function go(url: string) { window.location.href = url; }\n', [R6]),
        ('types.d.ts', 'declare const html: string;\nexport function f(el: HTMLElement) { el.innerHTML = html; }\n', []),
    ])

    legacy_messages = issue_messages(module, 'legacy.js', 'container.innerHTML = htmlFromServer;\n')
    require(legacy_messages, 'Expected the legacy .js rules to keep flagging innerHTML')
    require(
        not any(message.startswith('[ts-') for message in legacy_messages),
        f'.js files must keep the legacy rules, got {legacy_messages}',
    )

    vendor_file = module.REPO_ROOT / 'application' / 'v2_ui' / 'public' / 'vendor' / 'dompurify' / 'purify.min.js'
    source_file = module.REPO_ROOT / 'application' / 'v2_ui' / 'src' / 'App.tsx'
    require(module.is_skipped_vendor_browser_asset(vendor_file), 'V2 vendored browser assets must be skipped')
    require(not module.is_skipped_vendor_browser_asset(source_file), 'V2 source files must not be skipped')
    require(module.inspect_file(vendor_file) == [], 'inspect_file must skip V2 vendored assets before reading them')


def test_typescript_suppression_requires_a_justification() -> None:
    """Verify the suppression token works in TS/TSX comments only when a reason follows it."""
    module = load_checker_module()
    justified_tsx = (
        'export const A = ({ url }: { url: string }) => (\n'
        '  <>\n'
        '    {/* xss-check: ignore url comes from the reviewed server allowlist */}\n'
        '    <a href={url}>x</a>\n'
        '  </>\n'
        ');\n'
    )
    bare_tsx = justified_tsx.replace(' url comes from the reviewed server allowlist', '')
    justified_ts = (
        'export function go(url: string) {\n'
        '  // xss-check: ignore opened only with addresses from the reviewed allowlist\n'
        "  window.open(url, '_blank');\n"
        '}\n'
    )
    distant_ts = (
        '// xss-check: ignore opened only with addresses from the reviewed allowlist\n'
        '\n\n\n\n'
        "export function go(url: string) { window.open(url, '_blank'); }\n"
    )
    require_ts_cases(module, [
        ('suppressed.tsx', justified_tsx, []),
        ('bare-token.tsx', bare_tsx, [R5]),
        ('suppressed.ts', justified_ts, []),
        ('distant-token.ts', distant_ts, [R6]),
    ])

    bare_messages = issue_messages(module, 'bare-token.tsx', bare_tsx)
    require(
        len(bare_messages) == 1 and module.TS_BARE_SUPPRESSION_HINT in bare_messages[0],
        f'A bare token should keep the finding and explain the missing reason, got {bare_messages}',
    )


def test_typescript_diff_mode_checks_only_changed_lines() -> None:
    """Verify changed-line filtering covers every line of a multi-line JSX attribute."""
    module = load_checker_module()
    multiline_tsx = next(source for name, source, _ in TS_SYNTAX_CASES if name == 'syntax-multiline.tsx')
    expectations = [
        (None, [R5]),
        ({5}, [R5]),
        ({4}, [R5]),
        ({3}, []),
        ({8}, []),
        (set(), []),
    ]
    failures = []
    for changed_lines, expected in expectations:
        actual = ts_rule_ids(module, 'multiline.tsx', multiline_tsx, changed_lines=changed_lines)
        if actual != expected:
            failures.append(f'changed_lines={changed_lines}: expected {expected}, got {actual}')
    require(not failures, 'Diff filtering mismatches:\n' + '\n'.join(failures))


def run_git(repository: Path, *arguments: str) -> str:
    """Run one git command in a throwaway repository without touching global config."""
    command = [
        'git',
        '-c', 'user.name=XSS Guardrail Self-Test',
        '-c', 'user.email=xss-guardrail-self-test@example.invalid',
        '-c', 'commit.gpgsign=false',
        '-c', 'core.autocrlf=false',
        *arguments,
    ]
    result = subprocess.run(
        command,
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    require(result.returncode == 0, f'git {" ".join(arguments)} failed: {result.stderr.strip()}')
    return result.stdout.strip()


def run_checker_main(module, arguments: list[str]) -> tuple[int, str]:
    """Run the checker CLI in-process and return its exit code and output."""
    buffer = io.StringIO()
    original_argv = sys.argv
    sys.argv = ['check_xss_sinks.py', *arguments]
    try:
        with contextlib.redirect_stdout(buffer):
            exit_code = module.main()
    finally:
        sys.argv = original_argv
    return exit_code, buffer.getvalue()


def error_annotations(output: str) -> list[str]:
    """Return the GitHub error annotations printed by the checker."""
    return [line for line in output.splitlines() if line.startswith('::error ')]


def test_typescript_diff_mode_against_real_commits() -> None:
    """Verify --base-sha/--head-sha reports only added TSX lines, as the PR workflow runs it."""
    module = load_checker_module()
    require(shutil.which('git') is not None, 'git is required for the diff-mode check')
    temp_root = Path(tempfile.mkdtemp(prefix='xss-ts-diff-')).resolve()
    original_root = module.REPO_ROOT
    try:
        run_git(temp_root, 'init', '-q')
        (temp_root / 'src').mkdir()
        widget = temp_root / 'src' / 'Widget.tsx'
        base_lines = [
            '// Widget.tsx',
            'export const Old = ({ url }: { url: string }) => <a href={url}>old</a>;',
        ]
        widget.write_text('\n'.join(base_lines) + '\n', encoding='utf-8', newline='\n')
        run_git(temp_root, 'add', '--', 'src/Widget.tsx')
        run_git(temp_root, 'commit', '-q', '--no-verify', '-m', 'base')
        base_sha = run_git(temp_root, 'rev-parse', 'HEAD')

        head_lines = base_lines + [
            'export const Safe = ({ id }: { id: string }) => <a href={`/chat/${encodeURIComponent(id)}`}>safe</a>;',
            'export const Added = ({ link }: { link: string }) => (',
            '  <a',
            '    href={',
            '      link',
            '    }',
            '  >',
            '    new',
            '  </a>',
            ');',
        ]
        widget.write_text('\n'.join(head_lines) + '\n', encoding='utf-8', newline='\n')
        run_git(temp_root, 'commit', '-q', '--no-verify', '-am', 'head')
        head_sha = run_git(temp_root, 'rev-parse', 'HEAD')

        module.REPO_ROOT = temp_root
        diff_code, diff_output = run_checker_main(
            module, ['--base-sha', base_sha, '--head-sha', head_sha, 'src/Widget.tsx']
        )
        diff_annotations = error_annotations(diff_output)
        require(diff_code == 1, f'Expected diff mode to fail on the added link, got exit {diff_code}: {diff_output}')
        require(
            len(diff_annotations) == 1 and 'file=src/Widget.tsx,line=6::[ts-jsx-url-attribute]' in diff_annotations[0],
            f'Expected exactly the added multi-line href at line 6, got {diff_annotations}',
        )

        full_code, full_output = run_checker_main(module, ['--full-file', 'src/Widget.tsx'])
        full_lines = sorted(
            int(re.search(r',line=(\d+)::', annotation).group(1)) for annotation in error_annotations(full_output)
        )
        require(full_code == 1 and full_lines == [2, 6], f'Expected full-file findings on lines 2 and 6, got {full_lines}')

        widget.write_text('\n'.join(head_lines) + '\n// A comment-only follow-up.\n', encoding='utf-8', newline='\n')
        run_git(temp_root, 'commit', '-q', '--no-verify', '-am', 'comment only')
        comment_sha = run_git(temp_root, 'rev-parse', 'HEAD')
        clean_code, clean_output = run_checker_main(
            module, ['--base-sha', head_sha, '--head-sha', comment_sha, 'src/Widget.tsx']
        )
        require(
            clean_code == 0 and not error_annotations(clean_output),
            f'A comment-only change must not report existing findings, got exit {clean_code}: {clean_output}',
        )
    finally:
        module.REPO_ROOT = original_root
        remove_tree(temp_root)


def test_typescript_guardrail_wiring() -> None:
    """Verify the V2 suffixes, vendor skip, temporary V2 triggers, instruction and docs stay aligned."""
    module = load_checker_module()
    suffixes = set(module.SUPPORTED_SUFFIXES)
    require({'.js', '.html', '.py'} <= suffixes, f'Legacy suffixes must stay supported, got {sorted(suffixes)}')
    require({'.ts', '.tsx', '.jsx', '.mjs'} <= suffixes, f'V2 suffixes must be supported, got {sorted(suffixes)}')

    workflow_source = read_text(WORKFLOW_FILE)
    for suffix in sorted(suffixes):
        glob = f"'application/**/*{suffix}'"
        require(
            workflow_source.count(glob) >= 2,
            f'{glob} must be in both the pull_request paths filter and the xss_surface list of {WORKFLOW_FILE.name}',
        )

    for workflow_file in sorted(WORKFLOWS_DIR.glob('*.yml')):
        for line_number, line in enumerate(read_text(workflow_file).splitlines(), start=1):
            if V2_BRANCH in line:
                require(
                    'Temporary' in line,
                    f'{workflow_file.name}:{line_number} names {V2_BRANCH} without its temporary-trigger comment',
                )

    instruction_source = read_text(INSTRUCTION_FILE)
    apply_to = next((line for line in instruction_source.splitlines() if line.startswith('applyTo:')), '')
    for suffix in sorted(suffixes):
        require(f'**/*{suffix}' in apply_to, f'{INSTRUCTION_FILE.name} applyTo must include **/*{suffix}')
    require('dangerouslySetInnerHTML' in instruction_source, 'The instruction must cover dangerouslySetInnerHTML')

    feature_doc_source = read_text(FEATURE_DOC)
    require('## V2 React/TypeScript Coverage' in feature_doc_source, 'The feature doc must describe V2 coverage')
    require('application/v2_ui/public/vendor/' in feature_doc_source, 'The feature doc must name the V2 vendor skip')

    prompt_source = read_text(FULL_AUDIT_PROMPT_FILE)
    require('application/v2_ui/src' in prompt_source, 'The full-audit prompt must cover the V2 source tree')


if __name__ == '__main__':
    tests = [
        test_checker_flags_dynamic_html_sinks_and_attribute_interpolation,
        test_checker_flags_marked_parse_inline_handlers_and_server_side_bypasses,
        test_checker_allows_safe_dom_patterns_static_shells_and_reviewed_suppressions,
        test_checker_assets_and_version_are_wired_into_repo,
        test_typescript_rules_flag_unsafe_and_allow_safe_patterns,
        test_typescript_rules_handle_typescript_syntax,
        test_typescript_precision_tuning_keeps_real_findings,
        test_typescript_file_types_route_to_the_right_rules,
        test_typescript_suppression_requires_a_justification,
        test_typescript_diff_mode_checks_only_changed_lines,
        test_typescript_diff_mode_against_real_commits,
        test_typescript_guardrail_wiring,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            print('✅ PASS')
            results.append(True)
        except Exception as exc:  # pragma: no cover - standalone script reporting
            print(f'❌ FAIL: {exc}')
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)