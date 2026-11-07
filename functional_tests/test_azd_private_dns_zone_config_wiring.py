# test_azd_private_dns_zone_config_wiring.py
#!/usr/bin/env python3
"""
Functional test for AZD private DNS zone config wiring.
Version: 0.261.333
Implemented in: 0.240.006
Enhanced in: 0.261.333 (Refs #1765)

This test ensures that AZD deployments can pass private DNS zone reuse settings
through the PRIVATE_DNS_ZONE_CONFIGS environment value instead of silently
forcing privateDnsZoneConfigs to an empty object.
"""

from pathlib import Path
import importlib.util
import ipaddress
import json
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest
import yaml

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"
PARAMETERS_PATH = REPO_ROOT / "deployers" / "bicep" / "main.parameters.json"
PREREQUISITES_PATH = REPO_ROOT / "deployers" / "bicep" / "validate_azd_prerequisites.py"
README_PATH = REPO_ROOT / "deployers" / "bicep" / "README.md"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_azd_private_dns_zone_configs_are_wired() -> None:
    print("🧪 Testing AZD private DNS zone config parameter wiring")
    print("=" * 70)

    parameters_content = PARAMETERS_PATH.read_text(encoding="utf-8")
    prerequisites_content = PREREQUISITES_PATH.read_text(encoding="utf-8")
    readme_content = README_PATH.read_text(encoding="utf-8")

    require_contains(
        parameters_content,
        '"value": "${PRIVATE_DNS_ZONE_CONFIGS}"',
        "AZD parameter pass-through for privateDnsZoneConfigs",
    )
    require_contains(
        prerequisites_content,
        "AZURE_ENV_PRIVATE_DNS_ZONE_CONFIGS",
        "preprovision AZD environment variable lookup",
    )
    require_contains(
        prerequisites_content,
        "PRIVATE_DNS_ZONE_CONFIGS",
        "preprovision local environment variable lookup",
    )
    require_contains(
        readme_content,
        "PRIVATE_DNS_ZONE_CONFIGS",
        "README guidance for AZD private DNS zone configuration",
    )
    assert_app_version_at_least("0.240.006")

    print("✅ AZD parameters file passes PRIVATE_DNS_ZONE_CONFIGS into Bicep")
    print("✅ Preprovision validation reads PRIVATE_DNS_ZONE_CONFIGS before deployment")
    print("✅ README documents the AZD environment variable path")
    print("✅ Config version was updated for the fix")


def load_prerequisites():
    spec = importlib.util.spec_from_file_location('networking_prerequisites_under_test', PREREQUISITES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_monitor_private_link_preflight():
    module = load_prerequisites()
    with patch.object(module, '_run_command') as command:
        disabled = module._validate_monitor_private_link(False, False, '')
        invalid = module._validate_monitor_private_link(False, True, '')
        new_network = module._validate_monitor_private_link(True, True, '')
    assert disabled and new_network and not invalid
    command.assert_not_called()

    for prefix, expected in [('10.0.2.0/28', False), ('10.0.2.0/27', True), ('10.0.2.0/26', True)]:
        with patch.object(module, '_run_command', return_value=(0, json.dumps({'addressPrefix': prefix}), '')) as command:
            valid = module._validate_monitor_private_link(True, True, '/subscriptions/test/subnets/pe')
        assert valid is expected
        assert command.call_args.args[0][1:5] == ['network', 'vnet', 'subnet', 'show']

    with patch.object(module, '_run_command', return_value=(1, '', 'access denied')):
        failed = module._validate_monitor_private_link(True, True, '/subnet')
    assert not failed

    with patch.object(module, '_run_command', return_value=(0, '{"addressPrefix":"not-a-network"}', '')):
        malformed = module._validate_monitor_private_link(True, True, '/subnet')
    assert not malformed


def test_monitor_invalid_combination_stops_before_azure_calls():
    module = load_prerequisites()
    with patch.dict(module.os.environ, {'ENABLE_AZURE_MONITOR_PRIVATE_LINK': 'true', 'ENABLE_PRIVATE_NETWORKING': 'false'}, clear=True), patch.object(module, '_run_command') as command:
        result = module.main()
    assert result == 1
    command.assert_not_called()


def test_cloud_dns_and_private_endpoint_contracts():
    modules = REPO_ROOT / 'deployers' / 'bicep' / 'modules'
    zones = json.loads((modules / 'privateDNSZones.json').read_text(encoding='utf-8'))
    commercial = zones['azurecloud']
    government = zones['azureusgovernment']
    assert government['keyVault'] == 'privatelink.vaultcore.usgovcloudapi.net'
    assert commercial['videoIndexer'] == 'privatelink.api.videoindexer.ai'
    assert government['videoIndexer'] == ''
    assert commercial['redisManaged'] == 'privatelink.redis.azure.net'
    assert government['redisClassic'] == 'privatelink.redis.cache.usgovcloudapi.net'
    assert government['redisManaged'] == ''
    for key, suffix in [('monitor', 'monitor.azure.us'), ('monitorAdx', 'adx.monitor.azure.us'), ('monitorOms', 'oms.opinsights.azure.us'), ('monitorOds', 'ods.opinsights.azure.us'), ('monitorAgent', 'agentsvc.azure-automation.us')]:
        assert government[key] == f'privatelink.{suffix}'
    assert commercial['monitorAdx'] == ''

    networking = (modules / 'privateNetworking.bicep').read_text(encoding='utf-8')
    video = networking[networking.index("module videoIndexerPE "):]
    assert 'videoIndexerDNSZone!.outputs.privateDnsZoneId' in video
    assert 'docIntelDNSZone.outputs.privateDnsZoneId' not in video
    assert "redisCacheKind == 'managed' ? 'redisEnterprise' : 'redisCache'" in networking


def test_ampls_template_and_azd_wiring():
    modules = REPO_ROOT / 'deployers' / 'bicep' / 'modules'
    template = json.loads((modules.parent / 'main.json').read_text(encoding='utf-8'))
    parameters = json.loads(PARAMETERS_PATH.read_text(encoding='utf-8'))['parameters']
    assert parameters['enableAzureMonitorPrivateLink']['value'] == '${ENABLE_AZURE_MONITOR_PRIVATE_LINK=false}'
    assert template['parameters']['enableAzureMonitorPrivateLink']['defaultValue'] is False
    monitor = (modules / 'azureMonitorPrivateNetworking.bicep').read_text(encoding='utf-8')
    assert "ingestionAccessMode: 'PrivateOnly'" in monitor
    assert "queryAccessMode: 'PrivateOnly'" in monitor
    assert "groupIDs: ['azuremonitor']" in monitor
    assert 'take(zoneConfigs, 4)' in monitor
    assert '[blobStorageDnsZoneId]' in monitor
    assert "module adxDnsRecords 'privateDNSRecords.bicep'" in monitor
    assert 'monitorNic.properties.ipConfigurations' in monitor
    assert 'endsWith(entry.fqdn' in monitor
    for filename in ['applicationInsights.bicep', 'logAnalyticsWorkspace.bicep']:
        content = (modules / filename).read_text(encoding='utf-8')
        assert "publicNetworkAccessForIngestion: enableAzureMonitorPrivateLink ? 'Disabled' : 'Enabled'" in content
        assert "publicNetworkAccessForQuery: enableAzureMonitorPrivateLink ? 'Disabled' : 'Enabled'" in content
    assert_app_version_at_least('0.261.333')


def test_redis_lockdown_in_both_azd_hooks():
    manifest = yaml.safe_load((REPO_ROOT / 'deployers' / 'azure.yaml').read_text(encoding='utf-8'))
    for platform in ['posix', 'windows']:
        hook = manifest['hooks']['postup'][platform]['run']
        assert 'var_redisCacheResourceId' in hook
        assert '2025-07-01' in hook and '2024-11-01' in hook
        assert 'properties.publicNetworkAccess=Disabled' in hook
        assert hook.index('var_enablePrivateNetworking') < hook.index('Disabling public network access for Redis')


def test_fresh_and_compact_network_tables():
    guide = (REPO_ROOT / 'docs' / 'guides' / 'enterprise-networking.md').read_text(encoding='utf-8')
    for cloud in ['Commercial', 'Government']:
        section = guide.split(f'### Networking in Azure {cloud}', 1)[1].split('\n### ', 1)[0]
        assert '**Fresh deployment defaults:**' in section
        assert '**Compact existing-network reference:**' in section
        compact_subnets = []
        fresh_subnets = []
        for row in section.splitlines():
            cells = [cell.strip().replace('`', '').replace('*', '') for cell in row.split('|')]
            if len(cells) < 7 or cells[1] not in {'AppServiceIntegration', 'PrivateEndpoints'} and not cells[1].startswith('snet-'):
                continue
            network = ipaddress.IPv4Network(cells[2])
            assert int(cells[3]) == network.num_addresses
            assert int(cells[4]) == network.num_addresses - 5
            if cells[1].startswith('snet-'):
                compact_subnets.append(network)
            else:
                fresh_subnets.append(network)

        assert len(compact_subnets) == 5 and len(fresh_subnets) == 2
        for subnet_index, subnet in enumerate(compact_subnets):
            assert subnet.subnet_of(ipaddress.IPv4Network('10.42.0.0/24'))
            for neighbor in compact_subnets[subnet_index + 1:]:
                assert not subnet.overlaps(neighbor)
        assert sum(subnet.num_addresses for subnet in compact_subnets) == 208
        assert sum(subnet.num_addresses for subnet in fresh_subnets) == 512
        assert '**48**' in section and '**1536**' in section
        assert '10.42.0.64/26' in section

    template = json.loads((REPO_ROOT / 'deployers' / 'bicep' / 'main.json').read_text(encoding='utf-8'))
    network_parameters = template['resources']['virtualNetwork']['properties']['parameters']
    assert network_parameters['addressSpaces']['value'] == ['10.0.0.0/21']
    assert [subnet['addressPrefix'] for subnet in network_parameters['subnetConfigs']['value']] == ['10.0.0.0/24', '10.0.2.0/24']

    for path in ['docs/deploy/special-scenarios.md', 'deployers/bicep/README.md', 'deployers/terraform/ReadMe.md', 'deployers/azurecli/README.md', 'artifacts/PRIVATE_ENDPOINTS_NETWORK_REFERENCE.md']:
        reference = (REPO_ROOT / path).read_text(encoding='utf-8')
        assert 'enterprise-networking.md#networking-in-azure-commercial' in reference
        assert 'enterprise-networking.md#networking-in-azure-government' in reference


def test_cli_monitor_failure_and_existing_dns_reconciliation():
    powershell = shutil.which('pwsh')
    if not powershell:
        pytest.skip('PowerShell is required for CLI mock execution.')
    script_path = str(REPO_ROOT / 'deployers' / 'azurecli' / 'deploy-simplechat.ps1').replace("'", "''")
    harness = r"""
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('__SCRIPT_PATH__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'CLI script does not parse' }
$names = @('Test-PrivateNetworkingConfiguration', 'Configure-PrivateNetworkingForDeployment', 'Ensure-PrivateEndpoint', 'Show-PrivateNetworkingChecklist')
foreach ($definition in $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    if ($definition.Name -in $names) {
        $definitionText = $definition.Extent.Text.Replace('$PSScriptRoot', "(Split-Path '__SCRIPT_PATH__')")
        . ([scriptblock]::Create($definitionText))
    }
}
$global:mockNetworkCalls = [System.Collections.Generic.List[string]]::new()
$global:mockMonitorDeploymentFails = $true
function az {
    $commandText = $args -join ' '
    $global:mockNetworkCalls.Add($commandText)
    $global:LASTEXITCODE = 0
    if ($commandText.StartsWith('network vnet subnet show')) { return '{"addressPrefix":"10.42.0.64/26"}' }
    if ($commandText.StartsWith('deployment group create') -and $global:mockMonitorDeploymentFails) { $global:LASTEXITCODE = 7; return }
    return '/subscriptions/test/resourceGroups/network/providers/test/resource'
}
function Ensure-PrivateNetworkingInfrastructure {
    $script:ResolvedVirtualNetworkId = '/vnet'
    $script:ResolvedPrivateEndpointSubnetId = '/subnet'
    $script:ResolvedAppServiceSubnetId = '/outbound'
}
function Ensure-PrivateDnsZone { param($ZoneKey) return '/zones/videoIndexer' }
function Get-PrivateDnsZoneConfig { param($ZoneKey) return @{ ZoneName = 'privatelink.api.videoindexer.ai' } }
function Update-ResourcePropertiesById { param($ResourceId, $PropertyAssignments, $DisplayName) }
$paramBaseName = 'test'
$paramEnvironment = 'dev'
$paramLocation = 'eastus'
$resourceGroupName = 'test-rg'
$appServiceName = 'test-app'
$appInsightsName = 'test-ai'
$logAnalyticsWorkspaceId = '/workspaces/test-law'
$tags = @{}
$param_PrivateDnsZoneConfigs = @{}
$param_DeployVideoIndexerService = $false
$globalWhichAzurePlatform = 'AzureCloud'
$param_EnableAzureMonitorPrivateLink = $true
$param_EnablePrivateNetworking = $false
try { Test-PrivateNetworkingConfiguration; throw 'Expected invalid combination failure' } catch {
    if ($_.Exception.Message -notlike '*requires param_EnablePrivateNetworking*') { throw }
}
if ($global:mockNetworkCalls.Count) { throw 'Invalid options contacted Azure' }
Configure-PrivateNetworkingForDeployment -OpenAiResourceId ''
if ($global:mockNetworkCalls.Count) { throw 'Disabled networking contacted Azure' }

Ensure-PrivateEndpoint -NameSuffix videoIndexer -ServiceResourceId '/videoIndexer' -GroupId account -ZoneKey videoIndexer
$dnsWrites = @($global:mockNetworkCalls | Where-Object { $_.StartsWith('network private-endpoint dns-zone-group create') })
if ($dnsWrites.Count -ne 1 -or $dnsWrites[0] -notlike '*privatelink.api.videoindexer.ai*') { throw 'Existing PE DNS was not reconciled' }
function Ensure-PrivateEndpoint { param($NameSuffix, $ServiceResourceId, $GroupId, $ZoneKey) }
$global:mockNetworkCalls.Clear()
$param_EnablePrivateNetworking = $true
$param_EnableAzureMonitorPrivateLink = $false
$script:SupportedPrivateDnsZoneKeys = @('blobStorage', 'monitor', 'monitorAdx', 'videoIndexer')
$param_AllowedIpAddresses = @()
$checklist = Show-PrivateNetworkingChecklist 6>&1 | Out-String
if ($checklist -like '*monitor =>*' -or $checklist -like '*monitorAdx =>*' -or $checklist -like '*videoIndexer =>*') { throw 'Disabled optional DNS zones appear in checklist' }
$param_EnableAzureMonitorPrivateLink = $true
try { Configure-PrivateNetworkingForDeployment -OpenAiResourceId ''; throw 'Expected AMPLS failure' } catch {
    if ($_.Exception.Message -notlike 'Failed to deploy AMPLS*') { throw }
}
$lockdown = @($global:mockNetworkCalls | Where-Object { $_.StartsWith('resource update') -and $_ -like '*publicNetworkAccessForIngestion*' })
if ($lockdown.Count) { throw 'Monitoring was locked down before AMPLS succeeded' }

$global:mockNetworkCalls.Clear()
$global:mockMonitorDeploymentFails = $false
Configure-PrivateNetworkingForDeployment -OpenAiResourceId ''
$lockdown = @($global:mockNetworkCalls | Where-Object { $_.StartsWith('resource update') -and $_ -like '*publicNetworkAccessForIngestion=Disabled*' -and $_ -like '*publicNetworkAccessForQuery=Disabled*' })
if ($lockdown.Count -ne 2) { throw 'Both monitoring resources must be locked down after AMPLS success' }
Write-Output 'CLI mock checks passed'
""".replace('__SCRIPT_PATH__', script_path)
    result = subprocess.run([powershell, '-NoProfile', '-Command', harness], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CLI mock checks passed' in result.stdout


if __name__ == "__main__":
    try:
        test_azd_private_dns_zone_configs_are_wired()
        test_monitor_private_link_preflight()
        test_monitor_invalid_combination_stops_before_azure_calls()
        test_cloud_dns_and_private_endpoint_contracts()
        test_ampls_template_and_azd_wiring()
        test_redis_lockdown_in_both_azd_hooks()
        test_fresh_and_compact_network_tables()
        test_cli_monitor_failure_and_existing_dns_reconciliation()
        success = True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)