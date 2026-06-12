# functions_cosmos_throughput.py

import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import requests
from azure.identity import DefaultAzureCredential

from functions_appinsights import log_event


COSMOS_THROUGHPUT_ARM_API_VERSION = '2023-04-15'
COSMOS_THROUGHPUT_METRICS_API_VERSION = '2018-01-01'
COSMOS_THROUGHPUT_METRIC_NAMESPACE = 'Microsoft.DocumentDB/databaseAccounts'
COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU = 10000
COSMOS_THROUGHPUT_DEFAULT_MAX_RU = COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU
COSMOS_THROUGHPUT_DEFAULT_MIN_RU = 1000
COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU = 1000
COSMOS_THROUGHPUT_MANUAL_MIN_RU = 400
COSMOS_THROUGHPUT_CONTAINER_METRIC_MAX_RESULTS = 1000
COSMOS_THROUGHPUT_CONTAINER_THROUGHPUT_WORKERS = 8
COSMOS_THROUGHPUT_AUTOSCALE_DEFAULT_INTERVAL_SECONDS = 300
COSMOS_THROUGHPUT_AUTOSCALE_MIN_INTERVAL_SECONDS = 60
COSMOS_THROUGHPUT_AUTOSCALE_MAX_INTERVAL_SECONDS = 3600
DEFAULT_COSMOS_DATABASE_NAME = 'SimpleChat'
COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE = (
    'Throughput above 10,000 RU/s is monitored only in SimpleChat. Use the Azure portal to change capacity; '
    'capacity changes above this level can take 4 to 6 hours.'
)

COSMOS_THROUGHPUT_SETTING_KEYS = (
    'cosmos_throughput_autoscale_enabled',
    'cosmos_throughput_auto_scale_up_enabled',
    'cosmos_throughput_auto_scale_down_enabled',
    'cosmos_throughput_subscription_id',
    'cosmos_throughput_resource_group',
    'cosmos_throughput_account_name',
    'cosmos_throughput_database_name',
    'cosmos_throughput_metrics_window_minutes',
    'cosmos_throughput_scale_up_threshold_percent',
    'cosmos_throughput_scale_down_threshold_percent',
    'cosmos_throughput_scale_up_step_ru',
    'cosmos_throughput_scale_down_step_ru',
    'cosmos_throughput_scale_up_cooldown_minutes',
    'cosmos_throughput_scale_down_cooldown_minutes',
    'cosmos_throughput_min_ru',
    'cosmos_throughput_max_ru',
    'cosmos_throughput_ignore_min_limit',
    'cosmos_throughput_ignore_max_limit',
    'cosmos_throughput_convert_manual_to_autoscale_enabled',
    'cosmos_throughput_enforce_container_defaults',
    'cosmos_throughput_container_policies',
)


class CosmosThroughputError(Exception):
    """Raised when Cosmos throughput management cannot complete."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def get_default_cosmos_throughput_settings():
    """Return default settings for Cosmos throughput monitoring and scaling."""
    return {
        'cosmos_throughput_autoscale_enabled': False,
        'cosmos_throughput_auto_scale_up_enabled': True,
        'cosmos_throughput_auto_scale_down_enabled': True,
        'cosmos_throughput_subscription_id': os.getenv('AZURE_SUBSCRIPTION_ID', ''),
        'cosmos_throughput_resource_group': os.getenv('AZURE_RESOURCE_GROUP', ''),
        'cosmos_throughput_account_name': os.getenv('AZURE_COSMOS_ACCOUNT_NAME', ''),
        'cosmos_throughput_database_name': os.getenv('AZURE_COSMOS_DATABASE_NAME', DEFAULT_COSMOS_DATABASE_NAME),
        'cosmos_throughput_metrics_window_minutes': 5,
        'cosmos_throughput_scale_up_threshold_percent': 90,
        'cosmos_throughput_scale_down_threshold_percent': 70,
        'cosmos_throughput_scale_up_step_ru': 1000,
        'cosmos_throughput_scale_down_step_ru': 1000,
        'cosmos_throughput_scale_up_cooldown_minutes': 5,
        'cosmos_throughput_scale_down_cooldown_minutes': 20,
        'cosmos_throughput_min_ru': COSMOS_THROUGHPUT_DEFAULT_MIN_RU,
        'cosmos_throughput_max_ru': COSMOS_THROUGHPUT_DEFAULT_MAX_RU,
        'cosmos_throughput_ignore_min_limit': False,
        'cosmos_throughput_ignore_max_limit': False,
        'cosmos_throughput_convert_manual_to_autoscale_enabled': False,
        'cosmos_throughput_enforce_container_defaults': False,
        'cosmos_throughput_container_policies': {},
        'cosmos_throughput_last_checked_at': None,
        'cosmos_throughput_last_observed_percent': None,
        'cosmos_throughput_last_observed_ru': None,
        'cosmos_throughput_last_mode': None,
        'cosmos_throughput_last_scale_action': None,
        'cosmos_throughput_last_scale_at': None,
        'cosmos_throughput_last_scale_up_at': None,
        'cosmos_throughput_last_scale_down_at': None,
        'cosmos_throughput_last_scale_from_ru': None,
        'cosmos_throughput_last_scale_to_ru': None,
        'cosmos_throughput_last_scale_reason': None,
        'cosmos_throughput_last_error': '',
        'cosmos_throughput_cached_status': {},
    }


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _coerce_int(value, default, minimum=None, maximum=None):
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default

    if minimum is not None:
        parsed_value = max(minimum, parsed_value)
    if maximum is not None:
        parsed_value = min(maximum, parsed_value)
    return parsed_value


def _coerce_dict(value, default=None):
    if isinstance(value, dict):
        return value
    return default or {}


def normalize_ru(value, mode='autoscale', direction='up'):
    """Normalize RU/s to Cosmos-supported increments for the throughput mode."""
    normalized_mode = str(mode or '').strip().lower()
    quantum = 1000 if normalized_mode == 'autoscale' else 100
    service_minimum = COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU if normalized_mode == 'autoscale' else COSMOS_THROUGHPUT_MANUAL_MIN_RU
    raw_value = _coerce_int(value, service_minimum, minimum=service_minimum)

    if direction == 'down':
        adjusted_value = math.floor(raw_value / quantum) * quantum
    else:
        adjusted_value = math.ceil(raw_value / quantum) * quantum

    return max(service_minimum, adjusted_value)


def _get_current_ru_int(throughput):
    try:
        return int((throughput or {}).get('current_ru'))
    except (TypeError, ValueError):
        return None


def _get_simplechat_scaling_limit(mode='autoscale'):
    return normalize_ru(COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU, mode=mode, direction='down')


def _is_simplechat_scaling_supported(throughput):
    current_ru = _get_current_ru_int(throughput)
    if current_ru is None or not (throughput or {}).get('is_scalable'):
        return False
    return current_ru <= _get_simplechat_scaling_limit((throughput or {}).get('mode') or 'autoscale')


def _is_portal_managed_throughput(throughput):
    current_ru = _get_current_ru_int(throughput)
    if current_ru is None or not (throughput or {}).get('is_scalable'):
        return False
    return current_ru > _get_simplechat_scaling_limit((throughput or {}).get('mode') or 'autoscale')


def _cap_simplechat_scale_target(target_ru, mode='autoscale'):
    return min(target_ru, _get_simplechat_scaling_limit(mode))


def _build_portal_managed_decision(scope='database', container_name='', current_ru=None, observed_percent=None):
    decision = {
        'should_scale': False,
        'reason': 'portal_managed_throughput',
        'scope': scope,
        'from_ru': current_ru,
        'simplechat_max_ru': COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
        'message': COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE,
    }
    if container_name:
        decision['container_name'] = container_name
    if observed_percent is not None:
        decision['observed_percent'] = observed_percent
    return decision


def normalize_cosmos_throughput_settings(settings, repair_policy_relationships=True):
    """Return validated Cosmos throughput settings merged with defaults."""
    source_settings = settings or {}
    normalized = get_default_cosmos_throughput_settings()
    normalized.update({key: source_settings.get(key, normalized.get(key)) for key in normalized.keys()})

    normalized['cosmos_throughput_autoscale_enabled'] = _coerce_bool(
        normalized.get('cosmos_throughput_autoscale_enabled'),
        False,
    )
    normalized['cosmos_throughput_auto_scale_up_enabled'] = _coerce_bool(
        normalized.get('cosmos_throughput_auto_scale_up_enabled'),
        True,
    )
    normalized['cosmos_throughput_auto_scale_down_enabled'] = _coerce_bool(
        normalized.get('cosmos_throughput_auto_scale_down_enabled'),
        True,
    )
    normalized['cosmos_throughput_ignore_min_limit'] = _coerce_bool(
        normalized.get('cosmos_throughput_ignore_min_limit'),
        False,
    )
    normalized['cosmos_throughput_ignore_max_limit'] = _coerce_bool(
        normalized.get('cosmos_throughput_ignore_max_limit'),
        False,
    )
    normalized['cosmos_throughput_convert_manual_to_autoscale_enabled'] = _coerce_bool(
        normalized.get('cosmos_throughput_convert_manual_to_autoscale_enabled'),
        False,
    )
    normalized['cosmos_throughput_enforce_container_defaults'] = _coerce_bool(
        normalized.get('cosmos_throughput_enforce_container_defaults'),
        False,
    )

    for key in (
        'cosmos_throughput_subscription_id',
        'cosmos_throughput_resource_group',
        'cosmos_throughput_account_name',
        'cosmos_throughput_database_name',
    ):
        normalized[key] = str(normalized.get(key) or '').strip()

    normalized['cosmos_throughput_metrics_window_minutes'] = _coerce_int(
        normalized.get('cosmos_throughput_metrics_window_minutes'),
        5,
        minimum=1,
        maximum=60,
    )
    normalized['cosmos_throughput_scale_up_threshold_percent'] = _coerce_int(
        normalized.get('cosmos_throughput_scale_up_threshold_percent'),
        90,
        minimum=1,
        maximum=100,
    )
    normalized['cosmos_throughput_scale_down_threshold_percent'] = _coerce_int(
        normalized.get('cosmos_throughput_scale_down_threshold_percent'),
        70,
        minimum=0,
        maximum=99,
    )

    if (
        repair_policy_relationships
        and normalized['cosmos_throughput_scale_down_threshold_percent'] >= normalized['cosmos_throughput_scale_up_threshold_percent']
    ):
        normalized['cosmos_throughput_scale_down_threshold_percent'] = max(
            0,
            normalized['cosmos_throughput_scale_up_threshold_percent'] - 1,
        )

    normalized['cosmos_throughput_scale_up_step_ru'] = normalize_ru(
        normalized.get('cosmos_throughput_scale_up_step_ru'),
        mode='autoscale',
        direction='up',
    )
    normalized['cosmos_throughput_scale_down_step_ru'] = normalize_ru(
        normalized.get('cosmos_throughput_scale_down_step_ru'),
        mode='autoscale',
        direction='up',
    )
    normalized['cosmos_throughput_scale_up_cooldown_minutes'] = _coerce_int(
        normalized.get('cosmos_throughput_scale_up_cooldown_minutes'),
        5,
        minimum=1,
        maximum=1440,
    )
    normalized['cosmos_throughput_scale_down_cooldown_minutes'] = _coerce_int(
        normalized.get('cosmos_throughput_scale_down_cooldown_minutes'),
        20,
        minimum=1,
        maximum=1440,
    )
    normalized['cosmos_throughput_min_ru'] = normalize_ru(
        normalized.get('cosmos_throughput_min_ru'),
        mode='autoscale',
        direction='up',
    )
    normalized['cosmos_throughput_max_ru'] = normalize_ru(
        normalized.get('cosmos_throughput_max_ru'),
        mode='autoscale',
        direction='up',
    )

    normalized['cosmos_throughput_min_ru'] = min(
        normalized['cosmos_throughput_min_ru'],
        COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
    )
    normalized['cosmos_throughput_max_ru'] = min(
        normalized['cosmos_throughput_max_ru'],
        COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
    )

    if repair_policy_relationships and normalized['cosmos_throughput_max_ru'] < normalized['cosmos_throughput_min_ru']:
        normalized['cosmos_throughput_max_ru'] = normalized['cosmos_throughput_min_ru']

    normalized['cosmos_throughput_container_policies'] = normalize_container_policies(
        normalized.get('cosmos_throughput_container_policies'),
        normalized,
        repair_policy_relationships=repair_policy_relationships,
    )

    return normalized


def _append_policy_validation_errors(errors, policy_label, policy, metrics_window_minutes):
    scale_up_threshold = policy.get('scale_up_threshold_percent')
    scale_down_threshold = policy.get('scale_down_threshold_percent')
    scale_up_interval = policy.get('scale_up_cooldown_minutes')
    scale_down_interval = policy.get('scale_down_cooldown_minutes')

    if scale_up_threshold <= scale_down_threshold:
        errors.append(f'{policy_label}: Scale Up At must be higher than Scale Down At.')
    if scale_up_interval < metrics_window_minutes:
        errors.append(
            f'{policy_label}: Scale Up Interval must be greater than or equal to the Metrics Window '
            f'({metrics_window_minutes} minutes).'
        )
    if scale_down_interval < metrics_window_minutes:
        errors.append(
            f'{policy_label}: Scale Down Interval must be greater than or equal to the Metrics Window '
            f'({metrics_window_minutes} minutes).'
        )


def validate_cosmos_throughput_policy_settings(settings, include_container_policies=True):
    """Return save-blocking validation errors for Cosmos throughput policy settings."""
    normalized = normalize_cosmos_throughput_settings(
        settings,
        repair_policy_relationships=False,
    )

    if not normalized.get('cosmos_throughput_autoscale_enabled'):
        return []

    errors = []
    metrics_window_minutes = normalized['cosmos_throughput_metrics_window_minutes']
    _append_policy_validation_errors(
        errors,
        'Cosmos throughput policy',
        {
            'scale_up_threshold_percent': normalized['cosmos_throughput_scale_up_threshold_percent'],
            'scale_down_threshold_percent': normalized['cosmos_throughput_scale_down_threshold_percent'],
            'scale_up_cooldown_minutes': normalized['cosmos_throughput_scale_up_cooldown_minutes'],
            'scale_down_cooldown_minutes': normalized['cosmos_throughput_scale_down_cooldown_minutes'],
        },
        metrics_window_minutes,
    )

    if include_container_policies and not normalized.get('cosmos_throughput_enforce_container_defaults'):
        for container_name, policy in normalized.get('cosmos_throughput_container_policies', {}).items():
            if policy.get('enabled') is False:
                continue
            _append_policy_validation_errors(
                errors,
                f"Container '{container_name}' policy",
                policy,
                metrics_window_minutes,
            )

    return errors


def build_cosmos_throughput_access_validation(status):
    """Return admin-facing validation checks for Cosmos throughput access."""
    status = status or {}
    checks = []

    def add_check(name, label, passed, message):
        checks.append({
            'name': name,
            'label': label,
            'passed': bool(passed),
            'message': message,
        })

    configured = bool(status.get('configured'))
    add_check(
        'configuration',
        'Resource configuration',
        configured,
        'Cosmos subscription, resource group, account, and database are configured.'
        if configured else status.get('error') or 'Cosmos resource settings are incomplete.',
    )
    if not configured:
        return {
            'success': False,
            'variant': 'danger',
            'message': 'Cosmos throughput access validation could not run because resource settings are incomplete.',
            'checks': checks,
        }

    throughput = status.get('throughput') or {}
    containers = status.get('containers') or []
    has_database_throughput = bool(throughput.get('is_scalable'))
    scalable_container_count = sum(1 for container in containers if container.get('is_scalable'))
    portal_managed_database = bool(throughput.get('portal_managed_scaling_required'))
    portal_managed_container_count = sum(
        1 for container in containers if container.get('portal_managed_scaling_required')
    )
    simplechat_container_count = sum(
        1 for container in containers
        if container.get('is_scalable') and not container.get('portal_managed_scaling_required')
    )
    has_scalable_target = has_database_throughput or scalable_container_count > 0
    throughput_error = status.get('throughput_error') or throughput.get('error') or ''
    container_error = status.get('container_error') or ''
    metric_error = status.get('metric_error') or ''

    if has_database_throughput:
        throughput_message = (
            'Database throughput is readable for monitoring; scaling above 10,000 RU/s must be managed in the Azure portal. '
            'Capacity changes above this level can take 4 to 6 hours.'
            if portal_managed_database else 'Database throughput is readable and manageable by SimpleChat.'
        )
    elif scalable_container_count:
        if portal_managed_container_count and simplechat_container_count:
            throughput_message = (
                f'{simplechat_container_count} dedicated container throughput target(s) are manageable by SimpleChat; '
                f'{portal_managed_container_count} target(s) are above 10,000 RU/s and are monitored only. '
                'Capacity changes above this level can take 4 to 6 hours.'
            )
        elif portal_managed_container_count:
            throughput_message = (
                f'{portal_managed_container_count} dedicated container throughput target(s) are readable for monitoring; '
                'scaling above 10,000 RU/s must be managed in the Azure portal. '
                'Capacity changes above this level can take 4 to 6 hours.'
            )
        else:
            throughput_message = f'{scalable_container_count} dedicated container throughput target(s) are readable and manageable.'
    else:
        throughput_message = 'No scalable database or dedicated container throughput target was found.'

    add_check(
        'database_throughput_read',
        'Database throughput read access',
        not bool(throughput_error),
        'Database throughput settings were read from Azure Resource Manager.'
        if not throughput_error and not throughput.get('throughput_not_found') else (
            'No database-level throughput is configured; using dedicated container throughput checks.'
            if not throughput_error else throughput_error
        ),
    )

    add_check(
        'throughput_read',
        'Scalable throughput target',
        has_scalable_target,
        throughput_message,
    )
    add_check(
        'container_discovery',
        'Container discovery access',
        not bool(container_error),
        f'Container discovery completed; {len(containers)} container(s) found.' if not container_error else container_error,
    )
    add_check(
        'metrics_read',
        'Azure Monitor metrics access',
        not bool(metric_error),
        'Azure Monitor metrics query completed.' if not metric_error else metric_error,
    )

    success = all(check['passed'] for check in checks)
    return {
        'success': success,
        'variant': 'success' if success else 'danger',
        'message': 'Cosmos throughput configuration and access validated successfully.'
        if success else 'Cosmos throughput access validation found issues. Review the failed checks before enabling automation.',
        'checks': checks,
    }


def calculate_cosmos_throughput_autoscale_interval_seconds(settings=None):
    """Calculate the background autoscale check cadence from the metrics window."""
    normalized = normalize_cosmos_throughput_settings(settings or {})
    interval_seconds = normalized['cosmos_throughput_metrics_window_minutes'] * 60
    return max(
        COSMOS_THROUGHPUT_AUTOSCALE_MIN_INTERVAL_SECONDS,
        min(COSMOS_THROUGHPUT_AUTOSCALE_MAX_INTERVAL_SECONDS, interval_seconds),
    )


def normalize_container_policy(container_name, policy=None, settings=None, repair_policy_relationships=True):
    """Return a validated throughput policy for one Cosmos container."""
    settings = settings or get_default_cosmos_throughput_settings()
    source_policy = policy or {}
    normalized = {
        'container_name': str(container_name or source_policy.get('container_name') or '').strip(),
        'enabled': _coerce_bool(source_policy.get('enabled'), True),
        'auto_scale_up_enabled': _coerce_bool(
            source_policy.get('auto_scale_up_enabled'),
            settings.get('cosmos_throughput_auto_scale_up_enabled', True),
        ),
        'auto_scale_down_enabled': _coerce_bool(
            source_policy.get('auto_scale_down_enabled'),
            settings.get('cosmos_throughput_auto_scale_down_enabled', True),
        ),
        'scale_up_threshold_percent': _coerce_int(
            source_policy.get('scale_up_threshold_percent'),
            settings.get('cosmos_throughput_scale_up_threshold_percent', 90),
            minimum=1,
            maximum=100,
        ),
        'scale_down_threshold_percent': _coerce_int(
            source_policy.get('scale_down_threshold_percent'),
            settings.get('cosmos_throughput_scale_down_threshold_percent', 70),
            minimum=0,
            maximum=99,
        ),
        'scale_up_step_ru': normalize_ru(
            source_policy.get('scale_up_step_ru', settings.get('cosmos_throughput_scale_up_step_ru', 1000)),
            mode='autoscale',
            direction='up',
        ),
        'scale_down_step_ru': normalize_ru(
            source_policy.get('scale_down_step_ru', settings.get('cosmos_throughput_scale_down_step_ru', 1000)),
            mode='autoscale',
            direction='up',
        ),
        'scale_up_cooldown_minutes': _coerce_int(
            source_policy.get('scale_up_cooldown_minutes'),
            settings.get('cosmos_throughput_scale_up_cooldown_minutes', 5),
            minimum=1,
            maximum=1440,
        ),
        'scale_down_cooldown_minutes': _coerce_int(
            source_policy.get('scale_down_cooldown_minutes'),
            settings.get('cosmos_throughput_scale_down_cooldown_minutes', 20),
            minimum=1,
            maximum=1440,
        ),
        'min_ru': normalize_ru(
            source_policy.get('min_ru', settings.get('cosmos_throughput_min_ru', COSMOS_THROUGHPUT_DEFAULT_MIN_RU)),
            mode='autoscale',
            direction='up',
        ),
        'max_ru': normalize_ru(
            source_policy.get('max_ru', settings.get('cosmos_throughput_max_ru', COSMOS_THROUGHPUT_DEFAULT_MAX_RU)),
            mode='autoscale',
            direction='up',
        ),
        'ignore_min_limit': _coerce_bool(
            source_policy.get('ignore_min_limit'),
            settings.get('cosmos_throughput_ignore_min_limit', False),
        ),
        'ignore_max_limit': _coerce_bool(
            source_policy.get('ignore_max_limit'),
            settings.get('cosmos_throughput_ignore_max_limit', False),
        ),
        'convert_manual_to_autoscale_enabled': _coerce_bool(
            source_policy.get('convert_manual_to_autoscale_enabled'),
            settings.get('cosmos_throughput_convert_manual_to_autoscale_enabled', False),
        ),
        'last_scale_up_at': source_policy.get('last_scale_up_at'),
        'last_scale_down_at': source_policy.get('last_scale_down_at'),
        'last_mode_conversion_at': source_policy.get('last_mode_conversion_at'),
    }

    if repair_policy_relationships and normalized['scale_down_threshold_percent'] >= normalized['scale_up_threshold_percent']:
        normalized['scale_down_threshold_percent'] = max(0, normalized['scale_up_threshold_percent'] - 1)
    normalized['min_ru'] = min(normalized['min_ru'], COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU)
    normalized['max_ru'] = min(normalized['max_ru'], COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU)
    if repair_policy_relationships and normalized['max_ru'] < normalized['min_ru']:
        normalized['max_ru'] = normalized['min_ru']

    return normalized


def normalize_container_policies(policies=None, settings=None, repair_policy_relationships=True):
    """Return a normalized mapping of container name to throughput policy."""
    normalized_policies = {}
    for container_name, policy in _coerce_dict(policies).items():
        normalized_name = str(container_name or '').strip()
        if not normalized_name:
            continue
        normalized_policies[normalized_name] = normalize_container_policy(
            normalized_name,
            policy,
            settings,
            repair_policy_relationships=repair_policy_relationships,
        )

    return normalized_policies


def get_container_policy(settings, container_name):
    """Resolve a container policy from saved settings or global defaults."""
    normalized = normalize_cosmos_throughput_settings(settings)
    policies = normalized.get('cosmos_throughput_container_policies') or {}
    saved_policy = policies.get(container_name) or {}
    if normalized.get('cosmos_throughput_enforce_container_defaults'):
        saved_policy = {
            'container_name': container_name,
            'last_scale_up_at': saved_policy.get('last_scale_up_at'),
            'last_scale_down_at': saved_policy.get('last_scale_down_at'),
            'last_mode_conversion_at': saved_policy.get('last_mode_conversion_at'),
        }
    return normalize_container_policy(container_name, saved_policy, normalized)


def get_cosmos_throughput_setting_keys():
    """Return persisted admin setting keys for Cosmos throughput controls."""
    return COSMOS_THROUGHPUT_SETTING_KEYS


def _copy_keys(source, keys):
    """Copy selected keys from a dictionary into a new dictionary."""
    source = source or {}
    return {key: source.get(key) for key in keys if key in source}


def build_cached_cosmos_throughput_status(status=None, scale_result=None):
    """Build a compact, admin-display-safe cached throughput status."""
    status = status or {}
    scale_result = scale_result or {}
    throughput = _copy_keys(
        status.get('throughput'),
        (
            'scope',
            'mode',
            'current_ru',
            'is_scalable',
            'throughput_not_found',
            'message',
            'simplechat_scaling_supported',
            'simplechat_max_ru',
            'portal_managed_scaling_required',
            'portal_managed_message',
        ),
    )
    if scale_result and scale_result.get('scope') != 'container' and scale_result.get('to_ru') is not None:
        throughput['current_ru'] = scale_result.get('to_ru')
        if scale_result.get('to_mode'):
            throughput['mode'] = scale_result.get('to_mode')

    containers = []
    for container in status.get('containers') or []:
        cached_container = _copy_keys(
            container,
            (
                'container_name',
                'database_name',
                'normalized_ru_percent',
                'request_units',
                'mode',
                'current_ru',
                'is_scalable',
                'throughput_not_found',
                'error',
                'has_normalized_ru_metric',
                'has_request_units_metric',
                'policy',
                'simplechat_scaling_supported',
                'simplechat_max_ru',
                'portal_managed_scaling_required',
                'portal_managed_message',
            ),
        )
        if (
            scale_result
            and scale_result.get('scope') == 'container'
            and scale_result.get('container_name') == cached_container.get('container_name')
            and scale_result.get('to_ru') is not None
        ):
            cached_container['current_ru'] = scale_result.get('to_ru')
            if scale_result.get('to_mode'):
                cached_container['mode'] = scale_result.get('to_mode')
        containers.append(cached_container)

    cached_status = {
        'configured': bool(status.get('configured')),
        'resource': _copy_keys(
            status.get('resource'),
            ('subscription_id', 'resource_group', 'account_name', 'database_name'),
        ),
        'throughput': throughput,
        'capacity_scope': status.get('capacity_scope'),
        'metrics': _copy_keys(
            status.get('metrics'),
            ('window_minutes', 'normalized_ru_percent', 'total_request_units'),
        ),
        'containers': containers,
        'throughput_error': status.get('throughput_error', ''),
        'metric_error': status.get('metric_error', ''),
        'container_error': status.get('container_error', ''),
        'last_checked_at': status.get('last_checked_at'),
        'cached_at': datetime.now(timezone.utc).isoformat(),
    }
    if status.get('error'):
        cached_status['error'] = status.get('error')
    return cached_status


def get_cached_cosmos_throughput_status(settings=None):
    """Return the last saved Cosmos throughput status for initial admin rendering."""
    cached_status = (settings or {}).get('cosmos_throughput_cached_status')
    if not isinstance(cached_status, dict) or not cached_status:
        return {}

    normalized_status = build_cached_cosmos_throughput_status(cached_status)
    normalized_status['is_cached'] = True
    normalized_status['last_checked_at'] = cached_status.get('last_checked_at')
    normalized_status['cached_at'] = cached_status.get('cached_at')
    normalized_status['configured'] = bool(cached_status.get('configured'))
    return normalized_status


def parse_cosmos_account_name(endpoint):
    """Extract a Cosmos DB account name from a document endpoint."""
    if not endpoint:
        return ''

    parsed_endpoint = urlparse(endpoint)
    hostname = parsed_endpoint.hostname or str(endpoint).split('/')[0]
    if not hostname:
        return ''
    return hostname.split('.')[0].strip()


def get_cosmos_resource_config(settings=None):
    """Resolve Cosmos management-plane resource identifiers from settings and environment."""
    normalized = normalize_cosmos_throughput_settings(settings)
    account_name = normalized.get('cosmos_throughput_account_name') or parse_cosmos_account_name(os.getenv('AZURE_COSMOS_ENDPOINT', ''))
    database_name = normalized.get('cosmos_throughput_database_name') or DEFAULT_COSMOS_DATABASE_NAME

    return {
        'subscription_id': normalized.get('cosmos_throughput_subscription_id') or os.getenv('AZURE_SUBSCRIPTION_ID', ''),
        'resource_group': normalized.get('cosmos_throughput_resource_group') or os.getenv('AZURE_RESOURCE_GROUP', ''),
        'account_name': account_name or os.getenv('AZURE_COSMOS_ACCOUNT_NAME', ''),
        'database_name': database_name or os.getenv('AZURE_COSMOS_DATABASE_NAME', DEFAULT_COSMOS_DATABASE_NAME),
    }


def _quote_part(value):
    return quote(str(value or '').strip(), safe='')


def build_cosmos_resource_ids(settings=None):
    """Build ARM resource IDs for the configured Cosmos account and database."""
    config = get_cosmos_resource_config(settings)
    missing = [key for key, value in config.items() if not value]
    if missing:
        raise CosmosThroughputError(f"Missing Cosmos resource settings: {', '.join(missing)}")

    account_id = (
        f"/subscriptions/{_quote_part(config['subscription_id'])}"
        f"/resourceGroups/{_quote_part(config['resource_group'])}"
        f"/providers/Microsoft.DocumentDB/databaseAccounts/{_quote_part(config['account_name'])}"
    )
    database_id = f"{account_id}/sqlDatabases/{_quote_part(config['database_name'])}"
    throughput_id = f"{database_id}/throughputSettings/default"

    return {
        'account_id': account_id,
        'database_id': database_id,
        'throughput_id': throughput_id,
        **config,
    }


def build_cosmos_container_resource_ids(resource_ids, container_name):
    """Build ARM resource IDs for a configured Cosmos SQL container."""
    container_id = f"{resource_ids['database_id']}/containers/{_quote_part(container_name)}"
    throughput_id = f"{container_id}/throughputSettings/default"
    return {
        **resource_ids,
        'container_name': container_name,
        'container_id': container_id,
        'throughput_id': throughput_id,
    }


def _build_credential():
    credential_authority = None
    try:
        from config import authority as configured_authority
        credential_authority = configured_authority
    except Exception:
        credential_authority = None

    try:
        return DefaultAzureCredential(authority=credential_authority) if credential_authority else DefaultAzureCredential()
    except TypeError:
        return DefaultAzureCredential()


def _get_resource_manager_endpoint():
    try:
        from config import resource_manager as configured_resource_manager
        return configured_resource_manager.rstrip('/')
    except Exception:
        return os.getenv('CUSTOM_RESOURCE_MANAGER_URL_VALUE', 'https://management.azure.com').rstrip('/')


def _get_credential_scope():
    try:
        from config import credential_scopes as configured_credential_scopes
        if configured_credential_scopes:
            return configured_credential_scopes[0]
    except Exception:
        pass

    return f"{_get_resource_manager_endpoint()}/.default"


def _log_refresh_event(message, refresh_id='', extra=None, level=logging.INFO):
    log_extra = dict(extra or {})
    if refresh_id:
        log_extra['refresh_id'] = refresh_id
    log_event(message, extra=log_extra, level=level)


def _get_arm_resource_kind(resource_path):
    if '/containers/' in resource_path and '/throughputSettings/' in resource_path:
        return 'container_throughput'
    if resource_path.endswith('/containers'):
        return 'container_list'
    if '/throughputSettings/' in resource_path:
        return 'database_throughput'
    return 'unknown'


def _build_arm_request_context(refresh_id='', resource_kind='unknown'):
    credential_start = time.perf_counter()
    _log_refresh_event(
        '[CosmosThroughput] ARM credential acquisition starting.',
        refresh_id=refresh_id,
        extra={'resource_kind': resource_kind},
    )
    credential = _build_credential()
    token = credential.get_token(_get_credential_scope())
    credential_elapsed_ms = int((time.perf_counter() - credential_start) * 1000)
    _log_refresh_event(
        '[CosmosThroughput] ARM credential acquired.',
        refresh_id=refresh_id,
        extra={'resource_kind': resource_kind, 'credential_elapsed_ms': credential_elapsed_ms},
    )
    return {
        'resource_manager_endpoint': _get_resource_manager_endpoint(),
        'token': token.token,
        'credential_elapsed_ms': credential_elapsed_ms,
    }


def _arm_request(method, resource_path, payload=None, refresh_id='', request_context=None):
    request_start = time.perf_counter()
    resource_kind = _get_arm_resource_kind(resource_path)

    _log_refresh_event(
        '[CosmosThroughput] ARM request starting.',
        refresh_id=refresh_id,
        extra={'method': method, 'resource_kind': resource_kind},
    )

    request_context = request_context or _build_arm_request_context(refresh_id=refresh_id, resource_kind=resource_kind)
    credential_elapsed_ms = request_context.get('credential_elapsed_ms', 0)

    separator = '&' if '?' in resource_path else '?'
    request_url = (
        f"{request_context['resource_manager_endpoint']}{resource_path}"
        f"{separator}api-version={COSMOS_THROUGHPUT_ARM_API_VERSION}"
    )

    _log_refresh_event(
        '[CosmosThroughput] ARM HTTP request sending.',
        refresh_id=refresh_id,
        extra={'method': method, 'resource_kind': resource_kind},
    )
    try:
        response = requests.request(
            method,
            request_url,
            headers={
                'Authorization': f"Bearer {request_context['token']}",
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=30,
        )
    except Exception as exc:
        _log_refresh_event(
            '[CosmosThroughput] ARM request exception.',
            refresh_id=refresh_id,
            extra={
                'method': method,
                'resource_kind': resource_kind,
                'elapsed_ms': int((time.perf_counter() - request_start) * 1000),
                'credential_elapsed_ms': credential_elapsed_ms,
                'error': str(exc),
            },
            level=logging.ERROR,
        )
        raise

    elapsed_ms = int((time.perf_counter() - request_start) * 1000)
    _log_refresh_event(
        '[CosmosThroughput] ARM request completed.',
        refresh_id=refresh_id,
        extra={
            'method': method,
            'resource_kind': resource_kind,
            'status_code': response.status_code,
            'elapsed_ms': elapsed_ms,
            'credential_elapsed_ms': credential_elapsed_ms,
        },
    )

    if response.status_code >= 400:
        detail = response.text[:500] if response.text else response.reason
        raise CosmosThroughputError(
            f"ARM request failed with {response.status_code}: {detail}",
            status_code=response.status_code,
        )

    if not response.text:
        return {}

    try:
        return response.json()
    except ValueError:
        return {}


def _is_not_found_error(error):
    return getattr(error, 'status_code', None) == 404 or 'ARM request failed with 404' in str(error)


def _parse_throughput_body(body, resource_ids, scope='database', container_name=''):
    resource = body.get('properties', {}).get('resource', {}) if isinstance(body, dict) else {}
    autoscale_settings = resource.get('autoscaleSettings') or {}
    max_throughput = autoscale_settings.get('maxThroughput')
    manual_throughput = resource.get('throughput')

    if max_throughput:
        mode = 'autoscale'
        current_ru = int(max_throughput)
    elif manual_throughput:
        mode = 'manual'
        current_ru = int(manual_throughput)
    else:
        mode = 'serverless_or_shared'
        current_ru = None

    is_scalable = mode in {'autoscale', 'manual'} and current_ru is not None
    simplechat_scaling_limit = _get_simplechat_scaling_limit(mode)
    simplechat_scaling_supported = bool(is_scalable and current_ru <= simplechat_scaling_limit)
    portal_managed_scaling_required = bool(is_scalable and current_ru > simplechat_scaling_limit)

    return {
        'scope': scope,
        'container_name': container_name,
        'mode': mode,
        'current_ru': current_ru,
        'resource': resource,
        'resource_ids': resource_ids,
        'is_scalable': is_scalable,
        'simplechat_scaling_supported': simplechat_scaling_supported,
        'simplechat_max_ru': COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
        'portal_managed_scaling_required': portal_managed_scaling_required,
        'portal_managed_message': COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE if portal_managed_scaling_required else '',
    }


def get_database_throughput(settings=None, refresh_id=''):
    """Read database-level throughput settings from ARM."""
    resource_ids = build_cosmos_resource_ids(settings)
    try:
        body = _arm_request('GET', resource_ids['throughput_id'], refresh_id=refresh_id)
    except CosmosThroughputError as exc:
        if not _is_not_found_error(exc):
            raise
        _log_refresh_event(
            '[CosmosThroughput] Database throughput not found; falling back to container throughput scan.',
            refresh_id=refresh_id,
            extra={'database_name': resource_ids.get('database_name')},
            level=logging.WARNING,
        )
        return {
            'scope': 'database',
            'mode': 'container_or_serverless',
            'current_ru': None,
            'resource': {},
            'resource_ids': resource_ids,
            'is_scalable': False,
            'throughput_not_found': True,
            'message': 'Database-level throughput settings were not found. Checking container throughput settings.',
        }

    return _parse_throughput_body(body, resource_ids, scope='database')


def list_database_containers(settings=None, resource_ids=None, refresh_id=''):
    """List SQL containers for the configured database through ARM."""
    resource_ids = resource_ids or build_cosmos_resource_ids(settings)
    list_start = time.perf_counter()
    body = _arm_request('GET', f"{resource_ids['database_id']}/containers", refresh_id=refresh_id)
    container_names = []
    seen_names = set()

    for item in body.get('value', []) if isinstance(body, dict) else []:
        properties = item.get('properties', {}) if isinstance(item, dict) else {}
        resource = properties.get('resource', {}) if isinstance(properties, dict) else {}
        container_name = resource.get('id') or item.get('name') or str(item.get('id', '')).split('/')[-1]
        container_name = str(container_name or '').strip()
        if container_name and container_name not in seen_names:
            container_names.append(container_name)
            seen_names.add(container_name)

    _log_refresh_event(
        '[CosmosThroughput] Container list resolved.',
        refresh_id=refresh_id,
        extra={
            'container_count': len(container_names),
            'elapsed_ms': int((time.perf_counter() - list_start) * 1000),
        },
    )
    return container_names


def get_container_throughput(settings, container_name, resource_ids=None, refresh_id='', request_context=None):
    """Read dedicated container-level throughput settings from ARM."""
    database_resource_ids = resource_ids or build_cosmos_resource_ids(settings)
    container_resource_ids = build_cosmos_container_resource_ids(database_resource_ids, container_name)

    try:
        body = _arm_request(
            'GET',
            container_resource_ids['throughput_id'],
            refresh_id=refresh_id,
            request_context=request_context,
        )
    except CosmosThroughputError as exc:
        if not _is_not_found_error(exc):
            raise
        return {
            'scope': 'container',
            'container_name': container_name,
            'mode': 'shared_or_serverless',
            'current_ru': None,
            'resource': {},
            'resource_ids': container_resource_ids,
            'is_scalable': False,
            'throughput_not_found': True,
            'simplechat_scaling_supported': False,
            'simplechat_max_ru': COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
            'portal_managed_scaling_required': False,
            'portal_managed_message': '',
        }

    return _parse_throughput_body(
        body,
        container_resource_ids,
        scope='container',
        container_name=container_name,
    )


def get_container_throughputs(settings=None, resource_ids=None, refresh_id=''):
    """Read throughput settings for every container in the configured database."""
    container_start = time.perf_counter()
    database_resource_ids = resource_ids or build_cosmos_resource_ids(settings)
    container_names = list_database_containers(settings, database_resource_ids, refresh_id=refresh_id)

    if not container_names:
        _log_refresh_event(
            '[CosmosThroughput] Container throughput scan completed.',
            refresh_id=refresh_id,
            extra={
                'container_count': 0,
                'scalable_container_count': 0,
                'worker_count': 0,
                'elapsed_ms': int((time.perf_counter() - container_start) * 1000),
            },
        )
        return []

    request_context = _build_arm_request_context(
        refresh_id=refresh_id,
        resource_kind='container_throughput_batch',
    )
    worker_count = min(COSMOS_THROUGHPUT_CONTAINER_THROUGHPUT_WORKERS, len(container_names))
    container_throughputs_by_name = {}

    def read_container(container_name):
        try:
            return get_container_throughput(
                settings,
                container_name,
                database_resource_ids,
                refresh_id=refresh_id,
                request_context=request_context,
            )
        except Exception as exc:
            log_event(
                '[CosmosThroughput] Failed to read container throughput settings.',
                extra={'container_name': container_name, 'error': str(exc), 'refresh_id': refresh_id},
                level=logging.WARNING,
            )
            return {
                'scope': 'container',
                'container_name': container_name,
                'mode': 'unknown',
                'current_ru': None,
                'resource': {},
                'resource_ids': build_cosmos_container_resource_ids(database_resource_ids, container_name),
                'is_scalable': False,
                'error': str(exc),
                'simplechat_scaling_supported': False,
                'simplechat_max_ru': COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
                'portal_managed_scaling_required': False,
                'portal_managed_message': '',
            }

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_by_container = {
            executor.submit(read_container, container_name): container_name
            for container_name in container_names
        }
        for future in as_completed(future_by_container):
            container_name = future_by_container[future]
            container_throughputs_by_name[container_name] = future.result()

    container_throughputs = [
        container_throughputs_by_name[container_name]
        for container_name in container_names
        if container_name in container_throughputs_by_name
    ]

    _log_refresh_event(
        '[CosmosThroughput] Container throughput scan completed.',
        refresh_id=refresh_id,
        extra={
            'container_count': len(container_names),
            'scalable_container_count': sum(1 for item in container_throughputs if item.get('is_scalable')),
            'worker_count': worker_count,
            'elapsed_ms': int((time.perf_counter() - container_start) * 1000),
        },
    )
    return container_throughputs


def _normalize_throughput_mode(mode, default_mode='manual'):
    normalized_mode = str(mode or default_mode or '').strip().lower()
    if normalized_mode not in {'manual', 'autoscale'}:
        raise CosmosThroughputError('Cosmos throughput target mode must be manual or autoscale.')
    return normalized_mode


def _build_throughput_payload(mode, target_ru):
    mode = _normalize_throughput_mode(mode)
    if mode == 'autoscale':
        return {
            'properties': {
                'resource': {
                    'autoscaleSettings': {
                        'maxThroughput': target_ru,
                    },
                },
            },
        }

    return {
        'properties': {
            'resource': {
                'throughput': target_ru,
            },
        },
    }


def _migrate_throughput_to_autoscale(current):
    resource_ids = current['resource_ids']
    migration_url = f"{resource_ids['throughput_id']}/migrateToAutoscale"
    _arm_request('POST', migration_url)

    try:
        migrated_body = _arm_request('GET', resource_ids['throughput_id'])
        migrated = _parse_throughput_body(
            migrated_body,
            resource_ids,
            scope=current.get('scope', 'database'),
            container_name=current.get('container_name', ''),
        )
        if migrated.get('mode') == 'autoscale' and migrated.get('current_ru'):
            return migrated
    except Exception as exc:
        log_event(
            '[CosmosThroughput] Autoscale migration submitted but follow-up throughput read failed.',
            extra={
                'scope': current.get('scope'),
                'container_name': current.get('container_name', ''),
                'error': str(exc),
            },
            level=logging.WARNING,
        )

    migrated = dict(current)
    migrated['mode'] = 'autoscale'
    migrated['current_ru'] = normalize_ru(current.get('current_ru'), mode='autoscale', direction='up')
    return migrated


def _apply_throughput_update(current, target_ru, initiated_by, reason, target_mode=None):
    if not current.get('is_scalable'):
        raise CosmosThroughputError('Cosmos throughput is not scalable for this capacity mode.')

    mode = current.get('mode')
    update_mode = _normalize_throughput_mode(target_mode or mode, default_mode=mode)
    normalized_target = normalize_ru(target_ru, mode=update_mode, direction='up')
    if _is_portal_managed_throughput(current) or normalized_target > _get_simplechat_scaling_limit(update_mode):
        raise CosmosThroughputError(COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE)
    resource_ids = current['resource_ids']
    if mode == 'manual' and update_mode == 'autoscale':
        migrated = _migrate_throughput_to_autoscale(current)
        normalized_target = migrated.get('current_ru') or normalized_target
    else:
        _arm_request(
            'PUT',
            resource_ids['throughput_id'],
            payload=_build_throughput_payload(update_mode, normalized_target),
        )

    log_event(
        '[CosmosThroughput] Throughput update submitted.',
        extra={
            'scope': current.get('scope'),
            'container_name': current.get('container_name', ''),
            'from_mode': mode,
            'to_mode': update_mode,
            'from_ru': current.get('current_ru'),
            'to_ru': normalized_target,
            'initiated_by': initiated_by,
            'reason': reason,
        },
        level=logging.INFO,
    )

    return {
        'scope': current.get('scope'),
        'container_name': current.get('container_name', ''),
        'mode': update_mode,
        'from_mode': mode,
        'to_mode': update_mode,
        'from_ru': current.get('current_ru'),
        'to_ru': normalized_target,
        'resource_ids': resource_ids,
    }


def set_database_throughput(settings, target_ru, initiated_by='system', reason='', decision=None):
    """Set database or fallback container throughput through ARM."""
    decision = decision or {}
    if decision.get('scope') == 'container':
        container_name = decision.get('container_name')
        if not container_name:
            raise CosmosThroughputError('Container throughput target was not specified.')
        current = get_container_throughput(settings, container_name)
    else:
        current = get_database_throughput(settings)

    return _apply_throughput_update(
        current,
        target_ru,
        initiated_by,
        reason,
        target_mode=decision.get('target_mode'),
    )


def _metadata_to_dict(metadata_values):
    metadata = {}
    for metadata_value in metadata_values or []:
        if isinstance(metadata_value, dict):
            name_value = metadata_value.get('name')
            if isinstance(name_value, dict):
                name = name_value.get('value') or name_value.get('localizedValue')
            else:
                name = name_value
            value = metadata_value.get('value')
        else:
            name = getattr(getattr(metadata_value, 'name', None), 'value', None) or getattr(metadata_value, 'name', None)
            value = getattr(metadata_value, 'value', None)
        if name:
            metadata[str(name)] = value
    return metadata


def _metric_value(data_points, attribute_name):
    values = []
    for point in data_points or []:
        value = point.get(attribute_name) if isinstance(point, dict) else getattr(point, attribute_name, None)
        if value is not None:
            values.append(float(value))

    if not values:
        return None
    return sum(values) if attribute_name == 'total' else max(values)


def _escape_metric_filter_value(value):
    return str(value or '').replace("'", "''")


def build_cosmos_container_metric_filter(database_name):
    """Build an Azure Monitor filter that splits Cosmos metrics by container."""
    escaped_database_name = _escape_metric_filter_value(database_name or DEFAULT_COSMOS_DATABASE_NAME)
    return f"DatabaseName eq '{escaped_database_name}' and CollectionName eq '*'"


def _format_metric_time(value):
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')


def _query_cosmos_metric_rest_response(
    resource_ids,
    start_time,
    end_time,
    metric_names,
    aggregation,
    metric_filter=None,
    request_context=None,
):
    request_context = request_context or _build_arm_request_context(resource_kind='metrics')
    request_url = (
        f"{request_context['resource_manager_endpoint']}{resource_ids['account_id']}"
        "/providers/microsoft.insights/metrics"
    )
    params = {
        'api-version': COSMOS_THROUGHPUT_METRICS_API_VERSION,
        'metricnamespace': COSMOS_THROUGHPUT_METRIC_NAMESPACE,
        'metricnames': metric_names,
        'timespan': f"{_format_metric_time(start_time)}/{_format_metric_time(end_time)}",
        'interval': 'PT1M',
        'aggregation': aggregation,
    }
    if metric_filter:
        params['$filter'] = metric_filter
        params['top'] = str(COSMOS_THROUGHPUT_CONTAINER_METRIC_MAX_RESULTS)

    response = requests.get(
        request_url,
        headers={'Authorization': f"Bearer {request_context['token']}"},
        params=params,
        timeout=30,
    )
    if response.status_code >= 400:
        detail = response.text[:500] if response.text else response.reason
        raise CosmosThroughputError(
            f"Azure Monitor metrics request failed with {response.status_code}: {detail}",
            status_code=response.status_code,
        )

    try:
        return response.json()
    except ValueError:
        return {'value': []}


def _query_cosmos_metrics_response(resource_ids, start_time, end_time, split_by_container=False, request_context=None):
    metric_filter = None
    if split_by_container:
        metric_filter = build_cosmos_container_metric_filter(resource_ids.get('database_name'))

    return _query_cosmos_metric_rest_response(
        resource_ids,
        start_time,
        end_time,
        'NormalizedRUConsumption,TotalRequestUnits',
        'Maximum,Total',
        metric_filter=metric_filter,
        request_context=request_context,
    )


def _parse_cosmos_metrics_response(response, resource_ids, window_minutes, container_dimensions_requested=False):
    containers = {}
    normalized_ru_percent = None
    total_request_units = 0.0

    metrics = response.get('value', []) if isinstance(response, dict) else response.metrics or []
    for metric in metrics:
        if isinstance(metric, dict):
            metric_name_value = metric.get('name', {})
            metric_name = metric_name_value.get('value') if isinstance(metric_name_value, dict) else str(metric_name_value or '')
            time_series_items = metric.get('timeseries', [])
        else:
            metric_name_value = getattr(metric, 'name', '')
            metric_name = getattr(metric_name_value, 'value', None) or str(metric_name_value or '')
            time_series_items = metric.timeseries or []
        for time_series in time_series_items:
            if isinstance(time_series, dict):
                metadata = _metadata_to_dict(time_series.get('metadatavalues', []))
                data_points = time_series.get('data', [])
            else:
                metadata = _metadata_to_dict(getattr(time_series, 'metadata_values', []))
                data_points = time_series.data
            database_name = (
                metadata.get('DatabaseName')
                or metadata.get('databaseName')
                or metadata.get('databasename')
                or metadata.get('Database')
                or metadata.get('database')
                or metadata.get('DatabaseId')
                or metadata.get('databaseId')
                or metadata.get('databaseid')
            )
            container_name = (
                metadata.get('CollectionName')
                or metadata.get('collectionName')
                or metadata.get('collectionname')
                or metadata.get('Collection')
                or metadata.get('collection')
                or metadata.get('ContainerName')
                or metadata.get('containerName')
                or metadata.get('containername')
                or metadata.get('Container')
                or metadata.get('container')
            )

            if database_name and database_name != resource_ids['database_name']:
                continue

            container_key = container_name or 'database'
            container_entry = containers.setdefault(
                container_key,
                {
                    'container_name': container_key,
                    'database_name': database_name or resource_ids['database_name'],
                    'normalized_ru_percent': None,
                    'request_units': 0.0,
                    'has_normalized_ru_metric': False,
                    'has_request_units_metric': False,
                },
            )

            if metric_name == 'NormalizedRUConsumption':
                series_value = _metric_value(data_points, 'maximum')
                if series_value is not None:
                    container_entry['normalized_ru_percent'] = max(
                        container_entry['normalized_ru_percent'] or 0,
                        series_value,
                    )
                    container_entry['has_normalized_ru_metric'] = True
                    normalized_ru_percent = max(normalized_ru_percent or 0, series_value)
            elif metric_name == 'TotalRequestUnits':
                series_value = _metric_value(data_points, 'total')
                if series_value is not None:
                    container_entry['request_units'] += series_value
                    container_entry['has_request_units_metric'] = True
                    total_request_units += series_value

    sorted_containers = sorted(
        containers.values(),
        key=lambda item: (
            item.get('normalized_ru_percent') or 0,
            item.get('request_units') or 0,
        ),
        reverse=True,
    )

    return {
        'window_minutes': window_minutes,
        'normalized_ru_percent': normalized_ru_percent,
        'total_request_units': total_request_units,
        'containers': sorted_containers,
        'container_dimensions_requested': container_dimensions_requested,
        'container_metric_count': sum(1 for item in sorted_containers if item.get('container_name') != 'database'),
    }


def query_cosmos_metrics(settings=None, refresh_id=''):
    """Query Azure Monitor for Cosmos RU utilization and per-container request units."""
    metrics_start = time.perf_counter()
    resource_ids = build_cosmos_resource_ids(settings)
    normalized = normalize_cosmos_throughput_settings(settings)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=normalized['cosmos_throughput_metrics_window_minutes'])

    _log_refresh_event(
        '[CosmosThroughput] Azure Monitor metrics query starting.',
        refresh_id=refresh_id,
        extra={
            'window_minutes': normalized['cosmos_throughput_metrics_window_minutes'],
            'container_metric_filter': build_cosmos_container_metric_filter(resource_ids.get('database_name')),
        },
    )
    request_context = _build_arm_request_context(refresh_id=refresh_id, resource_kind='metrics')
    try:
        response = _query_cosmos_metrics_response(
            resource_ids,
            start_time,
            end_time,
            split_by_container=True,
            request_context=request_context,
        )
        result = _parse_cosmos_metrics_response(
            response,
            resource_ids,
            normalized['cosmos_throughput_metrics_window_minutes'],
            container_dimensions_requested=True,
        )
    except Exception as exc:
        _log_refresh_event(
            '[CosmosThroughput] Azure Monitor container metric query failed; retrying aggregate query.',
            refresh_id=refresh_id,
            extra={
                'window_minutes': normalized['cosmos_throughput_metrics_window_minutes'],
                'error': str(exc),
            },
            level=logging.WARNING,
        )
        try:
            aggregate_response = _query_cosmos_metrics_response(
                resource_ids,
                start_time,
                end_time,
                request_context=request_context,
            )
            result = _parse_cosmos_metrics_response(
                aggregate_response,
                resource_ids,
                normalized['cosmos_throughput_metrics_window_minutes'],
            )
        except Exception as aggregate_exc:
            _log_refresh_event(
                '[CosmosThroughput] Azure Monitor metrics query failed.',
                refresh_id=refresh_id,
                extra={
                    'window_minutes': normalized['cosmos_throughput_metrics_window_minutes'],
                    'elapsed_ms': int((time.perf_counter() - metrics_start) * 1000),
                    'error': str(aggregate_exc),
                },
                level=logging.WARNING,
            )
            raise

    if result.get('normalized_ru_percent') is None or result.get('container_metric_count', 0) == 0:
        try:
            aggregate_response = _query_cosmos_metrics_response(
                resource_ids,
                start_time,
                end_time,
                request_context=request_context,
            )
            aggregate_result = _parse_cosmos_metrics_response(
                aggregate_response,
                resource_ids,
                normalized['cosmos_throughput_metrics_window_minutes'],
            )
            if result.get('normalized_ru_percent') is None:
                result['normalized_ru_percent'] = aggregate_result.get('normalized_ru_percent')
            if result.get('container_metric_count', 0) == 0:
                result['total_request_units'] = aggregate_result.get('total_request_units')
        except Exception as exc:
            _log_refresh_event(
                '[CosmosThroughput] Azure Monitor aggregate metric fallback failed.',
                refresh_id=refresh_id,
                extra={'error': str(exc)},
                level=logging.WARNING,
            )

    _log_refresh_event(
        '[CosmosThroughput] Azure Monitor metrics query completed.',
        refresh_id=refresh_id,
        extra={
            'window_minutes': result['window_minutes'],
            'normalized_ru_percent': result['normalized_ru_percent'],
            'container_dimensions_requested': result.get('container_dimensions_requested', False),
            'container_metric_count': result.get('container_metric_count', 0),
            'elapsed_ms': int((time.perf_counter() - metrics_start) * 1000),
        },
    )
    return result


def merge_container_statuses(settings, container_throughputs=None, metrics=None):
    """Merge ARM container throughput state, Azure Monitor metrics, and saved policies."""
    metrics = metrics or {}
    container_throughputs = container_throughputs or []
    metric_rows = {
        row.get('container_name'): row
        for row in metrics.get('containers', [])
        if row.get('container_name') and row.get('container_name') != 'database'
    }
    throughput_container_names = {
        row.get('container_name')
        for row in container_throughputs
        if row.get('container_name')
    }
    metric_container_names = {name for name in metric_rows.keys() if name}
    all_container_names = sorted(throughput_container_names or metric_container_names)

    throughput_by_container = {
        row.get('container_name'): row
        for row in container_throughputs
        if row.get('container_name')
    }
    merged_rows = []
    for container_name in all_container_names:
        throughput = throughput_by_container.get(container_name, {})
        metric_row = metric_rows.get(container_name)
        request_units = None
        if metric_row and metric_row.get('has_request_units_metric'):
            request_units = metric_row.get('request_units', 0.0)
        policy = get_container_policy(settings, container_name)
        merged_rows.append({
            'container_name': container_name,
            'database_name': (metric_row or {}).get('database_name') or get_cosmos_resource_config(settings).get('database_name'),
            'normalized_ru_percent': (metric_row or {}).get('normalized_ru_percent'),
            'request_units': request_units,
            'mode': throughput.get('mode', 'unknown'),
            'current_ru': throughput.get('current_ru'),
            'is_scalable': throughput.get('is_scalable', False),
            'throughput_not_found': throughput.get('throughput_not_found', False),
            'error': throughput.get('error', ''),
            'has_normalized_ru_metric': bool(metric_row and metric_row.get('has_normalized_ru_metric')),
            'has_request_units_metric': bool(metric_row and metric_row.get('has_request_units_metric')),
            'policy': policy,
            'simplechat_scaling_supported': throughput.get(
                'simplechat_scaling_supported',
                _is_simplechat_scaling_supported(throughput),
            ),
            'simplechat_max_ru': COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
            'portal_managed_scaling_required': throughput.get(
                'portal_managed_scaling_required',
                _is_portal_managed_throughput(throughput),
            ),
            'portal_managed_message': throughput.get('portal_managed_message') or (
                COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE
                if _is_portal_managed_throughput(throughput) else ''
            ),
        })

    return sorted(
        merged_rows,
        key=lambda item: (
            item.get('normalized_ru_percent') or 0,
            item.get('current_ru') or 0,
            item.get('request_units') or 0,
        ),
        reverse=True,
    )


def get_cosmos_throughput_status(settings=None, include_metrics=True, refresh_id=''):
    """Return Cosmos throughput state and recent RU usage for admin display."""
    status_start = time.perf_counter()
    try:
        resource_ids = build_cosmos_resource_ids(settings)
    except CosmosThroughputError as exc:
        _log_refresh_event(
            '[CosmosThroughput] Refresh configuration incomplete.',
            refresh_id=refresh_id,
            extra={'error': str(exc)},
            level=logging.WARNING,
        )
        return {
            'configured': False,
            'error': str(exc),
            'resource': get_cosmos_resource_config(settings),
            'throughput': {},
            'metrics': {},
            'containers': [],
        }

    _log_refresh_event(
        '[CosmosThroughput] Throughput status refresh starting.',
        refresh_id=refresh_id,
        extra={
            'account_name': resource_ids.get('account_name'),
            'database_name': resource_ids.get('database_name'),
            'include_metrics': include_metrics,
        },
    )
    throughput_error = ''
    try:
        throughput = get_database_throughput(settings, refresh_id=refresh_id)
    except Exception as exc:
        throughput_error = str(exc)
        log_event(
            '[CosmosThroughput] Failed to query Cosmos database throughput settings.',
            extra={'error': throughput_error, 'database_id': resource_ids.get('database_id'), 'refresh_id': refresh_id},
            level=logging.WARNING,
        )
        throughput = {
            'scope': 'database',
            'mode': 'unknown',
            'current_ru': None,
            'resource': {},
            'resource_ids': resource_ids,
            'is_scalable': False,
            'error': throughput_error,
        }

    container_throughputs = []
    container_error = ''
    try:
        container_throughputs = get_container_throughputs(settings, resource_ids=resource_ids, refresh_id=refresh_id)
    except Exception as exc:
        container_error = str(exc)
        log_event(
            '[CosmosThroughput] Failed to query Cosmos container throughput settings.',
            extra={'error': container_error, 'database_id': resource_ids.get('database_id'), 'refresh_id': refresh_id},
            level=logging.WARNING,
        )

    metrics = {}
    metric_error = ''
    if include_metrics:
        try:
            metrics = query_cosmos_metrics(settings, refresh_id=refresh_id)
        except Exception as exc:
            metric_error = str(exc)
            log_event(
                '[CosmosThroughput] Failed to query Cosmos metrics.',
                extra={'error': metric_error, 'account_id': resource_ids.get('account_id'), 'refresh_id': refresh_id},
                level=logging.WARNING,
            )

    containers = merge_container_statuses(settings, container_throughputs, metrics)
    capacity_scope = 'database' if throughput.get('is_scalable') else 'container'
    if not any(container.get('is_scalable') for container in containers) and not throughput.get('is_scalable'):
        capacity_scope = 'unscalable'

    status = {
        'configured': True,
        'resource': {
            'subscription_id': resource_ids['subscription_id'],
            'resource_group': resource_ids['resource_group'],
            'account_name': resource_ids['account_name'],
            'database_name': resource_ids['database_name'],
            'account_id': resource_ids['account_id'],
        },
        'throughput': {
            'scope': throughput.get('scope', 'database'),
            'mode': throughput.get('mode'),
            'current_ru': throughput.get('current_ru'),
            'is_scalable': throughput.get('is_scalable'),
            'throughput_not_found': throughput.get('throughput_not_found', False),
            'message': throughput.get('message', ''),
            'simplechat_scaling_supported': throughput.get(
                'simplechat_scaling_supported',
                _is_simplechat_scaling_supported(throughput),
            ),
            'simplechat_max_ru': COSMOS_THROUGHPUT_SIMPLECHAT_MAX_RU,
            'portal_managed_scaling_required': throughput.get(
                'portal_managed_scaling_required',
                _is_portal_managed_throughput(throughput),
            ),
            'portal_managed_message': throughput.get('portal_managed_message') or (
                COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE
                if _is_portal_managed_throughput(throughput) else ''
            ),
        },
        'capacity_scope': capacity_scope,
        'metrics': metrics,
        'containers': containers,
        'throughput_error': throughput_error,
        'metric_error': metric_error,
        'container_error': container_error,
        'last_checked_at': datetime.now(timezone.utc).isoformat(),
    }
    _log_refresh_event(
        '[CosmosThroughput] Throughput status refresh completed.',
        refresh_id=refresh_id,
        extra={
            'capacity_scope': capacity_scope,
            'database_mode': throughput.get('mode'),
            'container_count': len(containers),
            'scalable_container_count': sum(1 for container in containers if container.get('is_scalable')),
            'throughput_error': bool(throughput_error),
            'metric_error': bool(metric_error),
            'container_error': bool(container_error),
            'elapsed_ms': int((time.perf_counter() - status_start) * 1000),
        },
    )
    return status


def calculate_container_scale_decision(settings, status, current_time=None):
    """Decide whether a dedicated container throughput target should scale."""
    normalized = normalize_cosmos_throughput_settings(settings)
    now = current_time or datetime.now(timezone.utc)
    up_candidates = []
    down_candidates = []
    conversion_candidates = []
    portal_managed_candidates = []
    conversion_blocked_count = 0
    scalable_container_count = 0
    metric_container_count = 0

    if not normalized.get('cosmos_throughput_autoscale_enabled'):
        return {'should_scale': False, 'reason': 'disabled'}

    for container in status.get('containers') or []:
        if not container.get('is_scalable') or not container.get('current_ru'):
            continue
        scalable_container_count += 1

        container_name = container.get('container_name')
        policy = normalize_container_policy(
            container_name,
            container.get('policy'),
            normalized,
        )
        if not policy.get('enabled'):
            continue

        observed_percent = container.get('normalized_ru_percent')
        if observed_percent is not None:
            metric_container_count += 1

        current_ru = int(container.get('current_ru'))
        mode = container.get('mode') or 'autoscale'
        if _is_portal_managed_throughput(container):
            threshold_reached = False
            if policy.get('convert_manual_to_autoscale_enabled') and mode == 'manual':
                threshold_reached = True
            if observed_percent is not None:
                threshold_reached = (
                    threshold_reached
                    or (
                        policy.get('auto_scale_up_enabled')
                        and observed_percent >= policy['scale_up_threshold_percent']
                    )
                    or (
                        policy.get('auto_scale_down_enabled')
                        and observed_percent <= policy['scale_down_threshold_percent']
                    )
                )
            if threshold_reached:
                portal_managed_candidates.append(_build_portal_managed_decision(
                    scope='container',
                    container_name=container_name,
                    current_ru=current_ru,
                    observed_percent=observed_percent,
                ))
            continue

        if policy.get('convert_manual_to_autoscale_enabled') and mode == 'manual':
            try:
                conversion_candidates.append(_build_autoscale_conversion_decision(
                    container,
                    policy['min_ru'],
                    policy['max_ru'],
                    ignore_min_limit=policy['ignore_min_limit'],
                    ignore_max_limit=policy['ignore_max_limit'],
                    scope='container',
                    container_name=container_name,
                ))
            except CosmosThroughputError:
                conversion_blocked_count += 1
            continue

        if observed_percent is None:
            continue

        service_minimum = COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU if mode == 'autoscale' else COSMOS_THROUGHPUT_MANUAL_MIN_RU

        if policy.get('auto_scale_up_enabled') and observed_percent >= policy['scale_up_threshold_percent']:
            if not _cooldown_elapsed(policy.get('last_scale_up_at'), policy['scale_up_cooldown_minutes'], now):
                continue
            target_ru = normalize_ru(current_ru + policy['scale_up_step_ru'], mode=mode, direction='up')
            if not policy.get('ignore_max_limit'):
                target_ru = min(target_ru, normalize_ru(policy['max_ru'], mode=mode, direction='up'))
            target_ru = _cap_simplechat_scale_target(target_ru, mode=mode)
            if target_ru > current_ru:
                up_candidates.append({
                    'should_scale': True,
                    'scope': 'container',
                    'container_name': container_name,
                    'direction': 'up',
                    'from_ru': current_ru,
                    'to_ru': target_ru,
                    'observed_percent': observed_percent,
                    'reason': 'container_utilization_above_threshold',
                })
            else:
                portal_managed_candidates.append(_build_portal_managed_decision(
                    scope='container',
                    container_name=container_name,
                    current_ru=current_ru,
                    observed_percent=observed_percent,
                ))

        if policy.get('auto_scale_down_enabled') and observed_percent <= policy['scale_down_threshold_percent']:
            if not _cooldown_elapsed(policy.get('last_scale_down_at'), policy['scale_down_cooldown_minutes'], now):
                continue
            target_ru = normalize_ru(current_ru - policy['scale_down_step_ru'], mode=mode, direction='down')
            if not policy.get('ignore_min_limit'):
                target_ru = max(target_ru, normalize_ru(policy['min_ru'], mode=mode, direction='up'))
            target_ru = max(service_minimum, target_ru)
            if target_ru < current_ru:
                down_candidates.append({
                    'should_scale': True,
                    'scope': 'container',
                    'container_name': container_name,
                    'direction': 'down',
                    'from_ru': current_ru,
                    'to_ru': target_ru,
                    'observed_percent': observed_percent,
                    'reason': 'container_utilization_below_threshold',
                })

    if conversion_candidates:
        return sorted(
            [candidate for candidate in conversion_candidates if candidate],
            key=lambda item: (item['from_ru'], item.get('container_name') or ''),
            reverse=True,
        )[0]
    if up_candidates:
        return sorted(up_candidates, key=lambda item: item['observed_percent'], reverse=True)[0]
    if down_candidates:
        return sorted(down_candidates, key=lambda item: (item['observed_percent'], -item['from_ru']))[0]
    if portal_managed_candidates:
        return sorted(
            portal_managed_candidates,
            key=lambda item: (item.get('observed_percent') or 0, item.get('from_ru') or 0),
            reverse=True,
        )[0]
    if conversion_blocked_count:
        return {
            'should_scale': False,
            'reason': 'manual_to_autoscale_guardrail_blocked',
            'blocked_container_count': conversion_blocked_count,
        }
    if scalable_container_count and not metric_container_count:
        return {
            'should_scale': False,
            'reason': 'container_metrics_unavailable',
            'scalable_container_count': scalable_container_count,
        }

    return {'should_scale': False, 'reason': 'container_thresholds_not_met'}


def parse_utc_datetime(value):
    """Parse a stored timestamp into a timezone-aware UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        parsed_value = value
    else:
        try:
            parsed_value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return None

    if parsed_value.tzinfo is None:
        return parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value.astimezone(timezone.utc)


def _cooldown_elapsed(last_action_at, cooldown_minutes, current_time):
    last_action_time = parse_utc_datetime(last_action_at)
    if not last_action_time:
        return True
    return current_time - last_action_time >= timedelta(minutes=cooldown_minutes)


def _has_scale_action(decision):
    return bool((decision or {}).get('should_scale'))


def _is_container_priority_action(decision):
    return _has_scale_action(decision) and decision.get('direction') in {'convert_to_autoscale', 'up'}


def _calculate_autoscale_conversion_target(throughput, min_ru, max_ru, ignore_min_limit=False, ignore_max_limit=False):
    current_ru = throughput.get('current_ru')
    if not current_ru:
        raise CosmosThroughputError('Current Cosmos throughput could not be determined.')
    if throughput.get('mode') != 'manual':
        raise CosmosThroughputError('Cosmos throughput is not in manual mode.')
    if _is_portal_managed_throughput(throughput):
        raise CosmosThroughputError(COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE)

    target_ru = normalize_ru(int(current_ru), mode='autoscale', direction='up')
    if not ignore_min_limit:
        target_ru = max(target_ru, normalize_ru(min_ru, mode='autoscale', direction='up'))
    if target_ru > _get_simplechat_scaling_limit('autoscale'):
        raise CosmosThroughputError(COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE)
    if not ignore_max_limit:
        max_ru = normalize_ru(max_ru, mode='autoscale', direction='up')
        if target_ru > max_ru:
            raise CosmosThroughputError('Current manual RU/s exceeds the maximum autoscale guardrail.')

    return target_ru


def _build_autoscale_conversion_decision(throughput, min_ru, max_ru, ignore_min_limit=False, ignore_max_limit=False, scope='database', container_name='', observed_percent=None):
    if throughput.get('mode') != 'manual' or not throughput.get('current_ru'):
        return None

    target_ru = _calculate_autoscale_conversion_target(
        throughput,
        min_ru,
        max_ru,
        ignore_min_limit=ignore_min_limit,
        ignore_max_limit=ignore_max_limit,
    )
    decision = {
        'should_scale': True,
        'scope': scope,
        'direction': 'convert_to_autoscale',
        'target_mode': 'autoscale',
        'from_mode': 'manual',
        'to_mode': 'autoscale',
        'from_ru': int(throughput.get('current_ru')),
        'to_ru': target_ru,
        'reason': 'manual_throughput_conversion_requested',
    }
    if container_name:
        decision['container_name'] = container_name
    if observed_percent is not None:
        decision['observed_percent'] = observed_percent
    return decision


def calculate_manual_to_autoscale_target(settings, status, container_name=''):
    """Calculate the native Cosmos autoscale max RU/s for a manual throughput conversion."""
    normalized = normalize_cosmos_throughput_settings(settings)
    if container_name:
        matching_container = next(
            (
                container
                for container in status.get('containers') or []
                if container.get('container_name') == container_name
            ),
            None,
        )
        if not matching_container:
            raise CosmosThroughputError('Container throughput target was not found.')
        policy = normalize_container_policy(container_name, matching_container.get('policy'), normalized)
        return _calculate_autoscale_conversion_target(
            matching_container,
            policy['min_ru'],
            policy['max_ru'],
            ignore_min_limit=policy['ignore_min_limit'],
            ignore_max_limit=policy['ignore_max_limit'],
        )

    return _calculate_autoscale_conversion_target(
        status.get('throughput') or {},
        normalized['cosmos_throughput_min_ru'],
        normalized['cosmos_throughput_max_ru'],
        ignore_min_limit=normalized.get('cosmos_throughput_ignore_min_limit'),
        ignore_max_limit=normalized.get('cosmos_throughput_ignore_max_limit'),
    )


def calculate_scale_decision(settings, status, current_time=None):
    """Decide whether Cosmos throughput should scale based on status and settings."""
    normalized = normalize_cosmos_throughput_settings(settings)
    now = current_time or datetime.now(timezone.utc)
    throughput = status.get('throughput') or {}
    metrics = status.get('metrics') or {}
    current_ru = throughput.get('current_ru')
    mode = throughput.get('mode') or 'autoscale'
    observed_percent = metrics.get('normalized_ru_percent')

    if not normalized.get('cosmos_throughput_autoscale_enabled'):
        return {'should_scale': False, 'reason': 'disabled'}

    container_decision = calculate_container_scale_decision(settings, status, current_time=current_time)
    if not throughput.get('is_scalable') or not current_ru:
        return container_decision
    if _is_portal_managed_throughput(throughput):
        if _has_scale_action(container_decision):
            return container_decision
        threshold_reached = False
        if mode == 'manual' and normalized.get('cosmos_throughput_convert_manual_to_autoscale_enabled'):
            threshold_reached = True
        if observed_percent is not None:
            threshold_reached = (
                threshold_reached
                or (
                    normalized.get('cosmos_throughput_auto_scale_up_enabled')
                    and observed_percent >= normalized['cosmos_throughput_scale_up_threshold_percent']
                )
                or (
                    normalized.get('cosmos_throughput_auto_scale_down_enabled')
                    and observed_percent <= normalized['cosmos_throughput_scale_down_threshold_percent']
                )
            )
        if threshold_reached:
            return _build_portal_managed_decision(
                scope='database',
                current_ru=int(current_ru),
                observed_percent=observed_percent,
            )
    if mode == 'manual' and normalized.get('cosmos_throughput_convert_manual_to_autoscale_enabled'):
        try:
            return _build_autoscale_conversion_decision(
                throughput,
                normalized['cosmos_throughput_min_ru'],
                normalized['cosmos_throughput_max_ru'],
                ignore_min_limit=normalized.get('cosmos_throughput_ignore_min_limit'),
                ignore_max_limit=normalized.get('cosmos_throughput_ignore_max_limit'),
                scope='database',
                observed_percent=observed_percent,
            )
        except CosmosThroughputError as exc:
            if _has_scale_action(container_decision):
                return container_decision
            return {'should_scale': False, 'reason': 'manual_to_autoscale_guardrail_blocked', 'error': str(exc)}

    if observed_percent is None:
        if _is_container_priority_action(container_decision):
            return container_decision
        return {'should_scale': False, 'reason': 'missing_utilization_metric'}

    service_minimum = COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU if mode == 'autoscale' else COSMOS_THROUGHPUT_MANUAL_MIN_RU

    if (
        normalized.get('cosmos_throughput_auto_scale_up_enabled')
        and observed_percent >= normalized['cosmos_throughput_scale_up_threshold_percent']
    ):
        if not _cooldown_elapsed(
            normalized.get('cosmos_throughput_last_scale_up_at'),
            normalized['cosmos_throughput_scale_up_cooldown_minutes'],
            now,
        ):
            return {'should_scale': False, 'reason': 'scale_up_cooldown'}

        target_ru = normalize_ru(
            int(current_ru) + normalized['cosmos_throughput_scale_up_step_ru'],
            mode=mode,
            direction='up',
        )
        if not normalized.get('cosmos_throughput_ignore_max_limit'):
            target_ru = min(target_ru, normalize_ru(normalized['cosmos_throughput_max_ru'], mode=mode, direction='up'))
        target_ru = _cap_simplechat_scale_target(target_ru, mode=mode)
        if target_ru <= int(current_ru):
            if int(current_ru) >= _get_simplechat_scaling_limit(mode):
                return _build_portal_managed_decision(
                    scope='database',
                    current_ru=int(current_ru),
                    observed_percent=observed_percent,
                )
            return {'should_scale': False, 'reason': 'max_limit_reached'}
        database_decision = {
            'should_scale': True,
            'scope': 'database',
            'direction': 'up',
            'from_ru': int(current_ru),
            'to_ru': target_ru,
            'observed_percent': observed_percent,
            'reason': 'utilization_above_threshold',
        }
        if _is_container_priority_action(container_decision):
            if container_decision.get('direction') == 'convert_to_autoscale':
                return container_decision
            if (container_decision.get('observed_percent') or 0) >= observed_percent:
                return container_decision
        return database_decision

    if _is_container_priority_action(container_decision):
        return container_decision

    if (
        normalized.get('cosmos_throughput_auto_scale_down_enabled')
        and observed_percent <= normalized['cosmos_throughput_scale_down_threshold_percent']
    ):
        if not _cooldown_elapsed(
            normalized.get('cosmos_throughput_last_scale_down_at'),
            normalized['cosmos_throughput_scale_down_cooldown_minutes'],
            now,
        ):
            return {'should_scale': False, 'reason': 'scale_down_cooldown'}

        target_ru = normalize_ru(
            int(current_ru) - normalized['cosmos_throughput_scale_down_step_ru'],
            mode=mode,
            direction='down',
        )
        if not normalized.get('cosmos_throughput_ignore_min_limit'):
            target_ru = max(target_ru, normalize_ru(normalized['cosmos_throughput_min_ru'], mode=mode, direction='up'))
        target_ru = max(service_minimum, target_ru)
        if target_ru >= int(current_ru):
            return {'should_scale': False, 'reason': 'min_limit_reached'}
        return {
            'should_scale': True,
            'scope': 'database',
            'direction': 'down',
            'from_ru': int(current_ru),
            'to_ru': target_ru,
            'observed_percent': observed_percent,
            'reason': 'utilization_below_threshold',
        }

    if _has_scale_action(container_decision):
        return container_decision

    return {'should_scale': False, 'reason': 'within_thresholds'}


def build_runtime_update(status=None, decision=None, scale_result=None, error='', settings=None):
    """Build settings fields that record throughput monitor runtime state."""
    status = status or {}
    decision = decision or {}
    scale_result = scale_result or {}
    throughput = status.get('throughput') or {}
    metrics = status.get('metrics') or {}
    current_time = datetime.now(timezone.utc).isoformat()
    update = {
        'cosmos_throughput_last_checked_at': current_time,
        'cosmos_throughput_last_observed_percent': metrics.get('normalized_ru_percent'),
        'cosmos_throughput_last_observed_ru': throughput.get('current_ru'),
        'cosmos_throughput_last_mode': throughput.get('mode'),
        'cosmos_throughput_last_error': error or status.get('throughput_error') or status.get('metric_error') or status.get('container_error') or '',
    }
    if status:
        update['cosmos_throughput_cached_status'] = build_cached_cosmos_throughput_status(status, scale_result)

    if scale_result:
        direction = decision.get('direction') or scale_result.get('direction') or 'manual'
        update.update({
            'cosmos_throughput_last_scale_action': direction,
            'cosmos_throughput_last_scale_at': current_time,
            'cosmos_throughput_last_scale_from_ru': scale_result.get('from_ru'),
            'cosmos_throughput_last_scale_to_ru': scale_result.get('to_ru'),
            'cosmos_throughput_last_scale_reason': decision.get('reason') or scale_result.get('reason') or '',
        })
        if direction == 'up':
            update['cosmos_throughput_last_scale_up_at'] = current_time
        elif direction == 'down':
            update['cosmos_throughput_last_scale_down_at'] = current_time

        if scale_result.get('scope') == 'container' and scale_result.get('container_name'):
            normalized_settings = normalize_cosmos_throughput_settings(settings or {})
            policies = dict(normalized_settings.get('cosmos_throughput_container_policies') or {})
            container_name = scale_result['container_name']
            policy = normalize_container_policy(container_name, policies.get(container_name), normalized_settings)
            if direction == 'up':
                policy['last_scale_up_at'] = current_time
            elif direction == 'down':
                policy['last_scale_down_at'] = current_time
            elif direction == 'convert_to_autoscale':
                policy['last_mode_conversion_at'] = current_time
            policies[container_name] = policy
            update['cosmos_throughput_container_policies'] = policies

    return update


def evaluate_and_apply_cosmos_throughput_scaling(settings, current_time=None, refresh_id=''):
    """Evaluate Cosmos RU usage and apply a scale action when configured thresholds require it."""
    try:
        status = get_cosmos_throughput_status(settings, include_metrics=True, refresh_id=refresh_id)
        decision = calculate_scale_decision(settings, status, current_time=current_time)
        scale_result = None

        if decision.get('should_scale'):
            scale_result = set_database_throughput(
                settings,
                decision['to_ru'],
                initiated_by='background_scheduler',
                reason=decision.get('reason', ''),
                decision=decision,
            )
            scale_result['direction'] = decision.get('direction')
            scale_result['reason'] = decision.get('reason')

        return {
            'status': status,
            'decision': decision,
            'scale_result': scale_result,
            'settings_update': build_runtime_update(status, decision, scale_result, settings=settings),
        }
    except Exception as exc:
        log_event(
            '[CosmosThroughput] Autoscale evaluation failed.',
            extra={'error': str(exc)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return {
            'status': {},
            'decision': {'should_scale': False, 'reason': 'error'},
            'scale_result': None,
            'settings_update': build_runtime_update(error=str(exc)),
            'error': str(exc),
        }


def calculate_manual_scale_target(settings, status, direction, container_name=''):
    """Calculate a manual scale target using configured steps and min/max guards."""
    normalized = normalize_cosmos_throughput_settings(settings)
    if container_name:
        matching_container = next(
            (
                container
                for container in status.get('containers') or []
                if container.get('container_name') == container_name
            ),
            None,
        )
        if not matching_container:
            raise CosmosThroughputError('Container throughput target was not found.')
        throughput = matching_container
        policy = normalize_container_policy(container_name, matching_container.get('policy'), normalized)
        up_step_ru = policy['scale_up_step_ru']
        down_step_ru = policy['scale_down_step_ru']
        min_ru = policy['min_ru']
        max_ru = policy['max_ru']
        ignore_min_limit = policy['ignore_min_limit']
        ignore_max_limit = policy['ignore_max_limit']
    else:
        throughput = status.get('throughput') or {}
        up_step_ru = normalized['cosmos_throughput_scale_up_step_ru']
        down_step_ru = normalized['cosmos_throughput_scale_down_step_ru']
        min_ru = normalized['cosmos_throughput_min_ru']
        max_ru = normalized['cosmos_throughput_max_ru']
        ignore_min_limit = normalized.get('cosmos_throughput_ignore_min_limit')
        ignore_max_limit = normalized.get('cosmos_throughput_ignore_max_limit')

    current_ru = throughput.get('current_ru')
    mode = throughput.get('mode') or 'autoscale'

    if not current_ru:
        raise CosmosThroughputError('Current Cosmos throughput could not be determined.')
    if _is_portal_managed_throughput(throughput):
        raise CosmosThroughputError(COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE)

    if direction == 'up':
        target_ru = normalize_ru(
            int(current_ru) + up_step_ru,
            mode=mode,
            direction='up',
        )
        if not ignore_max_limit:
            target_ru = min(target_ru, normalize_ru(max_ru, mode=mode, direction='up'))
        target_ru = _cap_simplechat_scale_target(target_ru, mode=mode)
        if target_ru <= int(current_ru):
            if int(current_ru) >= _get_simplechat_scaling_limit(mode):
                raise CosmosThroughputError(COSMOS_THROUGHPUT_PORTAL_MANAGED_MESSAGE)
            raise CosmosThroughputError('Maximum RU/s limit is already reached.')
        return target_ru

    if direction == 'down':
        service_minimum = COSMOS_THROUGHPUT_AUTOSCALE_MIN_RU if mode == 'autoscale' else COSMOS_THROUGHPUT_MANUAL_MIN_RU
        target_ru = normalize_ru(
            int(current_ru) - down_step_ru,
            mode=mode,
            direction='down',
        )
        if not ignore_min_limit:
            target_ru = max(target_ru, normalize_ru(min_ru, mode=mode, direction='up'))
        target_ru = max(service_minimum, target_ru)
        if target_ru >= int(current_ru):
            raise CosmosThroughputError('Minimum RU/s limit is already reached.')
        return target_ru

    raise CosmosThroughputError('Scale direction must be up or down.')