#!/usr/bin/env python3
# test_cosmos_throughput_autoscale_logic.py
"""
Functional test for Cosmos throughput autoscale decision logic.
Version: 0.241.155
Implemented in: 0.241.147; container policy enforcement added in 0.241.153; container metric guardrail added in 0.241.155

This test ensures that Cosmos DB throughput automation scales the shared
SimpleChat database up and down using separate thresholds, cooldowns, and
minimum/maximum RU guardrails without requiring live Azure resources. It also
validates enforced global container policy behavior for current and future
containers.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_cosmos_throughput import (
    calculate_manual_scale_target,
    calculate_scale_decision,
    get_container_policy,
    normalize_cosmos_throughput_settings,
)


def _base_settings(**overrides):
    settings = normalize_cosmos_throughput_settings({
        'cosmos_throughput_autoscale_enabled': True,
        'cosmos_throughput_auto_scale_up_enabled': True,
        'cosmos_throughput_auto_scale_down_enabled': True,
        'cosmos_throughput_scale_up_threshold_percent': 90,
        'cosmos_throughput_scale_down_threshold_percent': 70,
        'cosmos_throughput_scale_up_step_ru': 1000,
        'cosmos_throughput_scale_down_step_ru': 1000,
        'cosmos_throughput_scale_up_cooldown_minutes': 5,
        'cosmos_throughput_scale_down_cooldown_minutes': 20,
        'cosmos_throughput_min_ru': 3000,
        'cosmos_throughput_max_ru': 6000,
        'cosmos_throughput_ignore_min_limit': False,
        'cosmos_throughput_ignore_max_limit': False,
    })
    settings.update(overrides)
    return normalize_cosmos_throughput_settings(settings)


def _status(current_ru, utilization_percent):
    return {
        'throughput': {
            'mode': 'autoscale',
            'current_ru': current_ru,
            'is_scalable': True,
        },
        'metrics': {
            'normalized_ru_percent': utilization_percent,
        },
    }


def _container_status(containers):
    return {
        'throughput': {
            'mode': 'container_or_serverless',
            'current_ru': None,
            'is_scalable': False,
        },
        'metrics': {
            'normalized_ru_percent': max(
                [container.get('normalized_ru_percent') or 0 for container in containers],
                default=None,
            ),
        },
        'containers': containers,
    }


def test_scales_up_when_utilization_is_high():
    """High utilization should scale up by the configured step."""
    decision = calculate_scale_decision(
        _base_settings(),
        _status(4000, 95),
        current_time=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is True
    assert decision['direction'] == 'up'
    assert decision['from_ru'] == 4000
    assert decision['to_ru'] == 5000


def test_scale_up_respects_max_guardrail():
    """Scale up should stop at the configured maximum RU/s unless ignored."""
    decision = calculate_scale_decision(
        _base_settings(),
        _status(6000, 99),
        current_time=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is False
    assert decision['reason'] == 'max_limit_reached'


def test_scale_down_respects_min_guardrail():
    """Scale down should stop at the configured minimum RU/s unless ignored."""
    decision = calculate_scale_decision(
        _base_settings(),
        _status(3000, 20),
        current_time=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is False
    assert decision['reason'] == 'min_limit_reached'


def test_scale_down_uses_separate_cooldown():
    """Scale down should use the slower configured cooldown independent of scale up."""
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    decision = calculate_scale_decision(
        _base_settings(cosmos_throughput_last_scale_down_at=(now - timedelta(minutes=10)).isoformat()),
        _status(5000, 20),
        current_time=now,
    )

    assert decision['should_scale'] is False
    assert decision['reason'] == 'scale_down_cooldown'


def test_ignored_limits_allow_scale_beyond_guardrails():
    """Ignore toggles should allow scaling beyond saved min and max guardrails."""
    up_decision = calculate_scale_decision(
        _base_settings(cosmos_throughput_ignore_max_limit=True),
        _status(6000, 95),
        current_time=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    down_decision = calculate_scale_decision(
        _base_settings(cosmos_throughput_ignore_min_limit=True),
        _status(3000, 20),
        current_time=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    assert up_decision['should_scale'] is True
    assert up_decision['to_ru'] == 7000
    assert down_decision['should_scale'] is True
    assert down_decision['to_ru'] == 2000


def test_container_targeted_scale_up_when_database_throughput_missing():
    """When database throughput is absent, the hottest dedicated container should scale."""
    settings = _base_settings(cosmos_throughput_container_policies={
        'messages': {
            'scale_up_threshold_percent': 80,
            'scale_up_step_ru': 2000,
            'max_ru': 8000,
        },
        'settings': {
            'enabled': False,
        },
    })
    decision = calculate_scale_decision(
        settings,
        _container_status([
            {
                'container_name': 'messages',
                'mode': 'autoscale',
                'current_ru': 4000,
                'is_scalable': True,
                'normalized_ru_percent': 95,
                'policy': settings['cosmos_throughput_container_policies']['messages'],
            },
            {
                'container_name': 'settings',
                'mode': 'autoscale',
                'current_ru': 4000,
                'is_scalable': True,
                'normalized_ru_percent': 99,
                'policy': settings['cosmos_throughput_container_policies']['settings'],
            },
        ]),
        current_time=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is True
    assert decision['scope'] == 'container'
    assert decision['container_name'] == 'messages'
    assert decision['direction'] == 'up'
    assert decision['from_ru'] == 4000
    assert decision['to_ru'] == 6000


def test_container_targeted_scaling_waits_for_per_container_metrics():
    """Container autoscale should not use aggregate utilization for rows."""
    decision = calculate_scale_decision(
        _base_settings(),
        {
            'throughput': {
                'mode': 'container_or_serverless',
                'current_ru': None,
                'is_scalable': False,
            },
            'metrics': {
                'normalized_ru_percent': 95,
            },
            'containers': [
                {
                    'container_name': 'messages',
                    'mode': 'autoscale',
                    'current_ru': 4000,
                    'is_scalable': True,
                    'normalized_ru_percent': None,
                    'policy': {},
                },
            ],
        },
        current_time=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is False
    assert decision['reason'] == 'container_metrics_unavailable'
    assert decision['scalable_container_count'] == 1


def test_container_manual_scale_uses_container_policy():
    """Manual container scale should use the selected container's policy values."""
    settings = _base_settings(cosmos_throughput_container_policies={
        'messages': {
            'scale_down_step_ru': 2000,
            'min_ru': 2000,
        },
    })
    target_ru = calculate_manual_scale_target(
        settings,
        _container_status([
            {
                'container_name': 'messages',
                'mode': 'autoscale',
                'current_ru': 5000,
                'is_scalable': True,
                'normalized_ru_percent': 20,
                'policy': settings['cosmos_throughput_container_policies']['messages'],
            },
        ]),
        'down',
        container_name='messages',
    )

    assert target_ru == 3000


def test_enforced_global_container_policy_overrides_saved_container_policy():
    """Enforcement should make current and future containers use global policy values."""
    settings = _base_settings(
        cosmos_throughput_scale_up_threshold_percent=85,
        cosmos_throughput_scale_down_threshold_percent=55,
        cosmos_throughput_scale_up_step_ru=3000,
        cosmos_throughput_scale_down_step_ru=2000,
        cosmos_throughput_min_ru=3000,
        cosmos_throughput_max_ru=12000,
        cosmos_throughput_enforce_container_defaults=True,
        cosmos_throughput_container_policies={
            'messages': {
                'enabled': False,
                'scale_up_threshold_percent': 99,
                'scale_up_step_ru': 1000,
                'last_scale_up_at': '2026-06-05T10:00:00+00:00',
            }
        },
    )

    existing_policy = get_container_policy(settings, 'messages')
    future_policy = get_container_policy(settings, 'new_container')

    assert existing_policy['enabled'] is True
    assert existing_policy['scale_up_threshold_percent'] == 85
    assert existing_policy['scale_down_threshold_percent'] == 55
    assert existing_policy['scale_up_step_ru'] == 3000
    assert existing_policy['scale_down_step_ru'] == 2000
    assert existing_policy['min_ru'] == 3000
    assert existing_policy['max_ru'] == 12000
    assert existing_policy['last_scale_up_at'] == '2026-06-05T10:00:00+00:00'
    assert future_policy['scale_up_threshold_percent'] == 85
    assert future_policy['container_name'] == 'new_container'


if __name__ == "__main__":
    tests = [
        test_scales_up_when_utilization_is_high,
        test_scale_up_respects_max_guardrail,
        test_scale_down_respects_min_guardrail,
        test_scale_down_uses_separate_cooldown,
        test_ignored_limits_allow_scale_beyond_guardrails,
        test_container_targeted_scale_up_when_database_throughput_missing,
        test_container_targeted_scaling_waits_for_per_container_metrics,
        test_container_manual_scale_uses_container_policy,
        test_enforced_global_container_policy_overrides_saved_container_policy,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
