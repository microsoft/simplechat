#!/usr/bin/env python3
"""
Validate and explain deployment prerequisites before `azd provision` or `azd up` continues.

Version: 0.237.018
Implemented in: 0.237.018

This script ensures users understand the prerequisites for reusing an existing VNet
and for configuring private DNS zones when private networking is enabled.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request


def _to_bool(value: str | None) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y'}


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
