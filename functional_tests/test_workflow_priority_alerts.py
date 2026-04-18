#!/usr/bin/env python3
# test_workflow_priority_alerts.py
"""
Functional test for workflow priority alerts.
Version: 0.241.036
Implemented in: 0.241.029

This test ensures workflows store an alert priority, workflow runs create
priority-aware notifications, and the global modal plumbing exists for
personal, group, and collaborative deep-link targets.
"""

from pathlib import Path
import importlib
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workflow_priority_alert_contracts():
    config_content = read_text("application/single_app/config.py")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    notifications_content = read_text("application/single_app/functions_notifications.py")
    notifications_route_content = read_text("application/single_app/route_backend_notifications.py")
    workspace_template_content = read_text("application/single_app/templates/workspace.html")
    base_template_content = read_text("application/single_app/templates/base.html")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    notifications_js_content = read_text("application/single_app/static/js/notifications.js")
    feature_doc_content = read_text("docs/explanation/features/WORKFLOW_PRIORITY_ALERTS.md")

    assert 'VERSION = "0.241.036"' in config_content
    assert "WORKFLOW_ALERT_PRIORITIES = {'none', 'low', 'medium', 'high'}" in workflow_store_content
    assert "'alert_priority': alert_priority," in workflow_store_content
    assert 'id="workflow-alert-priority"' in workspace_template_content
    assert 'alert_priority: normalizeText(workflowAlertPrioritySelect?.value).toLowerCase() || "none"' in workflow_js_content
    assert 'window.dispatchEvent(new CustomEvent("workflow-alert-refresh-requested"));' in workflow_js_content
    assert "WORKFLOW_ALERT_NOTIFICATION_TYPE = 'workflow_priority_alert'" in notifications_content
    assert 'def create_workflow_priority_notification(' in notifications_content
    assert 'def get_unread_workflow_priority_notifications(user_id, limit=5):' in notifications_content
    assert '/api/notifications/workflow-alerts' in notifications_route_content
    assert 'create_workflow_priority_notification' in workflow_runner_content
    assert "default_label='Open workflow'" in workflow_runner_content
    assert 'def _summarize_workflow_alert_text(text, max_length=140):' in workflow_runner_content
    assert 'def _select_preferred_workflow_alert_targets(targets):' in workflow_runner_content
    assert 'plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)' in workflow_runner_content
    assert 'g.conversation_id = conversation_id' in workflow_runner_content
    assert "'link_targets': workflow_targets," in workflow_runner_content
    assert 'id="workflowAlertModal"' in base_template_content
    assert 'workflow-alert-type-card' in base_template_content
    assert 'workflow-alert-summary-panel' in base_template_content
    assert 'workflow-alert-refresh-requested' in notifications_js_content
    assert '/api/notifications/workflow-alerts?limit=5' in notifications_js_content
    assert "const workflowAlertModalEl = document.getElementById('workflowAlertModal');" in notifications_js_content
    assert 'function buildWorkflowAlertSummary(text, maxLength = 140)' in notifications_js_content
    assert 'function selectPreferredWorkflowAlertTargets(targets)' in notifications_js_content
    assert "return 'Open workflow';" in notifications_js_content
    assert 'Workflow Priority Alerts' in feature_doc_content


def test_workflow_alert_target_priority_prefers_group_created_conversation():
    workflow_runner = importlib.import_module('functions_workflow_runner')

    selected_targets = workflow_runner._select_preferred_workflow_alert_targets([
        {
            'label': 'Open created conversation',
            'conversation_id': 'personal-001',
            'link_url': '/chats?conversationId=personal-001',
            'link_context': {
                'workspace_type': 'personal',
                'conversation_id': 'personal-001',
                'chat_type': 'personal_single_user',
            },
        },
        {
            'label': 'Open created conversation',
            'conversation_id': 'group-001',
            'link_url': '/chats?conversationId=group-001',
            'link_context': {
                'workspace_type': 'group',
                'group_id': 'group-123',
                'conversation_id': 'group-001',
                'chat_type': 'group_multi_user',
            },
        },
        {
            'label': 'Open workflow',
            'conversation_id': 'workflow-001',
            'link_url': '/chats?conversationId=workflow-001',
            'link_context': {
                'workspace_type': 'personal',
                'conversation_id': 'workflow-001',
            },
        },
    ])

    assert len(selected_targets) == 2
    assert selected_targets[0]['conversation_id'] == 'group-001'
    assert selected_targets[0]['label'] == 'Open created conversation'
    assert selected_targets[1]['label'] == 'Open workflow'


if __name__ == '__main__':
    test_workflow_priority_alert_contracts()
    test_workflow_alert_target_priority_prefers_group_created_conversation()
    print('Workflow priority alert checks passed.')