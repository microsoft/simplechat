# check_xss_sinks.py

"""Validate changed files for risky XSS sink patterns."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SUFFIXES = {'.js', '.html', '.py'}
SUPPRESSION_TOKEN = 'xss-check: ignore'
INLINE_EVENT_ATTRIBUTE_RE = re.compile(
    r'\bon(?:abort|auxclick|beforeinput|blur|change|click|contextmenu|dblclick|error|focus|input|keydown|keypress|keyup|load|mousedown|mouseenter|mouseleave|mousemove|mouseout|mouseover|mouseup|reset|scroll|submit|touchend|touchstart|transitionend)\s*=\s*["\']',
    re.IGNORECASE,
)
INLINE_EVENT_API_RE = re.compile(
    r'\.(?:onabort|onblur|onchange|onclick|ondblclick|onerror|onfocus|oninput|onkeydown|onkeyup|onload|onmousedown|onmouseenter|onmouseleave|onmousemove|onmouseout|onmouseover|onmouseup|onscroll|onsubmit)\s*=|setAttribute\(\s*["\']on',
    re.IGNORECASE,
)
JAVASCRIPT_URL_RE = re.compile(r'javascript\s*:', re.IGNORECASE)
MARKUP_RE = re.compile(r'\bMarkup\s*\(')
JINJA_SAFE_RE = re.compile(r'\|\s*safe\b')
MARKED_PARSE_RE = re.compile(r'\bmarked\.parse\s*\(')
DANGEROUS_REACT_HTML_RE = re.compile(r'\bdangerouslySetInnerHTML\b')
ATTRIBUTE_INTERPOLATION_RE = re.compile(
    r'\b(?:href|src|title|style|data-[\w-]+)\s*=\s*["\'][^"\'\n]*\$\{[^}]+\}',
    re.IGNORECASE,
)
HTML_ASSIGNMENT_RE = re.compile(
    r'\.(?P<sink>innerHTML|outerHTML)\s*=\s*(?P<expr>.{0,500}?);',
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
    window_start = max(1, start_line - 2)
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


def is_allowed_html_expression(expression: str) -> bool:
    """Return True when an HTML sink expression is explicitly allowed."""
    if 'DOMPurify.sanitize(' in expression:
        return True
    return is_static_html_expression(expression)


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
        if not matches_changed_lines(changed_lines, start_line, end_line):
            continue
        if is_suppressed(source_lines, start_line, end_line):
            continue
        issues.append(Issue(file_path=file_path, line=start_line, message=message))
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
    for match in pattern.finditer(source_text):
        expression = match.group('expr')
        if is_allowed_html_expression(expression):
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


def inspect_source(file_path: Path, source_text: str, changed_lines: set[int] | None = None) -> list[Issue]:
    """Inspect one source string and return any XSS-related issues."""
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
        collect_regex_issues(
            file_path=file_path,
            source_text=source_text,
            source_lines=source_lines,
            changed_lines=changed_lines,
            pattern=ATTRIBUTE_INTERPOLATION_RE,
            message=(
                f"Avoid interpolating untrusted values directly into href/src/title/style/data-* attributes. "
                f"Prefer DOM APIs and explicit URL normalization, or add '{SUPPRESSION_TOKEN}' with a justification."
            ),
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