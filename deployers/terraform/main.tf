####################################################################################################
# File:         main.tf
# Description:  Terraform configuration for deploying the Simple Chat application on Azure Government. (Extensible for Azure Commercial)
# Author:       Microsoft Federal
# Created:      2025-May-15
# Version:      <v1.0.0>
####################################################################################################
#
# Disclaimer:
#
# - This script is provided as-is and is not officially supported by Microsoft.
# - It is intended for educational purposes and may require modifications to fit specific use cases.
# - Ensure you have the necessary permissions and configurations in your Azure environment before deploying.
#
# Notes:
#
# - This Terraform script has been tested deploying the Simple Chat application to Azure Government.
# - It includes resources such as Azure Container Registry, App Service, Cosmos DB, OpenAI, and more.
#
####################################################################################################

terraform {
  required_version = ">= 1.12.0"
  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = ">= 3.4.0"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.29, < 5.0.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.1.0"
    }
  }
}

# Configure the AzureRM Provider for Azure Government
provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    cognitive_account {
      purge_soft_delete_on_destroy = true
    }
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
    log_analytics_workspace {
      permanently_delete_on_destroy = true
    }
  }
  storage_use_azuread = true
  environment = var.global_which_azure_platform == "AzureUSGovernment" ? "usgovernment" : (var.global_which_azure_platform == "AzureCloud" ? "public" : null)
  tenant_id   = var.param_tenant_id
  subscription_id = var.param_subscription_id
}

# Configure the AzureAD Provider
provider "azuread" {
  environment = var.global_which_azure_platform == "AzureUSGovernment" ? "usgovernment" : (var.global_which_azure_platform == "AzureCloud" ? "public" : null)
  tenant_id = var.param_tenant_id
}

# Variables
variable "global_which_azure_platform" {
  description = "Set to 'AzureUSGovernment' for Azure Government, 'AzureCloud' for Azure Commercial."
  type        = string
  default     = "AzureUSGovernment" # Default from script
  validation {
    condition     = contains(["AzureUSGovernment", "AzureCloud"], var.global_which_azure_platform)
    error_message = "Invalid Azure platform. Must be 'AzureUSGovernment' or 'AzureCloud'."
  }
}

variable "param_subscription_id" {
  description = "Your Azure Subscription ID."
  type        = string
}

variable "param_tenant_id" {
  description = "Your Azure AD Tenant ID."
  type        = string
}

variable "param_location" {
  description = "Primary Azure Government region for deployments (e.g., usgovvirginia, usgovarizona, usgovtexas)."
  type        = string
}

variable "param_resource_owner_id" {
  description = "Used for tagging resources (e.g., Tom Jones)."
  type        = string
}

variable "param_resource_owner_email_id" {
  description = "Used for tagging resources (e.g., somebody@somebody.onmicrosoft.us)."
  type        = string
}


variable "param_environment" {
  description = "Environment identifier (e.g., dev, test, prod, uat)."
  type        = string
}

variable "param_base_name" {
  description = "A short base name for your organization or project (e.g., contoso1, projectx2)."
  type        = string
}

variable "acr_name" {
  description = "Azure Container Registry name (must be globally unique, lowercase alphanumeric)."
  type        = string
}

variable "acr_resource_group_name" {
  description = "Azure Container Registry resource group name."
  type        = string
}

variable "image_name" {
  description = "Container image name (e.g., simple-chat:2025-05-15_7)."
  type        = string
}

variable "param_use_existing_openai_instance" {
  description = "Set to true to use an existing Azure OpenAI instance."
  type        = bool
}

variable "param_existing_azure_openai_resource_name" {
  description = "Existing Azure OpenAI resource name."
  type        = string
}

variable "param_existing_azure_openai_resource_group_name" {
  description = "Existing Azure OpenAI resource group name."
  type        = string
}

variable "param_create_entra_security_groups" {
  description = "Set to true to create Entra ID security groups."
  type        = bool
  default     = true # Default from script
}

# ACR Credentials (assumed to be available for Terraform)
variable "acr_username" {
  description = "Username for the Azure Container Registry."
  type        = string
  sensitive   = true
}

variable "acr_password" {
  description = "Password for the Azure Container Registry."
  type        = string
  sensitive   = true
}

# Resource Naming Convention (matching PowerShell script logic)
locals {
  resource_group_name         = "sc-${var.param_base_name}-${var.param_environment}-rg"
  app_registration_name       = "${var.param_base_name}-${var.param_environment}-ar"
  app_service_plan_name       = "${var.param_base_name}-${var.param_environment}-asp"
  app_service_name            = "${var.param_base_name}-${var.param_environment}-app"
  app_insights_name           = "${var.param_base_name}-${var.param_environment}-ai"
  cosmos_db_name              = "${var.param_base_name}-${var.param_environment}-cosmos"
  open_ai_name                = "${var.param_base_name}-${var.param_environment}-oai"
  doc_intel_name              = "${var.param_base_name}-${var.param_environment}-docintel"
  key_vault_name              = "${var.param_base_name}-${var.param_environment}-kv"
  log_analytics_name          = "${var.param_base_name}-${var.param_environment}-la"
  managed_identity_name       = "${var.param_base_name}-${var.param_environment}-id"
  search_service_name         = "${var.param_base_name}-${var.param_environment}-search"
  storage_account_base        = "${var.param_base_name}${var.param_environment}sa"
  storage_account_name        = substr(replace(local.storage_account_base, "/[^a-z0-9]/", ""), 0, 24)
  
  acr_base_url                = var.global_which_azure_platform == "AzureUSGovernment" ? "${var.acr_name}.azurecr.us" : "${var.acr_name}.azurecr.io"  
  param_registry_server   = var.global_which_azure_platform == "AzureUSGovernment" ? "https://${var.acr_name}.azurecr.us" : "https://${var.acr_name}.azurecr.io"

  app_service_fqdn_suffix = var.global_which_azure_platform == "AzureUSGovernment" ? ".azurewebsites.us" : ".azurewebsites.net"
  graph_url               = var.global_which_azure_platform == "AzureUSGovernment" ? "https://graph.microsoft.us" : "https://graph.microsoft.com"
  cosmos_db_url_template  = var.global_which_azure_platform == "AzureUSGovernment" ? "https://%s.documents.azure.us:443/" : "https://%s.documents.azure.com:443/"
  openai_url_template     = var.global_which_azure_platform == "AzureUSGovernment" ? "https://%s.openai.azure.us/" : "https://%s.openai.azure.com/"

  # Tags for resources
  common_tags = {
    Environment     = var.param_environment
    Owner           = var.param_resource_owner_id
    #CreatedDateTime = formatdate("YYYY-MM-DD hh:mm:ss", timestamp()) # time part causes updates to resources on update. Stopping this.
    CreatedDateTime = formatdate("YYYY-MM-DD", timestamp())
    Project         = "SimpleChat"
  }
}

data "azuread_user" "owner_user" {
  user_principal_name = var.param_resource_owner_email_id
}

data "azuread_user" "application_owner" {
  user_principal_name = var.param_resource_owner_email_id
}

data "azuread_client_config" "current" {}

data "azurerm_container_registry" "acrregistry" {
  name                = var.acr_name
  resource_group_name = var.acr_resource_group_name
}

# --- Entra ID Security Groups ---
resource "azuread_group" "simplechat_admins" {
  count        = var.param_create_entra_security_groups ? 1 : 0
  display_name = "${var.param_base_name}-${var.param_environment}-sg-Admins"
  mail_nickname = "${var.param_base_name}-${var.param_environment}-sg-Admins"
  description  = "Security group for ${var.param_base_name} ${var.param_environment} environment"
  security_enabled = true
}

resource "azuread_group" "simplechat_users" {
  count        = var.param_create_entra_security_groups ? 1 : 0
  display_name = "${var.param_base_name}-${var.param_environment}-sg-Users"
  mail_nickname = "${var.param_base_name}-${var.param_environment}-sg-Users"
  description  = "Security group for ${var.param_base_name} ${var.param_environment} environment"
  security_enabled = true
}

resource "azuread_group" "simplechat_creategroup" {
  count        = var.param_create_entra_security_groups ? 1 : 0
  display_name = "${var.param_base_name}-${var.param_environment}-sg-CreateGroup"
  mail_nickname = "${var.param_base_name}-${var.param_environment}-sg-CreateGroup"
  description  = "Security group for ${var.param_base_name} ${var.param_environment} environment"
  security_enabled = true
}

resource "azuread_group" "simplechat_safetyviolationadmin" {
  count        = var.param_create_entra_security_groups ? 1 : 0
  display_name = "${var.param_base_name}-${var.param_environment}-sg-SafetyViolationAdmin"
  mail_nickname = "${var.param_base_name}-${var.param_environment}-sg-SafetyViolationAdmin"
  description  = "Security group for ${var.param_base_name} ${var.param_environment} environment"
  security_enabled = true
}

resource "azuread_group" "simplechat_feedbackadmin" {
  count        = var.param_create_entra_security_groups ? 1 : 0
  display_name = "${var.param_base_name}-${var.param_environment}-sg-FeedbackAdmin"
  mail_nickname = "${var.param_base_name}-${var.param_environment}-sg-FeedbackAdmin"
  description  = "Security group for ${var.param_base_name} ${var.param_environment} environment"
  security_enabled = true
}

# --- Resource Group ---
resource "azurerm_resource_group" "rg" {
  name     = local.resource_group_name
  location = var.param_location
  tags     = local.common_tags
}

# --- Log Analytics Workspace ---
resource "azurerm_log_analytics_workspace" "la" {
  name                = local.log_analytics_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018" # Pay-as-you-go SKU
  tags                = local.common_tags
}

# --- Key Vault ---
# Note: Terraform does not directly recover deleted Key Vaults.
# If a Key Vault exists in soft-deleted state, you might need to recover it manually
# or destroy/re-create the resource group if recovery is not an option.
resource "azurerm_key_vault" "kv" {
  name                        = local.key_vault_name
  location                    = azurerm_resource_group.rg.location
  resource_group_name         = azurerm_resource_group.rg.name
  enabled_for_disk_encryption = false
  purge_protection_enabled    = false # Set to true in production
  sku_name                    = "standard" # or "premium"
  tenant_id                   = var.param_tenant_id

  # Using RBAC authorization as recommended by the script
  # The script attempts to get current user's object ID for initial permissions
  # In Terraform, we can assign roles after creation.
  rbac_authorization_enabled = true

  tags = local.common_tags
}

# Grant "Key Vault Secrets Officer" role to the deploying user/service principal
# This typically requires the `client_id` or `object_id` of the user/SP running Terraform.
# For simplicity, assuming the running user/SP is the intended Secrets Officer.
# In a CI/CD pipeline, the service principal running Terraform would be assigned this.
resource "azurerm_role_assignment" "kv_secrets_officer_current_user" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azuread_client_config.current.object_id
}


# --- Application Insights ---
resource "azurerm_application_insights" "ai" {
  name                = local.app_insights_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.la.id
  tags                = local.common_tags
}

# --- Storage Account ---
resource "azurerm_storage_account" "sa" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # Standard_LRS
  account_kind             = "StorageV2"
  access_tier              = "Hot"
  allow_nested_items_to_be_public =  false
  public_network_access_enabled = false # From script's allow-blob-public-access false
  shared_access_key_enabled = false
  tags                     = local.common_tags
}

# --- User-Assigned Managed Identity ---
resource "azurerm_user_assigned_identity" "id" {
  name                = local.managed_identity_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
}

# Grant Managed Identity access to Key Vault secrets (get/list)
resource "azurerm_role_assignment" "kv_secrets_user_managed_identity" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.id.principal_id
}

# --- App Service Plan ---
resource "azurerm_service_plan" "asp" {
  name                = local.app_service_plan_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux" # Script uses --is-linux
  sku_name            = "P1v3" # Basic tier, 1 core, 1.75GB RAM.
  # ["B1" "B2" "B3" "S1" "S2" "S3" "P1v2" "P2v2" "P3v2" "P0v3" "P1v3" "P2v3" "P3v3" 
  # "P1mv3" "P2mv3" "P3mv3" "P4mv3" "P5mv3" "Y1" "EP1" "EP2" "EP3" "FC1" "F1" 
  # "I1" "I2" "I3" "I1v2" "I2v2" "I3v2" "I4v2" "I5v2" "I6v2" "I1mv2" "I2mv2" 
  # "I3mv2" "I4mv2" "I5mv2" "D1" "SHARED" "WS1" "WS2" "WS3"]
  tags                = local.common_tags
}

# --- App Service (Web App) ---
resource "azurerm_linux_web_app" "app" {
  name                = local.app_service_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  service_plan_id     = azurerm_service_plan.asp.id
  ftp_publish_basic_authentication_enabled = false
  webdeploy_publish_basic_authentication_enabled = false   

  # auth_settings {
  #     enabled                 = true
  #     default_provider         = "azure_active_directory"
  #     token_store_enabled     = true
  #     active_directory {
  #       allowed_audiences = [
  #         format("https://%s%s/.auth/login/aad/callback", local.app_service_name, local.app_service_fqdn_suffix),
  #         format("https://%s%s/.auth/login/aad/callback", local.app_service_name, local.app_service_fqdn_suffix),
  #       ]
  #       client_id = azuread_application.app_registration.client_id
  #       client_secret_setting_name = "AZURE_CLIENT_SECRET" # This is the secret name in Key Vault
  #     }
  # }

  auth_settings_v2 {
    auth_enabled           = true
    unauthenticated_action = "RedirectToLoginPage"
    default_provider       = "azureactivedirectory"
    require_authentication = true
    require_https          = true

    active_directory_v2 {
      client_id = azuread_application.app_registration.client_id
      client_secret_setting_name = "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET" # This should be allowed optional
      tenant_auth_endpoint       = var.global_which_azure_platform == "AzureUSGovernment" ? "https://login.microsoftonline.us/${data.azuread_client_config.current.tenant_id}/v2.0" : "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/v2.0"
    }

    login {
      token_store_enabled = true
    }
  }

  app_settings = {
    "AZURE_ENDPOINT"                = var.global_which_azure_platform == "AzureUSGovernment" ? "usgovernment" : "public"
    "SCM_DO_BUILD_DURING_DEPLOYMENT" = "false"
    "AZURE_COSMOS_AUTHENTICATION_TYPE" = "key"
    "AZURE_COSMOS_ENDPOINT"         = format(local.cosmos_db_url_template, azurerm_cosmosdb_account.cosmos.name)
    "AZURE_COSMOS_KEY"              = azurerm_cosmosdb_account.cosmos.primary_key
    "TENANT_ID"                     = var.param_tenant_id
    "CLIENT_ID"                     = azuread_application.app_registration.client_id
    "SECRET_KEY"                    = azuread_application_password.app_registration_secret.value
    "WEBSITE_AUTH_AAD_ALLOWED_TENANTS" = var.param_tenant_id
    "AZURE_OPENAI_RESOURCE_NAME"       = var.param_use_existing_openai_instance ? var.param_existing_azure_openai_resource_name : azurerm_cognitive_account.openai[0].name
    "AZURE_OPENAI_RESOURCE_GROUP_NAME" = var.param_use_existing_openai_instance ? var.param_existing_azure_openai_resource_group_name : azurerm_resource_group.rg.name
    "AZURE_OPENAI_URL"                 = var.param_use_existing_openai_instance ? format(local.openai_url_template, var.param_existing_azure_openai_resource_name) : format(local.openai_url_template, azurerm_cognitive_account.openai[0].name)
    "AZURE_SEARCH_SERVICE_NAME"        = azurerm_search_service.search.name
    "AZURE_SEARCH_API_KEY"             = azurerm_search_service.search.primary_key
    "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT" = azurerm_cognitive_account.docintel.endpoint
    "AZURE_DOCUMENT_INTELLIGENCE_API_KEY"  = azurerm_cognitive_account.docintel.primary_access_key
    "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET" = azuread_application_password.app_registration_secret.value
    "APPINSIGHTS_INSTRUMENTATIONKEY" = azurerm_application_insights.ai.instrumentation_key
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.ai.connection_string
    "APPINSIGHTS_PROFILERFEATURE_VERSION" = "1.0.0"
    "APPINSIGHTS_SNAPSHOTFEATURE_VERSION" = "1.0.0"
    "APPLICATIONINSIGHTS_CONFIGURATION_CONTENT" = ""
    "ApplicationInsightsAgent_EXTENSION_VERSION" = "~3"
    "DiagnosticServices_EXTENSION_VERSION" = "~3"
    "InstrumentationEngine_EXTENSION_VERSION" = "disabled"
    "SnapshotDebugger_EXTENSION_VERSION" = "disabled"
    "XDT_MicrosoftApplicationInsights_BaseExtensions" = "disabled"
    "XDT_MicrosoftApplicationInsights_Mode" = "recommended"
    "XDT_MicrosoftApplicationInsights_PreemptSdk" = "disabled"
  }

  site_config {
    always_on  = true
    minimum_tls_version = "1.2"
    container_registry_use_managed_identity = true

    application_stack {
      docker_image_name = "${var.image_name}"
      docker_registry_username = var.acr_username
      docker_registry_password = var.acr_password
      docker_registry_url = local.param_registry_server
    }
  }

  identity {
    type = "SystemAssigned, UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.id.id]
  }

  lifecycle {
    ignore_changes = [
      site_config[0].application_stack[0].docker_image_name
    ]
  }
  
  tags = local.common_tags
}

# --- Entra App Registration & Service Principal ---
resource "azuread_application" "app_registration" {
  display_name  = local.app_registration_name
  owners        = [data.azuread_client_config.current.object_id, data.azuread_user.application_owner.object_id] # Owner object ID
  # sign_in_audience        = local.signInAudience
  # group_membership_claims = var.groupMembershipClaims

  web {
    redirect_uris = [
      "https://${local.app_service_name}${local.app_service_fqdn_suffix}/.auth/login/aad/callback",
      "https://${local.app_service_name}${local.app_service_fqdn_suffix}/getAToken",
    ]
    logout_url = "https://${local.app_service_name}${local.app_service_fqdn_suffix}/logout"
    implicit_grant {
      access_token_issuance_enabled = true
      id_token_issuance_enabled     = true
    }
  }

  lifecycle {
    ignore_changes = [
      app_role,
    ]
  }
}

resource "azuread_application_password" "app_registration_secret" {
  application_id = azuread_application.app_registration.id
  rotate_when_changed = {
    rotation = 180
  }
}

data "azuread_application_published_app_ids" "well_known" {}

data "azuread_service_principal" "msgraph" {
  client_id = data.azuread_application_published_app_ids.well_known.result.MicrosoftGraph
}

##################################################################
# Add "Expose an API" Permissions (User.Read, Profile, email)
##################################################################
resource "azuread_application_api_access" "api_permissions" {
  api_client_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  application_id   = azuread_application.app_registration.id
  scope_ids = [
    data.azuread_service_principal.msgraph.oauth2_permission_scope_ids["User.Read"],
    data.azuread_service_principal.msgraph.oauth2_permission_scope_ids["profile"],
    data.azuread_service_principal.msgraph.oauth2_permission_scope_ids["email"],
    data.azuread_service_principal.msgraph.oauth2_permission_scope_ids["Group.Read.All"],
    data.azuread_service_principal.msgraph.oauth2_permission_scope_ids["offline_access"],
    data.azuread_service_principal.msgraph.oauth2_permission_scope_ids["openid"]
  ]
}

##################################################################
# **** Not working in Azure Government **** 
# Grant admin consent - this is a manual step in the script for sovereign clouds.
# "azuread_application" "app_registration"
# "azuread_service_principal" "app_registration_sp"
##################################################################
resource "azuread_service_principal_delegated_permission_grant" "delegatedpermissiongrant" {
  service_principal_object_id          = azuread_service_principal.app_registration_sp.object_id
  resource_service_principal_object_id = data.azuread_service_principal.msgraph.object_id
  claim_values                         = ["User.Read", "profile", "email", "Group.Read.All", "offline_access", "openid"]
}

##################################################################
# Entra App Registration App Roles
##################################################################
resource "azuread_application_app_role" "app_registration_admin" {
  application_id        = azuread_application.app_registration.id
  allowed_member_types  = ["User"]
  description           = "Allows access to Admin Settings page."
  display_name          = "Admins"
  value                 = "Admin"
  role_id               = "e9b4823f-d17a-44f1-9d71-0f2c0ee45656"
}

resource "azuread_application_app_role" "app_registration_user" {
  application_id        = azuread_application.app_registration.id
  allowed_member_types  = ["User"]
  description           = "Standard user access to chat features."
  display_name          = "Users"
  value                 = "User"
  role_id               = "633746c6-3d03-480f-b273-58ece728be52"
}

resource "azuread_application_app_role" "app_registration_feedbackadmin" {
  application_id        = azuread_application.app_registration.id
  allowed_member_types  = ["User"]
  description           = "Allows access to view user feedback admin page."
  display_name          = "Feedback Admin"
  value                 = "FeedbackAdmin"
  role_id               = "12e32860-88a8-421e-8a6f-faf08e3efe2e"
}

resource "azuread_application_app_role" "app_registration_safetyviolationadmin" {
  application_id        = azuread_application.app_registration.id
  allowed_member_types  = ["User"]
  description           = "Allows access to view content safety violations."
  display_name          = "Safety Violation Admin"
  value                 = "SafetyViolationAdmin"
  role_id               = "877166d4-eaa3-4fa6-8d79-e2f325f0e331"
}

resource "azuread_application_app_role" "app_registration_feedback_admin" {
  application_id        = azuread_application.app_registration.id
  allowed_member_types  = ["User"]
  description           = "Allows user to create new groups (if enabled)."
  display_name          = "Create Group"
  value                 = "CreateGroups"
  role_id               = "3a614cbb-7f8b-47e1-8e55-5b3c4f71a1c8"
}

resource "azuread_service_principal" "app_registration_sp" {
  client_id = azuread_application.app_registration.client_id
  use_existing   = true
  owners         = [data.azuread_user.application_owner.object_id]
}

#################################################################
# Assign Security Groups to App Roles
#################################################################
resource "azuread_app_role_assignment" "assignment_admin" {
  count               = var.param_create_entra_security_groups ? 1 : 0
  resource_object_id  = azuread_service_principal.app_registration_sp.object_id
  app_role_id         = azuread_application_app_role.app_registration_admin.role_id
  principal_object_id = azuread_group.simplechat_admins[0].object_id
}

#################################################################
# Assign member to Admin Security Groups
#################################################################
resource "azuread_group_member" "group_membership_admin" {
  count             = var.param_create_entra_security_groups ? 1 : 0
  group_object_id   = azuread_group.simplechat_admins[0].object_id
  member_object_id  = data.azuread_user.application_owner.object_id
}

#################################################################
#
# Azure Cosmos DB account
#
#################################################################
resource "azurerm_cosmosdb_account" "cosmos" {
  name                = local.cosmos_db_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "GlobalDocumentDB" # SQL API

  offer_type = "Standard"

  capabilities {
    name = "EnableServerless" # Or specify Provisioned Throughput
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.rg.location
    failover_priority = 0
  }

  tags = local.common_tags
}

# --- Azure OpenAI Service (Cognitive Services) ---
resource "azurerm_cognitive_account" "openai" {
  count               = var.param_use_existing_openai_instance ? 0 : 1 # Only create if not using existing
  name                = local.open_ai_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "OpenAI"
  sku_name            = "S0" # Standard tier
  tags                = local.common_tags
}

# Data source for existing OpenAI instance
data "azurerm_cognitive_account" "existing_openai" {
  count               = var.param_use_existing_openai_instance ? 1 : 0
  name                = var.param_existing_azure_openai_resource_name
  resource_group_name = var.param_existing_azure_openai_resource_group_name
}

# --- Document Intelligence Service (Cognitive Services) ---
resource "azurerm_cognitive_account" "docintel" {
  name                = local.doc_intel_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "FormRecognizer"
  sku_name            = "S0" # Standard tier
  custom_subdomain_name = local.doc_intel_name # Maps to --custom-domain
  tags                = local.common_tags
}

# https://medium.com/expert-thinking/mastering-azure-search-with-terraform-a-how-to-guide-7edc3a6b1ee3
# --- Azure AI Search Service ---
resource "azurerm_search_service" "search" {
  name                = local.search_service_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "basic" # Other options: standard, standard2, standard3
  replica_count       = 1
  partition_count     = 1
  semantic_search_sku = "standard" #other options:  free
  public_network_access_enabled = true # From script's public-network-access enabled
  tags                = local.common_tags
}


#########################################
#
# RBAC ASSIGNMENTS
#
#########################################

# Managed Identity RBAC
# Cognitive Services Contributor on OpenAI
resource "azurerm_role_assignment" "managed_identity_openai_contributor" {
  scope                = var.param_use_existing_openai_instance ? data.azurerm_cognitive_account.existing_openai[0].id : azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services Contributor"
  principal_id         = azurerm_user_assigned_identity.id.principal_id
}

# Cognitive Services User on OpenAI
resource "azurerm_role_assignment" "managed_identity_openai_user" {
  scope                = var.param_use_existing_openai_instance ? data.azurerm_cognitive_account.existing_openai[0].id : azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.id.principal_id
}

# Cosmos DB Contributor on Cosmos DB Account
resource "azurerm_role_assignment" "managed_identity_cosmosdb_contributor" {
  scope                = azurerm_cosmosdb_account.cosmos.id
  role_definition_name = "Contributor" # The script specifies "Contributor" here. For Cosmos DB data plane, "Cosmos DB Built-in Data Contributor" or "Cosmos DB Operator" might be more appropriate.
  principal_id         = azurerm_user_assigned_identity.id.principal_id
}

# Storage Blob Data Contributor on Storage Account
resource "azurerm_role_assignment" "managed_identity_storage_contributor" {
  scope                = azurerm_storage_account.sa.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.id.principal_id
}

# App Registration Service Principal RBAC
# Cognitive Services OpenAI Contributor on OpenAI
resource "azurerm_role_assignment" "app_reg_sp_openai_contributor" {
  scope                = var.param_use_existing_openai_instance ? data.azurerm_cognitive_account.existing_openai[0].id : azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services OpenAI Contributor"
  principal_id         = azuread_service_principal.app_registration_sp.object_id
}

# Cognitive Services OpenAI User on OpenAI
resource "azurerm_role_assignment" "app_reg_sp_openai_user" {
  scope                = var.param_use_existing_openai_instance ? data.azurerm_cognitive_account.existing_openai[0].id : azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azuread_service_principal.app_registration_sp.object_id
}

# App Service System Managed Identity RBAC
# Cognitive Services OpenAI User on OpenAI
resource "azurerm_role_assignment" "app_service_smi_openai_user" {
  scope                = var.param_use_existing_openai_instance ? data.azurerm_cognitive_account.existing_openai[0].id : azurerm_cognitive_account.openai[0].id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_linux_web_app.app.identity[0].principal_id
}

# Storage Blob Data Contributor on Storage Account
resource "azurerm_role_assignment" "app_service_smi_storage_contributor" {
  scope                = azurerm_storage_account.sa.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_web_app.app.identity[0].principal_id
}

# Storage Blob Data Contributor on Storage Account
resource "azurerm_role_assignment" "acr_pull" {
  scope                = data.azurerm_container_registry.acrregistry.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_linux_web_app.app.identity[0].principal_id
}


##################################################
#
# Outputs
#
##################################################
output "web_app_url" {
  description = "The URL of the deployed App Service."
  value       = azurerm_linux_web_app.app.default_hostname
}

# output "app_registration_client_id" {
#   description = "The Client ID of the Entra App Registration."
#   value       = azuread_application.app_registration.client_id
# }

# output "app_registration_secret_value" {
#   description = "The generated secret for the Entra App Registration. Treat this as sensitive!"
#   value       = azuread_application_password.app_registration_secret.value
#   sensitive   = true
# }

output "resource_group_name" {
  description = "Name of the created Resource Group."
  value       = azurerm_resource_group.rg.name
}