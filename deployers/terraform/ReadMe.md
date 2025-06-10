# ReadMe.Md

## Login to Azure CLI

```azurecli
az cache purge
az account clear
az cloud set --name AzureUSGovernment
az login --scope https://management.core.usgovcloudapi.net//.default --service-principal --username @SERVICE_PRINCIPAL_USERNAME --password @SERVICE_PRINCIPAL_PASSWORD --tenant @AZURE_TENANT_ID
az login --scope https://graph.microsoft.us//.default --service-principal --username @SERVICE_PRINCIPAL_USERNAME --password @SERVICE_PRINCIPAL_PASSWORD> --tenant @AZURE_TENANT_ID
az account set -s '@AZURE_SUBSCRIPTION_ID'
```

## To use this Terraform configuration

Create a terraform.tfvars: Create a terraform.tfvars file (or provide via environment variables) for sensitive variables like ACR credentials:

```hcl
acr_username = "your_acr_username"
acr_password = "your_acr_password"
# Optionally override other defaults
# param_tenant_id = "your-actual-tenant-id"
# param_location = "usgovvirginia"
```

Initialize: Run terraform init to download the necessary providers.
Plan: Run terraform plan to see the resources that will be created.
Apply: Run terraform apply to provision the resources.

Login to Azure CLI (See instructions above)
terraform init
terraform init -uprade

### .tfvars

#### Azure Environment Variables

global_which_azure_platform = "AzureUSGovernment"
param_tenant_id = "6bc5b33e-bc05-493c-b076-8f8ce1331511"
param_subscription_id = "4c1ccd07-9ebc-4701-b87f-c249066e0911"
param_location = "usgovvirginia"

#### ACR Variables

acr_name = "acr8000"
acr_resource_group_name = "sc-emma1-sbx1-rg"
acr_username = "acr8000"
acr_password = "@YOUR_ACR_PASSWORD"
image_name = "rudy1simple-chat:2025-05-15_6"

#### SimpleChat Variables

param_environment = "sbx"
param_base_name = "rudy1"

#### Open AI Variables

param_use_existing_openai_instance = "true"
param_existing_azure_openai_resource_name = "gregazureopenai1"
param_existing_azure_openai_resource_group_name = "azureopenairg"

#### Other Settings Variables

param_resource_owner_id = "Tom Jones"
param_resource_owner_email_id = "tom@somedomain.onmicrosoft.us"
param_create_entra_security_groups = "true"

### How to deploy with tfvars file

terraform plan -var-file="./params/rudy1.tfvars"
terraform apply -var-file="./params/rudy1.tfvars" -auto-approve
terraform destroy -var-file="./params/rudy1.tfvars" -auto-approve

## Post-Deployment Manual Steps

STEP 1) Configure Azure Search indexes:
Deploy index as json files to Azure Search: ai_search-index-group.json, ai_search-index-user.json via the portal.

STEP 2) App Service:

Authentication > identity provider > Delete 100% of this if it exists. You will redo it manually.

Authentication > Add identity provider: Setup identity per instructions in the README.md file.

Deployment Center > Change "Authentication" to "Managed Identity" and then select the correct container image. (This change takes about 5 minutes to kick in after a restart.)

Monitoring > Logs > File System > 14 days expire

Restart the app service.

STEP 3) Navigate to Web UI url in a browser.

In the web ui, click on "Admin" > "app settings" to configure your app settings.

STEP 4) Test Web UI fully.
