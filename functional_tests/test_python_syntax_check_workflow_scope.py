#!/usr/bin/env python3
"""
Functional test for the Python syntax check workflow file discovery scope.
Version: 0.261.027
Implemented in: 0.261.027

This test ensures that .github/workflows/python-syntax-check.yml compiles every
Python file under application/single_app, including nested packages such as
semantic_kernel_plugins/, instead of only the top level of the directory.
"""

import glob
import os
import re
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

SINGLE_APP_DIR = os.path.join('application', 'single_app')
NESTED_PACKAGE_DIR = os.path.join(SINGLE_APP_DIR, 'semantic_kernel_plugins')


def repo_root():
    """Return the repository root path."""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def read_workflow():
    """Read the python syntax check workflow."""
    with open(os.path.join(repo_root(), '.github', 'workflows', 'python-syntax-check.yml'), 'r', encoding='utf-8') as handle:
        return handle.read()


def test_workflow_discovers_files_recursively():
    """Verify the workflow walks the tree instead of globbing a single level."""
    print('🔍 Testing recursive file discovery in the syntax check workflow...')

    try:
        content = read_workflow()

        if 'for file in *.py;' in content:
            print('❌ Workflow still uses a single-level *.py glob that skips nested packages')
            return False

        if not re.search(r"find\s+\.\s+-type\s+f\s+-name\s+'\*\.py'", content):
            print('❌ Workflow does not discover .py files with a recursive find')
            return False

        if "-not -path '*/__pycache__/*'" not in content:
            print('❌ Workflow does not exclude __pycache__ directories')
            return False

        print('✅ Workflow discovers Python files recursively')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_nested_packages_are_covered():
    """Verify nested packages contain files that a single-level glob would miss."""
    print('🔍 Testing that nested packages are not skipped...')

    try:
        top_level_count = len(glob.glob(os.path.join(repo_root(), SINGLE_APP_DIR, '*.py')))
        recursive_count = len([
            path for path in glob.glob(os.path.join(repo_root(), SINGLE_APP_DIR, '**', '*.py'), recursive=True)
            if '__pycache__' not in path
        ])

        print(f'  Top-level files matched by "*.py": {top_level_count}')
        print(f'  Files matched recursively: {recursive_count}')

        nested_count = len([
            path for path in glob.glob(os.path.join(repo_root(), NESTED_PACKAGE_DIR, '**', '*.py'), recursive=True)
            if '__pycache__' not in path
        ])

        if nested_count == 0:
            print(f'❌ Expected nested Python files under {NESTED_PACKAGE_DIR}')
            return False

        if recursive_count <= top_level_count:
            print('❌ Recursive discovery does not find more files than the single-level glob')
            return False

        print(f'✅ Nested packages contribute {nested_count} file(s) that the old glob skipped')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def find_bash():
    """Return a working bash executable path, or None when bash is unavailable.

    Real Git Bash is preferred over the WSL shim, which resolves on PATH but
    fails when no distribution is installed.
    """
    import shutil

    candidates = [
        r'C:\Program Files\Git\bin\bash.exe',
        r'C:\Program Files\Git\usr\bin\bash.exe',
        shutil.which('bash'),
    ]

    for candidate in candidates:
        if not candidate or not os.path.exists(candidate):
            continue

        try:
            probe = subprocess.run(
                [candidate, '-c', 'echo ok'],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe.returncode == 0 and 'ok' in probe.stdout:
                return candidate
        except Exception:
            continue

    return None


def test_discovery_command_matches_repository_files():
    """Verify the workflow find command returns every repository Python file."""
    print('🔍 Testing the find command output against the repository tree...')

    try:
        bash_path = find_bash()
        if not bash_path:
            print('⏭️  Skipped: no bash executable is available on this machine')
            return True

        expected = sorted([
            os.path.relpath(path, repo_root()).replace('\\', '/')
            for path in glob.glob(os.path.join(repo_root(), SINGLE_APP_DIR, '**', '*.py'), recursive=True)
            if '__pycache__' not in path
        ])

        find_script = (
            "cd application/single_app && "
            "find . -type f -name '*.py' -not -path '*/__pycache__/*' -print0 | sort -z | tr '\\0' '\\n'"
        )

        result = subprocess.run(
            [bash_path, '-c', find_script],
            capture_output=True,
            text=True,
            cwd=repo_root(),
        )

        if result.returncode != 0:
            print('❌ Could not run the find command from the workflow')
            print(result.stderr)
            return False

        discovered = sorted(
            f"{SINGLE_APP_DIR.replace(os.sep, '/')}/{line.strip().lstrip('./').replace(os.sep, '/')}"
            for line in result.stdout.splitlines()
            if line.strip()
        )

        missing = [path for path in expected if path not in discovered]

        if missing:
            print(f'❌ The workflow find command misses {len(missing)} file(s):')
            for path in missing[:10]:
                print(f'  - {path}')
            return False

        print(f'✅ Workflow find command discovers all {len(discovered)} Python file(s)')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_workflow_discovers_files_recursively,
        test_nested_packages_are_covered,
        test_discovery_command_matches_repository_files,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)