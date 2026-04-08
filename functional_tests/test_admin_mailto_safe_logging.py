# test_admin_mailto_safe_logging.py
#!/usr/bin/env python3
"""
Functional test for admin mailto safe logging and telemetry hardening.
Version: 0.240.002
Implemented in: 0.240.002

This test ensures the admin mailto routes use centralized log_event error
handling, return generic client errors, and avoid storing free-form feedback
content in activity logging metadata.
"""

import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_settings.py')
ACTIVITY_LOGGING = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_activity_logging.py')
FIX_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'fixes', 'ADMIN_MAILTO_SAFE_LOGGING_FIX.md')
SEND_FEEDBACK_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'features', 'SEND_FEEDBACK_ADMIN.md')
RELEASE_NOTIFICATIONS_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'features', 'RELEASE_NOTIFICATIONS_REGISTRATION.md')


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_admin_mailto_routes_use_safe_errors_and_telemetry():
    """Ensure admin mailto routes log through log_event and avoid raw exception responses."""
    print('🔍 Validating admin mailto route error handling...')

    backend_content = read_file_text(BACKEND_SETTINGS)

    assert 'current_app.logger.error(' not in backend_content, (
        'Admin mailto routes should not use route-local logger.error calls.'
    )
    assert "return jsonify({'error': f'Failed to prepare feedback email: {str(e)}'}), 500" not in backend_content, (
        'Feedback mailto route must not return raw exception text to the browser.'
    )
    assert "return jsonify({'error': f'Failed to prepare registration email: {str(e)}'}), 500" not in backend_content, (
        'Release notifications route must not return raw exception text to the browser.'
    )
    assert "return jsonify({'error': 'Failed to prepare feedback email'}), 500" in backend_content, (
        'Feedback mailto route should return a generic client-facing error.'
    )
    assert "return jsonify({'error': 'Failed to prepare registration email'}), 500" in backend_content, (
        'Release notifications route should return a generic client-facing error.'
    )
    assert backend_content.count('exceptionTraceback=True') >= 2, (
        'Admin mailto route failures should capture traceback details through log_event.'
    )

    print('✅ Admin mailto route error handling is hardened')


def test_admin_mailto_activity_logging_reduces_sensitive_metadata():
    """Ensure admin mailto activity logging avoids free-form previews and full contact fields."""
    print('🔍 Validating admin mailto activity logging metadata...')

    logging_content = read_file_text(ACTIVITY_LOGGING)

    assert 'def _get_email_domain(' in logging_content, (
        'Activity logging should normalize emails down to domains for mailto metadata.'
    )
    assert 'def _build_contact_metadata(' in logging_content, (
        'Activity logging should centralize reduced contact metadata generation.'
    )
    assert 'details_preview' not in logging_content, (
        'Activity logging must not keep a free-form feedback preview for admin mailto telemetry.'
    )
    assert "'reporter_email': reporter_email" not in logging_content, (
        'Admin feedback activity logging should not persist the full reporter email in metadata.'
    )
    assert "'registrant_email': registrant_email" not in logging_content, (
        'Release notifications activity logging should not persist the full registrant email in metadata.'
    )
    assert "'name_provided': bool((name or '').strip())" in logging_content, (
        'Reduced contact metadata should capture whether a name was provided.'
    )
    assert "'email_domain': _get_email_domain(email)" in logging_content, (
        'Reduced contact metadata should retain only the email domain.'
    )
    assert "'organization_length': len((organization or '').strip())" in logging_content, (
        'Reduced contact metadata should retain organization length rather than the raw organization text.'
    )

    print('✅ Admin mailto activity logging metadata is reduced')


def test_admin_mailto_safe_logging_documentation_exists():
    """Ensure fix and related feature documentation describe the hardening change."""
    print('🔍 Validating admin mailto safe logging documentation...')

    fix_doc_content = read_file_text(FIX_DOC)
    send_feedback_doc_content = read_file_text(SEND_FEEDBACK_DOC)
    release_notifications_doc_content = read_file_text(RELEASE_NOTIFICATIONS_DOC)

    assert 'Fixed/Implemented in version: **0.240.002**' in fix_doc_content, (
        'Fix documentation should reference the current implementation version.'
    )
    assert 'generic error messages' in fix_doc_content.lower() or 'generic error' in fix_doc_content.lower(), (
        'Fix documentation should describe the client-facing error hardening.'
    )
    assert 'preview' in fix_doc_content.lower(), (
        'Fix documentation should describe the telemetry data reduction.'
    )
    assert 'Safe logging updated in version: **0.240.002**' in send_feedback_doc_content, (
        'Send Feedback documentation should note the safe logging update version.'
    )
    assert 'generic error response' in send_feedback_doc_content.lower(), (
        'Send Feedback documentation should mention generic error handling.'
    )
    assert 'Safe logging updated in version: **0.240.002**' in release_notifications_doc_content, (
        'Release notifications documentation should note the safe logging update version.'
    )
    assert 'generic error response' in release_notifications_doc_content.lower(), (
        'Release notifications documentation should mention generic error handling.'
    )

    print('✅ Admin mailto safe logging documentation is present')


if __name__ == '__main__':
    test_admin_mailto_routes_use_safe_errors_and_telemetry()
    print()
    test_admin_mailto_activity_logging_reduces_sensitive_metadata()
    print()
    test_admin_mailto_safe_logging_documentation_exists()
