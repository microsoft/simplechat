# check_xss_sinks.py

"""Validate changed files for risky XSS sink patterns."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SUFFIXES = {'.js', '.html', '.py', '.ts', '.tsx', '.jsx', '.mjs'}
TYPESCRIPT_FAMILY_SUFFIXES = {'.ts', '.tsx', '.jsx', '.mjs'}
JSX_ENABLED_SUFFIXES = {'.tsx', '.jsx'}
SUPPRESSION_TOKEN = 'xss-check: ignore'
INLINE_EVENT_ATTRIBUTE_RE = re.compile(
    r'\bon(?:abort|auxclick|beforeinput|blur|change|click|contextmenu|dblclick|error|focus|input|keydown|keypress|keyup|load|mousedown|mouseenter|mouseleave|mousemove|mouseout|mouseover|mouseup|reset|scroll|submit|touchend|touchstart|transitionend)\s*=\s*["\'][^"\'\n]*(?:\$\{|\{\{)',
    re.IGNORECASE,
)
INLINE_EVENT_API_RE = re.compile(
    r'\.(?:onabort|onblur|onchange|onclick|ondblclick|onerror|onfocus|oninput|onkeydown|onkeyup|onload|onmousedown|onmouseenter|onmouseleave|onmousemove|onmouseout|onmouseover|onmouseup|onscroll|onsubmit)\s*=\s*["\'`]|setAttribute\(\s*["\']on',
    re.IGNORECASE,
)
JAVASCRIPT_URL_RE = re.compile(r'javascript\s*:', re.IGNORECASE)
MARKUP_RE = re.compile(r'\bMarkup\s*\(')
JINJA_SAFE_RE = re.compile(r'\|\s*safe\b')
MARKED_PARSE_RE = re.compile(r'\bmarked\.parse\s*\(')
DANGEROUS_REACT_HTML_RE = re.compile(r'\bdangerouslySetInnerHTML\b')
ATTRIBUTE_INTERPOLATION_RE = re.compile(
    r'\b(?P<attr>href|src|title|style|data-[\w-]+)\s*=\s*(?P<quote>["\'])(?P<value>[^"\'\n]*\$\{[^}]+\}[^"\'\n]*)\2',
    re.IGNORECASE,
)
TEMPLATE_INTERPOLATION_RE = re.compile(r'\$\{(?P<expr>[^}]+)\}')
SAFE_ATTRIBUTE_FUNCTION_RE = re.compile(
    r'^(?:escapeHtml|escapeGroupHtml|encodeURIComponent|CSS\.escape|window\.CSS\.escape|DOMPurify\.sanitize|sanitize[A-Za-z0-9_]*|normalize[A-Za-z0-9_]*Url)\s*\(',
)
SAFE_URL_FUNCTION_RE = re.compile(
    r'^(?:'
    r'(?:encodeURIComponent|sanitize[A-Za-z0-9_]*Url|normalize[A-Za-z0-9_]*Url)\s*\('
    r'|escapeHtml\(\s*(?:safe[A-Za-z0-9_$]*(?:Url|URL|Src|Image|Img)|[A-Za-z_$][\w$]*(?:Url|URL|Src|Image|Img))\s*\)'
    r')',
)
SAFE_HTML_FUNCTION_RE = re.compile(r'^(?:escapeHtml|escapeGroupHtml|this\.escapeHtml|DOMPurify\.sanitize)\s*\(')
SAFE_IDENTIFIER_ASSIGNMENT_RE = re.compile(
    r'\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*'
    r'(?:escapeHtml|escapeGroupHtml|encodeURIComponent|CSS\.escape|window\.CSS\.escape|DOMPurify\.sanitize|sanitize[A-Za-z0-9_]*|normalize[A-Za-z0-9_]*Url)\s*\(',
)
SAFE_HTML_IDENTIFIER_ASSIGNMENT_RE = re.compile(
    r'\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*'
    r'(?:escapeHtml|escapeGroupHtml|this\.escapeHtml|DOMPurify\.sanitize)\s*\(',
)
SAFE_HTML_EXPRESSION_RE = re.compile(
    r'^(?:'
    r'(?:originalHtml|originalButtonHtml|originalText|button\.dataset\.originalHtml)|'
    r'actionConfig\.(?:label|pendingLabel|iconClass|title)|'
    r'(?:safe[A-Z][\w$]*|[A-Za-z_$][\w$]*(?:Id|ID|Index|Percent|Pct|Count|Total|Number|Class|State|Mode|Status|Role|Text|Label|Title|Url|URL|Src|Image|Img|Html|HTML|Message|Icon|Icons|Button|Buttons|Dropdown|Column|Columns|Row|Rows))|'
    r'(?:[A-Za-z_$][\w$]*\.)*htmlContent|'
    r'(?:build|render|create|highlight)[A-Za-z0-9_$]*(?:Html|HTML|Rows|Term)?\s*\(|'
    r'[A-Za-z_$][\w$]*\.join\(\s*["\']["\']\s*\)|'
    r'[A-Za-z_$][\w$]*\.filter\([^)]*\)\.map\([^)]*\)|'
    r'[A-Za-z_$][\w$]*\.map\('
    r')'
)
SAFE_ATTRIBUTE_PRIMITIVE_RE = re.compile(
    r'^(?:'
    r'actionConfig\.(?:label|pendingLabel|iconClass|title)|'
    r'(?:safe[A-Z][\w$]*|[A-Za-z_$][\w$]*(?:Id|ID|Index|Percent|Pct|Count|Total|Number|Class|State|Mode|Status|Role|Text|Label|Title|Url|URL|Src|Image|Img|Html|HTML)|'
    r'(?:is|has|can)[A-Z][\w$]*|(?:index|percent|pct|safePercent|laneIndex|days))'
    r'|(?:[A-Za-z_$][\w$]*\.)*(?:id|key|type|kind|state|status|mode|role)'
    r'|[A-Za-z_$][\w$]*\.toFixed\(\s*\d+\s*\)'
    r'|(?:true|false|null|undefined)'
    r'|\d+(?:\.\d+)?'
    r'|[^?]+\?\s*["\'][^"\']*["\']\s*:\s*["\'][^"\']*["\']'
    r')$'
)
VENDOR_BROWSER_ASSET_PREFIXES = (
    'application/single_app/static/js/openlayers/',
    'application/single_app/static/js/simplemde/',
    'application/v2_ui/public/vendor/',
)
HTML_ASSIGNMENT_RE = re.compile(
    r'(?P<target>[A-Za-z_$][\w$]*)\.(?P<sink>innerHTML|outerHTML)\s*=\s*(?P<expr>.{0,500}?);',
    re.DOTALL,
)
INSERT_ADJACENT_HTML_RE = re.compile(
    r'\.insertAdjacentHTML\s*\(\s*[^,]+,\s*(?P<expr>.{0,500}?)\)\s*;?',
    re.DOTALL,
)
JQUERY_HTML_RE = re.compile(
    r'\.html\s*\(\s*(?P<expr>.{0,500}?)\)\s*;?',
    re.DOTALL,
)
DIFF_HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@')


@dataclass(frozen=True)
class Issue:
    """A single checker violation."""

    file_path: Path
    line: int
    message: str


def get_relative_path(file_path: Path) -> str:
    """Return a repository-relative path when possible."""
    try:
        return file_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return file_path.as_posix()


def is_skipped_vendor_browser_asset(file_path: Path) -> bool:
    """Return True for pinned third-party browser assets outside app rendering review."""
    relative_path = get_relative_path(file_path)
    return any(relative_path.startswith(prefix) for prefix in VENDOR_BROWSER_ASSET_PREFIXES)


def format_error_annotation(issue: Issue) -> str:
    """Return a GitHub Actions annotation for one issue."""
    return f"::error file={get_relative_path(issue.file_path)},line={issue.line}::{issue.message}"


def normalize_paths(paths: list[str]) -> list[Path]:
    """Resolve CLI paths relative to the repository root and keep supported files."""
    normalized: list[Path] = []
    for raw_path in paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        if candidate.exists() and candidate.suffix in SUPPORTED_SUFFIXES:
            normalized.append(candidate)
    return normalized


def get_line_number(source_text: str, offset: int) -> int:
    """Return the 1-based line number for a source offset."""
    return source_text.count('\n', 0, offset) + 1


def matches_changed_lines(changed_lines: set[int] | None, start_line: int, end_line: int) -> bool:
    """Return True when the issue overlaps the changed lines or full-file mode is active."""
    if changed_lines is None:
        return True
    return any(line in changed_lines for line in range(start_line, end_line + 1))


def is_suppressed(source_lines: list[str], start_line: int, end_line: int) -> bool:
    """Return True when a suppression token is present near the reported lines."""
    window_start = max(1, start_line - 4)
    window_end = min(len(source_lines), end_line)
    for line_number in range(window_start, window_end + 1):
        if SUPPRESSION_TOKEN in source_lines[line_number - 1]:
            return True
    return False


def is_static_html_expression(expression: str) -> bool:
    """Return True when an HTML expression is a static literal without interpolation."""
    stripped = expression.strip()
    if not stripped:
        return True

    quote_pairs = [("'", "'"), ('"', '"'), ('`', '`')]
    for start_quote, end_quote in quote_pairs:
        if stripped.startswith(start_quote) and stripped.endswith(end_quote):
            return '${' not in stripped and '+' not in stripped

    return False


def get_safe_html_identifiers(source_text: str) -> set[str]:
    """Return local variable names assigned from known HTML-safe helpers."""
    return {
        match.group('name')
        for match in SAFE_HTML_IDENTIFIER_ASSIGNMENT_RE.finditer(source_text)
    }


def is_html_template_expression_allowed(expression: str, safe_html_identifiers: set[str] | None = None) -> bool:
    """Return True when all template interpolations are explicitly HTML-safe."""
    stripped = expression.strip()
    if not (stripped.startswith('`') and stripped.endswith('`')):
        return False

    expressions = get_template_interpolation_expressions(stripped)
    if not expressions:
        return True

    safe_identifiers = safe_html_identifiers or set()
    return all(
        interpolation in safe_identifiers
        or SAFE_HTML_FUNCTION_RE.match(interpolation)
        or SAFE_HTML_EXPRESSION_RE.match(interpolation)
        for interpolation in expressions
    )


def split_simple_concatenation(expression: str) -> list[str]:
    """Split a simple JS concatenation expression outside quoted strings."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    for char in expression:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == '\\':
            current.append(char)
            escaped = True
            continue
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'", '`'}:
            quote = char
            current.append(char)
            continue
        if char == '+':
            parts.append(''.join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append(''.join(current).strip())
    return parts


def is_allowed_html_concat_expression(expression: str, safe_html_identifiers: set[str] | None = None) -> bool:
    """Return True for static HTML concatenated only with escaped/safe pieces."""
    if '+' not in expression:
        return False
    safe_identifiers = safe_html_identifiers or set()
    parts = split_simple_concatenation(expression)
    if len(parts) < 2:
        return False
    return all(
        is_static_html_expression(part)
        or part in safe_identifiers
        or SAFE_HTML_FUNCTION_RE.match(part)
        or SAFE_HTML_EXPRESSION_RE.match(part)
        for part in parts
    )


def is_allowed_html_expression(expression: str, safe_html_identifiers: set[str] | None = None) -> bool:
    """Return True when an HTML sink expression is explicitly allowed."""
    stripped_expression = expression.strip()
    if 'DOMPurify.sanitize(' in expression:
        return True
    if stripped_expression in (safe_html_identifiers or set()):
        return True
    if SAFE_HTML_EXPRESSION_RE.match(stripped_expression):
        return True
    if is_allowed_html_concat_expression(stripped_expression, safe_html_identifiers=safe_html_identifiers):
        return True
    return is_static_html_expression(expression) or is_html_template_expression_allowed(
        expression,
        safe_html_identifiers=safe_html_identifiers,
    )


def get_safe_attribute_identifiers(source_text: str) -> set[str]:
    """Return local variable names assigned from known attribute-safe helpers."""
    return {
        match.group('name')
        for match in SAFE_IDENTIFIER_ASSIGNMENT_RE.finditer(source_text)
    }


def is_selector_interpolation_context(source_text: str, offset: int) -> bool:
    """Return True when interpolation appears in a CSS selector lookup, not rendered HTML."""
    line_start = source_text.rfind('\n', 0, offset) + 1
    line_end = source_text.find('\n', offset)
    if line_end == -1:
        line_end = len(source_text)
    line_text = source_text[line_start:line_end]
    stripped_line = line_text.strip()
    if stripped_line.startswith(('`.', '`#', "'.", "'#", '".', '"#')) and '<' not in stripped_line:
        return True
    return any(
        selector_api in line_text
        for selector_api in (
            'querySelector(',
            'querySelectorAll(',
            '.closest(',
            '.matches(',
        )
    )


def get_template_interpolation_expressions(attribute_value: str) -> list[str]:
    """Return JavaScript template expressions inside one attribute value."""
    return [
        match.group('expr').strip()
        for match in TEMPLATE_INTERPOLATION_RE.finditer(attribute_value)
    ]


def is_safe_attribute_expression(expression: str, safe_identifiers: set[str], *, url_attribute: bool) -> bool:
    """Return True when a template expression has an explicit safe boundary."""
    normalized_expression = expression.strip()
    if not normalized_expression:
        return True
    if '||' in normalized_expression:
        return all(
            is_safe_attribute_expression(part, safe_identifiers, url_attribute=url_attribute)
            for part in normalized_expression.split('||')
        )
    if normalized_expression in safe_identifiers:
        return True
    if SAFE_ATTRIBUTE_PRIMITIVE_RE.match(normalized_expression):
        return True
    if url_attribute:
        return bool(SAFE_URL_FUNCTION_RE.match(normalized_expression))
    return bool(SAFE_ATTRIBUTE_FUNCTION_RE.match(normalized_expression))


def is_local_url_template(attribute_value: str) -> bool:
    """Return True when an href/src template targets only app-local URL shapes."""
    stripped_value = attribute_value.strip()
    return stripped_value.startswith(('/', './', '../', '#'))


def is_allowed_attribute_interpolation(attr_name: str, attribute_value: str, safe_identifiers: set[str]) -> bool:
    """Return True for reviewed-safe template interpolation in inert attributes."""
    attr = attr_name.lower()
    expressions = get_template_interpolation_expressions(attribute_value)
    if not expressions:
        return True

    if attr in {'href', 'src'}:
        if not is_local_url_template(attribute_value):
            return all(
                is_safe_attribute_expression(expression, safe_identifiers, url_attribute=True)
                for expression in expressions
            )
        return all(
            is_safe_attribute_expression(expression, safe_identifiers, url_attribute=True)
            or is_safe_attribute_expression(expression, safe_identifiers, url_attribute=False)
            for expression in expressions
        )

    if attr.startswith('data-'):
        return all(
            is_safe_attribute_expression(expression, safe_identifiers, url_attribute=False)
            or SAFE_HTML_FUNCTION_RE.match(expression)
            for expression in expressions
        )

    return all(
        is_safe_attribute_expression(expression, safe_identifiers, url_attribute=False)
        for expression in expressions
    )


def get_changed_lines(file_path: Path, base_sha: str, head_sha: str) -> set[int] | None:
    """Return the added-line numbers for one file between two revisions."""
    relative_path = get_relative_path(file_path)
    command = [
        'git',
        'diff',
        '--unified=0',
        base_sha,
        head_sha,
        '--',
        relative_path,
    ]

    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
    except OSError:
        return None

    if result.returncode not in {0, 1}:
        return None

    changed_lines: set[int] = set()
    for line in result.stdout.splitlines():
        match = DIFF_HUNK_RE.match(line)
        if not match:
            continue

        start_line = int(match.group('start'))
        line_count = int(match.group('count') or '1')
        if line_count == 0:
            continue

        changed_lines.update(range(start_line, start_line + line_count))

    return changed_lines


def collect_regex_issues(
    *,
    file_path: Path,
    source_text: str,
    source_lines: list[str],
    changed_lines: set[int] | None,
    pattern: re.Pattern[str],
    message: str,
) -> list[Issue]:
    """Collect issues for a simple regex rule."""
    issues: list[Issue] = []
    for match in pattern.finditer(source_text):
        start_line = get_line_number(source_text, match.start())
        end_line = get_line_number(source_text, match.end())
        if pattern is JINJA_SAFE_RE:
            line_text = source_lines[start_line - 1] if start_line - 1 < len(source_lines) else ''
            if '|tojson' in line_text:
                continue
        if not matches_changed_lines(changed_lines, start_line, end_line):
            continue
        if is_suppressed(source_lines, start_line, end_line):
            continue
        issues.append(Issue(file_path=file_path, line=start_line, message=message))
    return issues


def collect_attribute_interpolation_issues(
    *,
    file_path: Path,
    source_text: str,
    source_lines: list[str],
    changed_lines: set[int] | None,
) -> list[Issue]:
    """Collect unsafe dynamic interpolation into rendered HTML attributes."""
    issues: list[Issue] = []
    safe_identifiers = get_safe_attribute_identifiers(source_text)
    for match in ATTRIBUTE_INTERPOLATION_RE.finditer(source_text):
        if is_selector_interpolation_context(source_text, match.start()):
            continue

        attr_name = match.group('attr')
        attr_value = match.group('value')
        if is_allowed_attribute_interpolation(attr_name, attr_value, safe_identifiers):
            continue

        start_line = get_line_number(source_text, match.start())
        end_line = get_line_number(source_text, match.end())
        if not matches_changed_lines(changed_lines, start_line, end_line):
            continue
        if is_suppressed(source_lines, start_line, end_line):
            continue

        issues.append(
            Issue(
                file_path=file_path,
                line=start_line,
                message=(
                    f"Avoid interpolating untrusted values directly into href/src/title/style/data-* attributes. "
                    f"Prefer DOM APIs and explicit URL normalization, or add '{SUPPRESSION_TOKEN}' with a justification."
                ),
            )
        )

    return issues


def collect_html_sink_issues(
    *,
    file_path: Path,
    source_text: str,
    source_lines: list[str],
    changed_lines: set[int] | None,
    pattern: re.Pattern[str],
    sink_name: str,
) -> list[Issue]:
    """Collect issues for dangerous HTML sinks."""
    issues: list[Issue] = []
    safe_html_identifiers = get_safe_html_identifiers(source_text)
    for match in pattern.finditer(source_text):
        target_name = match.groupdict().get('target') or ''
        expression = match.group('expr')
        if target_name.lower().startswith('temp') and expression.strip().startswith('String('):
            continue
        if is_allowed_html_expression(expression, safe_html_identifiers=safe_html_identifiers):
            continue

        start_line = get_line_number(source_text, match.start())
        end_line = get_line_number(source_text, match.end())
        if not matches_changed_lines(changed_lines, start_line, end_line):
            continue
        if is_suppressed(source_lines, start_line, end_line):
            continue

        issues.append(
            Issue(
                file_path=file_path,
                line=start_line,
                message=(
                    f"Avoid dynamic {sink_name} sinks with untrusted data. Prefer DOM APIs, textContent, "
                    f"or DOMPurify.sanitize(...), or add '{SUPPRESSION_TOKEN}' with a justification."
                ),
            )
        )
    return issues


def collect_marked_parse_issues(
    *,
    file_path: Path,
    source_text: str,
    source_lines: list[str],
    changed_lines: set[int] | None,
) -> list[Issue]:
    """Collect issues where marked.parse is not paired with DOMPurify.sanitize."""
    issues: list[Issue] = []
    for match in MARKED_PARSE_RE.finditer(source_text):
        start_line = get_line_number(source_text, match.start())
        end_line = get_line_number(source_text, match.end())
        if not matches_changed_lines(changed_lines, start_line, end_line):
            continue
        if is_suppressed(source_lines, start_line, end_line):
            continue

        window_start = max(1, start_line - 2)
        window_end = min(len(source_lines), end_line + 2)
        window_text = '\n'.join(source_lines[window_start - 1:window_end])
        if 'DOMPurify.sanitize(' in window_text:
            continue

        issues.append(
            Issue(
                file_path=file_path,
                line=start_line,
                message=(
                    "Wrap marked.parse(...) output with DOMPurify.sanitize(...) before rendering HTML, "
                    f"or add '{SUPPRESSION_TOKEN}' with a justification."
                ),
            )
        )
    return issues


# ---------------------------------------------------------------------------
# TypeScript / React (V2 UI) pipeline
#
# .ts, .tsx, .jsx and .mjs files are checked by a separate, React-aware rule set.
# A small lexer blanks comments, string contents, template chunks, regex bodies
# and JSX text so the rules only match real code, and records JSX attributes so
# URL-bearing props can be classified by element. The legacy .js/.html/.py
# rules above are not used for these files.
# ---------------------------------------------------------------------------

TS_RULE_DANGEROUS_INNER_HTML = 'ts-dangerous-inner-html'
TS_RULE_HTML_SINK = 'ts-html-sink'
TS_RULE_CODE_EVAL = 'ts-code-eval'
TS_RULE_JAVASCRIPT_URL = 'ts-javascript-url'
TS_RULE_JSX_URL_ATTRIBUTE = 'ts-jsx-url-attribute'
TS_RULE_NAVIGATION_SINK = 'ts-navigation-sink'
TS_RULE_MARKDOWN_RAW_HTML = 'ts-markdown-raw-html'
TS_RULE_DOM_URL_PROPERTY = 'ts-dom-url-property'
TS_RULE_INLINE_EVENT_HANDLER = 'ts-inline-event-handler'
TS_RULE_ATTRIBUTE_INTERPOLATION = 'ts-attribute-interpolation'
TS_RULE_MARKED_PARSE = 'ts-marked-parse'
TS_RULE_IDS = (
    TS_RULE_DANGEROUS_INNER_HTML,
    TS_RULE_HTML_SINK,
    TS_RULE_CODE_EVAL,
    TS_RULE_JAVASCRIPT_URL,
    TS_RULE_JSX_URL_ATTRIBUTE,
    TS_RULE_NAVIGATION_SINK,
    TS_RULE_MARKDOWN_RAW_HTML,
    TS_RULE_DOM_URL_PROPERTY,
    TS_RULE_INLINE_EVENT_HANDLER,
    TS_RULE_ATTRIBUTE_INTERPOLATION,
    TS_RULE_MARKED_PARSE,
)
TS_SUPPRESSION_ADVICE = f"or add '{SUPPRESSION_TOKEN}' with a justification."

# Reviewed V2 URL builders. Every entry returns a same-origin path (or '') built
# from a literal path prefix and encoded segments, so it is approved for href,
# navigation and strict (script/iframe) contexts. Re-review before adding names.
TS_SAME_ORIGIN_URL_BUILDERS = frozenset({
    'actionDetailPath',
    'artifactDownloadPath',
    'chatHrefForAgent',
    'chatHrefForConversation',
    'chatHrefForPrompt',
    'chatUploadTabularDownloadUrl',
    'classicChatHref',
    'enhancedCitationImageUrl',
    'enhancedCitationVisioUrl',
    'generatedArtifactDownloadUrl',
    'groupWorkspaceDocumentPath',
    'groupWorkspacePath',
    'publicWorkspaceDocumentPath',
    'publicWorkspacePath',
    'sameSiteAddress',
    'tabularWorkspaceDownloadUrl',
    # Prefixes the build-time Vite BASE_URL; callers pass VENDOR_PATHS constants.
    'vendorUrl',
    'workspaceBasePath',
    'workspaceDocumentDownloadUrl',
})
# Reviewed builders that return a fixed non-script scheme (mailto:), so they are
# approved for href and navigation contexts only.
TS_HREF_URL_BUILDERS = frozenset({'emailDraftMailtoUrl'})
TS_URL_GUARD_FUNCTIONS = frozenset({'isSafeOriginHref'})

_TS_SAFE_URL_HELPER_NAME_RE = re.compile(
    r'^(?:[\w$]+\.)*(?:sanitize|normalize|safe)[\w$]*(?:Url|URL|Href|Src|Uri|URI)[\w$]*$'
)
_TS_SAFE_HTML_CALL_RE = re.compile(
    r'^(?:(?:[\w$]+\.)*[\w$]*[Pp]urify[\w$]*\.sanitize|(?:[\w$]+\.)*sanitize[\w$]*|(?:[\w$]+\.)*escape[\w$]*Html)$'
)
_TS_SAFE_URL_TRANSFORM_RE = re.compile(
    r'^(?:defaultUrlTransform|undefined|(?:[\w$]+\.)*(?:sanitize|safe|normalize)[\w$]*)$'
)
_TS_TYPE_ONLY_VALUE_RE = re.compile(
    r'^(?:string|boolean|number|unknown|any|TrustedHTML|UrlTransform|null|undefined)'
    r'(?:\s*\|\s*(?:string|boolean|number|unknown|any|TrustedHTML|UrlTransform|null|undefined))*$'
)
_TS_IDENTIFIER_RE = re.compile(r'[A-Za-z_$][\w$]*')
_TS_IDENTIFIER_FULL_RE = re.compile(r'^[A-Za-z_$][\w$]*$')
_TS_UPPER_CONSTANT_RE = re.compile(r'^[A-Z][A-Z0-9_]*(?:\.[A-Za-z_$][\w$]*)*$')
_TS_LOCATION_VALUE_RE = re.compile(
    r'^(?:(?:window|document|globalThis|self)\.)?location\.(?:href|origin|pathname|search|hash)$'
)
_TS_IMPORT_META_ENV_RE = re.compile(r'^import\.meta\.env(?:\.[A-Za-z_$][\w$]*)*$')
_TS_NUMBER_LITERAL_RE = re.compile(r'^-?(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?n?$|^0[xXoObB][\da-fA-F_]+n?$')
_TS_RELATIVE_SEGMENT_HEAD_RE = re.compile(r'^[A-Za-z0-9._~-]+[/?#]')
_TS_HREF_SCHEME_HEAD_RE = re.compile(r'^(?:https?:|mailto:|tel:|data:image/)', re.IGNORECASE)
_TS_PINNED_HTTP_HEAD_RE = re.compile(r'^https?://[A-Za-z0-9.-]+(?::\d+)?[/?#]', re.IGNORECASE)
_TS_DATA_IMAGE_HEAD_RE = re.compile(r'^data:image/', re.IGNORECASE)
_TS_SCHEME_GUARD_REGEX_BODY_RE = re.compile(r'^\^\(?(?:\?:)?(?P<alts>[A-Za-z?|]+)\)?:')
_TS_SCHEME_GUARD_ALTERNATIVES = frozenset({'http', 'https', 'https?', 'mailto', 'tel'})
_TS_STARTS_WITH_GUARD_PREFIXES = frozenset({'http://', 'https://', 'mailto:', 'tel:', '/', '#', '?'})
_TS_MEDIA_TARGET_HINTS = (
    'img', 'image', 'icon', 'avatar', 'logo', 'thumb', 'picture', 'video', 'audio', 'poster', 'preview', 'photo', 'media',
)
# A receiver that also names a frame, script, embed, object or worker stays strict even
# when it carries a media hint (for example previewFrame.src).
_TS_STRICT_TARGET_HINTS = ('frame', 'script', 'embed', 'object', 'worker')
_TS_STATE_HOOKS = frozenset({'useState', 'React.useState'})
_TS_DEPENDENCY_HOOKS = frozenset({
    'useEffect', 'useLayoutEffect', 'useInsertionEffect', 'useCallback', 'useMemo', 'useImperativeHandle',
})
_TS_GUARDABLE_TARGET_RE = re.compile(r'^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$')
_TS_EXIT_STATEMENT_RE = re.compile(r'(?<![\w$.])(?:return|throw|continue|break)(?![\w$])')
_TS_IF_STATEMENT_RE = re.compile(r'(?<![\w$.])if\s*\(')
_TS_FUNCTION_EXPRESSION_RE = re.compile(r'(?:async\s+)?function(?![\w$])')

_TS_WHITESPACE_RE = re.compile(r'\s+')
_TS_WORD_RE = re.compile(r'[\w$]+')
_TS_NUMBER_RE = re.compile(r'\d[\w.]*')
_TS_SINGLE_QUOTE_STRING_RE = re.compile(r"'(?:[^'\\\n]|\\[\s\S])*'?")
_TS_DOUBLE_QUOTE_STRING_RE = re.compile(r'"(?:[^"\\\n]|\\[\s\S])*"?')
_TS_TEMPLATE_TEXT_RE = re.compile(r'(?:[^`\\$]|\\[\s\S]|\$(?!\{))*')
_TS_REGEX_LITERAL_RE = re.compile(r'/(?:[^/\\\[\n]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[A-Za-z]*')
_TS_JSX_TEXT_RE = re.compile(r'[^{<]*')
_TS_JSX_NAME_RE = re.compile(r'[A-Za-z_$][\w$.:-]*')
_TS_GENERIC_TYPE_PARAMETER_RE = re.compile(r'^(?:[A-Z]|T[A-Z]\w*)$')
_TS_NON_NEWLINE_RE = re.compile(r'[^\n]')

_TS_REGEX_PREVIOUS_PUNCTUATION = frozenset('(,=:[!&|?{};~+-*%^')
_TS_REGEX_KEYWORDS = frozenset({
    'return', 'typeof', 'case', 'in', 'of', 'void', 'yield', 'await', 'throw', 'delete', 'new', 'else', 'do',
    'instanceof',
})
_TS_QUOTE_AFTER_WORD_KEYWORDS = _TS_REGEX_KEYWORDS | {'from', 'import', 'export', 'default', 'extends'}
_TS_TRACKED_KEYWORDS = _TS_QUOTE_AFTER_WORD_KEYWORDS
_TS_QUOTE_AFTER_WORD_PREVIOUS = frozenset(f'w:{keyword}' for keyword in _TS_QUOTE_AFTER_WORD_KEYWORDS)
_TS_JSX_PREVIOUS_PUNCTUATION = frozenset('(,=:?[{&|')
_TS_JSX_KEYWORDS = frozenset({'return', 'yield', 'await', 'default'})
_TS_MAX_JSX_RETRIES = 64


@dataclass(frozen=True)
class TsJsxAttribute:
    """One JSX attribute recorded by the TypeScript lexer."""

    tag: str
    name: str
    start: int
    kind: str
    value_start: int
    value_end: int


@dataclass
class TsLexResult:
    """Lexer output used by the TypeScript rules."""

    code: str
    skeleton: str
    literal_ranges: list[tuple[int, int]]
    regex_ranges: list[tuple[int, int]]
    string_spans: dict[int, int]
    template_spans: dict[int, int]
    template_parts: dict[int, list[tuple[int, int]]]
    jsx_attributes: list[TsJsxAttribute]
    degraded: bool = False
    jsx_retries: int = 0


class _TsLexFailure(Exception):
    """Raised when a heuristic JSX start does not lex as JSX."""

    def __init__(self, position: int) -> None:
        super().__init__(position)
        self.position = position


def _ts_blank_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    """Return text with every non-newline character in the ranges replaced by a space."""
    if not ranges:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(ranges):
        if end <= cursor:
            continue
        start = max(start, cursor)
        pieces.append(text[cursor:start])
        pieces.append(_TS_NON_NEWLINE_RE.sub(' ', text[start:end]))
        cursor = end
    pieces.append(text[cursor:])
    return ''.join(pieces)


class _TsLexer:
    """Single-pass TypeScript/JSX lexer that records literal, regex and JSX structure."""

    def __init__(self, text: str, jsx: bool, not_jsx: set[int]) -> None:
        self.text = text
        self.length = len(text)
        self.jsx = jsx
        self.not_jsx = not_jsx
        self.code_blanks: list[tuple[int, int]] = []
        self.skeleton_blanks: list[tuple[int, int]] = []
        self.literal_ranges: list[tuple[int, int]] = []
        self.regex_ranges: list[tuple[int, int]] = []
        self.string_spans: dict[int, int] = {}
        self.template_spans: dict[int, int] = {}
        self.template_parts: dict[int, list[tuple[int, int]]] = {}
        self.jsx_attributes: list[TsJsxAttribute] = []

    def run(self) -> TsLexResult:
        stack: list[dict] = [{'type': 'code', 'depth': 0, 'role': 'top', 'prev': None}]
        position = 0
        while position < self.length:
            frame = stack[-1]
            frame_type = frame['type']
            if frame_type == 'code':
                position = self._step_code(stack, frame, position)
            elif frame_type == 'template':
                position = self._step_template(stack, frame, position)
            elif frame_type == 'jsx_tag':
                position = self._step_jsx_tag(stack, frame, position)
            else:
                position = self._step_jsx_children(stack, frame, position)

        for frame in reversed(stack):
            if frame['type'] in {'jsx_tag', 'jsx_children'}:
                raise _TsLexFailure(frame['hstart'])
        for frame in stack:
            if frame['type'] == 'template':
                self.template_spans[frame['start']] = self.length
                self.template_parts[frame['start']] = frame['parts']

        code = _ts_blank_ranges(self.text, self.code_blanks)
        skeleton = _ts_blank_ranges(self.text, self.skeleton_blanks)
        return TsLexResult(
            code=code,
            skeleton=skeleton,
            literal_ranges=sorted(self.literal_ranges),
            regex_ranges=sorted(self.regex_ranges),
            string_spans=self.string_spans,
            template_spans=self.template_spans,
            template_parts=self.template_parts,
            jsx_attributes=self.jsx_attributes,
        )

    def _comment(self, start: int, end: int) -> None:
        self.code_blanks.append((start, end))
        self.skeleton_blanks.append((start, end))

    def _skip_whitespace(self, position: int) -> int:
        while position < self.length and self.text[position].isspace():
            position += 1
        return position

    @staticmethod
    def _regex_allowed(prev: str | None) -> bool:
        if prev is None or prev == '=>':
            return True
        if prev.startswith('w:'):
            return prev[2:] in _TS_REGEX_KEYWORDS
        return prev in _TS_REGEX_PREVIOUS_PUNCTUATION

    @staticmethod
    def _jsx_allowed(prev: str | None) -> bool:
        if prev is None or prev == '=>':
            return True
        if prev.startswith('w:'):
            return prev[2:] in _TS_JSX_KEYWORDS
        return prev in _TS_JSX_PREVIOUS_PUNCTUATION

    def _step_code(self, stack: list[dict], frame: dict, position: int) -> int:
        text = self.text
        char = text[position]
        if char.isspace():
            return _TS_WHITESPACE_RE.match(text, position).end()

        if char == '/':
            next_char = text[position + 1] if position + 1 < self.length else ''
            if next_char == '/' and not (position > 0 and text[position - 1] == ':'):
                end = text.find('\n', position)
                end = self.length if end == -1 else end
                self._comment(position, end)
                return end
            if next_char == '*':
                end = text.find('*/', position + 2)
                if end != -1:
                    self._comment(position, end + 2)
                    return end + 2
            elif self._regex_allowed(frame['prev']):
                match = _TS_REGEX_LITERAL_RE.match(text, position)
                if match:
                    closing_slash = text.rfind('/', position + 1, match.end())
                    self.regex_ranges.append((position, match.end()))
                    self.skeleton_blanks.append((position + 1, closing_slash))
                    frame['prev'] = 'value'
                    return match.end()
            frame['prev'] = '/'
            return position + 1

        if char in {"'", '"'}:
            if (
                position > 0
                and (text[position - 1].isalnum() or text[position - 1] in '_$')
                and frame['prev'] not in _TS_QUOTE_AFTER_WORD_PREVIOUS
            ):
                frame['prev'] = 'value'
                return position + 1
            pattern = _TS_SINGLE_QUOTE_STRING_RE if char == "'" else _TS_DOUBLE_QUOTE_STRING_RE
            end = pattern.match(text, position).end()
            closed = end - position >= 2 and text[end - 1] == char
            content_end = end - 1 if closed else end
            self.string_spans[position] = end
            self.literal_ranges.append((position + 1, content_end))
            self.skeleton_blanks.append((position + 1, content_end))
            frame['prev'] = 'value'
            return end

        if char == '`':
            stack.append({'type': 'template', 'start': position, 'parts': []})
            return position + 1

        if char == '{':
            frame['depth'] += 1
            frame['prev'] = '{'
            return position + 1

        if char == '}':
            if frame['depth'] > 0:
                frame['depth'] -= 1
                frame['prev'] = '}'
                return position + 1
            role = frame['role']
            if role == 'top':
                frame['prev'] = '}'
                return position + 1
            stack.pop()
            parent = stack[-1]
            if role == 'template':
                parent['parts'].append((frame['inner_start'], position))
            elif role == 'jsx_attr':
                tag, name, start = frame['attr']
                self.jsx_attributes.append(
                    TsJsxAttribute(tag, name, start, 'expression', frame['inner_start'], position)
                )
            elif role == 'jsx_spread':
                tag, name, start = frame['attr']
                self.jsx_attributes.append(
                    TsJsxAttribute(tag, name, start, 'spread', frame['inner_start'], position)
                )
            return position + 1

        if char == '<' and self.jsx and position not in self.not_jsx and self._jsx_allowed(frame['prev']):
            started = self._try_start_jsx(stack, frame, position)
            if started is not None:
                return started
            frame['prev'] = '<'
            return position + 1

        if char.isdigit():
            frame['prev'] = 'value'
            return _TS_NUMBER_RE.match(text, position).end()

        if char.isalpha() or char in '_$':
            match = _TS_WORD_RE.match(text, position)
            end = match.end() if match and match.end() > position else position + 1
            word = text[position:end]
            if frame['prev'] == '.':
                frame['prev'] = 'value'
            elif word in _TS_TRACKED_KEYWORDS:
                frame['prev'] = f'w:{word}'
            else:
                frame['prev'] = 'value'
            return end

        if char == '=' and text.startswith('=>', position):
            frame['prev'] = '=>'
            return position + 2

        if char in ')]':
            frame['prev'] = 'value'
            return position + 1

        frame['prev'] = char
        return position + 1

    def _skip_type_arguments(self, position: int) -> int:
        """Skip a JSX element's <TypeArguments> block when present."""
        if position >= self.length or self.text[position] != '<':
            return position
        depth = 0
        cursor = position
        while cursor < self.length:
            char = self.text[cursor]
            if char == '<':
                depth += 1
            elif char == '>' and self.text[cursor - 1] != '=':
                depth -= 1
                if depth == 0:
                    return cursor + 1
            elif char in '\n;':
                break
            cursor += 1
        return position

    def _try_start_jsx(self, stack: list[dict], frame: dict, position: int) -> int | None:
        text = self.text
        name_start = position + 1
        if name_start >= self.length:
            return None
        first = text[name_start]
        if first == '>':
            name = ''
            name_end = name_start
        else:
            if not (first.isalpha() or first in '_$'):
                return None
            name_match = _TS_JSX_NAME_RE.match(text, name_start)
            name = name_match.group()
            name_end = name_match.end()
            after = self._skip_whitespace(name_end)
            next_char = text[after] if after < self.length else ''
            if next_char in {',', '='}:
                return None
            if text.startswith('extends', after) and not text[after + 7:after + 8].isalnum():
                return None
            if next_char == '>' and _TS_GENERIC_TYPE_PARAMETER_RE.match(name):
                return None
            if frame['prev'] == ':' and next_char == '>':
                after_close = self._skip_whitespace(after + 1)
                if after_close < self.length and text[after_close] == '(':
                    return None

        tag_frame = {'type': 'jsx_tag', 'tag': name, 'hstart': position, 'from_code': True}
        stack.append(tag_frame)
        return self._skip_type_arguments(name_end)

    def _close_jsx_element(self, stack: list[dict], frame: dict) -> None:
        if frame['from_code'] and stack and stack[-1]['type'] == 'code':
            stack[-1]['prev'] = 'value'

    def _step_jsx_tag(self, stack: list[dict], frame: dict, position: int) -> int:
        text = self.text
        char = text[position]
        if char.isspace():
            return _TS_WHITESPACE_RE.match(text, position).end()

        if char == '/':
            next_char = text[position + 1] if position + 1 < self.length else ''
            if next_char == '>':
                stack.pop()
                self._close_jsx_element(stack, frame)
                return position + 2
            if next_char == '/':
                end = text.find('\n', position)
                end = self.length if end == -1 else end
                self._comment(position, end)
                return end
            if next_char == '*':
                end = text.find('*/', position + 2)
                if end == -1:
                    raise _TsLexFailure(frame['hstart'])
                self._comment(position, end + 2)
                return end + 2
            raise _TsLexFailure(frame['hstart'])

        if char == '>':
            frame['type'] = 'jsx_children'
            return position + 1

        if char == '{':
            stack.append({
                'type': 'code',
                'depth': 0,
                'role': 'jsx_spread',
                'prev': '{',
                'inner_start': position + 1,
                'attr': (frame['tag'], '...', position),
            })
            return position + 1

        if not (char.isalpha() or char in '_$'):
            raise _TsLexFailure(frame['hstart'])
        name_match = _TS_JSX_NAME_RE.match(text, position)
        name = name_match.group()
        after_name = self._skip_whitespace(name_match.end())
        if after_name < self.length and text[after_name] == '=':
            value_start = self._skip_whitespace(after_name + 1)
            quote = text[value_start] if value_start < self.length else ''
            if quote in {'"', "'"}:
                close = text.find(quote, value_start + 1)
                if close == -1:
                    raise _TsLexFailure(frame['hstart'])
                self.literal_ranges.append((value_start + 1, close))
                self.skeleton_blanks.append((value_start + 1, close))
                self.string_spans[value_start] = close + 1
                self.jsx_attributes.append(
                    TsJsxAttribute(frame['tag'], name, position, 'string', value_start + 1, close)
                )
                return close + 1
            if quote == '{':
                stack.append({
                    'type': 'code',
                    'depth': 0,
                    'role': 'jsx_attr',
                    'prev': '{',
                    'inner_start': value_start + 1,
                    'attr': (frame['tag'], name, position),
                })
                return value_start + 1
            raise _TsLexFailure(frame['hstart'])

        self.jsx_attributes.append(
            TsJsxAttribute(frame['tag'], name, position, 'boolean', name_match.end(), name_match.end())
        )
        return name_match.end()

    def _step_jsx_children(self, stack: list[dict], frame: dict, position: int) -> int:
        text = self.text
        char = text[position]
        if char == '{':
            stack.append({'type': 'code', 'depth': 0, 'role': 'jsx_child', 'prev': '{', 'inner_start': position + 1})
            return position + 1

        if char == '<':
            name_start = position + 1
            if name_start < self.length and text[name_start] == '/':
                cursor = self._skip_whitespace(name_start + 1)
                name_match = _TS_JSX_NAME_RE.match(text, cursor)
                name = name_match.group() if name_match else ''
                cursor = self._skip_whitespace(name_match.end() if name_match else cursor)
                if cursor >= self.length or text[cursor] != '>' or name != frame['tag']:
                    raise _TsLexFailure(frame['hstart'])
                stack.pop()
                self._close_jsx_element(stack, frame)
                return cursor + 1

            if name_start < self.length and text[name_start] == '>':
                name = ''
                name_end = name_start
            else:
                if name_start >= self.length or not (text[name_start].isalpha() or text[name_start] in '_$'):
                    raise _TsLexFailure(frame['hstart'])
                name_match = _TS_JSX_NAME_RE.match(text, name_start)
                name = name_match.group()
                name_end = name_match.end()
            stack.append({'type': 'jsx_tag', 'tag': name, 'hstart': frame['hstart'], 'from_code': False})
            return self._skip_type_arguments(name_end)

        end = _TS_JSX_TEXT_RE.match(text, position).end()
        if end <= position:
            end = position + 1
        self.skeleton_blanks.append((position, end))
        return end

    def _step_template(self, stack: list[dict], frame: dict, position: int) -> int:
        text = self.text
        end = _TS_TEMPLATE_TEXT_RE.match(text, position).end()
        if end > position:
            self.literal_ranges.append((position, end))
            self.skeleton_blanks.append((position, end))
        if end < self.length and text[end] == '`':
            stack.pop()
            self.template_spans[frame['start']] = end + 1
            self.template_parts[frame['start']] = frame['parts']
            if stack and stack[-1]['type'] == 'code':
                stack[-1]['prev'] = 'value'
            return end + 1
        if end < self.length and text.startswith('${', end):
            stack.append({'type': 'code', 'depth': 0, 'role': 'template', 'prev': '{', 'inner_start': end + 2})
            return end + 2
        # Unterminated template (or a dangling backslash at EOF): close it at EOF.
        stack.pop()
        self.template_spans[frame['start']] = self.length
        self.template_parts[frame['start']] = frame['parts']
        if self.length > end:
            self.literal_ranges.append((end, self.length))
            self.skeleton_blanks.append((end, self.length))
        return self.length


def lex_typescript(text: str, jsx: bool) -> TsLexResult:
    """Lex TypeScript source, retrying without JSX at positions that fail to lex as JSX."""
    if not jsx:
        return _TsLexer(text, False, set()).run()

    not_jsx: set[int] = set()
    for _ in range(_TS_MAX_JSX_RETRIES):
        try:
            result = _TsLexer(text, True, not_jsx).run()
            result.jsx_retries = len(not_jsx)
            return result
        except _TsLexFailure as failure:
            if failure.position in not_jsx:
                break
            not_jsx.add(failure.position)

    result = _TsLexer(text, False, set()).run()
    result.degraded = True
    result.jsx_retries = len(not_jsx)
    return result


_TS_DECLARATION_RE = re.compile(r'(?<![\w$.])(?:const|let|var)\s+')
_TS_ARROW_SINGLE_PARAMETER_RE = re.compile(r'(?<![\w$.])([A-Za-z_$][\w$]*)\s*=>')
_TS_CALL_HEAD_RE = re.compile(
    r'(?P<new>new\s+)?(?P<callee>[A-Za-z_$][\w$]*(?:\s*\??\.\s*[A-Za-z_$][\w$]*)*)\s*'
)
_TS_PARAMETER_MODIFIERS_RE = re.compile(r'(?:(?:public|private|protected|readonly|override)\s+)+')
_TS_PARAMETER_EXCLUDED_KEYWORDS = frozenset({'if', 'for', 'while', 'switch', 'with'})
_TS_TRAILING_WORD_RE = re.compile(r'([\w$]+)\s*$')
_TS_AS_PREFIX_RE = re.compile(r'(?<![\w$])as\s*$')
_TS_DECLARE_PREFIX_RE = re.compile(r'(?<![\w$])declare\s*$')
_TS_LOOP_BINDING_RE = re.compile(r'(?:of|in)(?![\w$])')
_TS_AWAIT_PREFIX_RE = re.compile(r'await\s+')
_TS_RETURN_RE = re.compile(r'(?<![\w$.])return\b[ \t]*')
_TS_REGEX_TEST_CALL_RE = re.compile(r'\s*\.\s*test\s*\(')
_TS_HTML_KEY_RE = re.compile(r'(?P<quote>["\']?)__html(?P=quote)(?![\w$])\s*(?P<optional>\?)?\s*(?P<colon>:)?')
_TS_PATHNAME_KEY_RE = re.compile(r'(?P<quote>["\']?)pathname(?P=quote)(?![\w$])\s*(?P<colon>:)?')
_TS_IDENTITY_ARROW_RE = re.compile(r'^\(?([A-Za-z_$][\w$]*)(?::[^)]*)?\)?=>\1$')
_TS_ASSIGNMENT_TARGET_RE = re.compile(
    r'(?<![\w$.])(?:(?:const|let|var)\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*(?:!\s*)?(?::\s*[\w$.<>\[\]|&\s]+?)?=(?![=>])'
)
_TS_JUSTIFICATION_RE = re.compile(r'[A-Za-z]{3,}')
_TS_CONTINUE_AFTER = frozenset('=+-*/%&|^!~?:,.<>([{')
_TS_CONTINUE_BEFORE = frozenset('.?:+-*/%&|^=<>')
_TS_TYPE_CONTINUE_AFTER = frozenset('|&:,.<([{?')
_TS_UNARY_PLUS_PREVIOUS = frozenset('=+-*/%&|^!~?:,<>')
_TS_LITERAL_KEYWORD_VALUES = frozenset({'undefined', 'null', 'false', 'true'})
_TS_MAX_RESOLVE_DEPTH = 12
_TS_MAX_EXPRESSION_DEPTH = 24


class TsSourceView:
    """Structural queries over one lexed TypeScript/TSX file.

    Offsets index the original text. Structural scans run on the lexer skeleton
    (comments, literal contents, regex bodies and JSX text blanked), so brackets
    and operators inside strings or comments never affect the result.
    """

    def __init__(self, text: str, lex: TsLexResult) -> None:
        self.text = text
        self.lex = lex
        self.code = lex.code
        self.skeleton = lex.skeleton
        self.lines = text.split('\n')
        self.line_starts = [0] + [match.end() for match in re.finditer(r'\n', text)]
        self.match = self._build_bracket_matches()
        self.reverse_match = {close: open_position for open_position, close in self.match.items()}
        self.literal_ranges = lex.literal_ranges
        self.literal_starts = [start for start, _ in lex.literal_ranges]
        self.regex_spans = dict(lex.regex_ranges)
        self.attribute_name_starts = {attribute.start for attribute in lex.jsx_attributes}
        self._definitions: dict[str, list[tuple[str, int, int]]] | None = None
        self._definition_sites: dict[str, list[int]] = {}
        self._function_scoped_names: set[str] = set()
        self._unresolvable: set[str] = set()
        self._unresolvable_sites: dict[str, list[int]] = {}
        self._declaration_name_offsets: set[int] = set()
        self._assignment_cache: dict[str, list[tuple[str, int, int]]] = {}
        self._block_cache: dict[int, int | None] = {}
        self._setter_cache: dict[int, list[tuple[str, int, int]]] = {}
        self._resolve_cache: dict[tuple, bool] = {}
        self._resolving: set[tuple] = set()

    def _build_bracket_matches(self) -> dict[int, int]:
        pairs = {')': '(', ']': '[', '}': '{'}
        matches: dict[int, int] = {}
        stack: list[tuple[str, int]] = []
        for match in re.finditer(r'[()\[\]{}]', self.skeleton):
            char = match.group()
            position = match.start()
            if char in '([{':
                stack.append((char, position))
                continue
            opener = pairs[char]
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == opener:
                    matches[stack[index][1]] = position
                    del stack[index:]
                    break
        return matches

    def line_of(self, position: int) -> int:
        return bisect_right(self.line_starts, position)

    def literal_range_at(self, position: int) -> tuple[int, int] | None:
        index = bisect_right(self.literal_starts, position) - 1
        if index >= 0:
            start, end = self.literal_ranges[index]
            if start <= position < end:
                return start, end
        return None

    def in_literal(self, position: int) -> bool:
        return self.literal_range_at(position) is not None

    def skip_space(self, position: int, end: int | None = None) -> int:
        limit = len(self.skeleton) if end is None else end
        skeleton = self.skeleton
        while position < limit and skeleton[position].isspace():
            position += 1
        return position

    def trim(self, start: int, end: int) -> tuple[int, int]:
        skeleton = self.skeleton
        while start < end and skeleton[start].isspace():
            start += 1
        while end > start and skeleton[end - 1].isspace():
            end -= 1
        return start, end

    def strip_wrapping(self, start: int, end: int) -> tuple[int, int]:
        """Trim whitespace, wrapping parentheses and a trailing non-null assertion."""
        skeleton = self.skeleton
        while True:
            start, end = self.trim(start, end)
            if end - start >= 2 and skeleton[end - 1] == '!' and (
                skeleton[end - 2].isalnum() or skeleton[end - 2] in '_$)]'
            ):
                end -= 1
                continue
            if start < end and skeleton[start] == '(' and self.match.get(start) == end - 1:
                start += 1
                end -= 1
                continue
            return start, end

    def norm(self, start: int, end: int) -> str:
        """Return a whitespace-free form of an expression for guard/target comparison."""
        start, end = self.strip_wrapping(start, end)
        value = _TS_WHITESPACE_RE.sub('', self.code[start:end]).replace('?.', '.')
        return value.rstrip('!')

    def iter_top(self, start: int, end: int):
        """Yield depth-0 positions in [start, end), jumping over bracket groups."""
        skeleton = self.skeleton
        position = start
        while position < end:
            char = skeleton[position]
            if char in '([{':
                close = self.match.get(position)
                if close is None or close >= end:
                    return
                yield position
                position = close + 1
                continue
            yield position
            position += 1

    def expression_end(self, start: int, limit: int | None = None) -> int:
        """Return the end offset of the expression that starts at start."""
        skeleton = self.skeleton
        end = len(skeleton) if limit is None else limit
        position = start
        last = ''
        while position < end:
            char = skeleton[position]
            if char in '([{':
                close = self.match.get(position)
                if close is None:
                    return position
                if close >= end:
                    return end
                position = close + 1
                last = skeleton[close]
                continue
            if char in ')]};,':
                return position
            if char == '\n':
                if last and last in _TS_CONTINUE_AFTER:
                    position += 1
                    continue
                following = self.skip_space(position, end)
                if following < end and skeleton[following] in _TS_CONTINUE_BEFORE:
                    position = following
                    continue
                return position
            if not char.isspace():
                last = char
            position += 1
        return end

    def skip_type(self, position: int) -> int:
        """Skip a type annotation that starts after ':' and return the offset where it ends."""
        skeleton = self.skeleton
        length = len(skeleton)
        angle = 0
        last = ':'
        previous = ''
        while position < length:
            char = skeleton[position]
            if char in '([{':
                close = self.match.get(position)
                if close is None:
                    return position
                position = close + 1
                previous, last = last, skeleton[close]
                continue
            if char == '<':
                angle += 1
            elif char == '>' and skeleton[position - 1] != '=':
                if angle > 0:
                    angle -= 1
            elif angle == 0:
                if char == '=' and skeleton[position + 1:position + 2] not in {'=', '>'}:
                    return position
                if char in ',;)]}':
                    return position
                if char == '\n':
                    arrow = previous == '=' and last == '>'
                    if not arrow and last not in _TS_TYPE_CONTINUE_AFTER:
                        following = self.skip_space(position)
                        if following >= length or skeleton[following] not in _TS_CONTINUE_BEFORE:
                            return position
            if not char.isspace():
                previous, last = last, char
            position += 1
        return position

    def skip_angle(self, position: int, end: int) -> int | None:
        """Skip a balanced <TypeArguments> block and return the offset after it."""
        skeleton = self.skeleton
        depth = 0
        while position < end:
            char = skeleton[position]
            if char in '([{':
                close = self.match.get(position)
                if close is None or close >= end:
                    return None
                position = close + 1
                continue
            if char == '<':
                depth += 1
            elif char == '>' and skeleton[position - 1] != '=':
                depth -= 1
                if depth == 0:
                    return position + 1
            elif char == ';':
                return None
            position += 1
        return None

    def split_commas(self, start: int, end: int) -> list[tuple[int, int]]:
        skeleton = self.skeleton
        spans: list[tuple[int, int]] = []
        segment_start = start
        for position in self.iter_top(start, end):
            if skeleton[position] == ',':
                spans.append(self.trim(segment_start, position))
                segment_start = position + 1
        spans.append(self.trim(segment_start, end))
        return [(span_start, span_end) for span_start, span_end in spans if span_start < span_end]

    def args(self, open_position: int) -> list[tuple[int, int]]:
        close = self.match.get(open_position)
        if close is None:
            return []
        return self.split_commas(open_position + 1, close)

    def split_ternary(self, start: int, end: int) -> tuple[int, int] | None:
        skeleton = self.skeleton
        question = None
        nested = 0
        for position in self.iter_top(start, end):
            char = skeleton[position]
            if char == '?':
                if skeleton[position + 1:position + 2] == '?' or skeleton[position - 1:position] == '?':
                    continue
                if skeleton[position + 1:position + 2] == '.' and not skeleton[position + 2:position + 3].isdigit():
                    continue
                if question is None:
                    question = position
                else:
                    nested += 1
            elif char == ':' and question is not None:
                if nested:
                    nested -= 1
                else:
                    return question, position
        return None

    def split_ops(self, start: int, end: int, operators: tuple[str, ...]) -> list[tuple[int, int]]:
        skeleton = self.skeleton
        parts: list[tuple[int, int]] = []
        segment_start = start
        skip_until = start
        for position in self.iter_top(start, end):
            if position < skip_until:
                continue
            for operator in operators:
                operator_end = position + len(operator)
                if operator_end <= end and skeleton.startswith(operator, position):
                    skip_until = operator_end
                    if skeleton[operator_end:operator_end + 1] == '=':
                        skip_until = operator_end + 1
                        break
                    parts.append((segment_start, position))
                    segment_start = operator_end
                    break
        if not parts:
            return [(start, end)]
        parts.append((segment_start, end))
        return parts

    def split_plus(self, start: int, end: int) -> list[tuple[int, int]]:
        skeleton = self.skeleton
        parts: list[tuple[int, int]] = []
        segment_start = start
        previous = ''
        for position in self.iter_top(start, end):
            char = skeleton[position]
            if char == '+':
                doubled = skeleton[position + 1:position + 2] in {'+', '='} or skeleton[position - 1:position] == '+'
                if not doubled and previous and previous not in _TS_UNARY_PLUS_PREVIOUS:
                    parts.append((segment_start, position))
                    segment_start = position + 1
                previous = char
                continue
            if not char.isspace():
                previous = char
        if not parts:
            return [(start, end)]
        parts.append((segment_start, end))
        return parts

    def find_as(self, start: int, end: int) -> int | None:
        """Return the offset of a depth-0 'as'/'satisfies' type operator."""
        skeleton = self.skeleton
        for position in self.iter_top(start, end):
            if not skeleton[position].isspace():
                continue
            for keyword in ('as', 'satisfies'):
                keyword_end = position + 1 + len(keyword)
                if (
                    skeleton.startswith(keyword, position + 1)
                    and keyword_end < end
                    and skeleton[keyword_end].isspace()
                ):
                    return position
        return None

    def literal_text(self, start: int, end: int) -> str | None:
        """Return the raw content of a string or interpolation-free template literal span."""
        start, end = self.strip_wrapping(start, end)
        text = self.text
        string_end = self.lex.string_spans.get(start)
        if string_end is not None and string_end == end:
            closed = end - start >= 2 and text[end - 1] == text[start]
            return text[start + 1:end - 1] if closed else text[start + 1:end]
        template_end = self.lex.template_spans.get(start)
        if template_end is not None and template_end == end and not self.lex.template_parts.get(start):
            closed = end - start >= 2 and text[end - 1] == '`'
            return text[start + 1:end - 1] if closed else text[start + 1:end]
        return None

    def parse_call(self, start: int, end: int) -> tuple[str, bool, int] | None:
        """Return (callee, is_new, open_paren_offset) when the span is exactly one call expression."""
        start, end = self.strip_wrapping(start, end)
        skeleton = self.skeleton
        if end - start < 3 or skeleton[end - 1] != ')':
            return None
        head = _TS_CALL_HEAD_RE.match(skeleton, start, end)
        if head is None:
            return None
        position = head.end()
        if position < end and skeleton[position] == '<':
            after_type_arguments = self.skip_angle(position, end)
            if after_type_arguments is None:
                return None
            position = self.skip_space(after_type_arguments, end)
        if position >= end or skeleton[position] != '(' or self.match.get(position) != end - 1:
            return None
        callee = _TS_WHITESPACE_RE.sub('', head.group('callee')).replace('?.', '.')
        return callee, bool(head.group('new')), position

    def member_target(self, dot_position: int) -> str | None:
        """Return the receiver text before '.prop', or None when it is a call/index result."""
        skeleton = self.skeleton
        position = dot_position
        while position > 0 and (skeleton[position - 1].isalnum() or skeleton[position - 1] in '_$.!?'):
            position -= 1
        if position > 0 and skeleton[position - 1] in ')]':
            return None
        target = self.code[position:dot_position].replace('?.', '.').rstrip('!?')
        return target or None

    # -- Definitions -------------------------------------------------------------------------

    def _ensure_definitions(self) -> None:
        """Collect const/let/var declarations and names that cannot be resolved (parameters, destructuring).

        Each declaration keeps its offset so block-scoped lookups can tell same-named
        bindings apart. `const [value, setValue] = useState(initial)` is recorded as the
        initial value plus every value later passed to the setter.
        """
        if self._definitions is not None:
            return
        skeleton = self.skeleton
        length = len(skeleton)
        definitions: dict[str, list[tuple[str, int, int]]] = {}

        def add(name: str, site: int, entry: tuple[str, int, int]) -> None:
            definitions.setdefault(name, []).append(entry)
            self._definition_sites.setdefault(name, []).append(site)

        for declaration in _TS_DECLARATION_RE.finditer(skeleton):
            before = skeleton[max(0, declaration.start() - 16):declaration.start()]
            if _TS_AS_PREFIX_RE.search(before):
                continue
            declared_only = bool(_TS_DECLARE_PREFIX_RE.search(before))
            function_scoped = declaration.group().startswith('var')
            position = declaration.end()
            while position < length:
                position = self.skip_space(position)
                if position >= length:
                    break
                if skeleton[position] in '{[':
                    close = self.match.get(position)
                    if close is None:
                        break
                    if declared_only or not (
                        skeleton[position] == '[' and self._record_state_binding(position, close, add)
                    ):
                        self._mark_unresolvable_pattern(position, close)
                    position = self._skip_declarator_tail(close + 1)
                else:
                    name_match = _TS_IDENTIFIER_RE.match(skeleton, position)
                    if name_match is None:
                        break
                    name = name_match.group()
                    site = name_match.start()
                    self._declaration_name_offsets.add(site)
                    if function_scoped:
                        self._function_scoped_names.add(name)
                    position = self.skip_space(name_match.end())
                    if skeleton.startswith('!', position):
                        position = self.skip_space(position + 1)
                    if skeleton.startswith(':', position):
                        position = self.skip_space(self.skip_type(position + 1))
                    if declared_only:
                        add(name, site, ('unknown', position, position))
                    elif skeleton.startswith('=', position) and not skeleton.startswith(('==', '=>'), position):
                        value_start = self.skip_space(position + 1)
                        value_end = self.expression_end(value_start)
                        add(name, site, ('value', value_start, value_end))
                        position = value_end
                    elif _TS_LOOP_BINDING_RE.match(skeleton, position):
                        add(name, site, ('unknown', position, position))
                        break
                    else:
                        add(name, site, ('undefined', position, position))
                position = self.skip_space(position)
                if position < length and skeleton[position] == ',':
                    position += 1
                    continue
                break
        self._collect_parameters()
        self._definitions = definitions

    def _record_state_binding(self, open_position: int, close: int, add) -> bool:
        """Record `const [value, setValue] = useState(initial)`; return False for any other pattern."""
        skeleton = self.skeleton
        if skeleton[self.skip_space(open_position + 1, close)] == ',':
            return False
        elements = self.split_commas(open_position + 1, close)
        if not 1 <= len(elements) <= 2:
            return False
        names: list[tuple[str, int]] = []
        for element_start, element_end in elements:
            text = skeleton[element_start:element_end]
            if not _TS_IDENTIFIER_FULL_RE.match(text):
                return False
            names.append((text, element_start))
        position = self.skip_space(close + 1)
        if skeleton.startswith(':', position):
            position = self.skip_space(self.skip_type(position + 1))
        if not skeleton.startswith('=', position) or skeleton.startswith(('==', '=>'), position):
            return False
        value_start = self.skip_space(position + 1)
        call = self.parse_call(value_start, self.expression_end(value_start))
        if call is None or call[1] or call[0] not in _TS_STATE_HOOKS:
            return False
        state_name, state_site = names[0]
        self._declaration_name_offsets.add(state_site)
        arguments = self.args(call[2])
        if arguments:
            add(state_name, open_position, ('value', *arguments[0]))
        else:
            add(state_name, open_position, ('undefined', call[2], call[2]))
        if len(names) == 2:
            self._declaration_name_offsets.add(names[1][1])
            add(state_name, open_position, ('setter', names[1][1], open_position))
        return True

    def _mark_unresolvable(self, name: str, site: int) -> None:
        self._unresolvable.add(name)
        self._unresolvable_sites.setdefault(name, []).append(site)

    def _mark_unresolvable_pattern(self, start: int, close: int) -> None:
        for identifier in _TS_IDENTIFIER_RE.finditer(self.skeleton, start, close):
            self._mark_unresolvable(identifier.group(), identifier.start())

    def _skip_declarator_tail(self, position: int) -> int:
        skeleton = self.skeleton
        position = self.skip_space(position)
        if skeleton.startswith(':', position):
            position = self.skip_space(self.skip_type(position + 1))
        if skeleton.startswith('=', position) and not skeleton.startswith(('==', '=>'), position):
            return self.expression_end(self.skip_space(position + 1))
        return position

    def _has_return_type_then_body(self, colon_position: int) -> bool:
        """Return True when ': Type' after ')' is a return type followed by a body or '=>'."""
        skeleton = self.skeleton
        length = len(skeleton)
        position = colon_position + 1
        angle = 0
        previous = ':'
        while position < length:
            char = skeleton[position]
            if char.isspace():
                position += 1
                continue
            if char == '{' and angle == 0 and previous not in ':|&,(<':
                return True
            if char in '([{':
                close = self.match.get(position)
                if close is None:
                    return False
                position = close + 1
                previous = skeleton[close]
                continue
            if char == '<':
                angle += 1
            elif char == '>':
                if previous == '=':
                    if angle == 0:
                        return True
                elif angle > 0:
                    angle -= 1
            elif angle == 0:
                if char in ',;)]}?:':
                    return False
                if char == '=' and skeleton[position + 1:position + 2] != '>':
                    return False
            previous = char
            position += 1
        return False

    def _collect_parameters(self) -> None:
        skeleton = self.skeleton
        for open_position, close_position in self.match.items():
            if skeleton[open_position] != '(':
                continue
            follower_position = self.skip_space(close_position + 1)
            follower = skeleton[follower_position:follower_position + 2]
            if follower.startswith('{'):
                word = _TS_TRAILING_WORD_RE.search(skeleton, max(0, open_position - 32), open_position)
                if word is not None and word.group(1) in _TS_PARAMETER_EXCLUDED_KEYWORDS:
                    continue
            elif follower.startswith(':'):
                if not self._has_return_type_then_body(follower_position):
                    continue
            elif follower != '=>':
                continue
            for start, end in self.split_commas(open_position + 1, close_position):
                self._mark_parameter(start, end)
        for match in _TS_ARROW_SINGLE_PARAMETER_RE.finditer(skeleton):
            self._mark_unresolvable(match.group(1), match.start(1))

    def _mark_parameter(self, start: int, end: int) -> None:
        skeleton = self.skeleton
        position = start
        if skeleton.startswith('...', position):
            position = self.skip_space(position + 3, end)
        modifiers = _TS_PARAMETER_MODIFIERS_RE.match(skeleton, position, end)
        if modifiers is not None:
            position = modifiers.end()
        if position >= end:
            return
        if skeleton[position] in '{[':
            close = self.match.get(position)
            if close is not None:
                self._mark_unresolvable_pattern(position, close)
            return
        name_match = _TS_IDENTIFIER_RE.match(skeleton, position, end)
        if name_match is not None and name_match.group() != 'this':
            self._mark_unresolvable(name_match.group(), name_match.start())

    def _assignments(self, name: str) -> list[tuple[str, int, int]]:
        cached = self._assignment_cache.get(name)
        if cached is not None:
            return cached
        pattern = re.compile(r'(?<![\w$.:-])' + re.escape(name) + r'\s*(\|\|=|\?\?=|&&=|\+=|=)(?![=>])')
        entries: list[tuple[str, int, int]] = []
        for match in pattern.finditer(self.skeleton):
            if match.start() in self._declaration_name_offsets or match.start() in self.attribute_name_starts:
                continue
            value_start = self.skip_space(match.end())
            value_end = self.expression_end(value_start)
            entries.append(('append' if match.group(1) == '+=' else 'value', value_start, value_end))
        self._assignment_cache[name] = entries
        return entries

    def name_definitions(self, name: str, position: int | None = None) -> list[tuple[str, int, int]] | None:
        """Return the declarations/assignments that can reach a name at position, or None when unresolvable."""
        return self._name_binding(name, position)[1]

    def _name_binding(self, name: str, position: int | None) -> tuple[object, list[tuple[str, int, int]] | None]:
        """Return (scope key, entries) for a name, with useState setters expanded into their values."""
        self._ensure_definitions()
        scoped = self._scoped_binding(name, position)
        if scoped is not None:
            scope, entries = scoped
            if entries is None:
                return scope, None
        else:
            if name in self._unresolvable:
                return 'file', None
            scope, entries = 'file', self._definitions.get(name, []) + self._assignments(name)
        expanded: list[tuple[str, int, int]] = []
        for entry in entries:
            if entry[0] == 'setter':
                expanded.extend(self._setter_entries(entry[1], entry[2]))
            else:
                expanded.append(entry)
        return scope, (expanded or None)

    def _scoped_binding(self, name: str, position: int | None) -> tuple[object, list[tuple[str, int, int]] | None] | None:
        """Pick the const/let binding of name whose block encloses position.

        Returns None to fall back to file-wide resolution (var, for-header or ambiguous
        parameter bindings), ('unbound', None) when no declared binding is in scope, or
        (block offset, entries) with the block's declarations plus assignments inside it.
        """
        if position is None or name in self._function_scoped_names:
            return None
        sites = self._definition_sites.get(name)
        if not sites:
            return None
        chosen: int | None = None
        found = False
        for site in sites:
            block = self._block_of(site)
            if block == -1:
                return None
            if block is None:
                contains = True
            else:
                close = self.match.get(block)
                contains = close is not None and block < position < close
            if contains and (not found or (block is not None and (chosen is None or block > chosen))):
                chosen = block
                found = True
        if not found:
            return 'unbound', None
        block_start = -1 if chosen is None else chosen
        block_end = len(self.skeleton) if chosen is None else self.match[chosen]
        if any(block_start < site < block_end for site in self._unresolvable_sites.get(name, ())):
            return None
        entries = [
            entry for entry, site in zip(self._definitions.get(name, []), sites) if self._block_of(site) == chosen
        ]
        entries.extend(entry for entry in self._assignments(name) if block_start < entry[1] < block_end)
        return ('block', block_start), entries

    def innermost_opener(self, position: int) -> int | None:
        """Return the offset of the innermost bracket that encloses position, or None at the top level."""
        skeleton = self.skeleton
        index = position - 1
        while index >= 0:
            char = skeleton[index]
            if char in ')]}':
                opener = self.reverse_match.get(index)
                if opener is None:
                    return None
                index = opener - 1
                continue
            if char in '([{':
                return index
            index -= 1
        return None

    def _block_of(self, site: int) -> int | None:
        """Return the '{' that scopes a declaration site, None at module level, or -1 when not a plain block."""
        if site in self._block_cache:
            return self._block_cache[site]
        opener = self.innermost_opener(site)
        if opener is not None and self.skeleton[opener] != '{':
            block: int | None = -1
        else:
            block = opener
        self._block_cache[site] = block
        return block

    def _setter_entries(self, site: int, declaration_site: int) -> list[tuple[str, int, int]]:
        """Return the values passed to a useState setter whose name starts at site.

        Direct calls contribute their argument; references inside hook dependency arrays are
        ignored; any other use (passing the setter along, updater functions) is unknown.
        """
        cached = self._setter_cache.get(site)
        if cached is not None:
            return cached
        skeleton = self.skeleton
        name_match = _TS_IDENTIFIER_RE.match(skeleton, site)
        entries: list[tuple[str, int, int]] = []
        if name_match is None:
            entries.append(('unknown', site, site))
        else:
            block = self._block_of(declaration_site)
            if block is None or block == -1:
                scan_start, scan_end = 0, len(skeleton)
            else:
                scan_start, scan_end = block, self.match.get(block, len(skeleton))
            pattern = re.compile(r'(?<![\w$.])' + re.escape(name_match.group()) + r'(?![\w$])')
            for reference in pattern.finditer(skeleton, scan_start, scan_end):
                if reference.start() == site:
                    continue
                after = self.skip_space(reference.end())
                if skeleton.startswith('(', after) and self.match.get(after) is not None:
                    arguments = self.args(after)
                    if not arguments:
                        entries.append(('undefined', after, after))
                    elif self._is_function_expression(*arguments[0]):
                        entries.append(('unknown', after, after))
                    else:
                        entries.append(('value', *arguments[0]))
                    continue
                if self._in_dependency_array(reference.start()):
                    continue
                entries.append(('unknown', reference.start(), reference.end()))
        self._setter_cache[site] = entries
        return entries

    def _is_function_expression(self, start: int, end: int) -> bool:
        if self.function_returns(start, end) is not None:
            return True
        start, end = self.strip_wrapping(start, end)
        return bool(_TS_FUNCTION_EXPRESSION_RE.match(self.skeleton, start, end))

    def _in_dependency_array(self, position: int) -> bool:
        """Return True when position sits in the trailing dependency array of a React hook call."""
        skeleton = self.skeleton
        opener = self.innermost_opener(position)
        if opener is None or skeleton[opener] != '[':
            return False
        close = self.match.get(opener)
        if close is None:
            return False
        after = self.skip_space(close + 1)
        if skeleton.startswith(',', after):
            after = self.skip_space(after + 1)
        if not skeleton.startswith(')', after):
            return False
        paren_open = self.reverse_match.get(after)
        if paren_open is None:
            return False
        word = _TS_TRAILING_WORD_RE.search(skeleton, max(0, paren_open - 48), paren_open)
        return word is not None and word.group(1) in _TS_DEPENDENCY_HOOKS

    def _resolve(self, key: tuple, name: str, depth: int, evaluate, position: int | None = None) -> bool:
        scope, entries = self._name_binding(name, position)
        key = key + (scope,)
        if key in self._resolve_cache:
            return self._resolve_cache[key]
        if key in self._resolving or depth > _TS_MAX_RESOLVE_DEPTH:
            return False
        result = False
        if entries is not None and not any(kind == 'unknown' for kind, _, _ in entries):
            self._resolving.add(key)
            try:
                result = evaluate(entries)
            finally:
                self._resolving.discard(key)
        self._resolve_cache[key] = result
        return result

    def resolve_url(self, name: str, level: str, prefix: bool, depth: int, position: int | None = None) -> bool:
        def evaluate(entries: list[tuple[str, int, int]]) -> bool:
            values = [(start, end) for kind, start, end in entries if kind == 'value']
            appends = any(kind == 'append' for kind, _, _ in entries)
            if not values:
                return not appends and not prefix
            return all(self.url_approved(start, end, level, prefix or appends, depth + 1) for start, end in values)

        return self._resolve(('url', name, level, prefix), name, depth, evaluate, position)

    def resolve_html(self, name: str, depth: int, position: int | None = None) -> bool:
        def evaluate(entries: list[tuple[str, int, int]]) -> bool:
            return all(
                self.html_safe(start, end, depth + 1)
                for kind, start, end in entries
                if kind in {'value', 'append'}
            )

        return self._resolve(('html', name), name, depth, evaluate, position)

    def resolve_html_object(self, name: str, depth: int, position: int | None = None) -> bool:
        def evaluate(entries: list[tuple[str, int, int]]) -> bool:
            if any(kind == 'append' for kind, _, _ in entries):
                return False
            return all(
                self.html_object_safe(start, end, depth + 1)
                for kind, start, end in entries
                if kind == 'value'
            )

        return self._resolve(('html-object', name), name, depth, evaluate, position)

    def function_returns(self, start: int, end: int) -> list[tuple[int, int]] | None:
        """Return the returned-expression spans of an arrow function span, or None when it is not one."""
        start, end = self.strip_wrapping(start, end)
        skeleton = self.skeleton
        arrow = None
        for position in self.iter_top(start, end):
            if skeleton.startswith('=>', position):
                arrow = position
                break
        if arrow is None:
            return None
        body_start, body_end = self.trim(arrow + 2, end)
        if body_start >= body_end:
            return None
        if skeleton[body_start] == '{' and self.match.get(body_start) == body_end - 1:
            spans = []
            for match in _TS_RETURN_RE.finditer(skeleton, body_start, body_end):
                value_start = match.end()
                value_end = self.expression_end(value_start, body_end - 1)
                spans.append(self.trim(value_start, value_end))
            return spans
        return [(body_start, body_end)]

    def _memo_returns(self, call: tuple[str, bool, int]) -> list[tuple[int, int]] | None:
        callee, is_new, open_position = call
        if is_new or callee not in {'useMemo', 'React.useMemo'}:
            return None
        arguments = self.args(open_position)
        if not arguments:
            return None
        return self.function_returns(*arguments[0])

    # -- URL classification ---------------------------------------------------------------

    def url_approved(self, start: int, end: int, level: str, prefix: bool = False, depth: int = 0) -> bool:
        """Return True when a URL expression is literal, same-origin or produced by an approved helper.

        level is 'href' for anchors, forms and navigation, or 'strict' for script/frame sources.
        prefix means more URL text follows the value, so only a safe head can approve it.
        """
        if depth > _TS_MAX_EXPRESSION_DEPTH:
            return False
        start, end = self.strip_wrapping(start, end)
        if start >= end:
            return False
        ternary = self.split_ternary(start, end)
        if ternary is not None:
            return self._ternary_url_approved(start, ternary[0], ternary[1], end, level, prefix, depth)
        parts = self.split_ops(start, end, ('||', '??'))
        if len(parts) > 1:
            return all(self.url_approved(part_start, part_end, level, prefix, depth + 1) for part_start, part_end in parts)
        parts = self.split_ops(start, end, ('&&',))
        if len(parts) > 1:
            last_start, last_end = parts[-1]
            target = self.norm(last_start, last_end)
            for part_start, part_end in parts[:-1]:
                guard = self.guard_target(part_start, part_end, level)
                if guard is not None and not guard[1] and guard[0] == target:
                    return True
            return self.url_approved(last_start, last_end, level, prefix, depth + 1)
        as_position = self.find_as(start, end)
        if as_position is not None:
            return self.url_approved(start, as_position, level, prefix, depth + 1)
        operands = self.split_plus(start, end)
        if len(operands) > 1:
            return self._concatenation_url_approved(operands, level, depth)
        return self._primary_url_approved(start, end, level, prefix, depth)

    def _ternary_url_approved(
        self, start: int, question: int, colon: int, end: int, level: str, prefix: bool, depth: int
    ) -> bool:
        true_target = self.norm(question + 1, colon)
        false_target = self.norm(colon + 1, end)
        true_approved = False
        for part_start, part_end in self.split_ops(start, question, ('&&',)):
            guard = self.guard_target(part_start, part_end, level)
            if guard is not None and not guard[1] and guard[0] == true_target:
                true_approved = True
                break
        if not true_approved:
            true_approved = self.url_approved(question + 1, colon, level, prefix, depth + 1)
        if not true_approved:
            return False
        guard = self.guard_target(start, question, level)
        if guard is not None and guard[1] and guard[0] == false_target:
            return True
        return self.url_approved(colon + 1, end, level, prefix, depth + 1)

    def _concatenation_url_approved(self, operands: list[tuple[int, int]], level: str, depth: int) -> bool:
        first_start, first_end = operands[0]
        if level == 'strict' and self.literal_text(first_start, first_end) == '/':
            second_start, second_end = operands[1]
            second_literal = self.literal_text(second_start, second_end)
            if second_literal is not None:
                return bool(second_literal) and not second_literal.startswith(('/', '\\'))
            return self._is_encode_component_call(second_start, second_end)
        return self.url_approved(first_start, first_end, level, True, depth + 1)

    def _is_encode_component_call(self, start: int, end: int) -> bool:
        call = self.parse_call(start, end)
        return call is not None and not call[1] and call[0] == 'encodeURIComponent'

    def _template_url_approved(self, start: int, end: int, level: str, prefix: bool, depth: int) -> bool:
        parts = self.lex.template_parts.get(start) or []
        text = self.text
        if not parts:
            literal = self.literal_text(start, end)
            return not prefix or self.head_is_safe(literal or '', level)
        head = text[start + 1:parts[0][0] - 2]
        first_start, first_end = parts[0]
        if head:
            if level == 'strict' and head == '/':
                return self._is_encode_component_call(first_start, first_end)
            return self.head_is_safe(head, level)
        closed = end - start >= 2 and text[end - 1] == '`'
        tail = text[parts[-1][1] + 1:end - 1 if closed else end]
        if len(parts) == 1 and not tail:
            return self.url_approved(first_start, first_end, level, prefix, depth + 1)
        return self.url_approved(first_start, first_end, level, True, depth + 1)

    def _primary_url_approved(self, start: int, end: int, level: str, prefix: bool, depth: int) -> bool:
        await_match = _TS_AWAIT_PREFIX_RE.match(self.skeleton, start, end)
        if await_match is not None:
            return self.url_approved(await_match.end(), end, level, prefix, depth + 1)
        text = self.norm(start, end)
        if text in _TS_LITERAL_KEYWORD_VALUES:
            return not prefix
        if _TS_NUMBER_LITERAL_RE.match(text):
            return True
        literal = self.literal_text(start, end)
        if literal is not None:
            return not prefix or self.head_is_safe(literal, level)
        if self.lex.template_spans.get(start) == end:
            return self._template_url_approved(start, end, level, prefix, depth)
        if start in self.regex_spans:
            return False
        call = self.parse_call(start, end)
        if call is not None:
            return self._call_url_approved(call, level, prefix, depth)
        if _TS_UPPER_CONSTANT_RE.match(text) or _TS_LOCATION_VALUE_RE.match(text) or _TS_IMPORT_META_ENV_RE.match(text):
            return True
        if _TS_IDENTIFIER_FULL_RE.match(text):
            return self.resolve_url(text, level, prefix, depth, start)
        return False

    def _call_url_approved(self, call: tuple[str, bool, int], level: str, prefix: bool, depth: int) -> bool:
        callee, is_new, open_position = call
        if is_new:
            return False
        last = callee.rsplit('.', 1)[-1]
        arguments = self.args(open_position)
        if callee == 'encodeURIComponent':
            return not prefix
        if last == 'createObjectURL':
            return level == 'href'
        if last == 'toDataURL':
            return True
        if callee == 'String':
            return bool(arguments) and self.url_approved(*arguments[0], level, prefix, depth + 1)
        if last == 'apiUrl':
            if level == 'href':
                return True
            return bool(arguments) and self.url_approved(*arguments[0], level, prefix, depth + 1)
        if last in TS_SAME_ORIGIN_URL_BUILDERS:
            return True
        if last in TS_HREF_URL_BUILDERS:
            return level == 'href'
        if _TS_SAFE_URL_HELPER_NAME_RE.match(callee):
            return True
        returns = self._memo_returns(call)
        if returns is None:
            return False
        if not returns:
            return not prefix
        return all(
            (not prefix) if span_start >= span_end else self.url_approved(span_start, span_end, level, prefix, depth + 1)
            for span_start, span_end in returns
        )

    @staticmethod
    def head_is_safe(head: str, level: str) -> bool:
        """Return True when a literal URL head fixes a same-origin path or a non-script scheme."""
        if not head:
            return False
        if level == 'strict':
            if head == '/' or head.startswith(('//', '/\\')):
                return False
            if head.startswith(('/', '#', '?', './', '../')):
                return True
            return bool(
                _TS_RELATIVE_SEGMENT_HEAD_RE.match(head)
                or _TS_PINNED_HTTP_HEAD_RE.match(head)
                or _TS_DATA_IMAGE_HEAD_RE.match(head)
            )
        if head.startswith(('/', '#', '?', './', '../')):
            return True
        return bool(_TS_RELATIVE_SEGMENT_HEAD_RE.match(head) or _TS_HREF_SCHEME_HEAD_RE.match(head))

    # -- URL guards ---------------------------------------------------------------------------

    def guard_target(self, start: int, end: int, level: str, depth: int = 0) -> tuple[str, bool] | None:
        """Return (guarded expression, negated) when the span is a recognised URL-scheme guard."""
        if depth > 8:
            return None
        start, end = self.strip_wrapping(start, end)
        if start >= end:
            return None
        parts = self.split_ops(start, end, ('||',))
        if len(parts) > 1:
            targets = set()
            for part_start, part_end in parts:
                guard = self.guard_target(part_start, part_end, level, depth + 1)
                if guard is None or guard[1]:
                    return None
                targets.add(guard[0])
            return (targets.pop(), False) if len(targets) == 1 else None
        skeleton = self.skeleton
        if skeleton[start] == '!' and skeleton[start + 1:start + 2] != '=':
            guard = self.guard_target(start + 1, end, level, depth + 1)
            return None if guard is None else (guard[0], not guard[1])
        target = self._single_guard_target(start, end, level)
        return None if target is None else (target, False)

    def _single_guard_target(self, start: int, end: int, level: str) -> str | None:
        if level == 'href' and start in self.regex_spans:
            regex_end = self.regex_spans[start]
            test_call = _TS_REGEX_TEST_CALL_RE.match(self.skeleton, regex_end, end)
            if test_call is None or not self._is_scheme_guard_regex(start, regex_end):
                return None
            open_position = test_call.end() - 1
            if self.match.get(open_position) != end - 1:
                return None
            arguments = self.args(open_position)
            return self.norm(*arguments[0]) if len(arguments) == 1 else None
        call = self.parse_call(start, end)
        if call is None or call[1]:
            return None
        callee, _, open_position = call
        arguments = self.args(open_position)
        last = callee.rsplit('.', 1)[-1]
        if last in TS_URL_GUARD_FUNCTIONS:
            return self.norm(*arguments[0]) if arguments else None
        if level != 'href' or len(arguments) != 1 or '.' not in callee:
            return None
        receiver = callee.rsplit('.', 1)[0]
        if last == 'test' and _TS_IDENTIFIER_FULL_RE.match(receiver):
            return self.norm(*arguments[0]) if self._is_scheme_guard_name(receiver, start) else None
        if last == 'startsWith' and self.literal_text(*arguments[0]) in _TS_STARTS_WITH_GUARD_PREFIXES:
            return receiver
        return None

    def _is_scheme_guard_regex(self, start: int, end: int) -> bool:
        closing_slash = self.text.rfind('/', start + 1, end)
        body = self.text[start + 1:closing_slash]
        match = _TS_SCHEME_GUARD_REGEX_BODY_RE.match(body)
        if match is None:
            return False
        return all(alternative.lower() in _TS_SCHEME_GUARD_ALTERNATIVES for alternative in match.group('alts').split('|'))

    def _is_scheme_guard_name(self, name: str, position: int | None = None) -> bool:
        entries = self.name_definitions(name, position)
        if not entries:
            return False
        for kind, start, end in entries:
            if kind != 'value':
                return False
            start, end = self.strip_wrapping(start, end)
            if self.regex_spans.get(start) != end or not self._is_scheme_guard_regex(start, end):
                return False
        return True

    # -- HTML classification ------------------------------------------------------------------

    def html_safe(self, start: int, end: int, depth: int = 0) -> bool:
        """Return True when an HTML string expression is literal or passed through a sanitizer/escaper."""
        if depth > _TS_MAX_EXPRESSION_DEPTH:
            return False
        start, end = self.strip_wrapping(start, end)
        if start >= end:
            return False
        ternary = self.split_ternary(start, end)
        if ternary is not None:
            question, colon = ternary
            return self.html_safe(question + 1, colon, depth + 1) and self.html_safe(colon + 1, end, depth + 1)
        parts = self.split_ops(start, end, ('||', '??'))
        if len(parts) > 1:
            return all(self.html_safe(part_start, part_end, depth + 1) for part_start, part_end in parts)
        conjuncts = self.split_ops(start, end, ('&&',))
        if len(conjuncts) > 1:
            return self.html_safe(*conjuncts[-1], depth + 1)
        as_position = self.find_as(start, end)
        if as_position is not None:
            return self.html_safe(start, as_position, depth + 1)
        operands = self.split_plus(start, end)
        if len(operands) > 1:
            return all(self.html_safe(part_start, part_end, depth + 1) for part_start, part_end in operands)
        await_match = _TS_AWAIT_PREFIX_RE.match(self.skeleton, start, end)
        if await_match is not None:
            return self.html_safe(await_match.end(), end, depth + 1)
        text = self.norm(start, end)
        if text in _TS_LITERAL_KEYWORD_VALUES or _TS_NUMBER_LITERAL_RE.match(text):
            return True
        if self.literal_text(start, end) is not None:
            return True
        if self.lex.template_spans.get(start) == end:
            return all(
                self.html_safe(part_start, part_end, depth + 1)
                for part_start, part_end in self.lex.template_parts.get(start, [])
            )
        call = self.parse_call(start, end)
        if call is not None:
            if not call[1] and _TS_SAFE_HTML_CALL_RE.match(call[0]):
                return True
            returns = self._memo_returns(call)
            return bool(returns) and all(
                span_start < span_end and self.html_safe(span_start, span_end, depth + 1)
                for span_start, span_end in returns
            )
        if _TS_IDENTIFIER_FULL_RE.match(text):
            return self.resolve_html(text, depth, start)
        return False

    def html_object_safe(self, start: int, end: int, depth: int = 0) -> bool:
        """Return True when a dangerouslySetInnerHTML value is an object whose __html is html_safe."""
        if depth > _TS_MAX_EXPRESSION_DEPTH:
            return False
        start, end = self.strip_wrapping(start, end)
        if start >= end:
            return False
        ternary = self.split_ternary(start, end)
        if ternary is not None:
            question, colon = ternary
            return self.html_object_safe(question + 1, colon, depth + 1) and self.html_object_safe(
                colon + 1, end, depth + 1
            )
        parts = self.split_ops(start, end, ('||', '??'))
        if len(parts) > 1:
            return all(self.html_object_safe(part_start, part_end, depth + 1) for part_start, part_end in parts)
        as_position = self.find_as(start, end)
        if as_position is not None:
            return self.html_object_safe(start, as_position, depth + 1)
        if self.skeleton[start] == '{' and self.match.get(start) == end - 1:
            return self._html_object_literal_safe(start, end, depth)
        text = self.norm(start, end)
        if text in {'undefined', 'null'}:
            return True
        call = self.parse_call(start, end)
        if call is not None:
            returns = self._memo_returns(call)
            return bool(returns) and all(
                span_start < span_end and self.html_object_safe(span_start, span_end, depth + 1)
                for span_start, span_end in returns
            )
        if _TS_IDENTIFIER_FULL_RE.match(text):
            return self.resolve_html_object(text, depth, start)
        return False

    def _html_object_literal_safe(self, start: int, end: int, depth: int) -> bool:
        found = False
        for entry_start, entry_end in self.split_commas(start + 1, end - 1):
            if self.skeleton.startswith('...', entry_start):
                return False
            key = _TS_HTML_KEY_RE.match(self.code, entry_start, entry_end)
            if key is None:
                continue
            found = True
            if key.group('optional'):
                continue
            if not key.group('colon'):
                if not self.resolve_html('__html', depth + 1, entry_start):
                    return False
                continue
            value_start = self.skip_space(key.end(), entry_end)
            value_end = self.expression_end(value_start, entry_end)
            if _TS_TYPE_ONLY_VALUE_RE.match(self.norm(value_start, value_end)):
                continue
            if not self.html_safe(value_start, value_end, depth + 1):
                return False
        return found

    def route_target_approved(self, start: int, end: int) -> bool:
        """Return True when a router 'to' value (string or location object) has an approved pathname."""
        start, end = self.strip_wrapping(start, end)
        if start < end and self.skeleton[start] == '{' and self.match.get(start) == end - 1:
            for entry_start, entry_end in self.split_commas(start + 1, end - 1):
                if self.skeleton.startswith('...', entry_start):
                    return False
                key = _TS_PATHNAME_KEY_RE.match(self.code, entry_start, entry_end)
                if key is None:
                    continue
                if not key.group('colon'):
                    return self.resolve_url('pathname', 'href', False, 0, entry_start)
                value_start = self.skip_space(key.end(), entry_end)
                return self.url_approved(value_start, self.expression_end(value_start, entry_end), 'href')
            return True
        return self.url_approved(start, end, 'href')

    # -- Statement guards ---------------------------------------------------------------------

    def statement_guarded(self, sink_start: int, value_start: int, value_end: int, level: str) -> bool:
        """Return True when an if/else branch or an earlier early exit guards the sink value.

        Recognised forms: `if (guard(x)) sink(x)`, `if (guard(x) && ...) { sink(x) }`,
        `if (!guard(x)) {...} else { sink(x) }` and `if (!guard(x) || ...) return;` earlier
        in an enclosing block. The value must be a plain name or member path that is not
        rebound or reassigned after the guard.
        """
        target = self.norm(value_start, value_end)
        if not _TS_GUARDABLE_TARGET_RE.match(target):
            return False
        guard_start = self._brace_less_if_guard(sink_start, target, level)
        if guard_start is None:
            guard_start = self._block_guard(sink_start, target, level)
        if guard_start is None:
            return False
        return not self._rebound_after_guard(target, guard_start, sink_start)

    def _rebound_after_guard(self, target: str, guard_start: int, sink_start: int) -> bool:
        self._ensure_definitions()
        root = target.split('.', 1)[0]
        for site in self._definition_sites.get(root, []) + self._unresolvable_sites.get(root, []):
            if guard_start < site < sink_start:
                return True
        names = {root, target}
        return any(entry[1] > guard_start for name in names for entry in self._assignments(name))

    def _skip_space_back(self, position: int) -> int:
        """Return the offset of the last non-space character before position, or -1."""
        skeleton = self.skeleton
        index = position - 1
        while index >= 0 and skeleton[index].isspace():
            index -= 1
        return index

    def _word_before(self, position: int) -> tuple[str, int] | None:
        """Return (word, start) for the identifier that ends right before position (skipping spaces)."""
        index = self._skip_space_back(position)
        if index < 0 or not (self.skeleton[index].isalnum() or self.skeleton[index] in '_$'):
            return None
        word = _TS_TRAILING_WORD_RE.search(self.skeleton, max(0, index - 48), index + 1)
        if word is None:
            return None
        return word.group(1), word.start(1)

    def _if_condition_before(self, position: int) -> tuple[int, int, int] | None:
        """Return (if keyword start, condition start, condition end) for `if (cond)` ending before position."""
        close = self._skip_space_back(position)
        if close < 0 or self.skeleton[close] != ')':
            return None
        open_position = self.reverse_match.get(close)
        if open_position is None:
            return None
        word = self._word_before(open_position)
        if word is None or word[0] != 'if':
            return None
        if word[1] > 0 and (self.skeleton[word[1] - 1] == '.' or self.skeleton[word[1] - 1].isalnum()):
            return None
        return word[1], open_position + 1, close

    def _prior_if_conditions(self, else_start: int) -> list[tuple[int, int]]:
        """Return the conditions of the braced if/else-if chain that precedes an else keyword."""
        conditions: list[tuple[int, int]] = []
        position = else_start
        for _ in range(64):
            block_close = self._skip_space_back(position)
            if block_close < 0 or self.skeleton[block_close] != '}':
                return []
            block_open = self.reverse_match.get(block_close)
            if block_open is None:
                return []
            condition = self._if_condition_before(block_open)
            if condition is None:
                return []
            conditions.append((condition[1], condition[2]))
            previous = self._word_before(condition[0])
            if previous is None or previous[0] != 'else':
                return conditions
            position = previous[1]
        return []

    def _condition_affirms(self, start: int, end: int, target: str, level: str) -> bool:
        """Return True when a true condition implies a positive guard on target."""
        start, end = self.strip_wrapping(start, end)
        if start >= end or self.split_ternary(start, end) is not None:
            return False
        if len(self.split_ops(start, end, ('||', '??'))) > 1:
            guard = self.guard_target(start, end, level)
            return guard is not None and not guard[1] and guard[0] == target
        for part_start, part_end in self.split_ops(start, end, ('&&',)):
            guard = self.guard_target(part_start, part_end, level)
            if guard is not None and not guard[1] and guard[0] == target:
                return True
        return False

    def _condition_negates(self, start: int, end: int, target: str, level: str) -> bool:
        """Return True when a false condition implies a positive guard on target."""
        start, end = self.strip_wrapping(start, end)
        if start >= end or self.split_ternary(start, end) is not None:
            return False
        if len(self.split_ops(start, end, ('??',))) > 1:
            return False
        for part_start, part_end in self.split_ops(start, end, ('||',)):
            guard = self.guard_target(part_start, part_end, level)
            if guard is not None and guard[1] and guard[0] == target:
                return True
        return False

    def _brace_less_if_guard(self, sink_start: int, target: str, level: str) -> int | None:
        skeleton = self.skeleton
        position = sink_start
        while position > 0 and (skeleton[position - 1].isalnum() or skeleton[position - 1] in '_$.?!'):
            position -= 1
        condition = self._if_condition_before(position)
        if condition is not None and self._condition_affirms(condition[1], condition[2], target, level):
            return condition[1]
        return None

    def _block_guard(self, sink_start: int, target: str, level: str) -> int | None:
        opener = self.innermost_opener(sink_start)
        while opener is not None:
            if self.skeleton[opener] == '{':
                guard_start = self._if_block_guard(opener, target, level)
                if guard_start is None:
                    guard_start = self._early_exit_guard(opener, sink_start, target, level)
                if guard_start is not None:
                    return guard_start
            opener = self.innermost_opener(opener)
        return None

    def _if_block_guard(self, open_brace: int, target: str, level: str) -> int | None:
        condition = self._if_condition_before(open_brace)
        if condition is not None:
            if self._condition_affirms(condition[1], condition[2], target, level):
                return condition[1]
            previous = self._word_before(condition[0])
            if previous is None or previous[0] != 'else':
                return None
            else_start = previous[1]
        else:
            word = self._word_before(open_brace)
            if word is None or word[0] != 'else':
                return None
            else_start = word[1]
        for condition_start, condition_end in self._prior_if_conditions(else_start):
            if self._condition_negates(condition_start, condition_end, target, level):
                return condition_start
        return None

    def _early_exit_guard(self, open_brace: int, sink_start: int, target: str, level: str) -> int | None:
        skeleton = self.skeleton
        before = self._skip_space_back(open_brace)
        if before >= 0 and skeleton[before] == ')':
            paren_open = self.reverse_match.get(before)
            word = None if paren_open is None else self._word_before(paren_open)
            if word is not None and word[0] == 'switch':
                return None
        for match in _TS_IF_STATEMENT_RE.finditer(skeleton, open_brace + 1, sink_start):
            if self.innermost_opener(match.start()) != open_brace:
                continue
            previous = self._skip_space_back(match.start())
            if previous >= 0 and skeleton[previous] not in '{;}':
                continue
            open_position = match.end() - 1
            close = self.match.get(open_position)
            if close is None or close >= sink_start:
                continue
            if not self._exits_at(self.skip_space(close + 1)):
                continue
            if self._condition_negates(open_position + 1, close, target, level):
                return open_position + 1
        return None

    def _exits_at(self, position: int) -> bool:
        """Return True when the statement at position always leaves the enclosing block."""
        skeleton = self.skeleton
        if position >= len(skeleton):
            return False
        if skeleton[position] != '{':
            return bool(_TS_EXIT_STATEMENT_RE.match(skeleton, position))
        close = self.match.get(position)
        if close is None:
            return False
        for match in _TS_EXIT_STATEMENT_RE.finditer(skeleton, position + 1, close):
            if self.innermost_opener(match.start()) != position:
                continue
            previous = self._skip_space_back(match.start())
            if previous >= 0 and skeleton[previous] in '{;}':
                return True
        return False

    # -- DOMParser output tracking ------------------------------------------------------------

    def enclosing_function_body(self, position: int) -> tuple[int, int]:
        """Return the innermost function body that contains position, or the whole file."""
        skeleton = self.skeleton
        candidates = sorted(
            (
                (open_position, close)
                for open_position, close in self.match.items()
                if skeleton[open_position] == '{' and open_position < position < close
            ),
            reverse=True,
        )
        for open_position, close in candidates:
            before = open_position - 1
            while before >= 0 and skeleton[before].isspace():
                before -= 1
            if before >= 1 and skeleton[before - 1:before + 1] == '=>':
                return open_position + 1, close
            if before >= 0 and skeleton[before] == ')':
                paren_open = self.reverse_match.get(before)
                if paren_open is None:
                    continue
                word = _TS_TRAILING_WORD_RE.search(skeleton, max(0, paren_open - 32), paren_open)
                if word is None or word.group(1) not in _TS_PARAMETER_EXCLUDED_KEYWORDS | {'catch'}:
                    return open_position + 1, close
        return 0, len(skeleton)

    def parsed_output_insertion(self, call_start: int, call_end: int) -> int | None:
        """Return the end of a DOM insertion that receives DOMParser output, or None."""
        body_start, body_end = self.enclosing_function_body(call_start)
        skeleton = self.skeleton
        tainted: set[str] = set()
        for _ in range(3):
            added = False
            for match in _TS_ASSIGNMENT_TARGET_RE.finditer(skeleton, body_start, body_end):
                name = match.group('name')
                if name in tainted:
                    continue
                value_start = self.skip_space(match.end(), body_end)
                value_end = self.expression_end(value_start, body_end)
                if self._mentions_parsed_output(value_start, value_end, call_start, call_end, tainted):
                    tainted.add(name)
                    added = True
            if not added:
                break
        for match in _TS_DOM_INSERTION_RE.finditer(skeleton, body_start, body_end):
            open_position = match.end() - 1
            close = self.match.get(open_position)
            if close is not None and self._mentions_parsed_output(
                open_position + 1, close, call_start, call_end, tainted
            ):
                return close + 1
        return None

    def _mentions_parsed_output(
        self, start: int, end: int, call_start: int, call_end: int, tainted: set[str]
    ) -> bool:
        if start <= call_start and call_end <= end:
            return True
        skeleton = self.skeleton
        for identifier in _TS_IDENTIFIER_RE.finditer(skeleton, start, end):
            if identifier.group() in tainted and (identifier.start() == 0 or skeleton[identifier.start() - 1] != '.'):
                return True
        return False


_TS_DANGEROUS_KEY_RE = re.compile(r'(?<![\w$.])dangerouslySetInnerHTML\s*(\?)?\s*:')
_TS_HTML_PROPERTY_ASSIGNMENT_RE = re.compile(r'\.\s*(innerHTML|outerHTML)\s*(\+)?=(?!=)')
_TS_INSERT_ADJACENT_HTML_RE = re.compile(r'\.\s*insertAdjacentHTML\s*\(')
_TS_DOCUMENT_WRITE_RE = re.compile(r'(?<![\w$.])(?:document|[\w$]*Document)\s*\.\s*(?:write|writeln)\s*\(')
_TS_CONTEXTUAL_FRAGMENT_RE = re.compile(r'\.\s*createContextualFragment\s*\(')
_TS_PARSE_FROM_STRING_RE = re.compile(r'\.\s*parseFromString\s*\(')
_TS_DOM_INSERTION_RE = re.compile(
    r'\.\s*(?:appendChild|append|prepend|replaceChildren|insertBefore|replaceWith|replaceChild|after|before'
    r'|importNode|adoptNode)\s*\('
)
_TS_EVAL_RE = re.compile(r'(?<![\w$.])(?:(?:window|globalThis|self)\s*\.\s*)?eval\s*\(')
_TS_FUNCTION_CONSTRUCTOR_RE = re.compile(r'(?<![\w$.])Function\s*\(')
_TS_TIMER_RE = re.compile(r'(?<![\w$.])(?:(?:window|globalThis|self)\s*\.\s*)?(?:setTimeout|setInterval)\s*\(')
_TS_JAVASCRIPT_SCHEME_RE = re.compile(r'javascript\s*:', re.IGNORECASE)
_TS_WINDOW_OPEN_RE = re.compile(r'(?<![\w$.])(?:window|globalThis|self|top|parent)\s*\.\s*open\s*\(')
_TS_LOCATION_HREF_ASSIGNMENT_RE = re.compile(r'\blocation\s*\.\s*href\s*=(?![=>])')
_TS_LOCATION_ASSIGNMENT_RE = re.compile(
    r'(?<![\w$.])(?:window|document|globalThis|self|top|parent)\s*\.\s*location\s*=(?![=>])'
)
_TS_LOCATION_METHOD_RE = re.compile(r'\blocation\s*\.\s*(?:assign|replace)\s*\(')
_TS_REHYPE_RAW_RE = re.compile(r'rehype-raw|rehypeRaw')
_TS_MARKDOWN_OPTION_KEY_RE = re.compile(
    r'(?<![\w$.])(allowDangerousHtml|urlTransform|transformLinkUri|transformImageUri)\s*(\?)?\s*:'
)
_TS_MARKDOWN_OPTION_NAMES = frozenset({'allowDangerousHtml', 'urlTransform', 'transformLinkUri', 'transformImageUri'})
_TS_DOM_URL_PROPERTY_RE = re.compile(r'\.\s*(href|src|action|formAction|srcdoc)\s*(\+)?=(?![=>])')
_TS_SET_ATTRIBUTE_RE = re.compile(r'\.\s*(setAttribute|setAttributeNS)\s*\(')
_TS_URL_ATTRIBUTE_NAMES = frozenset({'href', 'src', 'action', 'formaction', 'srcdoc', 'xlink:href'})
_TS_JSX_URL_ATTRIBUTE_NAMES = frozenset({
    'href', 'xlinkHref', 'xlink:href', 'formAction', 'srcDoc', 'src', 'action', 'data', 'to',
})
_TS_JSX_FALLBACK_ATTRIBUTE_RE = re.compile(
    r'(?<![\w$-])(href|xlinkHref|formAction|srcDoc|dangerouslySetInnerHTML|allowDangerousHtml|urlTransform'
    r'|transformLinkUri|transformImageUri)\s*=\s*\{'
)
_TS_JSX_FALLBACK_DECLARATION_RE = re.compile(r'(?<![\w$.])(?:const|let|var)\s*$')
_TS_ROUTER_LINK_TAGS = frozenset({'Link', 'NavLink', 'Navigate'})
_TS_STRICT_SRC_TAGS = frozenset({'script', 'iframe', 'frame', 'embed'})
_TS_DECLARATION_FILE_SUFFIXES = ('.d.ts', '.d.mts', '.d.cts')

TS_BARE_SUPPRESSION_HINT = (
    f" (A '{SUPPRESSION_TOKEN}' token was found without a justification; add a reason after it.)"
)
_TS_MESSAGE_DANGEROUS_INNER_HTML = (
    'dangerouslySetInnerHTML must receive {__html: ...} built from DOMPurify.sanitize(...) or another '
    'sanitizer/escaper. Sanitize the value, ' + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_HTML_SINK = (
    'Dynamic HTML reaches {sink}. Build DOM nodes, use textContent, or pass the value through '
    'DOMPurify.sanitize(...), ' + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_CODE_EVAL = '{sink} runs a string as code. Pass a function or data instead, ' + TS_SUPPRESSION_ADVICE
_TS_MESSAGE_JAVASCRIPT_URL = (
    'Avoid javascript: URLs. React 18 still renders them in href/src (it only warns). Use a real handler, '
    + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_JSX_URL = (
    'Dynamic {attribute} on <{tag}> is not a literal, a same-origin path or an approved URL helper/guard. '
    'Use a reviewed URL builder, sanitize*Url/normalize*Url, an isSafeOriginHref or scheme guard, '
    + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_NAVIGATION_SINK = (
    'Dynamic URL reaches {sink}. Navigate to a same-origin path, an approved URL helper result or a '
    'scheme-guarded value, ' + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_MARKDOWN_RAW_HTML = (
    '{option} lets markdown render raw HTML or unfiltered URLs. Keep raw HTML off and the default URL '
    'transform, ' + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_DOM_URL_PROPERTY = (
    'Dynamic value assigned to {sink}. Use a same-origin path, an approved URL helper or a scheme guard, '
    + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_INLINE_EVENT = (
    'Avoid inline event-handler attributes/APIs in generated HTML. Use addEventListener, ' + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_ATTRIBUTE_INTERPOLATION = (
    'Avoid interpolating untrusted values into href/src/title/style/data-* attributes of HTML strings. '
    'Prefer DOM APIs and explicit URL normalization, ' + TS_SUPPRESSION_ADVICE
)
_TS_MESSAGE_MARKED_PARSE = 'Wrap marked.parse(...) output with DOMPurify.sanitize(...), ' + TS_SUPPRESSION_ADVICE


def get_ts_suppression_state(source_lines: list[str], start_line: int, end_line: int) -> str:
    """Return 'justified', 'bare' or 'none' for suppression tokens near the reported lines.

    TypeScript findings honour the token only when a reason follows it on the same line.
    """
    window_start = max(1, start_line - 4)
    window_end = min(len(source_lines), end_line)
    state = 'none'
    for line_number in range(window_start, window_end + 1):
        line = source_lines[line_number - 1]
        index = line.find(SUPPRESSION_TOKEN)
        while index != -1:
            remainder = line[index + len(SUPPRESSION_TOKEN):]
            for closer in ('*/', '-->', '}'):
                remainder = remainder.replace(closer, ' ')
            if _TS_JUSTIFICATION_RE.search(remainder):
                return 'justified'
            state = 'bare'
            index = line.find(SUPPRESSION_TOKEN, index + 1)
    return state


class _TsContext:
    """Collects TypeScript findings with diff filtering and suppression handling."""

    def __init__(self, file_path: Path, view: TsSourceView, changed_lines: set[int] | None) -> None:
        self.file_path = file_path
        self.view = view
        self.changed_lines = changed_lines
        self.issues: list[Issue] = []

    def emit(self, rule: str, start: int, end: int, message: str) -> None:
        start_line = self.view.line_of(start)
        end_line = self.view.line_of(max(start, end - 1))
        if not matches_changed_lines(self.changed_lines, start_line, end_line):
            return
        state = get_ts_suppression_state(self.view.lines, start_line, end_line)
        if state == 'justified':
            return
        if state == 'bare':
            message += TS_BARE_SUPPRESSION_HINT
        self.issues.append(Issue(file_path=self.file_path, line=start_line, message=f'[{rule}] {message}'))

    def finish(self) -> list[Issue]:
        unique: dict[tuple[int, str], Issue] = {}
        for issue in self.issues:
            unique.setdefault((issue.line, issue.message), issue)
        return sorted(unique.values(), key=lambda issue: (issue.line, issue.message))


def _ts_jsx_attributes(view: TsSourceView, names: frozenset[str] | set[str]) -> list[TsJsxAttribute]:
    """Return recorded JSX attributes, plus regex fallbacks where JSX lexing had to back off."""
    attributes = [attribute for attribute in view.lex.jsx_attributes if attribute.name in names]
    if not (view.lex.degraded or view.lex.jsx_retries):
        return attributes
    skeleton = view.skeleton
    for match in _TS_JSX_FALLBACK_ATTRIBUTE_RE.finditer(skeleton):
        name = match.group(1)
        if name not in names or match.start() in view.attribute_name_starts:
            continue
        if _TS_JSX_FALLBACK_DECLARATION_RE.search(skeleton, max(0, match.start() - 8), match.start()):
            continue
        open_position = match.end() - 1
        close = view.match.get(open_position)
        if close is not None:
            attributes.append(TsJsxAttribute('', name, match.start(), 'expression', open_position + 1, close))
    return attributes


def _ts_value_approved(view: TsSourceView, check: str, start: int, end: int) -> bool:
    if check == 'html':
        return view.html_safe(start, end)
    if check == 'route':
        return view.route_target_approved(start, end)
    return view.url_approved(start, end, check)


def _ts_rule_dangerous_inner_html(context: _TsContext, view: TsSourceView) -> None:
    for attribute in _ts_jsx_attributes(view, {'dangerouslySetInnerHTML'}):
        if attribute.kind == 'expression' and view.html_object_safe(attribute.value_start, attribute.value_end):
            continue
        context.emit(TS_RULE_DANGEROUS_INNER_HTML, attribute.start, attribute.value_end, _TS_MESSAGE_DANGEROUS_INNER_HTML)
    for match in _TS_DANGEROUS_KEY_RE.finditer(view.skeleton):
        if match.group(1):
            continue
        value_start = view.skip_space(match.end())
        value_end = view.expression_end(value_start)
        if not view.html_object_safe(value_start, value_end):
            context.emit(TS_RULE_DANGEROUS_INNER_HTML, match.start(), value_end, _TS_MESSAGE_DANGEROUS_INNER_HTML)


def _ts_rule_html_sink(context: _TsContext, view: TsSourceView) -> None:
    skeleton = view.skeleton
    for match in _TS_HTML_PROPERTY_ASSIGNMENT_RE.finditer(skeleton):
        value_start = view.skip_space(match.end())
        value_end = view.expression_end(value_start)
        if not view.html_safe(value_start, value_end):
            context.emit(TS_RULE_HTML_SINK, match.start(), value_end, _TS_MESSAGE_HTML_SINK.format(sink=match.group(1)))
    call_sinks = (
        (_TS_INSERT_ADJACENT_HTML_RE, 'insertAdjacentHTML', (1,)),
        (_TS_DOCUMENT_WRITE_RE, 'document.write', None),
        (_TS_CONTEXTUAL_FRAGMENT_RE, 'createContextualFragment', (0,)),
    )
    for pattern, sink, indexes in call_sinks:
        for match in pattern.finditer(skeleton):
            open_position = match.end() - 1
            arguments = view.args(open_position)
            if not arguments:
                continue
            selected = arguments if indexes is None else [arguments[index] for index in indexes if index < len(arguments)]
            if all(view.html_safe(start, end) for start, end in selected):
                continue
            close = view.match.get(open_position, open_position)
            context.emit(TS_RULE_HTML_SINK, match.start(), close + 1, _TS_MESSAGE_HTML_SINK.format(sink=sink))
    for match in _TS_PARSE_FROM_STRING_RE.finditer(skeleton):
        open_position = match.end() - 1
        close = view.match.get(open_position)
        arguments = view.args(open_position)
        if close is None or not arguments or view.html_safe(*arguments[0]):
            continue
        insertion_end = view.parsed_output_insertion(match.start(), close + 1)
        if insertion_end is not None:
            context.emit(
                TS_RULE_HTML_SINK,
                match.start(),
                insertion_end,
                _TS_MESSAGE_HTML_SINK.format(sink='the DOM via DOMParser.parseFromString output'),
            )


def _ts_rule_code_eval(context: _TsContext, view: TsSourceView) -> None:
    skeleton = view.skeleton
    for pattern, sink in ((_TS_EVAL_RE, 'eval(...)'), (_TS_FUNCTION_CONSTRUCTOR_RE, 'Function(...)')):
        for match in pattern.finditer(skeleton):
            context.emit(TS_RULE_CODE_EVAL, match.start(), match.end(), _TS_MESSAGE_CODE_EVAL.format(sink=sink))
    for match in _TS_TIMER_RE.finditer(skeleton):
        arguments = view.args(match.end() - 1)
        if arguments and skeleton[arguments[0][0]] in '\'"`':
            context.emit(
                TS_RULE_CODE_EVAL,
                match.start(),
                arguments[0][1],
                _TS_MESSAGE_CODE_EVAL.format(sink='setTimeout/setInterval with a string argument'),
            )


def _ts_rule_javascript_url(context: _TsContext, view: TsSourceView) -> None:
    for match in _TS_JAVASCRIPT_SCHEME_RE.finditer(view.code):
        literal = view.literal_range_at(match.start())
        if literal is None:
            continue
        if view.text[literal[0]:literal[1]].strip().lower() == match.group().lower():
            continue
        context.emit(TS_RULE_JAVASCRIPT_URL, match.start(), match.end(), _TS_MESSAGE_JAVASCRIPT_URL)


def _ts_jsx_url_check(attribute: TsJsxAttribute) -> str | None:
    name = attribute.name
    tag = attribute.tag
    if name in {'href', 'xlinkHref', 'xlink:href', 'formAction'}:
        return 'href'
    if name == 'srcDoc':
        return 'html'
    if name == 'src' and tag in _TS_STRICT_SRC_TAGS:
        return 'strict'
    if name == 'action' and tag == 'form':
        return 'href'
    if name == 'data' and tag == 'object':
        return 'strict'
    if name == 'to' and tag.rsplit('.', 1)[-1] in _TS_ROUTER_LINK_TAGS:
        return 'route'
    return None


def _ts_rule_jsx_url_attribute(context: _TsContext, view: TsSourceView) -> None:
    for attribute in _ts_jsx_attributes(view, _TS_JSX_URL_ATTRIBUTE_NAMES):
        if attribute.kind != 'expression':
            continue
        check = _ts_jsx_url_check(attribute)
        if check is None or _ts_value_approved(view, check, attribute.value_start, attribute.value_end):
            continue
        context.emit(
            TS_RULE_JSX_URL_ATTRIBUTE,
            attribute.start,
            attribute.value_end,
            _TS_MESSAGE_JSX_URL.format(attribute=attribute.name, tag=attribute.tag or 'element'),
        )


def _ts_rule_navigation_sink(context: _TsContext, view: TsSourceView) -> None:
    skeleton = view.skeleton
    for pattern, sink in ((_TS_WINDOW_OPEN_RE, 'window.open'), (_TS_LOCATION_METHOD_RE, 'location.assign/replace')):
        for match in pattern.finditer(skeleton):
            open_position = match.end() - 1
            arguments = view.args(open_position)
            if not arguments or view.url_approved(*arguments[0], 'href'):
                continue
            if view.statement_guarded(match.start(), *arguments[0], 'href'):
                continue
            context.emit(TS_RULE_NAVIGATION_SINK, match.start(), arguments[0][1], _TS_MESSAGE_NAVIGATION_SINK.format(sink=sink))
    for pattern, sink in ((_TS_LOCATION_HREF_ASSIGNMENT_RE, 'location.href'), (_TS_LOCATION_ASSIGNMENT_RE, 'location')):
        for match in pattern.finditer(skeleton):
            value_start = view.skip_space(match.end())
            value_end = view.expression_end(value_start)
            if view.url_approved(value_start, value_end, 'href'):
                continue
            if view.statement_guarded(match.start(), value_start, value_end, 'href'):
                continue
            context.emit(TS_RULE_NAVIGATION_SINK, match.start(), value_end, _TS_MESSAGE_NAVIGATION_SINK.format(sink=sink))


def _ts_markdown_option_unsafe(view: TsSourceView, option: str, start: int, end: int) -> bool:
    value = view.norm(start, end)
    if option == 'allowDangerousHtml':
        return value != 'false' and not _TS_TYPE_ONLY_VALUE_RE.match(value)
    if option == 'urlTransform':
        return not (_TS_SAFE_URL_TRANSFORM_RE.match(value) or _TS_TYPE_ONLY_VALUE_RE.match(value))
    if value == 'null':
        return True
    if _TS_TYPE_ONLY_VALUE_RE.match(value):
        return False
    return bool(_TS_IDENTITY_ARROW_RE.match(value))


def _ts_rule_markdown_raw_html(context: _TsContext, view: TsSourceView) -> None:
    for match in _TS_REHYPE_RAW_RE.finditer(view.code):
        context.emit(
            TS_RULE_MARKDOWN_RAW_HTML, match.start(), match.end(), _TS_MESSAGE_MARKDOWN_RAW_HTML.format(option='rehype-raw')
        )
    for attribute in _ts_jsx_attributes(view, _TS_MARKDOWN_OPTION_NAMES):
        if attribute.kind == 'boolean':
            unsafe = attribute.name == 'allowDangerousHtml'
        elif attribute.kind == 'expression':
            unsafe = _ts_markdown_option_unsafe(view, attribute.name, attribute.value_start, attribute.value_end)
        else:
            unsafe = False
        if unsafe:
            context.emit(
                TS_RULE_MARKDOWN_RAW_HTML,
                attribute.start,
                attribute.value_end,
                _TS_MESSAGE_MARKDOWN_RAW_HTML.format(option=attribute.name),
            )
    for match in _TS_MARKDOWN_OPTION_KEY_RE.finditer(view.skeleton):
        if match.group(2):
            continue
        value_start = view.skip_space(match.end())
        value_end = view.expression_end(value_start)
        if _ts_markdown_option_unsafe(view, match.group(1), value_start, value_end):
            context.emit(
                TS_RULE_MARKDOWN_RAW_HTML, match.start(), value_end, _TS_MESSAGE_MARKDOWN_RAW_HTML.format(option=match.group(1))
            )


def _ts_dom_url_check(attribute_name: str, target: str | None, via_property: bool = False) -> str | None:
    if attribute_name == 'action' and via_property and target is not None and 'form' not in target.lower():
        # `.action` is also a common data field (for example transaction.action); only
        # receivers named like forms, and call/index results, are treated as form elements.
        return None
    if attribute_name in {'href', 'action', 'formaction', 'xlink:href'}:
        return 'href'
    if attribute_name == 'srcdoc':
        return 'html'
    if attribute_name == 'src':
        if target is not None:
            lowered = target.lower()
            if any(hint in lowered for hint in _TS_MEDIA_TARGET_HINTS) and not any(
                hint in lowered for hint in _TS_STRICT_TARGET_HINTS
            ):
                return None
        return 'strict'
    return None


def _ts_dom_value_approved(view: TsSourceView, check: str, sink_start: int, value_start: int, value_end: int) -> bool:
    if _ts_value_approved(view, check, value_start, value_end):
        return True
    return check != 'html' and view.statement_guarded(sink_start, value_start, value_end, check)


def _ts_rule_dom_url_property(context: _TsContext, view: TsSourceView) -> None:
    skeleton = view.skeleton
    for match in _TS_DOM_URL_PROPERTY_RE.finditer(skeleton):
        if match.group(2):
            continue
        target = view.member_target(match.start())
        if target is not None and target.rsplit('.', 1)[-1] == 'location':
            continue
        check = _ts_dom_url_check(match.group(1).lower(), target, via_property=True)
        if check is None:
            continue
        value_start = view.skip_space(match.end())
        value_end = view.expression_end(value_start)
        if not _ts_dom_value_approved(view, check, match.start(), value_start, value_end):
            sink = f'{target or "element"}.{match.group(1)}'
            context.emit(TS_RULE_DOM_URL_PROPERTY, match.start(), value_end, _TS_MESSAGE_DOM_URL_PROPERTY.format(sink=sink))
    for match in _TS_SET_ATTRIBUTE_RE.finditer(skeleton):
        open_position = match.end() - 1
        arguments = view.args(open_position)
        name_index = 1 if match.group(1) == 'setAttributeNS' else 0
        if len(arguments) <= name_index + 1:
            continue
        attribute_name = view.literal_text(*arguments[name_index])
        if attribute_name is None or attribute_name.lower() not in _TS_URL_ATTRIBUTE_NAMES:
            continue
        check = _ts_dom_url_check(attribute_name.lower(), view.member_target(match.start()))
        value_start, value_end = arguments[name_index + 1]
        if check is None or _ts_dom_value_approved(view, check, match.start(), value_start, value_end):
            continue
        sink = f"{match.group(1)}('{attribute_name}')"
        context.emit(TS_RULE_DOM_URL_PROPERTY, match.start(), value_end, _TS_MESSAGE_DOM_URL_PROPERTY.format(sink=sink))


def _ts_rule_legacy_patterns(context: _TsContext, view: TsSourceView) -> None:
    code = view.code
    for match in INLINE_EVENT_ATTRIBUTE_RE.finditer(code):
        if view.in_literal(match.start()):
            context.emit(TS_RULE_INLINE_EVENT_HANDLER, match.start(), match.end(), _TS_MESSAGE_INLINE_EVENT)
    for match in INLINE_EVENT_API_RE.finditer(code):
        context.emit(TS_RULE_INLINE_EVENT_HANDLER, match.start(), match.end(), _TS_MESSAGE_INLINE_EVENT)
    safe_identifiers = get_safe_attribute_identifiers(code)
    for match in ATTRIBUTE_INTERPOLATION_RE.finditer(code):
        if not view.in_literal(match.start()) or is_selector_interpolation_context(code, match.start()):
            continue
        if is_allowed_attribute_interpolation(match.group('attr'), match.group('value'), safe_identifiers):
            continue
        context.emit(TS_RULE_ATTRIBUTE_INTERPOLATION, match.start(), match.end(), _TS_MESSAGE_ATTRIBUTE_INTERPOLATION)
    for match in MARKED_PARSE_RE.finditer(view.skeleton):
        start_line = view.line_of(match.start())
        window_text = '\n'.join(view.lines[max(0, start_line - 3):start_line + 2])
        if 'DOMPurify.sanitize(' not in window_text:
            context.emit(TS_RULE_MARKED_PARSE, match.start(), match.end(), _TS_MESSAGE_MARKED_PARSE)


_TS_RULES = (
    _ts_rule_dangerous_inner_html,
    _ts_rule_html_sink,
    _ts_rule_code_eval,
    _ts_rule_javascript_url,
    _ts_rule_jsx_url_attribute,
    _ts_rule_navigation_sink,
    _ts_rule_markdown_raw_html,
    _ts_rule_dom_url_property,
    _ts_rule_legacy_patterns,
)


def inspect_typescript_source(
    file_path: Path, source_text: str, changed_lines: set[int] | None = None
) -> list[Issue]:
    """Inspect one TypeScript/TSX/JSX/MJS source string with the React-aware rules."""
    if file_path.name.endswith(_TS_DECLARATION_FILE_SUFFIXES):
        return []
    lex = lex_typescript(source_text, file_path.suffix in JSX_ENABLED_SUFFIXES)
    view = TsSourceView(source_text, lex)
    context = _TsContext(file_path, view, changed_lines)
    for rule in _TS_RULES:
        rule(context, view)
    return context.finish()


def inspect_source(file_path: Path, source_text: str, changed_lines: set[int] | None = None) -> list[Issue]:
    """Inspect one source string and return any XSS-related issues."""
    if file_path.suffix in TYPESCRIPT_FAMILY_SUFFIXES:
        return inspect_typescript_source(file_path, source_text, changed_lines=changed_lines)
    source_lines = source_text.splitlines()
    issues: list[Issue] = []

    issues.extend(
        collect_regex_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=INLINE_EVENT_ATTRIBUTE_RE,
            message=(
                f"Avoid inline event-handler attributes in rendered HTML. Use addEventListener or data-* hooks, "
                f"or add '{SUPPRESSION_TOKEN}' with a justification."
            ),
        )
    )
    issues.extend(
        collect_regex_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=INLINE_EVENT_API_RE,
            message=(
                f"Avoid inline event-handler APIs such as onclick/onerror. Use addEventListener, "
                f"or add '{SUPPRESSION_TOKEN}' with a justification."
            ),
        )
    )
    issues.extend(
        collect_regex_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=JAVASCRIPT_URL_RE,
            message=(
                f"Avoid javascript: URLs in rendered content. Normalize dynamic URLs explicitly, "
                f"or add '{SUPPRESSION_TOKEN}' with a justification."
            ),
        )
    )
    issues.extend(
        collect_attribute_interpolation_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
        )
    )
    issues.extend(
        collect_regex_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=DANGEROUS_REACT_HTML_RE,
            message=(
                f"Avoid dangerouslySetInnerHTML without a reviewed sanitizer boundary, "
                f"or add '{SUPPRESSION_TOKEN}' with a justification."
            ),
        )
    )

    if file_path.suffix == '.py':
        issues.extend(
            collect_regex_issues(
                file_path=file_path,
                source_text=source_text,
                source_lines=source_lines,
                changed_lines=changed_lines,
                pattern=MARKUP_RE,
                message=(
                    f"Avoid Markup(...) on untrusted content without a reviewed sanitizer boundary, "
                    f"or add '{SUPPRESSION_TOKEN}' with a justification."
                ),
            )
        )

    if file_path.suffix == '.html':
        issues.extend(
            collect_regex_issues(
                file_path=file_path,
                source_text=source_text,
                source_lines=source_lines,
                changed_lines=changed_lines,
                pattern=JINJA_SAFE_RE,
                message=(
                    f"Avoid Jinja '|safe' on untrusted content without a reviewed sanitizer boundary, "
                    f"or add '{SUPPRESSION_TOKEN}' with a justification."
                ),
            )
        )

    issues.extend(
        collect_html_sink_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=HTML_ASSIGNMENT_RE,
            sink_name='innerHTML/outerHTML',
        )
    )
    issues.extend(
        collect_html_sink_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=INSERT_ADJACENT_HTML_RE,
            sink_name='insertAdjacentHTML',
        )
    )
    issues.extend(
        collect_html_sink_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=JQUERY_HTML_RE,
            sink_name='jQuery .html()',
        )
    )
    issues.extend(
        collect_marked_parse_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
        )
    )

    unique_issues: list[Issue] = []
    seen = set()
    for issue in issues:
        dedupe_key = (issue.file_path, issue.line, issue.message)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        unique_issues.append(issue)

    return unique_issues


def inspect_file(file_path: Path, changed_lines: set[int] | None = None) -> list[Issue]:
    """Load one file and return any XSS-related issues."""
    if is_skipped_vendor_browser_asset(file_path):
        return []

    try:
        source_text = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        source_text = file_path.read_text(encoding='utf-8-sig')
    except OSError as exc:
        return [
            Issue(
                file_path=file_path,
                line=1,
                message=f'Unable to read file for XSS sink validation: {exc}',
            )
        ]

    return inspect_source(file_path, source_text, changed_lines=changed_lines)


def main() -> int:
    """Run the XSS sink checker for the provided files."""
    parser = argparse.ArgumentParser(description='Validate changed files for risky XSS sink patterns.')
    parser.add_argument('files', nargs='*', help='Files to validate relative to the repository root.')
    parser.add_argument('--base-sha', help='Base git revision used to limit checks to added lines.')
    parser.add_argument('--head-sha', help='Head git revision used to limit checks to added lines.')
    parser.add_argument(
        '--full-file',
        action='store_true',
        help='Scan the full file contents instead of only added lines.',
    )
    args = parser.parse_args()

    files = normalize_paths(args.files)
    if not files:
        print('No supported files to validate for XSS sink coverage.')
        return 0

    all_issues: list[Issue] = []
    checked_files = 0

    for file_path in files:
        changed_lines = None
        if not args.full_file and args.base_sha and args.head_sha:
            changed_lines = get_changed_lines(file_path, args.base_sha, args.head_sha)
            if changed_lines == set():
                continue

        issues = inspect_file(file_path, changed_lines=changed_lines)
        checked_files += 1
        all_issues.extend(issues)

    if all_issues:
        print('XSS sink validation failed:')
        for issue in all_issues:
            print(format_error_annotation(issue))
        return 1

    if checked_files == 0:
        print('No added lines found in the provided files. XSS sink check skipped.')
        return 0

    print(f'XSS sink validation passed for {checked_files} file(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())