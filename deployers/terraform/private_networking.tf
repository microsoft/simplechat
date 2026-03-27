####################################################################################################
# File:         private_networking.tf
# Description:  Terraform private networking support for the Simple Chat deployment.
# Author:       Microsoft Federal
# Created:      2026-Mar-11
####################################################################################################

provider "azapi" {}

variable "param_enable_private_networking" {
  description = "Set to true to enable private endpoints and App Service VNet integration."
  type        = bool
  default     = false
}

variable "param_existing_virtual_network_id" {
  description = "Optional existing virtual network resource ID to reuse when private networking is enabled."
  type        = string
  default     = ""
}

variable "param_existing_app_service_subnet_id" {
  description = "Optional existing subnet resource ID to use for App Service VNet integration."
  type        = string
  default     = ""
}

variable "param_existing_private_endpoint_subnet_id" {
  description = "Optional existing subnet resource ID to use for private endpoints."
  type        = string
  default     = ""
}

variable "param_private_network_address_space" {
  description = "Address spaces to use when Terraform creates a new virtual network for private networking."
  type        = list(string)
  default     = ["10.0.0.0/21"]
}

variable "param_app_service_integration_subnet_prefixes" {
  description = "Address prefixes to use when Terraform creates the App Service integration subnet."
  type        = list(string)
  default     = ["10.0.0.0/24"]
}

variable "param_private_endpoint_subnet_prefixes" {
  description = "Address prefixes to use when Terraform creates the private endpoint subnet."
  type        = list(string)
  default     = ["10.0.2.0/24"]
}

variable "param_private_dns_zone_configs" {
  description = "Optional per-zone configuration for private DNS create or reuse behavior. Supported keys: keyVault, cosmosDb, containerRegistry, aiSearch, blobStorage, cognitiveServices, openAi, webSites."
  type = map(object({
    zone_resource_id = optional(string, "")
    create_vnet_link = optional(bool, true)
  }))
  default = {}

  validation {
    condition = length(setsubtract(
      toset(keys(var.param_private_dns_zone_configs)),
      toset(["keyVault", "cosmosDb", "containerRegistry", "aiSearch", "blobStorage", "cognitiveServices", "openAi", "webSites"])
    )) == 0
    error_message = "param_private_dns_zone_configs only supports these keys: keyVault, cosmosDb, containerRegistry, aiSearch, blobStorage, cognitiveServices, openAi, webSites."
  }
}

locals {
  inferred_virtual_network_id          = var.param_existing_app_service_subnet_id != "" ? regexreplace(var.param_existing_app_service_subnet_id, "/subnets/[^/]+$", "") : (var.param_existing_private_endpoint_subnet_id != "" ? regexreplace(var.param_existing_private_endpoint_subnet_id, "/subnets/[^/]+$", "") : "")
  resolved_existing_virtual_network_id = var.param_existing_virtual_network_id != "" ? var.param_existing_virtual_network_id : local.inferred_virtual_network_id
  use_existing_private_network         = var.param_enable_private_networking && (local.resolved_existing_virtual_network_id != "" || var.param_existing_app_service_subnet_id != "" || var.param_existing_private_endpoint_subnet_id != "")

  private_dns_zone_names = var.global_which_azure_platform == "AzureUSGovernment" ? {
    aiSearch          = "privatelink.search.azure.us"
    blobStorage       = "privatelink.blob.core.usgovcloudapi.net"
    cognitiveServices = "privatelink.cognitiveservices.azure.us"
    containerRegistry = "privatelink.azurecr.us"
    cosmosDb          = "privatelink.documents.azure.us"
    keyVault          = "privatelink.vaultcore.azure.us"
    openAi            = "privatelink.openai.azure.us"
    webSites          = "privatelink.azurewebsites.us"
    } : {
    aiSearch          = "privatelink.search.windows.net"
    blobStorage       = "privatelink.blob.core.windows.net"
    cognitiveServices = "privatelink.cognitiveservices.azure.com"
    containerRegistry = "privatelink.azurecr.io"
    cosmosDb          = "privatelink.documents.azure.com"
    keyVault          = "privatelink.vaultcore.azure.net"
    openAi            = "privatelink.openai.azure.com"
    webSites          = "privatelink.azurewebsites.net"
  }

  private_dns_zone_link_suffixes = {
    aiSearch          = "searchService"
    blobStorage       = "storage"
    cognitiveServices = "docIntelService"
    containerRegistry = "acr"
    cosmosDb          = "cosmosDb"
    keyVault          = "kv"
    openAi            = "openAiService"
    webSites          = "webApp"
  }

  resolved_private_dns_zone_configs = {
    for zone_key, zone_name in local.private_dns_zone_names : zone_key => {
      name             = zone_name
      zone_resource_id = try(var.param_private_dns_zone_configs[zone_key].zone_resource_id, "")
      create_vnet_link = try(var.param_private_dns_zone_configs[zone_key].create_vnet_link, true)
      link_name        = lower("${var.param_base_name}-${var.param_environment}-${local.private_dns_zone_link_suffixes[zone_key]}-pe-dnszonelink")
    }
  }
}

resource "terraform_data" "private_networking_validation" {
  input = {
    private_networking_enabled = var.param_enable_private_networking
  }

  lifecycle {
    precondition {
      condition     = !var.param_enable_private_networking || !local.use_existing_private_network || (var.param_existing_app_service_subnet_id != "" && var.param_existing_private_endpoint_subnet_id != "")
      error_message = "When reusing an existing virtual network for private networking, both param_existing_app_service_subnet_id and param_existing_private_endpoint_subnet_id must be provided."
    }

    precondition {
      condition     = !var.param_enable_private_networking || !local.use_existing_private_network || local.resolved_existing_virtual_network_id != ""
      error_message = "When reusing an existing virtual network for private networking, Terraform must be able to resolve the virtual network ID from param_existing_virtual_network_id or one of the provided subnet IDs."
    }
  }
}

resource "azurerm_virtual_network" "private" {
  count               = var.param_enable_private_networking && !local.use_existing_private_network ? 1 : 0
  name                = lower("${var.param_base_name}-${var.param_environment}-vnet")
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = var.param_private_network_address_space
  tags                = local.common_tags

  depends_on = [terraform_data.private_networking_validation]
}

resource "azurerm_subnet" "app_service_integration" {
  count                = var.param_enable_private_networking && !local.use_existing_private_network ? 1 : 0
  name                 = "AppServiceIntegration"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.private[0].name
  address_prefixes     = var.param_app_service_integration_subnet_prefixes

  private_endpoint_network_policies             = "Enabled"
  private_link_service_network_policies_enabled = true

  delegation {
    name = "delegation"

    service_delegation {
      name = "Microsoft.Web/serverFarms"
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  count                = var.param_enable_private_networking && !local.use_existing_private_network ? 1 : 0
  name                 = "PrivateEndpoints"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.private[0].name
  address_prefixes     = var.param_private_endpoint_subnet_prefixes

  private_endpoint_network_policies             = "Enabled"
  private_link_service_network_policies_enabled = true
}

locals {
  resolved_virtual_network_id         = var.param_enable_private_networking ? (local.use_existing_private_network ? local.resolved_existing_virtual_network_id : azurerm_virtual_network.private[0].id) : ""
  resolved_app_service_subnet_id      = var.param_enable_private_networking ? (local.use_existing_private_network ? var.param_existing_app_service_subnet_id : azurerm_subnet.app_service_integration[0].id) : null
  resolved_private_endpoint_subnet_id = var.param_enable_private_networking ? (local.use_existing_private_network ? var.param_existing_private_endpoint_subnet_id : azurerm_subnet.private_endpoints[0].id) : null
}

resource "azurerm_private_dns_zone" "managed" {
  for_each = {
    for zone_key, zone in local.resolved_private_dns_zone_configs : zone_key => zone
    if var.param_enable_private_networking && zone.zone_resource_id == ""
  }

  name                = each.value.name
  resource_group_name = azurerm_resource_group.rg.name
}

locals {
  private_dns_zone_ids = merge(
    {
      for zone_key, zone in local.resolved_private_dns_zone_configs : zone_key => zone.zone_resource_id
      if zone.zone_resource_id != ""
    },
    {
      for zone_key, zone in azurerm_private_dns_zone.managed : zone_key => zone.id
    }
  )
}

resource "azapi_resource" "private_dns_zone_link" {
  for_each = {
    for zone_key, zone in local.resolved_private_dns_zone_configs : zone_key => zone
    if var.param_enable_private_networking && zone.create_vnet_link
  }

  type                      = "Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01"
  name                      = each.value.link_name
  parent_id                 = each.value.zone_resource_id != "" ? each.value.zone_resource_id : azurerm_private_dns_zone.managed[each.key].id
  location                  = "global"
  schema_validation_enabled = false

  body = {
    properties = {
      registrationEnabled = false
      virtualNetwork = {
        id = local.resolved_virtual_network_id
      }
    }
  }

  depends_on = [
    terraform_data.private_networking_validation,
    azurerm_virtual_network.private,
    azurerm_private_dns_zone.managed,
  ]
}

locals {
  openai_private_endpoint_resource_id = var.param_use_existing_openai_instance ? (local.use_existing_openai_resource_metadata ? data.azurerm_cognitive_account.existing_openai[0].id : "") : azurerm_cognitive_account.openai[0].id

  private_endpoint_targets = var.param_enable_private_networking ? merge(
    {
      keyVault = {
        name         = "kv"
        resource_id  = azurerm_key_vault.kv.id
        subresource  = "vault"
        dns_zone_key = "keyVault"
      }
      cosmosDb = {
        name         = "cosmosdb"
        resource_id  = azurerm_cosmosdb_account.cosmos.id
        subresource  = "sql"
        dns_zone_key = "cosmosDb"
      }
      containerRegistry = {
        name         = "acr"
        resource_id  = data.azurerm_container_registry.acrregistry.id
        subresource  = "registry"
        dns_zone_key = "containerRegistry"
      }
      aiSearch = {
        name         = "search"
        resource_id  = azurerm_search_service.search.id
        subresource  = "searchService"
        dns_zone_key = "aiSearch"
      }
      blobStorage = {
        name         = "storage"
        resource_id  = azurerm_storage_account.sa.id
        subresource  = "blob"
        dns_zone_key = "blobStorage"
      }
      cognitiveServices = {
        name         = "docintel"
        resource_id  = azurerm_cognitive_account.docintel.id
        subresource  = "account"
        dns_zone_key = "cognitiveServices"
      }
      webSites = {
        name         = "webapp"
        resource_id  = azurerm_linux_web_app.app.id
        subresource  = "sites"
        dns_zone_key = "webSites"
      }
    },
    local.openai_private_endpoint_resource_id != "" ? {
      openAi = {
        name         = "openai"
        resource_id  = local.openai_private_endpoint_resource_id
        subresource  = "account"
        dns_zone_key = "openAi"
      }
    } : {},
    var.param_deploy_video_indexer_service && local.video_indexer_supports_private_endpoints ? {
      videoIndexer = {
        name         = "videoindexer"
        resource_id  = azapi_resource.video_indexer[0].id
        subresource  = "account"
        dns_zone_key = "cognitiveServices"
      }
    } : {}
  ) : {}
}

resource "azurerm_private_endpoint" "service" {
  for_each = local.private_endpoint_targets

  name                = lower("${var.param_base_name}-${var.param_environment}-${each.value.name}-pe")
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = local.resolved_private_endpoint_subnet_id
  tags                = local.common_tags

  private_service_connection {
    name                           = lower("${var.param_base_name}-${var.param_environment}-${each.value.name}-psc")
    private_connection_resource_id = each.value.resource_id
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = lower("${var.param_base_name}-${var.param_environment}-${each.value.name}-dns")
    private_dns_zone_ids = [local.private_dns_zone_ids[each.value.dns_zone_key]]
  }

  depends_on = [
    terraform_data.private_networking_validation,
    azapi_resource.private_dns_zone_link,
  ]
}

output "virtual_network_id" {
  description = "The virtual network ID used for private networking, if enabled."
  value       = local.resolved_virtual_network_id
}

output "app_service_subnet_id" {
  description = "The App Service VNet integration subnet ID used for private networking, if enabled."
  value       = local.resolved_app_service_subnet_id
}

output "private_endpoint_subnet_id" {
  description = "The private endpoint subnet ID used for private networking, if enabled."
  value       = local.resolved_private_endpoint_subnet_id
}
