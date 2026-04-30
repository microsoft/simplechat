# Terraform Private Networking Parity

Fixed/Implemented in version: **0.237.020**

## Overview

This feature brings the Terraform deployer closer to the Bicep deployer for private networking scenarios.

Terraform now supports:

- Creating a deployment VNet when private networking is enabled
- Reusing an existing VNet and existing subnets by resource ID
- Creating private endpoints for the core Simple Chat dependencies
- Creating private DNS zones automatically when customer-managed zones are not supplied
- Reusing existing private DNS zones by resource ID
- Creating per-zone VNet links, with the option to suppress link creation when networking teams manage that separately

## Dependencies

- Terraform `azurerm` provider
- Terraform `azuread` provider
- Terraform `azapi` provider for cross-scope private DNS VNet links
- Existing Azure OpenAI metadata when Azure OpenAI private endpoint automation is required for a reused resource

## Architecture Overview

The Terraform implementation now mirrors the Bicep private networking shape by using:

1. A dedicated App Service integration subnet
2. A dedicated private endpoint subnet
3. Private endpoints for Key Vault, Cosmos DB, Storage, Azure AI Search, Azure OpenAI, Document Intelligence, Container Registry, and the App Service
4. Private DNS zones for each private-link-enabled dependency
5. Optional reuse of enterprise-managed private DNS zones

## Configuration

Key Terraform variables:

- `param_enable_private_networking`
- `param_existing_virtual_network_id`
- `param_existing_app_service_subnet_id`
- `param_existing_private_endpoint_subnet_id`
- `param_private_dns_zone_configs`
- `param_existing_azure_openai_resource_name`
- `param_existing_azure_openai_resource_group_name`
- `param_existing_azure_openai_subscription_id`

## Usage Notes

- If you reuse an existing VNet, provide both existing subnet IDs.
- If central IT manages private DNS VNet links, set `create_vnet_link = false` for the relevant zone entries.
- Endpoint-only Azure OpenAI reuse still supports application configuration, but it does not provide enough Azure resource metadata for Terraform to automate the Azure OpenAI private endpoint.

## Validation

Validation completed with:

- `terraform fmt`
- `terraform init -upgrade`
- `terraform validate`

## Related Files

- `deployers/terraform/main.tf`
- `deployers/terraform/private_networking.tf`
- `deployers/terraform/ReadMe.md`
- `application/single_app/config.py`
