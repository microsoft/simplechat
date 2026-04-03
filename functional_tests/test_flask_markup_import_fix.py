# test_flask_markup_import_fix.py
#!/usr/bin/env python3
"""
Functional test for Flask 3 Markup import compatibility.
Version: 0.240.016
Implemented in: 0.240.016

This test ensures config.py imports Markup from markupsafe instead of flask so
the application can start correctly on Flask 3.x.
"""

import ast
import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_FILE = os.path.join(REPO_ROOT, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'fixes', 'FLASK_31_MARKUP_IMPORT_FIX.md')


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def get_imported_names(module_ast, module_name):
    imported_names = []

    for node in ast.walk(module_ast):
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            imported_names.extend(alias.name for alias in node.names)

    return imported_names


def test_config_uses_markupsafe_markup_for_flask_3():
    """Ensure config.py imports Markup from markupsafe instead of flask."""
    print('🔍 Validating Flask 3 Markup import compatibility...')

    config_content = read_file_text(CONFIG_FILE)
    config_ast = ast.parse(config_content, filename=CONFIG_FILE)
    flask_imports = get_imported_names(config_ast, 'flask')
    markupsafe_imports = get_imported_names(config_ast, 'markupsafe')

    assert 'Markup' not in flask_imports, (
        'config.py must not import Markup from flask on Flask 3.x.'
    )
    assert 'Markup' in markupsafe_imports, (
        'config.py should import Markup from markupsafe for Flask 3.x compatibility.'
    )

    print('✅ config.py uses the supported Markup import path')


def test_flask_markup_fix_documentation_exists():
    """Ensure the fix documentation records the Flask 3 compatibility change."""
    print('🔍 Validating Flask 3 Markup fix documentation...')

    fix_doc_content = read_file_text(FIX_DOC)

    assert 'Fixed/Implemented in version: **0.240.016**' in fix_doc_content, (
        'Fix documentation should reference the current implementation version.'
    )
    assert 'ImportError' in fix_doc_content, (
        'Fix documentation should describe the startup import failure.'
    )
    assert 'markupsafe' in fix_doc_content.lower(), (
        'Fix documentation should mention the markupsafe import path.'
    )
    assert 'Flask 3' in fix_doc_content, (
        'Fix documentation should explicitly call out the Flask 3 compatibility issue.'
    )

    print('✅ Flask 3 Markup fix documentation is present')


if __name__ == '__main__':
    test_config_uses_markupsafe_markup_for_flask_3()
    print()
    test_flask_markup_fix_documentation_exists()