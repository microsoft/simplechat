# PowerShell Managed Identity RBAC Script to assign Cosmos DB Built-in Data Contributor Role
## Run inside of Azure Cloud Shell or PowerShell on your desktop with the Az module installed and logged in to your Azure subscription.

## Background: this role is a data plane role inside of Cosmos DB that allows for read/write access to the data inside of Cosmos DB
## Currently, the value/ID for Cosmos DB Built-in Data Contributor role is hard-coded as 00000000-0000-0000-0000-000000000002, 
## but in case this changes in the future, the following can be run to get the ID (replace items in <> with your values):
## Get-AzCosmosDBSqlRoleDefinition `
## -AccountName "<accountName>" `
## -ResourceGroupName "<resourceGroupName>"

## You will also need: 
### principal-id - this will be the ObjectID of your System Managed Identity found on the Identity page of your web app.
### subscription-id - your Azure subscription ID (it will be included in the fully qualified path).

## Gather the necessary information - replace items in <> with your values and run in PowerShell in Cloud Shell or on desktop:

$resourceGroup = "<rg-name>"

$cosmosAccountName = "<cosmos-account-name>"

$roleDefinitionID = "00000000-0000-0000-0000-000000000002"

$SMIPrincipalID = "<smi-principal-id>"

$subscriptionID = "<subscription-id>"

$scope = "/subscriptions/$subscriptionID/resourceGroups/$resourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$cosmosAccountName"

## To check the content of your variables, you simply enter $<variableName> and press enter.
## Once satisfied with your variables you are ready to run the following:
New-AzCosmosDBSqlRoleAssignment `
    -ResourceGroupName $resourceGroup `
    -AccountName $cosmosAccountName `
    -RoleDefinitionId $roleDefinitionID `
    -Scope $scope `
    -PrincipalId $SMIPrincipalID