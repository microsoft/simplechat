# normalize_test_headers.py
"""Normalize the header of every SimpleChat test file to the repository standard.

Version: 0.261.489
Implemented in: 0.261.489

The standard, from CLAUDE.md "Functional Tests":

    #!/usr/bin/env python3            (optional, Python only)
    # test_feature_area.py            (filename comment; ``//`` for JavaScript)
    \"\"\"
    Functional test for <feature or fix>.
    Version: <current config.py VERSION>
    Implemented in: <version the feature or fix shipped in>

    This test ensures that ...
    \"\"\"

What this script changes, and nothing else:

* adds the filename comment when the first two lines do not have one, or
  corrects one that names a different file;
* adds ``Version:`` and ``Implemented in:`` lines to the module docstring (or
  JavaScript header comment) when they are missing, creating a docstring when
  the file has none;
* with ``--set-version``, rewrites the ``Version:`` line of the header to the
  current ``config.py`` VERSION, to record that the file was validated against
  that release. ``Implemented in:`` is history and is never rewritten.

A missing ``Implemented in:`` value is taken from the ``config.py`` VERSION in
the commit that added the file (``git log --diff-filter=A``), falling back to
the file's existing ``Version:`` value.

Usage (from the repository root):

    python scripts/normalize_test_headers.py --check
    python scripts/normalize_test_headers.py --write [--set-version] [paths...]

``--check`` exits 1 when any file needs a change, so it can run in CI.
"""

import argparse
import ast
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
TEST_DIRECTORIES = ("functional_tests", "ui_tests")
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
HEADER_VERSION_RE = re.compile(r"^(\s*\*?\s*)Version:\s*v?([0-9][0-9.]*)(.*)$", re.MULTILINE)
HEADER_IMPLEMENTED_RE = re.compile(r"^\s*\*?\s*Implemented in:", re.MULTILINE)
SKIP_PARTS = {"node_modules", "__pycache__", ".pytest_cache"}


def current_version():
    match = VERSION_RE.search(CONFIG_FILE.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"VERSION assignment not found in {CONFIG_FILE}")
    return match.group(1)


@lru_cache(maxsize=None)
def _version_at_commit(commit):
    try:
        source = subprocess.run(
            ["git", "show", f"{commit}:application/single_app/config.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return ""
    match = VERSION_RE.search(source)
    return match.group(1) if match else ""


def version_when_added(path):
    """Return the config.py VERSION in the commit that first added ``path``, or ''."""
    try:
        commits = subprocess.run(
            ["git", "log", "--diff-filter=A", "--follow", "--format=%H", "--", str(path.relative_to(REPO_ROOT))],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout.split()
    except subprocess.CalledProcessError:
        return ""
    return _version_at_commit(commits[-1]) if commits else ""


def iter_test_files(paths):
    if paths:
        for raw in paths:
            path = Path(raw).resolve()
            if path.is_dir():
                yield from sorted(_walk(path))
            elif path.is_file():
                yield path
        return
    for directory in TEST_DIRECTORIES:
        yield from sorted(_walk(REPO_ROOT / directory))


def _walk(directory):
    for path in directory.rglob("test_*"):
        if path.suffix not in (".py", ".js") or SKIP_PARTS.intersection(path.parts):
            continue
        yield path


def _header_region(text, suffix):
    """Return (start, end) of the header comment or docstring the version lines belong in."""
    if suffix == ".py":
        try:
            module = ast.parse(text)
        except SyntaxError:
            return None
        if module.body and isinstance(module.body[0], ast.Expr) and isinstance(
            getattr(module.body[0], "value", None), ast.Constant
        ) and isinstance(module.body[0].value.value, str):
            node = module.body[0]
            lines = text.splitlines(keepends=True)
            start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
            end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
            return start, end
        return None
    match = re.search(r"/\*.*?\*/", text, re.S)
    if match and match.start() < 400:
        return match.start(), match.end()
    return None


def _filename_comment(path):
    return ("# " if path.suffix == ".py" else "// ") + path.name


def normalize(path, version, set_version):
    """Return the normalized text of ``path`` and the list of changes made."""
    original = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    text = original.replace("\r\n", "\n")
    changes = []
    prefix = "#" if path.suffix == ".py" else "//"

    # 1. Filename comment on line 1, or line 2 after a shebang.
    lines = text.split("\n")
    comment_index = 1 if lines and lines[0].startswith("#!") else 0
    expected = _filename_comment(path)
    filename_re = re.compile(r"^" + re.escape(prefix) + r"\s*([\w.\-]+\.(py|js))\s*$")
    current = lines[comment_index] if comment_index < len(lines) else ""
    found = filename_re.match(current)
    if found and found.group(1) != path.name:
        lines[comment_index] = expected
        changes.append("filename comment corrected")
    elif not found:
        lines.insert(comment_index, expected)
        changes.append("filename comment added")
    text = "\n".join(lines)

    # 2. Version and Implemented in lines inside the header.
    region = _header_region(text, path.suffix)
    header = text[region[0]:region[1]] if region else ""
    has_version = bool(HEADER_VERSION_RE.search(header))
    has_implemented = bool(HEADER_IMPLEMENTED_RE.search(header))

    if not has_version or not has_implemented:
        existing = HEADER_VERSION_RE.search(header)
        implemented = version_when_added(path) or (existing.group(2) if existing else "") or version
        additions = []
        if not has_version:
            additions.append(f"Version: {version}")
        if not has_implemented:
            additions.append(f"Implemented in: {implemented}")

        if region is None:
            lines = text.split("\n")
            insert_at = comment_index + 1
            if path.suffix == ".py":
                block = ['"""', f"Tests for {path.stem.removeprefix('test_').replace('_', ' ')}.", *additions, '"""', ""]
            else:
                block = ["/*", *[f" * {line}" for line in additions], " */", ""]
            lines[insert_at:insert_at] = block
            text = "\n".join(lines)
        else:
            start, end = region
            header = text[start:end]
            if path.suffix == ".py":
                quote = header[-3:] if header[-3:] in ('"""', "'''") else header[-1]
                body_end = len(header) - len(quote)
                body = header[:body_end].rstrip(" ")
                if body.endswith("\n"):
                    new_header = body + "\n".join(additions) + "\n" + quote
                else:
                    new_header = body + "\n\n" + "\n".join(additions) + "\n" + quote
            else:
                body = header[:-2].rstrip()
                new_header = body + "\n" + "\n".join(f" * {line}" for line in additions) + "\n */"
            text = text[:start] + new_header + text[end:]
        changes.extend(f"{line.split(':')[0]} added" for line in additions)

    # 3. Optionally record the release the file was validated against.
    if set_version:
        region = _header_region(text, path.suffix)
        if region:
            start, end = region
            header = text[start:end]
            match = HEADER_VERSION_RE.search(header)
            if match and match.group(2) != version:
                new_line = f"{match.group(1)}Version: {version}{match.group(3)}"
                header = header[: match.start()] + new_line + header[match.end():]
                text = text[:start] + header + text[end:]
                changes.append(f"Version {match.group(2)} -> {version}")

    if changes:
        text = text.replace("\n", newline)
    return (text if changes else original), changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report files that need changes; exit 1 if any")
    mode.add_argument("--write", action="store_true", help="rewrite files in place")
    parser.add_argument("--set-version", action="store_true", help="also set Version: to the current config.py VERSION")
    parser.add_argument("paths", nargs="*", help="files or directories (default: functional_tests and ui_tests)")
    args = parser.parse_args(argv)

    version = current_version()
    changed = 0
    for path in iter_test_files(args.paths):
        new_text, changes = normalize(path, version, args.set_version)
        if not changes:
            continue
        changed += 1
        rel = path.relative_to(REPO_ROOT)
        print(f"{rel}: {', '.join(changes)}")
        if args.write:
            if path.suffix == ".py":
                try:
                    ast.parse(new_text)
                except SyntaxError as error:
                    print(f"  skipped: result would not parse ({error})", file=sys.stderr)
                    continue
            path.write_bytes(new_text.encode("utf-8"))

    verb = "updated" if args.write else "need changes"
    print(f"{changed} file(s) {verb}.")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
