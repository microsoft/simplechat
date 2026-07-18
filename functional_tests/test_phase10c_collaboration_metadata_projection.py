#!/usr/bin/env python3
# test_phase10c_collaboration_metadata_projection.py
"""
Functional test for Phase 10C collaboration metadata projection.
Version: 0.250.076
Implemented in: 0.250.076

This test ensures contextual-goal and clarification authorization lineage never
enters collaboration storage or collaborator-facing message payloads.
"""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from collaboration_models import (  # noqa: E402
    build_collaboration_message_doc_from_legacy,
)
from functions_collaboration import (  # noqa: E402
    build_collaboration_message_metadata_payload,
    serialize_collaboration_message,
)


PRIVATE_VALUES = (
    'private-source-message-id',
    'private-content-hash',
    'private internal contextual query',
    'private external query',
    'private-response-hash',
    'private trusted resume message',
    'private-clarification-id',
    'private-parent-run',
    'private-child-run',
)


def _private_metadata():
    return {
        'capability_proposal': {
            'proposal_id': 'safe-proposal-id',
            'prior_goal_included': True,
            'goal_source_count': 2,
            'goal_display_summary': 'Earlier public-record request',
            '_approved_user_turn_goal': {
                'source_user_message_ids': ['private-source-message-id'],
                'source_turn_lineage': [{
                    'message_id': 'private-source-message-id',
                    'content_hash': 'private-content-hash',
                }],
                'contextual_query': 'private internal contextual query',
                'external_query': 'private external query',
            },
        },
        'capability_resume_request': {
            'message': 'private trusted resume message',
        },
        'chat_clarification': {
            'version': 1,
            'clarification_id': 'private-clarification-id',
            'parent_run_id': 'private-parent-run',
            'code': 'jurisdiction_required',
            'question': 'Which jurisdiction applies?',
            'status': 'resolving',
            'options': ['Virginia'],
            '_source_user_message_id': 'private-source-message-id',
            '_response_hash': 'private-response-hash',
            'child_run_id': 'private-child-run',
        },
        'clarification_response': {
            'version': 1,
            'code': 'jurisdiction_required',
            'status': 'resolved',
            'response_mode': 'option',
            'parent_run_id': 'private-parent-run',
            'child_run_id': 'private-child-run',
            '_clarification_id': 'private-clarification-id',
        },
    }


def _assert_projected(payload):
    serialized = json.dumps(payload, sort_keys=True)
    for private_value in PRIVATE_VALUES:
        assert private_value not in serialized
    assert '_approved_user_turn_goal' not in serialized
    assert 'capability_resume_request' not in serialized
    assert payload['capability_proposal']['prior_goal_included'] is True
    assert payload['chat_clarification']['code'] == 'jurisdiction_required'
    assert payload['chat_clarification']['question'] == (
        'Which jurisdiction applies?'
    )
    assert payload['clarification_response'] == {
        'version': 1,
        'code': 'jurisdiction_required',
        'status': 'resolved',
        'response_mode': 'option',
        'idempotent': False,
    }


def test_legacy_conversion_strips_private_contextual_metadata_before_storage():
    converted = build_collaboration_message_doc_from_legacy(
        conversation_id='collaboration-1',
        legacy_message={
            'id': 'legacy-assistant-1',
            'conversation_id': 'personal-1',
            'role': 'assistant',
            'content': 'Choose how to continue.',
            'timestamp': '2026-07-17T12:00:00+00:00',
            'metadata': _private_metadata(),
        },
        default_sender_user={
            'userId': 'owner-1',
            'displayName': 'Owner',
            'email': 'owner@example.com',
        },
    )

    _assert_projected(converted['metadata'])


def test_collaboration_serializers_project_existing_private_rows():
    message = {
        'id': 'collaboration-message-1',
        'conversation_id': 'collaboration-1',
        'role': 'assistant',
        'message_kind': 'assistant_response',
        'content': 'Choose how to continue.',
        'timestamp': '2026-07-17T12:00:00+00:00',
        'metadata': {
            **_private_metadata(),
            'sender': {
                'user_id': 'assistant',
                'display_name': 'AI',
                'email': '',
            },
        },
    }
    serialized = serialize_collaboration_message(message)
    _assert_projected(serialized['metadata'])

    metadata_payload = build_collaboration_message_metadata_payload(
        message,
        {
            'id': 'collaboration-1',
            'title': 'Shared conversation',
            'conversation_kind': 'collaborative',
            'chat_type': 'personal_multi_user',
            'participant_count': 2,
            'participants': [],
        },
    )
    _assert_projected(metadata_payload['metadata'])
