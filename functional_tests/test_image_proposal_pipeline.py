#!/usr/bin/env python3
# test_image_proposal_pipeline.py
"""
Functional test for opt-in chat image proposal pipeline.
Version: 0.250.064
Implemented in: 0.250.064

This test ensures the reusable image proposal helpers normalize model-authored
proposal JSON, derive approval states from authorized orchestration evidence,
gate proposal guidance behind image generation settings, and produce inline
fenced simpleimage schemas used by the chat renderer.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_image_generation import (  # noqa: E402
    INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE,
    build_image_proposal_approval_review,
    build_image_proposal_guidance_message,
    image_generation_is_enabled,
    normalize_image_proposal,
    user_request_supports_image_proposals,
)


def test_normalize_image_proposal():
    """Validate model proposal payload normalization."""
    proposal = normalize_image_proposal({
        'version': 1,
        'visualId': 'slide 09 timeline!',
        'title': 'Timeline of major events, 1700-1750',
        'description': 'An illustrated timeline showing key early American events.',
        'prompt': 'Create a horizontal illustrated timeline with readable labels.',
        'visualType': 'timeline',
        'slideNumber': '9',
        'context': 'Major events',
        'evidenceIds': ['fact-timeline', 'fact timeline', 'fact-timeline'],
        'sourceSummary': 'Workspace plan and selected image.',
        'missingEvidence': ['Public launch date was not verified.'],
        'referenceImageIds': ['artifact-reference-image'],
    })

    assert proposal['version'] == 1
    assert proposal['visualId'] == 'slide_09_timeline'
    assert proposal['prompt'].startswith('Create a horizontal')
    assert proposal['slideNumber'] == 9
    assert proposal['visualType'] == 'timeline'
    assert proposal['evidenceIds'] == ['fact-timeline', 'fact_timeline']
    assert proposal['sourceSummary'] == 'Workspace plan and selected image.'
    assert proposal['missingEvidence'] == ['Public launch date was not verified.']
    assert proposal['referenceImageIds'] == ['artifact-reference-image']


def test_image_proposal_guidance_and_gating():
    """Validate guidance text and setting gates."""
    guidance = build_image_proposal_guidance_message()

    assert f'```{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}' in guidance
    assert 'The user must approve before generation' in guidance
    assert 'inline at the point where each visual belongs' in guidance
    assert 'immediately after the paragraph, bullet, slide section, or visual suggestion' in guidance
    assert 'zero, one, or multiple images based on value' in guidance
    assert 'Prefer 1 proposal' not in guidance
    assert 'Use up to 4' not in guidance
    assert '"prompt"' in guidance
    assert '"evidenceIds"' in guidance
    assert '"referenceImageIds"' in guidance
    assert image_generation_is_enabled({'enable_image_generation': True}) is True
    assert image_generation_is_enabled({'enable_image_generation': False}) is False
    assert user_request_supports_image_proposals('Create a classroom timeline slide deck') is True
    assert user_request_supports_image_proposals('Draw a landscape') is True
    assert user_request_supports_image_proposals('Draw insights from the SQL data') is False
    assert user_request_supports_image_proposals('What is the capital of France?') is False


def test_invalid_proposal_rejected():
    """Validate missing prompts are rejected before image generation."""
    try:
        normalize_image_proposal({'title': 'No prompt'})
    except ValueError as exc:
        assert 'prompt is required' in str(exc)
        return True

    raise AssertionError('Expected missing prompt to raise ValueError')


def _approval_ledger(status='ready', requirement_status='satisfied', include_fact=True):
    ledger = {
        'version': 1,
        'status': status,
        'requirements': [{
            'id': 'profile_evidence',
            'description': 'Verified profile evidence',
            'required': True,
            'status': requirement_status,
        }],
        'sources': [{
            'id': 'selected_agent',
            'type': 'selected_agent',
            'status': 'succeeded' if requirement_status == 'satisfied' else 'partial',
            'required': True,
            'authorization_status': 'authorized',
        }],
        'facts': [],
        'results': [],
        'citations': [],
        'artifacts': [{
            'id': 'artifact-headshot',
            'type': 'image_reference',
            'name': 'Selected headshot',
            'reference': 'message-headshot',
            'message_id': 'message-headshot',
            'source_ids': ['selected_agent'],
        }],
        'missing_or_failed': [],
    }
    if include_fact:
        ledger['facts'].append({
            'id': 'fact-profile-role',
            'text': 'The profile includes a verified role.',
            'source_ids': ['selected_agent'],
        })
    return ledger


def test_image_proposal_approval_review_ready():
    """Validate source and reference summaries for terminal supported evidence."""
    review = build_image_proposal_approval_review(
        _approval_ledger(),
        {'status': 'succeeded'},
        {
            'evidenceIds': ['fact-profile-role'],
            'referenceImageIds': ['artifact-headshot'],
        },
    )

    assert review['state'] == 'ready'
    assert review['can_approve'] is True
    assert review['requires_confirmation'] is False
    assert review['sources'] == [{
        'id': 'selected_agent',
        'type': 'selected_agent',
        'label': 'Selected Agent',
        'status': 'succeeded',
        'required': True,
        'used': True,
    }]
    assert review['reference_images'] == [{
        'id': 'artifact-headshot',
        'name': 'Selected headshot',
        'reference_id': 'message-headshot',
        'document_id': '',
        'message_id': 'message-headshot',
    }]

    unlinked_review = build_image_proposal_approval_review(
        _approval_ledger(),
        {'status': 'succeeded'},
    )
    assert unlinked_review['sources'][0]['used'] is False
    assert unlinked_review['reference_images'] == []


def test_image_proposal_approval_review_requires_partial_confirmation():
    """Validate terminal partial evidence remains opt-in with an acknowledgment."""
    ledger = _approval_ledger(status='partial', requirement_status='unsatisfied')
    ledger['missing_or_failed'].append({
        'status': 'not_found',
        'message': 'LinkedIn profile was requested but not verified.',
    })

    review = build_image_proposal_approval_review(ledger, {'status': 'partial'})

    assert review['state'] == 'confirmation_required'
    assert review['can_approve'] is True
    assert review['requires_confirmation'] is True
    assert review['missing_evidence'] == [
        'LinkedIn profile was requested but not verified.',
        'Verified profile evidence',
    ]

    completed_review = build_image_proposal_approval_review(
        _approval_ledger(status='completed', requirement_status='unsatisfied'),
        {'status': 'partial'},
    )
    assert completed_review['state'] == 'confirmation_required'


def test_image_proposal_approval_review_blocks_unfinished_or_unsupported_runs():
    """Validate active, cancelled, failed, and supportless evidence cannot proceed."""
    collecting = build_image_proposal_approval_review(
        _approval_ledger(status='collecting', requirement_status='pending'),
        {'status': 'running'},
    )
    cancelled = build_image_proposal_approval_review(
        _approval_ledger(status='cancelled', requirement_status='unsatisfied'),
        {'status': 'cancelled'},
    )
    failed = build_image_proposal_approval_review(
        _approval_ledger(status='failed', requirement_status='unsatisfied'),
        {'status': 'failed'},
    )
    unsupported = build_image_proposal_approval_review(
        _approval_ledger(
            status='partial',
            requirement_status='unsatisfied',
            include_fact=False,
        ) | {'artifacts': []},
        {'status': 'partial'},
    )

    assert collecting['state'] == 'blocked'
    assert cancelled['state'] == 'blocked'
    assert failed['state'] == 'blocked'
    assert unsupported['state'] == 'blocked'
    assert all(
        review['can_approve'] is False
        for review in (collecting, cancelled, failed, unsupported)
    )


if __name__ == '__main__':
    tests = [
        test_normalize_image_proposal,
        test_image_proposal_guidance_and_gating,
        test_invalid_proposal_rejected,
        test_image_proposal_approval_review_ready,
        test_image_proposal_approval_review_requires_partial_confirmation,
        test_image_proposal_approval_review_blocks_unfinished_or_unsupported_runs,
    ]
    results = []
    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print(f'{test.__name__} passed')
            results.append(True)
        except Exception as exc:
            print(f'{test.__name__} failed: {exc}')
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f'Results: {passed}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
