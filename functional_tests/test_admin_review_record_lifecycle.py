# test_admin_review_record_lifecycle.py
#!/usr/bin/env python3
"""
Functional test for admin review record lifecycle management.
Version: 0.250.075
Implemented in: 0.250.075

This test ensures feedback and safety records support active/archived filtering,
non-sensitive activity audits, protected lifecycle routes, and pending safety
remediation deletion safeguards.
"""

import importlib.util
import sys
import types
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / 'application' / 'single_app'
LIFECYCLE_PATH = APP_DIR / 'functions_review_lifecycle.py'
FEEDBACK_ROUTE_PATH = APP_DIR / 'route_backend_feedback.py'
SAFETY_ROUTE_PATH = APP_DIR / 'route_backend_safety.py'


def _load_lifecycle_module(activity_logger):
    fake_activity_module = types.ModuleType('functions_activity_logging')
    fake_activity_module.log_general_admin_action = activity_logger
    previous_module = sys.modules.get('functions_activity_logging')
    sys.modules['functions_activity_logging'] = fake_activity_module
    try:
        spec = importlib.util.spec_from_file_location(
            'test_functions_review_lifecycle',
            LIFECYCLE_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_module is None:
            sys.modules.pop('functions_activity_logging', None)
        else:
            sys.modules['functions_activity_logging'] = previous_module


def test_archive_metadata_query_filters_and_audit_payload():
    """Lifecycle helpers should preserve legacy active records and audit IDs only."""
    captured_audits = []

    def capture_audit(**kwargs):
        captured_audits.append(kwargs)
        return True

    lifecycle = _load_lifecycle_module(capture_audit)
    active_clauses = []
    archived_clauses = []
    lifecycle.append_archive_query_filter(active_clauses, 'active')
    lifecycle.append_archive_query_filter(archived_clauses, 'archived')

    assert 'NOT IS_DEFINED(c.is_archived)' in active_clauses[0]
    assert 'c.is_archived = true' in archived_clauses[0]

    item = {
        'id': 'feedback-1',
        'userId': 'user-1',
        'conversationId': 'conversation-1',
        'messageId': 'message-1',
        'prompt': 'Sensitive prompt content must not enter the audit.',
    }
    lifecycle.apply_archive_state(item, True, 'admin-1')
    metadata = lifecycle.serialize_archive_metadata(item)
    assert metadata['isArchived'] is True
    assert metadata['archivedBy'] == 'admin-1'
    assert metadata['archivedAt']

    assert lifecycle.log_review_lifecycle_action(
        'feedback',
        'archive',
        item,
        {'id': 'admin-1', 'email': 'admin@example.com'},
        was_archived=False,
    )
    audit = captured_audits[0]
    assert audit['action'] == 'feedback_archived'
    assert audit['additional_context']['record_id'] == 'feedback-1'
    assert audit['additional_context']['was_archived'] is False
    assert 'prompt' not in audit['additional_context']


def test_feedback_and_safety_route_contracts():
    """Admin lifecycle routes should keep auth gates and active-only user history."""
    feedback_source = FEEDBACK_ROUTE_PATH.read_text(encoding='utf-8')
    safety_source = SAFETY_ROUTE_PATH.read_text(encoding='utf-8')

    feedback_markers = [
        '@bp.route("/feedback/review/<feedbackId>/archive", methods=["PATCH"])',
        '@bp.route("/feedback/review/<feedbackId>", methods=["DELETE"])',
        'def feedback_review_archive(feedbackId):',
        'def feedback_review_delete(feedbackId):',
        '@feedback_admin_required',
        "archive_state='active'",
        'log_review_lifecycle_action(',
        "'audit_warning'",
    ]
    safety_markers = [
        "@bp.route('/api/safety/logs/<string:log_id>/archive', methods=['PATCH'])",
        "@bp.route('/api/safety/logs/<string:log_id>', methods=['DELETE'])",
        'def archive_safety_log(log_id):',
        'def delete_safety_log(log_id):',
        '@safety_violation_admin_required',
        "archive_state='active'",
        "action_request_status') or '').strip().lower() == 'pending'",
        'log_review_lifecycle_action(',
        "'audit_warning'",
    ]

    for marker in feedback_markers:
        assert marker in feedback_source, f'Missing feedback lifecycle marker: {marker}'
    for marker in safety_markers:
        assert marker in safety_source, f'Missing safety lifecycle marker: {marker}'

    assert feedback_source.count('@swagger_route(security=get_auth_security())') == feedback_source.count('@bp.route(')
    assert safety_source.count('@swagger_route(security=get_auth_security())') == safety_source.count('@bp.route(')


if __name__ == '__main__':
    test_archive_metadata_query_filters_and_audit_payload()
    test_feedback_and_safety_route_contracts()
    raise SystemExit(0)
