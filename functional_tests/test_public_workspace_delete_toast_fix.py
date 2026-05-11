# test_public_workspace_delete_toast_fix.py
"""
Functional test for public workspace delete toast fix.
Version: 0.240.056
Implemented in: 0.240.056

This test ensures public workspace document delete failures use the shared
Bootstrap toast helper instead of a blocking browser alert.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_WORKSPACE_JS = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'public' / 'public_workspace.js'
PUBLIC_WORKSPACE_UTILITY_JS = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'public' / 'public_workspace_utility.js'


def read_text(path):
    return path.read_text(encoding='utf-8')


def test_public_workspace_delete_failures_use_toast_helper():
    """Validate that public workspace delete failures use the toast helper."""
    workspace_content = read_text(PUBLIC_WORKSPACE_JS)
    utility_content = read_text(PUBLIC_WORKSPACE_UTILITY_JS)

    assert 'function showPublicWorkspaceToast(message, type = \'info\', duration = 5000)' in utility_content, (
        'Expected a shared public workspace toast helper in the utility script.'
    )
    assert "document.getElementById('toast-container')" in utility_content, (
        'Expected the public workspace toast helper to use the shared toast container.'
    )
    assert "showPublicWorkspaceToast(`Error deleting: ${e.error || e.message}`, 'danger');" in workspace_content, (
        'Expected single-document delete failures to use the shared toast helper.'
    )
    assert 'alert(`Error deleting: ${e.error || e.message}`);' not in workspace_content, (
        'Did not expect single-document delete failures to use browser alerts.'
    )
    assert 'showPublicWorkspaceToast(`Deleted ${successful} document(s). ${failed} failed to delete.`, toastType);' in workspace_content, (
        'Expected bulk delete partial failures to use the shared toast helper.'
    )
    assert 'alert(`Deleted ${successful} document(s). ${failed} failed to delete.`);' not in workspace_content, (
        'Did not expect bulk delete partial failures to use browser alerts.'
    )

    print('✅ Public workspace delete failure toast helper verified.')


if __name__ == '__main__':
    test_public_workspace_delete_failures_use_toast_helper()
    sys.exit(0)