#!/usr/bin/env python3
"""
Functional test for swagger route PR workflow and parser failure annotations.
Version: 0.240.003
Implemented in: 0.240.003

This test ensures that the pull request workflow and checker script validate
edited Flask route files for @swagger_route(security=get_auth_security())
and report read or parse failures as GitHub Actions annotations.
"""

import os
import subprocess
import sys
import tempfile
import textwrap

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def repo_root():
    """Return the repository root path."""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def read_repo_file(*parts):
    """Read a repository file for assertions."""
    file_path = os.path.join(repo_root(), *parts)
    with open(file_path, 'r', encoding='utf-8') as handle:
        return handle.read()


def run_checker_against_temp_file(file_contents):
    """Run the checker script against a temporary Python file."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file = os.path.join(temp_dir, 'temp_route_file.py')
        if isinstance(file_contents, bytes):
            with open(temp_file, 'wb') as handle:
                handle.write(file_contents)
        else:
            with open(temp_file, 'w', encoding='utf-8') as handle:
                handle.write(file_contents)

        command = [
            sys.executable,
            os.path.join(repo_root(), 'scripts', 'check_swagger_routes.py'),
            temp_file,
        ]
        return subprocess.run(command, capture_output=True, text=True, cwd=repo_root())


def test_workflow_exists_and_targets_pull_requests():
    """Verify the workflow file exists and runs for pull requests."""
    print('🔍 Testing swagger route workflow presence...')

    try:
        content = read_repo_file('.github', 'workflows', 'swagger-route-check.yml')

        required_fragments = [
            'name: Swagger Route Check',
            'pull_request:',
            "application/single_app/**/*.py",
            'scripts/check_swagger_routes.py',
            'tj-actions/changed-files@v46.0.1',
            'python scripts/check_swagger_routes.py $CHANGED_ROUTE_FILES',
        ]

        for fragment in required_fragments:
            if fragment not in content:
                print(f'❌ Missing workflow fragment: {fragment}')
                return False

        print('✅ Swagger route workflow file is present and configured for pull requests')
        return True
    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_checker_accepts_properly_decorated_route():
    """Verify the checker passes when a changed route includes swagger security."""
    print('🔍 Testing swagger route checker success case...')

    valid_route_file = textwrap.dedent(
        """
        from flask import Flask
        from swagger_wrapper import swagger_route, get_auth_security

        app = Flask(__name__)

        @app.route('/api/example', methods=['GET'])
        @swagger_route(security=get_auth_security())
        def example_route():
            return {'ok': True}
        """
    ).strip() + '\n'

    result = run_checker_against_temp_file(valid_route_file)
    if result.returncode != 0:
        print('❌ Checker rejected a valid swagger route file')
        print(result.stdout)
        print(result.stderr)
        return False

    print('✅ Checker accepted a valid swagger route file')
    return True


def test_checker_rejects_missing_swagger_route():
    """Verify the checker fails when a changed route is missing swagger security."""
    print('🔍 Testing swagger route checker failure case...')

    invalid_route_file = textwrap.dedent(
        """
        from flask import Flask

        app = Flask(__name__)

        @app.route('/api/example', methods=['GET'])
        def example_route():
            return {'ok': True}
        """
    ).strip() + '\n'

    result = run_checker_against_temp_file(invalid_route_file)
    if result.returncode == 0:
        print('❌ Checker accepted a route file that is missing swagger security')
        return False

    if 'missing @swagger_route(security=get_auth_security())' not in result.stdout:
        print('❌ Checker failed, but did not report the expected swagger error')
        print(result.stdout)
        print(result.stderr)
        return False

    print('✅ Checker rejected a route file that is missing swagger security')
    return True


def test_checker_reports_syntax_errors_as_annotations():
    """Verify the checker reports syntax errors as GitHub Actions annotations."""
    print('🔍 Testing swagger route checker syntax-error annotation...')

    invalid_python_file = textwrap.dedent(
        """
        from flask import Flask
        from swagger_wrapper import swagger_route, get_auth_security

        app = Flask(__name__)

        @app.route('/api/example', methods=['GET'])
        @swagger_route(security=get_auth_security())
        def broken_route()
            return {'ok': True}
        """
    ).strip() + '\n'

    result = run_checker_against_temp_file(invalid_python_file)
    if result.returncode == 0:
        print('❌ Checker accepted a route file with invalid Python syntax')
        return False

    if 'Unable to parse file for swagger route validation' not in result.stdout:
        print('❌ Checker failed, but did not report a parse annotation')
        print(result.stdout)
        print(result.stderr)
        return False

    if '::error file=' not in result.stdout or ',line=8::' not in result.stdout:
        print('❌ Checker did not emit a GitHub Actions syntax annotation with a line number')
        print(result.stdout)
        print(result.stderr)
        return False

    print('✅ Checker reports syntax errors as GitHub Actions annotations')
    return True


def test_checker_reports_utf8_read_errors_as_annotations():
    """Verify the checker reports UTF-8 read failures as GitHub Actions annotations."""
    print('🔍 Testing swagger route checker UTF-8 read annotation...')

    invalid_utf8_file = b'\xff\xfe\x00route-file'

    result = run_checker_against_temp_file(invalid_utf8_file)
    if result.returncode == 0:
        print('❌ Checker accepted a route file that cannot be decoded as UTF-8')
        return False

    if 'Unable to read file for swagger route validation' not in result.stdout:
        print('❌ Checker failed, but did not report a read annotation')
        print(result.stdout)
        print(result.stderr)
        return False

    if '::error file=' not in result.stdout or ',line=1::' not in result.stdout:
        print('❌ Checker did not emit a GitHub Actions read annotation with a fallback line number')
        print(result.stdout)
        print(result.stderr)
        return False

    print('✅ Checker reports UTF-8 read failures as GitHub Actions annotations')
    return True


if __name__ == '__main__':
    tests = [
        test_workflow_exists_and_targets_pull_requests,
        test_checker_accepts_properly_decorated_route,
        test_checker_rejects_missing_swagger_route,
        test_checker_reports_syntax_errors_as_annotations,
        test_checker_reports_utf8_read_errors_as_annotations,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)