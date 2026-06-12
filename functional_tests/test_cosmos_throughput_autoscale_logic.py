#!/usr/bin/env python3
# test_cosmos_throughput_autoscale_logic.py
"""
Functional test for Cosmos throughput autoscale decision logic.
Version: 0.241.199
Implemented in: 0.241.147; container policy enforcement added in 0.241.153; container metric guardrail added in 0.241.155; manual-to-autoscale conversion added in 0.241.159; migrateToAutoscale ARM action fix added in 0.241.160; save validation added in 0.241.161; access validation added in 0.241.162
Enhanced in: 0.241.183 with detailed access validation diagnostics for partial Azure permission failures.
Enhanced in: 0.241.184 with neutral container-targeted throughput status language.
Enhanced in: 0.241.194 with dedicated container scale-up-to-max coverage when mixed database and container throughput exist.
Enhanced in: 0.241.199 with SimpleChat's 10,000 RU/s scaling support ceiling and portal-managed monitoring coverage.

This test ensures that Cosmos DB throughput automation scales the shared
SimpleChat database up and down using separate thresholds, cooldowns, and
minimum/maximum RU guardrails without requiring live Azure resources. It also
validates enforced global container policy behavior for current and future
containers, including optional conversion from manual throughput to native
Cosmos autoscale throughput.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import functions_cosmos_throughput as cosmos_throughput

from functions_cosmos_throughput import (
    CosmosThroughputError,
    _build_throughput_payload,
    build_cosmos_throughput_access_validation,
    calculate_manual_scale_target,
    calculate_scale_decision,
    get_container_policy,
    get_cosmos_throughput_status,
    normalize_cosmos_throughput_settings,
    validate_cosmos_throughput_policy_settings,
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


def test_scale_up_reaches_max_guardrail_from_previous_step():
    """Scale up should move from one step below the configured maximum to the maximum."""
    decision = calculate_scale_decision(
        _base_settings(
            cosmos_throughput_scale_up_threshold_percent=70,
            cosmos_throughput_scale_down_threshold_percent=50,
            cosmos_throughput_min_ru=1000,
            cosmos_throughput_max_ru=10000,
        ),
        _status(9000, 75),
        current_time=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is True
    assert decision['direction'] == 'up'
    assert decision['from_ru'] == 9000
    assert decision['to_ru'] == 10000


def test_scale_up_at_simplechat_limit_becomes_portal_managed():
    """At 10,000 RU/s, scale-up pressure should inform admins to use the portal."""
    decision = calculate_scale_decision(
        _base_settings(
            cosmos_throughput_scale_up_threshold_percent=70,
            cosmos_throughput_scale_down_threshold_percent=50,
            cosmos_throughput_ignore_max_limit=True,
        ),
        _status(10000, 95),
        current_time=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is False
    assert decision['reason'] == 'portal_managed_throughput'
    assert decision['from_ru'] == 10000
    assert decision['simplechat_max_ru'] == cosmos_throughput.COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU
    assert 'Azure portal' in decision['message']


def test_database_above_simplechat_limit_is_monitor_only():
    """Database throughput above 10,000 RU/s should not be changed by SimpleChat."""
    decision = calculate_scale_decision(
        _base_settings(
            cosmos_throughput_scale_up_threshold_percent=70,
            cosmos_throughput_scale_down_threshold_percent=50,
            cosmos_throughput_ignore_min_limit=True,
            cosmos_throughput_ignore_max_limit=True,
        ),
        _status(11000, 25),
        current_time=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is False
    assert decision['reason'] == 'portal_managed_throughput'
    assert decision['scope'] == 'database'
    assert decision['from_ru'] == 11000
    assert '4 to 6 hours' in decision['message']


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


def test_dedicated_container_scale_up_to_max_when_database_throughput_exists():
    """A hot dedicated container should scale to its max even when database throughput is also present."""
    settings = _base_settings(
        cosmos_throughput_scale_up_threshold_percent=70,
        cosmos_throughput_scale_down_threshold_percent=50,
        cosmos_throughput_min_ru=1000,
        cosmos_throughput_max_ru=10000,
        cosmos_throughput_container_policies={
            'messages': {
                'scale_up_threshold_percent': 70,
                'scale_down_threshold_percent': 50,
                'scale_up_step_ru': 1000,
                'min_ru': 1000,
                'max_ru': 10000,
            },
        },
    )
    decision = calculate_scale_decision(
        settings,
        {
            'throughput': {
                'mode': 'autoscale',
                'current_ru': 4000,
                'is_scalable': True,
            },
            'metrics': {
                'normalized_ru_percent': 75,
            },
            'containers': [
                {
                    'container_name': 'messages',
                    'mode': 'autoscale',
                    'current_ru': 9000,
                    'is_scalable': True,
                    'normalized_ru_percent': 75,
                    'policy': settings['cosmos_throughput_container_policies']['messages'],
                },
            ],
        },
        current_time=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is True
    assert decision['scope'] == 'container'
    assert decision['container_name'] == 'messages'
    assert decision['direction'] == 'up'
    assert decision['from_ru'] == 9000
    assert decision['to_ru'] == 10000


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


def test_container_above_simplechat_limit_is_monitor_only():
    """Dedicated containers above 10,000 RU/s should remain visible but not scaled."""
    settings = _base_settings(cosmos_throughput_container_policies={
        'messages': {
            'scale_up_threshold_percent': 70,
            'scale_down_threshold_percent': 50,
            'scale_up_step_ru': 1000,
            'scale_down_step_ru': 1000,
            'max_ru': 200000,
            'ignore_max_limit': True,
            'ignore_min_limit': True,
        },
    })
    decision = calculate_scale_decision(
        settings,
        _container_status([
            {
                'container_name': 'messages',
                'mode': 'autoscale',
                'current_ru': 20000,
                'is_scalable': True,
                'normalized_ru_percent': 95,
                'policy': settings['cosmos_throughput_container_policies']['messages'],
            },
        ]),
        current_time=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is False
    assert decision['reason'] == 'portal_managed_throughput'
    assert decision['scope'] == 'container'
    assert decision['container_name'] == 'messages'
    assert decision['from_ru'] == 20000
    assert 'Azure portal' in decision['message']


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


def test_manual_scale_rejects_portal_managed_throughput():
    """Manual admin scale buttons should not change throughput above 10,000 RU/s."""
    try:
        calculate_manual_scale_target(
            _base_settings(cosmos_throughput_ignore_min_limit=True),
            _status(11000, 20),
            'down',
        )
    except CosmosThroughputError as exc:
        assert 'Azure portal' in str(exc)
    else:
        raise AssertionError('Expected portal-managed throughput to reject manual scale down.')


def test_normalization_clamps_simplechat_guardrails_to_10000():
    """Saved policies over 10,000 RU/s should normalize to SimpleChat's support ceiling."""
    settings = normalize_cosmos_throughput_settings({
        'cosmos_throughput_max_ru': 200000,
        'cosmos_throughput_min_ru': 12000,
        'cosmos_throughput_container_policies': {
            'messages': {
                'min_ru': 11000,
                'max_ru': 200000,
            },
        },
    })

    assert settings['cosmos_throughput_min_ru'] == 10000
    assert settings['cosmos_throughput_max_ru'] == 10000
    assert settings['cosmos_throughput_container_policies']['messages']['min_ru'] == 10000
    assert settings['cosmos_throughput_container_policies']['messages']['max_ru'] == 10000


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
    assert existing_policy['max_ru'] == 10000
    assert existing_policy['last_scale_up_at'] == '2026-06-05T10:00:00+00:00'
    assert future_policy['scale_up_threshold_percent'] == 85
    assert future_policy['container_name'] == 'new_container'


def test_manual_database_conversion_requires_explicit_policy():
    """Manual database throughput should only convert when the admin opts in."""
    disabled_decision = calculate_scale_decision(
        _base_settings(cosmos_throughput_convert_manual_to_autoscale_enabled=False),
        {
            'throughput': {
                'mode': 'manual',
                'current_ru': 1400,
                'is_scalable': True,
            },
            'metrics': {
                'normalized_ru_percent': None,
            },
        },
        current_time=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    enabled_decision = calculate_scale_decision(
        _base_settings(cosmos_throughput_convert_manual_to_autoscale_enabled=True),
        {
            'throughput': {
                'mode': 'manual',
                'current_ru': 1400,
                'is_scalable': True,
            },
            'metrics': {
                'normalized_ru_percent': None,
            },
        },
        current_time=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )

    assert disabled_decision['should_scale'] is False
    assert disabled_decision['reason'] == 'missing_utilization_metric'
    assert enabled_decision['should_scale'] is True
    assert enabled_decision['direction'] == 'convert_to_autoscale'
    assert enabled_decision['target_mode'] == 'autoscale'
    assert enabled_decision['from_ru'] == 1400
    assert enabled_decision['to_ru'] == 3000


def test_global_container_policy_converts_manual_containers_before_scaling():
    """Global policy enforcement should apply native autoscale conversion to manual containers."""
    settings = _base_settings(
        cosmos_throughput_convert_manual_to_autoscale_enabled=True,
        cosmos_throughput_enforce_container_defaults=True,
        cosmos_throughput_min_ru=3000,
        cosmos_throughput_max_ru=12000,
    )
    decision = calculate_scale_decision(
        settings,
        _container_status([
            {
                'container_name': 'messages',
                'mode': 'manual',
                'current_ru': 4500,
                'is_scalable': True,
                'normalized_ru_percent': None,
                'policy': {},
            },
        ]),
        current_time=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )

    assert decision['should_scale'] is True
    assert decision['scope'] == 'container'
    assert decision['container_name'] == 'messages'
    assert decision['direction'] == 'convert_to_autoscale'
    assert decision['target_mode'] == 'autoscale'
    assert decision['from_ru'] == 4500
    assert decision['to_ru'] == 5000


def test_manual_to_autoscale_payload_uses_autoscale_settings():
    """Conversion writes the Cosmos autoscaleSettings payload rather than manual throughput."""
    payload = _build_throughput_payload('autoscale', 5000)

    assert payload['properties']['resource']['autoscaleSettings']['maxThroughput'] == 5000
    assert 'throughput' not in payload['properties']['resource']


def test_manual_to_autoscale_update_uses_migration_action():
    """Manual offers must use Cosmos migrateToAutoscale before autoscale settings can be updated."""
    original_arm_request = cosmos_throughput._arm_request
    calls = []
    throughput_id = '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/acct/sqlDatabases/SimpleChat/containers/messages/throughputSettings/default'

    def fake_arm_request(method, resource_path, payload=None, **kwargs):
        calls.append({
            'method': method,
            'resource_path': resource_path,
            'payload': payload,
        })
        if method == 'GET':
            return {
                'properties': {
                    'resource': {
                        'autoscaleSettings': {
                            'maxThroughput': 5000,
                        },
                    },
                },
            }
        return {}

    try:
        cosmos_throughput._arm_request = fake_arm_request
        result = cosmos_throughput._apply_throughput_update(
            {
                'scope': 'container',
                'container_name': 'messages',
                'mode': 'manual',
                'current_ru': 4500,
                'is_scalable': True,
                'resource_ids': {'throughput_id': throughput_id},
            },
            5000,
            initiated_by='test',
            reason='manual_to_autoscale_conversion',
            target_mode='autoscale',
        )
    finally:
        cosmos_throughput._arm_request = original_arm_request

    assert calls[0]['method'] == 'POST'
    assert calls[0]['resource_path'] == f'{throughput_id}/migrateToAutoscale'
    assert calls[0]['payload'] is None
    assert not any(call['method'] == 'PUT' for call in calls)
    assert result['from_mode'] == 'manual'
    assert result['to_mode'] == 'autoscale'
    assert result['to_ru'] == 5000


def test_policy_validation_rejects_invalid_global_thresholds_and_intervals():
    """Invalid global throughput policy values should block Admin Settings saves."""
    errors = validate_cosmos_throughput_policy_settings({
        **_base_settings(),
        'cosmos_throughput_metrics_window_minutes': 10,
        'cosmos_throughput_scale_up_threshold_percent': 60,
        'cosmos_throughput_scale_down_threshold_percent': 70,
        'cosmos_throughput_scale_up_cooldown_minutes': 5,
        'cosmos_throughput_scale_down_cooldown_minutes': 9,
    })

    assert any('Scale Up At must be higher than Scale Down At' in error for error in errors)
    assert any('Scale Up Interval must be greater than or equal to the Metrics Window' in error for error in errors)
    assert any('Scale Down Interval must be greater than or equal to the Metrics Window' in error for error in errors)


def test_policy_validation_rejects_invalid_container_policy_values():
    """Invalid enabled container policies should block Admin Settings saves."""
    errors = validate_cosmos_throughput_policy_settings({
        **_base_settings(),
        'cosmos_throughput_metrics_window_minutes': 10,
        'cosmos_throughput_enforce_container_defaults': False,
        'cosmos_throughput_container_policies': {
            'messages': {
                'container_name': 'messages',
                'enabled': True,
                'scale_up_threshold_percent': 50,
                'scale_down_threshold_percent': 70,
                'scale_up_cooldown_minutes': 5,
                'scale_down_cooldown_minutes': 8,
            },
        },
    })

    assert any("Container 'messages' policy" in error for error in errors)
    assert any('Scale Up At must be higher than Scale Down At' in error for error in errors)
    assert any('Scale Up Interval must be greater than or equal to the Metrics Window' in error for error in errors)
    assert any('Scale Down Interval must be greater than or equal to the Metrics Window' in error for error in errors)


def test_access_validation_reports_successful_cosmos_checks():
    """Access validation should pass when configuration, throughput, containers, and metrics are available."""
    validation = build_cosmos_throughput_access_validation({
        'configured': True,
        'throughput': {
            'is_scalable': True,
            'mode': 'autoscale',
            'current_ru': 5000,
        },
        'containers': [
            {
                'container_name': 'messages',
                'is_scalable': False,
            },
        ],
        'metrics': {
            'normalized_ru_percent': 42,
        },
        'metric_error': '',
        'container_error': '',
    })

    assert validation['success'] is True
    assert validation['variant'] == 'success'
    assert all(check['passed'] for check in validation['checks'])


def test_access_validation_reports_portal_managed_monitoring_as_successful_read():
    """Portal-managed high throughput should validate as readable monitoring, not an access failure."""
    validation = build_cosmos_throughput_access_validation({
        'configured': True,
        'throughput': {
            'is_scalable': True,
            'mode': 'autoscale',
            'current_ru': 20000,
            'portal_managed_scaling_required': True,
        },
        'containers': [],
        'metrics': {
            'normalized_ru_percent': 82,
        },
        'metric_error': '',
        'container_error': '',
    })

    throughput_check = next(
        check for check in validation['checks']
        if check['name'] == 'throughput_read'
    )
    assert validation['success'] is True
    assert throughput_check['passed'] is True
    assert 'Azure portal' in throughput_check['message']


def test_access_validation_reports_configuration_and_permission_failures():
    """Access validation should explain missing config, throughput targets, and metrics failures."""
    missing_config_validation = build_cosmos_throughput_access_validation({
        'configured': False,
        'error': 'Missing Cosmos resource settings: subscription_id',
    })

    assert missing_config_validation['success'] is False
    assert any(
        check['name'] == 'configuration' and not check['passed']
        for check in missing_config_validation['checks']
    )

    access_validation = build_cosmos_throughput_access_validation({
        'configured': True,
        'throughput': {
            'is_scalable': False,
            'mode': 'container_or_serverless',
        },
        'containers': [],
        'metric_error': 'metrics read forbidden',
        'container_error': 'containers read forbidden',
    })

    assert access_validation['success'] is False
    assert access_validation['variant'] == 'danger'
    assert any(
        check['name'] == 'throughput_read' and not check['passed']
        for check in access_validation['checks']
    )
    assert any(
        check['name'] == 'container_discovery' and check['message'] == 'containers read forbidden'
        for check in access_validation['checks']
    )
    assert any(
        check['name'] == 'metrics_read' and check['message'] == 'metrics read forbidden'
        for check in access_validation['checks']
    )


def test_access_validation_uses_neutral_container_targeted_language():
    """Database throughput absence should read as a normal container-targeted mode, not an error."""
    validation = build_cosmos_throughput_access_validation({
        'configured': True,
        'throughput': {
            'is_scalable': False,
            'mode': 'container_or_serverless',
            'throughput_not_found': True,
        },
        'containers': [
            {
                'container_name': 'messages',
                'is_scalable': True,
            },
        ],
        'metric_error': '',
        'container_error': '',
    })

    database_check = next(
        check for check in validation['checks']
        if check['name'] == 'database_throughput_read'
    )
    assert database_check['passed'] is True
    assert database_check['message'] == 'No database-level throughput is configured; using dedicated container throughput checks.'
    assert 'not found' not in database_check['message'].lower()


def test_access_validation_reports_partial_azure_failures():
    """Access validation should preserve separate ARM and metrics failures instead of returning a generic error."""
    status = {
        'configured': True,
        'throughput': {
            'is_scalable': False,
            'mode': 'unknown',
            'error': 'ARM request failed with 403: database throughput forbidden',
        },
        'throughput_error': 'ARM request failed with 403: database throughput forbidden',
        'containers': [
            {
                'container_name': 'messages',
                'is_scalable': True,
            },
        ],
        'metric_error': 'ARM request failed with 403: metrics read forbidden',
        'container_error': '',
    }

    validation = build_cosmos_throughput_access_validation(status)

    assert validation['success'] is False
    assert any(
        check['name'] == 'database_throughput_read'
        and not check['passed']
        and 'database throughput forbidden' in check['message']
        for check in validation['checks']
    )
    assert any(
        check['name'] == 'throughput_read'
        and check['passed']
        and 'dedicated container throughput target' in check['message']
        for check in validation['checks']
    )
    assert any(
        check['name'] == 'container_discovery'
        and check['passed']
        and '1 container(s) found' in check['message']
        for check in validation['checks']
    )
    assert any(
        check['name'] == 'metrics_read'
        and not check['passed']
        and 'metrics read forbidden' in check['message']
        for check in validation['checks']
    )


def test_status_returns_partial_failure_details_for_validate_access():
    """Status loading should keep partial Azure failures in the response for Validate Access diagnostics."""
    original_build_resource_ids = cosmos_throughput.build_cosmos_resource_ids
    original_get_database_throughput = cosmos_throughput.get_database_throughput
    original_get_container_throughputs = cosmos_throughput.get_container_throughputs
    original_query_cosmos_metrics = cosmos_throughput.query_cosmos_metrics

    def fake_build_resource_ids(settings=None):
        return {
            'subscription_id': 'sub',
            'resource_group': 'rg',
            'account_name': 'acct',
            'database_name': 'SimpleChat',
            'account_id': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/acct',
            'database_id': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/acct/sqlDatabases/SimpleChat',
            'throughput_id': '/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DocumentDB/databaseAccounts/acct/sqlDatabases/SimpleChat/throughputSettings/default',
        }

    try:
        cosmos_throughput.build_cosmos_resource_ids = fake_build_resource_ids
        cosmos_throughput.get_database_throughput = lambda settings=None, refresh_id='': (_ for _ in ()).throw(
            CosmosThroughputError('ARM request failed with 403: database throughput forbidden', status_code=403)
        )
        cosmos_throughput.get_container_throughputs = lambda settings=None, resource_ids=None, refresh_id='': [
            {
                'container_name': 'messages',
                'mode': 'autoscale',
                'current_ru': 4000,
                'is_scalable': True,
            },
        ]
        cosmos_throughput.query_cosmos_metrics = lambda settings=None, refresh_id='': (_ for _ in ()).throw(
            CosmosThroughputError('ARM request failed with 403: metrics read forbidden', status_code=403)
        )

        status = get_cosmos_throughput_status(_base_settings(), include_metrics=True, refresh_id='test-validation')
    finally:
        cosmos_throughput.build_cosmos_resource_ids = original_build_resource_ids
        cosmos_throughput.get_database_throughput = original_get_database_throughput
        cosmos_throughput.get_container_throughputs = original_get_container_throughputs
        cosmos_throughput.query_cosmos_metrics = original_query_cosmos_metrics

    assert status['configured'] is True
    assert status['capacity_scope'] == 'container'
    assert 'database throughput forbidden' in status['throughput_error']
    assert 'metrics read forbidden' in status['metric_error']
    assert status['container_error'] == ''
    assert status['containers'][0]['container_name'] == 'messages'
    assert status['containers'][0]['is_scalable'] is True


if __name__ == "__main__":
    tests = [
        test_scales_up_when_utilization_is_high,
        test_scale_up_respects_max_guardrail,
        test_scale_up_reaches_max_guardrail_from_previous_step,
        test_scale_up_at_simplechat_limit_becomes_portal_managed,
        test_database_above_simplechat_limit_is_monitor_only,
        test_scale_down_respects_min_guardrail,
        test_scale_down_uses_separate_cooldown,
        test_ignored_limits_allow_scale_beyond_guardrails,
        test_container_targeted_scale_up_when_database_throughput_missing,
        test_dedicated_container_scale_up_to_max_when_database_throughput_exists,
        test_container_targeted_scaling_waits_for_per_container_metrics,
        test_container_above_simplechat_limit_is_monitor_only,
        test_container_manual_scale_uses_container_policy,
        test_manual_scale_rejects_portal_managed_throughput,
        test_normalization_clamps_simplechat_guardrails_to_10000,
        test_enforced_global_container_policy_overrides_saved_container_policy,
        test_manual_database_conversion_requires_explicit_policy,
        test_global_container_policy_converts_manual_containers_before_scaling,
        test_manual_to_autoscale_payload_uses_autoscale_settings,
        test_manual_to_autoscale_update_uses_migration_action,
        test_policy_validation_rejects_invalid_global_thresholds_and_intervals,
        test_policy_validation_rejects_invalid_container_policy_values,
        test_access_validation_reports_successful_cosmos_checks,
        test_access_validation_reports_portal_managed_monitoring_as_successful_read,
        test_access_validation_reports_configuration_and_permission_failures,
        test_access_validation_uses_neutral_container_targeted_language,
        test_access_validation_reports_partial_azure_failures,
        test_status_returns_partial_failure_details_for_validate_access,
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
