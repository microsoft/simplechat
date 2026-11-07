# Optional Azure Monitor Private Link (v0.261.333)

Implemented in version: **0.261.333**. Deployer version: **1.0.34**.
Related issue: [#1765](https://github.com/microsoft/simplechat/issues/1765).
The application version is recorded in `application/single_app/config.py`.

## Purpose and Dependencies

Private monitoring keeps telemetry ingestion and monitoring queries on private network paths. Administrators opt in at deployment time; public monitoring remains the default. Requires private networking, linked private DNS, a `/27` or larger endpoint subnet with at least 11 monitoring IPs, and private routes for senders and query clients.

## Architecture and Configuration

`deployers/bicep/modules/azureMonitorPrivateNetworking.bicep` owns the AMPLS, two scoped resource associations, private endpoint, and cloud-aware DNS. Its generated ARM template is reused by Terraform and CLI. Blob DNS comes from the existing Storage zone. The endpoint DNS group contains five zones; Government ADX DNS is linked separately, with matching endpoint NIC metadata grouped into A-record sets by `privateDNSRecords.bicep`.

Bicep/AZD uses `enableAzureMonitorPrivateLink` / `ENABLE_AZURE_MONITOR_PRIVATE_LINK`; Terraform uses `param_enable_azure_monitor_private_link`; PowerShell uses `param_EnableAzureMonitorPrivateLink`. All default false and require private networking. Monitoring resources deny public ingestion and queries when enabled, with AMPLS access modes set to `PrivateOnly`. Per-zone reuse uses the existing DNS override object.

## Administration

See the [Enterprise Networking guide](../../guides/enterprise-networking.md) for Commercial and Government **fresh deployment defaults**, **compact existing-network reference**, subnet/IP tables, DNS, opt-in commands, and shared-DNS considerations. Fresh deployments create one shared endpoint subnet, not the segmented reference.

Coordinate one AMPLS per shared DNS boundary. This option creates a new scope; where enterprise AMPLS exists, have its owner associate these monitoring resources instead. Reprovision Government overflow records after endpoint DNS/IP changes. Incremental Bicep/CLI deployment does not remove an old scope or DNS configuration when the option is disabled. No application UI route or API is added.

## Testing and Limitations

`functional_tests/test_azd_private_dns_zone_config_wiring.py` covers preflight failures/successes, cloud DNS, template wiring, and Redis hooks. Bicep compilation validates the resource graph and artifacts; Terraform validation and PowerShell parsing check adapters. Live telemetry and queries still require a cloud environment. AMPLS does not privatize all control-plane requests or external services. Coordinate explicit cleanup and validate all affected clients before changing shared DNS.
