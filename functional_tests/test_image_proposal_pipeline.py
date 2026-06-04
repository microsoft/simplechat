#!/usr/bin/env python3
# test_image_proposal_pipeline.py
"""
Functional test for opt-in chat image proposal pipeline.
Version: 0.241.138
Implemented in: 0.241.138

This test ensures the reusable image proposal helpers normalize model-authored
proposal JSON, gate proposal guidance behind image generation settings, and
produce inline fenced simpleimage schemas used by the chat renderer.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_image_generation import (  # noqa: E402
    INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE,
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
    })

    assert proposal['version'] == 1
    assert proposal['visualId'] == 'slide_09_timeline'
    assert proposal['prompt'].startswith('Create a horizontal')
    assert proposal['slideNumber'] == 9
    assert proposal['visualType'] == 'timeline'


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
    assert image_generation_is_enabled({'enable_image_generation': True}) is True
    assert image_generation_is_enabled({'enable_image_generation': False}) is False
    assert user_request_supports_image_proposals('Create a classroom timeline slide deck') is True
    assert user_request_supports_image_proposals('What is the capital of France?') is False


def test_invalid_proposal_rejected():
    """Validate missing prompts are rejected before image generation."""
    try:
        normalize_image_proposal({'title': 'No prompt'})
    except ValueError as exc:
        assert 'prompt is required' in str(exc)
        return True

    raise AssertionError('Expected missing prompt to raise ValueError')


if __name__ == '__main__':
    tests = [
        test_normalize_image_proposal,
        test_image_proposal_guidance_and_gating,
        test_invalid_proposal_rejected,
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
