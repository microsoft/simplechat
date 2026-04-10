# Private DNS Zone Configs AZD Wiring Fix

Fixed/Implemented in version: **0.240.006**

## Issue Description

The Bicep deployment supported `privateDnsZoneConfigs`, and the documentation described how to
reuse centrally managed private DNS zones, but AZD deployments could not actually supply a non-empty
value.

`deployers/bicep/main.parameters.json` hard-coded `privateDnsZoneConfigs` to `{}`, so `azd up` and
`azd provision` always sent an empty object to the infrastructure template even when the user had
prepared valid JSON for private DNS zone reuse.

## Root Cause Analysis

The infrastructure template, module wiring, prerequisite validator, and README were already aligned
around a `PRIVATE_DNS_ZONE_CONFIGS` input path, but the AZD parameters file never forwarded that
environment value into the deployment.

That created a mismatch where:

- documentation described a supported deployment option
- preprovision validation accepted and explained the JSON object
- the actual AZD deployment path silently discarded the value

## Technical Details

### Files Modified

- `deployers/bicep/main.parameters.json`
- `deployers/bicep/README.md`
- `functional_tests/test_azd_private_dns_zone_config_wiring.py`
- `application/single_app/config.py`

### Code Changes Summary

- Replaced the hard-coded empty object in `main.parameters.json` with the `PRIVATE_DNS_ZONE_CONFIGS`
  AZD environment placeholder.
- Added README guidance that tells AZD users to provide the private DNS configuration through the
  AZD environment value rather than editing the parameter file directly.
- Added a focused functional regression test that verifies the parameter wiring, prerequisite lookup,
  documentation guidance, and version update.
- Bumped the application version to `0.240.006`.

### Testing Approach

- Added `functional_tests/test_azd_private_dns_zone_config_wiring.py`.
- The test validates that:
  - AZD parameter substitution now forwards `PRIVATE_DNS_ZONE_CONFIGS`
  - preprovision validation still reads the expected environment values
  - deployment documentation mentions the AZD-specific configuration path
  - the config version reflects the fix

## Validation

### Before

- AZD deployments always passed `{}` for `privateDnsZoneConfigs`
- private DNS reuse worked in the Bicep template only if parameters were supplied outside the AZD flow
- README guidance for `privateDnsZoneConfigs` did not describe the AZD environment variable path clearly

### After

- AZD deployments can pass a JSON object through `PRIVATE_DNS_ZONE_CONFIGS`
- the existing prerequisite validator and Bicep template now align with the actual AZD deployment path
- users have explicit documentation for how to supply the setting during `azd up`

### Impact Analysis

This fix is limited to the AZD parameter pass-through path for private networking.

- deployments that leave `PRIVATE_DNS_ZONE_CONFIGS` empty still default to automatic private DNS zone creation
- deployments that reuse enterprise-managed private DNS zones can now do so through the standard AZD workflow
- no private networking resource behavior changed beyond receiving the intended parameter value