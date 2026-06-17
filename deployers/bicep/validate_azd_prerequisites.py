#!/usr/bin/env python3
# validate_azd_prerequisites.py
"""
Validate and explain deployment prerequisites before `azd provision` or `azd up` continues.

Version: 0.242.057
Implemented in: 0.237.018
Enhanced in: 0.242.057

This script ensures users understand the prerequisites for reusing an existing VNet
and for configuring private DNS zones when private networking is enabled. It also
fails fast when managed identity authentication is selected but the deployment
identity cannot create the required RBAC assignments.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import urllib.request


MANAGED_IDENTITY_AUTHENTICATION_TYPE = 'managed_identity'
MANAGED_IDENTITY_REQUIRED_PERMISSION_ACTIONS = (
    'Microsoft.Authorization/roleAssignments/write',
    'Microsoft.Authorization/roleDefinitions/write',
)


def _to_bool(value: str | None) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y'}


def _normalize_token(value: str | None) -> str:
    return str(value or '').strip().lower().replace('-', '_').replace(' ', '_')


def _get_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != '':
            return value
    return ''


def _print_header(title: str) -> None:
    print('')
    print('=' * 80)
    print(title)
    print('=' * 80)


def _run_command(command: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 127, '', f'Command not found: {command[0]}'

    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _get_target_subscription_id() -> tuple[str | None, str | None]:
    subscription_id = _get_env(
        'AZURE_SUBSCRIPTION_ID',
        'AZURE_ENV_AZURE_SUBSCRIPTION_ID',
        'AZURE_ENV_SUBSCRIPTION_ID',
        'SUBSCRIPTION_ID',
    ).strip()
    if subscription_id:
        return subscription_id, None

    exit_code, stdout, stderr = _run_command(['az', 'account', 'show', '--query', 'id', '-o', 'tsv'])
    if exit_code != 0 or not stdout:
        return None, stderr or stdout or 'Unable to resolve the active Azure subscription with Azure CLI.'

    return stdout, None


def _get_resource_manager_endpoint() -> tuple[str | None, str | None]:
    exit_code, stdout, stderr = _run_command([
        'az',
        'cloud',
        'show',
        '--query',
        'endpoints.resourceManager',
        '-o',
        'tsv',
    ])
    if exit_code != 0 or not stdout:
        return None, stderr or stdout or 'Unable to resolve the Azure Resource Manager endpoint.'

    return stdout.rstrip('/'), None


def _get_target_resource_group_name() -> str:
    explicit_resource_group = _get_env(
        'AZURE_ENV_RG_NAME',
        'RG_NAME',
        'var_rgName',
    ).strip()
    if explicit_resource_group:
        return explicit_resource_group

    app_name = _get_env(
        'AZURE_ENV_DEPLOYMENT_APPNAME',
        'DEPLOYMENT_APPNAME',
        'env_DEPLOYMENT_APPNAME',
    ).strip()
    environment_name = _get_env(
        'AZURE_ENV_ENVIRONMENT',
        'ENVIRONMENT',
        'environment',
        'AZURE_ENV_NAME',
    ).strip()

    if app_name and environment_name:
        return f'{app_name}-{environment_name}-rg'

    return ''


def _resource_group_exists(subscription_id: str, resource_group_name: str) -> bool:
    if not resource_group_name:
        return False

    exit_code, stdout, _ = _run_command([
        'az',
        'group',
        'exists',
        '--subscription',
        subscription_id,
        '--name',
        resource_group_name,
        '-o',
        'tsv',
    ])
    return exit_code == 0 and stdout.strip().lower() == 'true'


def _get_managed_identity_permission_scopes(subscription_id: str) -> list[str]:
    resource_group_name = _get_target_resource_group_name()
    if resource_group_name and _resource_group_exists(subscription_id, resource_group_name):
        scopes = [f'/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}']
    else:
        scopes = [f'/subscriptions/{subscription_id}']

    existing_openai_name = _get_env(
        'AZURE_ENV_EXISTING_AZURE_OPENAI_RESOURCE_NAME',
        'EXISTING_AZURE_OPENAI_RESOURCE_NAME',
    ).strip()
    existing_openai_resource_group = _get_env(
        'AZURE_ENV_EXISTING_AZURE_OPENAI_RESOURCE_GROUP',
        'EXISTING_AZURE_OPENAI_RESOURCE_GROUP',
    ).strip()
    existing_openai_subscription_id = _get_env(
        'AZURE_ENV_EXISTING_AZURE_OPENAI_SUBSCRIPTION_ID',
        'EXISTING_AZURE_OPENAI_SUBSCRIPTION_ID',
    ).strip() or subscription_id

    if existing_openai_name and existing_openai_resource_group:
        openai_scope = f'/subscriptions/{existing_openai_subscription_id}/resourceGroups/{existing_openai_resource_group}'
        if openai_scope not in scopes:
            scopes.append(openai_scope)

    return scopes


def _get_permissions_for_scope(scope: str, resource_manager_endpoint: str) -> tuple[list[dict] | None, str | None]:
    permissions_url = (
        f'{resource_manager_endpoint}{scope}'
        '/providers/Microsoft.Authorization/permissions?api-version=2022-04-01'
    )
    exit_code, stdout, stderr = _run_command([
        'az',
        'rest',
        '--method',
        'get',
        '--url',
        permissions_url,
        '-o',
        'json',
    ])
    if exit_code != 0:
        return None, stderr or stdout or f'Unable to list effective permissions for {scope}.'

    try:
        payload = json.loads(stdout or '{}')
    except json.JSONDecodeError as exc:
        return None, f'Unable to parse Azure permissions response for {scope}: {exc}'

    permission_entries = payload.get('value') if isinstance(payload, dict) else payload
    if not isinstance(permission_entries, list):
        return None, f'Azure permissions response for {scope} did not contain a permission list.'

    return permission_entries, None


def _action_pattern_matches(pattern: str, action: str) -> bool:
    return fnmatch.fnmatchcase(action.lower(), pattern.lower())


def _permissions_allow_action(permission_entries: list[dict], action: str) -> bool:
    for permission_entry in permission_entries:
        actions = permission_entry.get('actions') or []
        not_actions = permission_entry.get('notActions') or []

        if not any(_action_pattern_matches(pattern, action) for pattern in actions):
            continue

        if any(_action_pattern_matches(pattern, action) for pattern in not_actions):
            continue

        return True

    return False


def _print_managed_identity_failure(failures: list[tuple[str, list[str], str | None]]) -> None:
    print('', file=sys.stderr)
    print('ERROR: Managed identity authentication was selected, but the current Azure identity', file=sys.stderr)
    print('cannot validate or create all required deployment RBAC assignments.', file=sys.stderr)
    print('', file=sys.stderr)
    print('Missing or unverified permissions:', file=sys.stderr)
    for scope, missing_actions, error in failures:
        print(f'- Scope: {scope}', file=sys.stderr)
        if error:
            print(f'  Validation error: {error}', file=sys.stderr)
        for action in missing_actions:
            print(f'  Required action: {action}', file=sys.stderr)

    print('', file=sys.stderr)
    print('Use an Azure identity with Owner, Role Based Access Control Administrator,', file=sys.stderr)
    print('or an equivalent custom role at the listed scopes, then rerun azd.', file=sys.stderr)
    print('', file=sys.stderr)
    print('To continue with key-based authentication instead, run:', file=sys.stderr)
    print('  azd env set AUTHENTICATION_TYPE key', file=sys.stderr)
    print('Then rerun azd provision or azd up.', file=sys.stderr)


def _validate_managed_identity_preflight() -> bool:
    authentication_type = _normalize_token(_get_env(
        'AZURE_ENV_AUTHENTICATION_TYPE',
        'AUTHENTICATION_TYPE',
        'var_authenticationType',
    ))
    if authentication_type != MANAGED_IDENTITY_AUTHENTICATION_TYPE:
        return True

    configure_permissions_value = _get_env(
        'AZURE_ENV_CONFIGURE_APPLICATION_PERMISSIONS',
        'CONFIGURE_APPLICATION_PERMISSIONS',
    ).strip()
    if configure_permissions_value and not _to_bool(configure_permissions_value):
        print('', file=sys.stderr)
        print('ERROR: Managed identity authentication requires CONFIGURE_APPLICATION_PERMISSIONS=true', file=sys.stderr)
        print('so the deployer can create the application RBAC assignments.', file=sys.stderr)
        print('', file=sys.stderr)
        print('Set CONFIGURE_APPLICATION_PERMISSIONS=true and rerun azd with an identity that can', file=sys.stderr)
        print('create role assignments, or switch to key-based authentication with:', file=sys.stderr)
        print('  azd env set AUTHENTICATION_TYPE key', file=sys.stderr)
        return False

    _print_header('MANAGED IDENTITY PREFLIGHT')
    print('Managed identity authentication selected. Validating RBAC assignment permissions...')

    subscription_id, subscription_error = _get_target_subscription_id()
    if subscription_error or not subscription_id:
        _print_managed_identity_failure([
            ('target subscription', list(MANAGED_IDENTITY_REQUIRED_PERMISSION_ACTIONS), subscription_error),
        ])
        return False

    resource_manager_endpoint, endpoint_error = _get_resource_manager_endpoint()
    if endpoint_error or not resource_manager_endpoint:
        _print_managed_identity_failure([
            (f'/subscriptions/{subscription_id}', list(MANAGED_IDENTITY_REQUIRED_PERMISSION_ACTIONS), endpoint_error),
        ])
        return False

    failures = []
    for scope in _get_managed_identity_permission_scopes(subscription_id):
        permission_entries, permission_error = _get_permissions_for_scope(scope, resource_manager_endpoint)
        if permission_error or permission_entries is None:
            failures.append((scope, list(MANAGED_IDENTITY_REQUIRED_PERMISSION_ACTIONS), permission_error))
            continue

        missing_actions = [
            action
            for action in MANAGED_IDENTITY_REQUIRED_PERMISSION_ACTIONS
            if not _permissions_allow_action(permission_entries, action)
        ]
        if missing_actions:
            failures.append((scope, missing_actions, None))

    if failures:
        _print_managed_identity_failure(failures)
        return False

    print('Managed identity RBAC preflight passed.')
    return True


def _parse_private_dns(raw_value: str | None) -> tuple[dict, str | None]:
    if not raw_value or not raw_value.strip():
        return {}, None

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        return {}, f'privateDnsZoneConfigs is not valid JSON: {exc}'

    if not isinstance(parsed, dict):
        return {}, 'privateDnsZoneConfigs must be a JSON object.'

    return parsed, None


def _confirm_to_continue() -> bool:
    if _to_bool(os.getenv('CI')) or _to_bool(os.getenv('AZD_NONINTERACTIVE')):
        return True

    try:
        response = input('\nType CONTINUE to proceed with deployment, or anything else to stop: ').strip()
    except EOFError:
        return False

    return response == 'CONTINUE'


def _parse_allowed_ip_ranges(raw_value: str | None) -> list[str]:
    if not raw_value or not raw_value.strip():
        return []

    return [value.strip() for value in raw_value.split(',') if value.strip()]


def _get_runner_public_ip() -> str:
    with urllib.request.urlopen('https://api.ipify.org', timeout=10) as response:
        return response.read().decode().strip()


def _persist_allowed_ip_ranges(updated_ranges: str) -> tuple[bool, str | None]:
    command = ['azd', 'env', 'set', 'ALLOWED_IP_RANGES', updated_ranges]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error_output = (result.stderr or result.stdout or '').strip()
        return False, error_output or 'Unknown azd env set failure.'

    os.environ['ALLOWED_IP_RANGES'] = updated_ranges
    os.environ['AZURE_ENV_ALLOWED_IP_RANGES'] = updated_ranges
    return True, None


def _ensure_runner_ip_is_allowed(enable_private_networking: bool) -> None:
    if not enable_private_networking:
        return

    configured_ranges = _parse_allowed_ip_ranges(_get_env('AZURE_ENV_ALLOWED_IP_RANGES', 'ALLOWED_IP_RANGES'))

    try:
        runner_public_ip = _get_runner_public_ip()
    except Exception as exc:
        print('')
        print('WARNING: Could not resolve the deployment runner public IP automatically.')
        print(f'  Details: {exc}')
        print('  If this runner must reach Cosmos DB or Azure Container Registry over a public network path,')
        print('  set ALLOWED_IP_RANGES manually before rerunning azd.')
        return

    if runner_public_ip in configured_ranges:
        print('')
        print(f'Runner public IP {runner_public_ip} is already present in ALLOWED_IP_RANGES.')
        return

    updated_ranges_list = configured_ranges + [runner_public_ip]
    updated_ranges = ','.join(dict.fromkeys(updated_ranges_list))
    persisted, error_output = _persist_allowed_ip_ranges(updated_ranges)

    print('')
    if persisted:
        print(f'Added deployment runner public IP {runner_public_ip} to ALLOWED_IP_RANGES for this AZD environment.')
        print('This makes the runner IP available to Cosmos DB and Azure Container Registry firewall rules during provisioning.')
        print('If you later add firewall rules manually in Azure Portal, allow up to 30 minutes for the change to propagate before rerunning azd up.')
    else:
        print(f'WARNING: Failed to persist deployment runner public IP {runner_public_ip} into ALLOWED_IP_RANGES.')
        print(f'  Details: {error_output}')
        print('  If this runner needs public access to protected resources, set ALLOWED_IP_RANGES manually before rerunning azd.')


def main() -> int:
    enable_private_networking = _to_bool(_get_env('AZURE_ENV_ENABLE_PRIVATE_NETWORKING', 'ENABLE_PRIVATE_NETWORKING'))
    existing_vnet_id = _get_env('AZURE_ENV_EXISTING_VNET_RESOURCE_ID', 'EXISTING_VNET_RESOURCE_ID').strip()
    app_subnet_id = _get_env('AZURE_ENV_EXISTING_APP_SERVICE_SUBNET_RESOURCE_ID', 'EXISTING_APP_SERVICE_SUBNET_RESOURCE_ID').strip()
    pe_subnet_id = _get_env('AZURE_ENV_EXISTING_PRIVATE_ENDPOINT_SUBNET_RESOURCE_ID', 'EXISTING_PRIVATE_ENDPOINT_SUBNET_RESOURCE_ID').strip()
    private_dns_raw = _get_env('AZURE_ENV_PRIVATE_DNS_ZONE_CONFIGS', 'PRIVATE_DNS_ZONE_CONFIGS')

    if not _validate_managed_identity_preflight():
        return 1

    if not enable_private_networking:
        return 0

    _ensure_runner_ip_is_allowed(enable_private_networking)

    dns_config, dns_error = _parse_private_dns(private_dns_raw)
    if dns_error:
        print(f'ERROR: {dns_error}', file=sys.stderr)
        return 1

    if existing_vnet_id:
        _print_header('PRIVATE NETWORKING PREREQUISITES: EXISTING VNET SELECTED')
        print('You selected private networking and supplied an existing VNet resource ID.')
        print('Before deployment continues, verify these prerequisites are already in place:')
        print('')
        print('- Existing VNet is reachable and approved for this deployment')
        print('- Existing App Service integration subnet already exists')
        print('- Existing private endpoint subnet already exists')
        print('- App Service integration subnet is delegated to Microsoft.Web/serverFarms')
        print('- Cross-resource-group or cross-subscription access is approved if applicable')
        print('- Private DNS zones and VNet links are planned correctly')

        missing = []
        if not app_subnet_id:
            missing.append('AZURE_ENV_EXISTING_APP_SERVICE_SUBNET_RESOURCE_ID')
        if not pe_subnet_id:
            missing.append('AZURE_ENV_EXISTING_PRIVATE_ENDPOINT_SUBNET_RESOURCE_ID')

        if missing:
            print('')
            print('ERROR: Existing VNet reuse requires the following values:', file=sys.stderr)
            for item in missing:
                print(f'- {item}', file=sys.stderr)
            print('', file=sys.stderr)
            print('Pause and supply the missing subnet resource IDs before running azd again.', file=sys.stderr)
            return 1
    else:
        _print_header('PRIVATE NETWORKING PREREQUISITES: NEW VNET WILL BE CREATED')
        print('You selected private networking without an existing VNet resource ID.')
        print('The deployment will create the VNet and required subnets for you.')

    _print_header('PRIVATE DNS ZONE BEHAVIOR')
    if not dns_config:
        print('No privateDnsZoneConfigs value was provided.')
        print('The deployment will create the supported private DNS zones locally and create VNet links automatically.')
    else:
        print('privateDnsZoneConfigs was provided.')
        print('The deployment may reuse one or more existing private DNS zones instead of creating them locally.')
        print('Verify each reused zone is correct for the service and cloud environment.')
        print('')
        for zone_name, zone_config in dns_config.items():
            if not isinstance(zone_config, dict):
                print(f'- {zone_name}: invalid value; expected an object')
                continue
            zone_resource_id = zone_config.get('zoneResourceId')
            create_vnet_link = zone_config.get('createVNetLink', True)
            if zone_resource_id:
                print(f'- {zone_name}: reuse zone {zone_resource_id}')
            else:
                print(f'- {zone_name}: create zone in deployment resource group')
            if create_vnet_link:
                print(f'  - VNet link will be created automatically for {zone_name}')
            else:
                print(f'  - VNet link will NOT be created automatically for {zone_name}')
                print('    Ensure the zone is already linked to the target VNet, or name resolution will fail.')

    print('')
    print('Required private DNS coverage commonly includes:')
    print('- privatelink.azurewebsites.net')
    print('- privatelink.documents.azure.com')
    print('- privatelink.blob.core.windows.net')
    print('- privatelink.search.windows.net')
    print('- privatelink.openai.azure.com')
    print('- privatelink.cognitiveservices.azure.com')

    if not _confirm_to_continue():
        print('Deployment stopped. Review prerequisites, then rerun azd when ready.', file=sys.stderr)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
