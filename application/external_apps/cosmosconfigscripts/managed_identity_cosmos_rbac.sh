# Bash Managed Identity RBAC Script to assign Cosmos DB Built-in Data Contributor Role
## Run inside of Azure Cloud Shell or Bash on your desktop with the Azure CLI installed and logged in to your Azure subscription.

## Background: this role is a data plane role inside of Cosmos DB that allows for read/write access to the data inside of Cosmos DB
## Currently, the value/ID for Cosmos DB Built-in Data Contributor role is hard-coded as 00000000-0000-0000-0000-000000000002, 
## but in case this changes in the future, the following can be run to get the ID (replace items in <> with your values):
### az cosmosdb sql role definition list \
### --resource-group "<resource-group-name>" \
### --account-name "<cosmos-db-account-name>"

## You will also need: 
### principal-id - this will be the ObjectID of your System Managed Identity found on the Identity page of your web app.
### subscription-id - your Azure subscription ID (it will be included in the fully qualified path).

## Gather the necessary information - replace items in <> with your values and run in the Bash shell in Cloud Shell or az cli prompt on desktop:

export resourceGroup="<rg-name>"

export cosmosAccountName="<cosmos-name>"

export roleDefinitionID="00000000-0000-0000-0000-000000000002"

export SMIPrincipalID="<smi-principal-id>"

export subscriptionID="<subscription-id>"

## To check the content of your variables, you can use "echo ${<variable>}".  

## Once satisfied with your variables, you are ready to run the following:
az cosmosdb sql role assignment create \
--resource-group "${resourceGroup}" \
--account-name "${cosmosAccountName}" \
--role-definition-id "${roleDefinitionID}" \
--principal-id "${SMIPrincipalID}" \
--scope "/subscriptions/${subscriptionID}/resourceGroups/${resourceGroup}/providers/Microsoft.DocumentDB/databaseAccounts/${cosmosAccountName}"