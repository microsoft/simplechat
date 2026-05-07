# check_broken_access_control.py

"""Validate changed Python files for high-confidence broken access control regressions."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_SUFFIXES = {'.py'}
SUPPRESSION_TOKEN = 'bac-check: ignore'
DIFF_HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@')
ACTIVE_SCOPE_KEYS = {
    'activeGroupOid': {
        'read_helper': 'require_active_group(...)',
        'write_helper': 'update_active_group_for_user(...)',
    },
    'activePublicWorkspaceOid': {
        'read_helper': 'require_active_public_workspace(...)',
        'write_helper': 'update_active_public_workspace_for_user(...)',
    },
}
ACTIVE_SCOPE_READ_ALLOWED_PATHS = {
    'application/single_app/functions_group.py',
    'application/single_app/functions_public_workspaces.py',
}
ACTIVE_SCOPE_READ_TARGET_PREFIXES = (
    'application/single_app/route_backend_',
    'application/single_app/semantic_kernel_plugins/',
)
APPROVED_ACTIVE_SCOPE_WRITE_CONTEXTS = {
    ('application/single_app/functions_group.py', 'update_active_group_for_user', 'activeGroupOid'),
    (
        'application/single_app/functions_public_workspaces.py',
        'update_active_public_workspace_for_user',
        'activePublicWorkspaceOid',
    ),
}
KERNEL_SENSITIVE_PARAMS = {
    'user_id',
    'conversation_id',
    'group_id',
    'public_workspace_id',
    'scope_id',
    'scope_type',
    'active_group_id',
    'active_group_ids',
    'active_public_workspace_id',
    'active_public_workspace_ids',
}
APPROVED_KERNEL_SCOPE_HELPERS = {
    '_resolve_authorized_scope_arguments',
    '_resolve_authorized_fact_memory_call',
    '_resolve_blob_location_with_fallback',
    '_get_authenticated_history_user_id',
}
PERSONAL_CONVERSATION_ROUTE_FILES = {
    'application/single_app/route_backend_chats.py',
    'application/single_app/route_backend_conversations.py',
    'application/single_app/route_backend_documents.py',
    'application/single_app/route_backend_feedback.py',
    'application/single_app/route_frontend_conversations.py',
}
ADMIN_DECORATORS = {'admin_required', 'control_center_required'}
EXPLICIT_OWNERSHIP_SNIPPETS = (
    "conversation_item.get('user_id') != user_id",
    'conversation_item.get("user_id") != user_id',
    "conversation_item['user_id'] != user_id",
    'conversation_item["user_id"] != user_id',
    "conversation.get('user_id') != user_id",
    'conversation.get("user_id") != user_id',
    "conversation['user_id'] != user_id",
    'conversation["user_id"] != user_id',
)


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
    """Return a GitHub Actions error annotation for one issue."""
    return f'::error file={get_relative_path(issue.file_path)},line={issue.line}::{issue.message}'


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


def matches_changed_lines(changed_lines: set[int] | None, start_line: int, end_line: int) -> bool:
    """Return True when the issue overlaps changed lines or full-file mode is active."""
    if changed_lines is None:
        return True
    return any(line in changed_lines for line in range(start_line, end_line + 1))


def is_suppressed(source_lines: list[str], start_line: int, end_line: int) -> bool:
    """Return True when a suppression token exists near the reported lines."""
    window_start = max(1, start_line - 2)
    window_end = min(len(source_lines), end_line)
    for line_number in range(window_start, window_end + 1):
        if SUPPRESSION_TOKEN in source_lines[line_number - 1]:
            return True
    return False


def get_changed_lines(file_path: Path, base_sha: str, head_sha: str) -> set[int] | None:
    """Return added-line numbers for one file between two revisions."""
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


def call_name(call_node: ast.Call) -> str | None:
    """Return the simple callable name for a Call node when available."""
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    if isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return None


def decorator_name(decorator_node: ast.expr) -> str | None:
    """Return the simple decorator name for a decorator node when available."""
    if isinstance(decorator_node, ast.Name):
        return decorator_node.id
    if isinstance(decorator_node, ast.Attribute):
        return decorator_node.attr
    if isinstance(decorator_node, ast.Call):
        if isinstance(decorator_node.func, ast.Name):
            return decorator_node.func.id
        if isinstance(decorator_node.func, ast.Attribute):
            return decorator_node.func.attr
    return None


def has_decorator(function_node: ast.FunctionDef | ast.AsyncFunctionDef, names: set[str]) -> bool:
    """Return True when the function has any decorator in the provided set."""
    return any(decorator_name(decorator) in names for decorator in function_node.decorator_list)


def build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Return a child-to-parent AST mapping."""
    parent_map: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent
    return parent_map


def get_enclosing_function(
    node: ast.AST,
    parent_map: dict[ast.AST, ast.AST],
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the nearest enclosing function for a node when available."""
    current_node = node
    while current_node in parent_map:
        current_node = parent_map[current_node]
        if isinstance(current_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current_node
    return None


def string_constant(node: ast.AST | None) -> str | None:
    """Return a string constant value when the AST node is a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def iter_dict_literals(call_node: ast.Call) -> list[ast.Dict]:
    """Return dict literal arguments passed to a call."""
    dict_literals: list[ast.Dict] = []
    for argument in call_node.args:
        if isinstance(argument, ast.Dict):
            dict_literals.append(argument)
    for keyword in call_node.keywords:
        if isinstance(keyword.value, ast.Dict):
            dict_literals.append(keyword.value)
    return dict_literals


def collect_function_call_names(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return the set of simple call names used inside a function."""
    call_names: set[str] = set()
    for node in ast.walk(function_node):
        if isinstance(node, ast.Call):
            name = call_name(node)
            if name:
                call_names.add(name)
    return call_names


def get_function_source(source_text: str, function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return the exact source segment for one function."""
    return ast.get_source_segment(source_text, function_node) or ''


def is_conversation_authorization_helper_name(name: str) -> bool:
    """Return True when a helper name clearly represents a conversation authorization helper."""
    lowered_name = str(name or '').lower()
    return lowered_name.startswith('_authorize_') and 'conversation' in lowered_name


def function_has_conversation_auth(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_text: str,
) -> bool:
    """Return True when the function already uses an approved conversation auth boundary."""
    if is_conversation_authorization_helper_name(function_node.name):
        return True
    if has_decorator(function_node, ADMIN_DECORATORS):
        return True

    function_calls = collect_function_call_names(function_node)
    if any(is_conversation_authorization_helper_name(name) for name in function_calls):
        return True

    function_source = get_function_source(source_text, function_node)
    return any(snippet in function_source for snippet in EXPLICIT_OWNERSHIP_SNIPPETS)


def call_references_name_fragment(call_node: ast.Call, fragment: str, source_text: str) -> bool:
    """Return True when the call source references the provided name fragment."""
    call_source = ast.get_source_segment(source_text, call_node) or ''
    return fragment in call_source


def collect_direct_active_scope_write_issues(
    *,
    file_path: Path,
    relative_path: str,
    tree: ast.AST,
    parent_map: dict[ast.AST, ast.AST],
    source_lines: list[str],
    changed_lines: set[int] | None,
) -> list[Issue]:
    """Collect issues for direct persistence of authorization-sensitive active scope keys."""
    issues: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or call_name(node) != 'update_user_settings':
            continue

        function_node = get_enclosing_function(node, parent_map)
        function_name = function_node.name if function_node else ''

        for dict_literal in iter_dict_literals(node):
            for key_node in dict_literal.keys:
                key_name = string_constant(key_node)
                if key_name not in ACTIVE_SCOPE_KEYS:
                    continue
                if (relative_path, function_name, key_name) in APPROVED_ACTIVE_SCOPE_WRITE_CONTEXTS:
                    continue

                start_line = getattr(dict_literal, 'lineno', node.lineno)
                end_line = getattr(dict_literal, 'end_lineno', start_line)
                if not matches_changed_lines(changed_lines, start_line, end_line):
                    continue
                if is_suppressed(source_lines, start_line, end_line):
                    continue

                helper_name = ACTIVE_SCOPE_KEYS[key_name]['write_helper']
                issues.append(
                    Issue(
                        file_path=file_path,
                        line=start_line,
                        message=(
                            f"Do not persist {key_name} through update_user_settings(...) outside {helper_name}. "
                            f"Route active-scope writes through the validator, or add '{SUPPRESSION_TOKEN}' with a justification."
                        ),
                    )
                )
    return issues


def collect_direct_active_scope_read_issues(
    *,
    file_path: Path,
    relative_path: str,
    tree: ast.AST,
    source_lines: list[str],
    changed_lines: set[int] | None,
) -> list[Issue]:
    """Collect issues for raw active scope reads in backend and plugin code."""
    if relative_path in ACTIVE_SCOPE_READ_ALLOWED_PATHS:
        return []
    if not relative_path.startswith(ACTIVE_SCOPE_READ_TARGET_PREFIXES):
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or call_name(node) != 'get' or not node.args:
            continue

        key_name = string_constant(node.args[0])
        if key_name not in ACTIVE_SCOPE_KEYS:
            continue

        start_line = node.lineno
        end_line = getattr(node, 'end_lineno', start_line)
        if not matches_changed_lines(changed_lines, start_line, end_line):
            continue
        if is_suppressed(source_lines, start_line, end_line):
            continue

        helper_name = ACTIVE_SCOPE_KEYS[key_name]['read_helper']
        issues.append(
            Issue(
                file_path=file_path,
                line=start_line,
                message=(
                    f"Avoid reading {key_name} from raw settings in backend or plugin code. "
                    f"Use {helper_name} or a request-scoped authorization helper, "
                    f"or add '{SUPPRESSION_TOKEN}' with a justification."
                ),
            )
        )
    return issues


def collect_kernel_scope_param_issues(
    *,
    file_path: Path,
    relative_path: str,
    tree: ast.AST,
    source_lines: list[str],
    changed_lines: set[int] | None,
) -> list[Issue]:
    """Collect issues for kernel functions that expose sensitive scope ids without normalization."""
    if not relative_path.startswith('application/single_app/semantic_kernel_plugins/'):
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not has_decorator(node, {'kernel_function'}):
            continue

        parameter_names = {
            argument.arg
            for argument in (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            )
            if argument.arg != 'self'
        }
        sensitive_params = sorted(parameter_names & KERNEL_SENSITIVE_PARAMS)
        if not sensitive_params:
            continue

        start_line = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
        end_line = getattr(node, 'end_lineno', node.lineno)
        if not matches_changed_lines(changed_lines, start_line, end_line):
            continue
        if is_suppressed(source_lines, start_line, end_line):
            continue

        function_call_names = collect_function_call_names(node)
        if function_call_names & APPROVED_KERNEL_SCOPE_HELPERS:
            continue

        issues.append(
            Issue(
                file_path=file_path,
                line=start_line,
                message=(
                    f"Kernel functions that expose {', '.join(sensitive_params)} must immediately normalize those values "
                    f"through an approved authorization helper such as _resolve_authorized_scope_arguments(...), "
                    f"_resolve_blob_location_with_fallback(...), or _resolve_authorized_fact_memory_call(...), "
                    f"or add '{SUPPRESSION_TOKEN}' with a justification."
                ),
            )
        )
    return issues


def collect_direct_personal_conversation_read_issues(
    *,
    file_path: Path,
    relative_path: str,
    tree: ast.AST,
    source_text: str,
    source_lines: list[str],
    changed_lines: set[int] | None,
) -> list[Issue]:
    """Collect issues for direct personal conversation reads without an auth boundary."""
    if relative_path not in PERSONAL_CONVERSATION_ROUTE_FILES:
        return []

    issues: list[Issue] = []
    for function_node in ast.walk(tree):
        if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if function_has_conversation_auth(function_node, source_text):
            continue

        for node in ast.walk(function_node):
            if not isinstance(node, ast.Call) or call_name(node) != 'read_item':
                continue

            call_source = ast.get_source_segment(source_text, node) or ''
            if 'cosmos_conversations_container.read_item' not in call_source:
                continue
            if not call_references_name_fragment(node, 'conversation_id', source_text):
                continue

            start_line = node.lineno
            end_line = getattr(node, 'end_lineno', start_line)
            if not matches_changed_lines(changed_lines, start_line, end_line):
                continue
            if is_suppressed(source_lines, start_line, end_line):
                continue

            issues.append(
                Issue(
                    file_path=file_path,
                    line=start_line,
                    message=(
                        "Avoid direct personal conversation reads from request-derived conversation_id values without "
                        "_authorize_personal_conversation_read(...), _authorize_personal_conversation_access(...), "
                        f"or an explicit ownership check, or add '{SUPPRESSION_TOKEN}' with a justification."
                    ),
                )
            )
    return issues


def inspect_source(file_path: Path, source_text: str, changed_lines: set[int] | None = None) -> list[Issue]:
    """Inspect one Python source string and return any BAC-related issues."""
    source_lines = source_text.splitlines()

    try:
        tree = ast.parse(source_text, filename=str(file_path))
    except SyntaxError as exc:
        return [
            Issue(
                file_path=file_path,
                line=exc.lineno or 1,
                message=f'Unable to parse file for BAC validation: {exc.msg}',
            )
        ]

    relative_path = get_relative_path(file_path)
    parent_map = build_parent_map(tree)
    issues: list[Issue] = []
    issues.extend(
        collect_direct_active_scope_write_issues(
            file_path=file_path,
            relative_path=relative_path,
            tree=tree,
            parent_map=parent_map,
            source_lines=source_lines,
            changed_lines=changed_lines,
        )
    )
    issues.extend(
        collect_direct_active_scope_read_issues(
            file_path=file_path,
            relative_path=relative_path,
            tree=tree,
            source_lines=source_lines,
            changed_lines=changed_lines,
        )
    )
    issues.extend(
        collect_kernel_scope_param_issues(
            file_path=file_path,
            relative_path=relative_path,
            tree=tree,
            source_lines=source_lines,
            changed_lines=changed_lines,
        )
    )
    issues.extend(
        collect_direct_personal_conversation_read_issues(
            file_path=file_path,
            relative_path=relative_path,
            tree=tree,
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
    """Load one file and return any BAC-related issues."""
    try:
        source_text = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        source_text = file_path.read_text(encoding='utf-8-sig')
    except OSError as exc:
        return [
            Issue(
                file_path=file_path,
                line=1,
                message=f'Unable to read file for BAC validation: {exc}',
            )
        ]

    return inspect_source(file_path, source_text, changed_lines=changed_lines)


def main() -> int:
    """Run the Broken Access Control checker for the provided files."""
    parser = argparse.ArgumentParser(
        description='Validate changed Python files for high-confidence broken access control regressions.'
    )
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
        print('No supported files to validate for Broken Access Control guardrails.')
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
        print('Broken Access Control guardrail validation failed:')
        for issue in all_issues:
            print(format_error_annotation(issue))
        return 1

    if checked_files == 0:
        print('No added lines found in the provided files. Broken Access Control check skipped.')
        return 0

    print(f'Broken Access Control guardrail validation passed for {checked_files} file(s).')
    return 0


if __name__ == '__main__':
    sys.exit(main())