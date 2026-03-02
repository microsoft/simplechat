#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

# Expected environment variables (populated by azure.yaml):
# - var_rgName
# - var_cosmosDb_uri

if (-not $Env:var_rgName) { throw "var_rgName is required" }
if (-not $Env:var_cosmosDb_uri) { throw "var_cosmosDb_uri is required" }

$rgName = $Env:var_rgName
$cosmosUri = $Env:var_cosmosDb_uri

# Extract account name from https://<account>.documents.azure.com...
$uri = [Uri]$cosmosUri
# Works for commercial and gov (e.g., .azure.com, .azure.us); strip suffix after account name
$accountName = $uri.Host -replace '\.documents\.azure\..*',''
if ([string]::IsNullOrWhiteSpace($accountName)) { throw "Unable to parse Cosmos DB account name from URI: $cosmosUri" }

Write-Host "==============================="
Write-Host "Cosmos DB Account Name: $accountName"

$upn = az account show --query user.name -o tsv
$objectId = az ad signed-in-user show --query id -o tsv
$subscriptionId = az account show --query id -o tsv

# Control-plane assignment
$scope = "/subscriptions/$subscriptionId/resourceGroups/$rgName/providers/Microsoft.DocumentDB/databaseAccounts/$accountName"
$roleName = "Contributor"
$roleId = az role definition list --name $roleName --query "[0].id" -o tsv

Write-Host "Assigning role '$roleName' to user '$upn' on scope '$scope'..."
az role assignment create `
  --assignee-object-id $objectId `
  --assignee-principal-type User `
  --role $roleId `
  --scope $scope #`
  #| Out-Null

# Data-plane assignment
$dpRoleName = "Cosmos DB Built-in Data Contributor"
$dpRoleId = az cosmosdb sql role definition list `
  --account-name $accountName `
  --resource-group $rgName `
  --query "[?roleName=='$dpRoleName'].id | [0]" -o tsv

Write-Host "Assigning data-plane role '$dpRoleName' to user '$upn' on Cosmos DB account '$accountName'..."
az cosmosdb sql role assignment create `
  --account-name $accountName `
  --resource-group $rgName `
  --scope "/" `
  --principal-id $objectId `
  --role-definition-id $dpRoleId #`
  #| Out-Null

Write-Host "Assigned Cosmos roles to $upn ($objectId)."
Write-Host "==============================="
