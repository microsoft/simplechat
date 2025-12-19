
#!/usr/bin/env bash
set -euo pipefail

RG_NAME="${var_rgName}"

COSMOS_URI="${var_cosmosDb_uri}"
ACCOUNT_NAME=$(echo "$COSMOS_URI" | sed -E 's#https://([^.]*)\.documents\.azure\.com.*#\1#')

echo "==============================="
echo "Cosmos DB Account Name: $ACCOUNT_NAME"

UPN=$(az account show --query user.name -o tsv)
OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

# Control-plane assignment
SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_NAME/providers/Microsoft.DocumentDB/databaseAccounts/$ACCOUNT_NAME"

ROLE_NAME="Contributor"
ROLE_ID=$(az role definition list --name "$ROLE_NAME" --query "[0].id" -o tsv)

echo "Assigning role '$ROLE_NAME' to user '$UPN' on scope '$SCOPE'..."
az role assignment create \
  --assignee-object-id "$OBJECT_ID" \
  --assignee-principal-type "User" \
  --role "$ROLE_ID" \
  --scope "$SCOPE" || echo "Control-plane role may already exist."


# Data-plane assignment
DP_ROLE_NAME="Cosmos DB Built-in Data Contributor"
DP_ROLE_ID=$(az cosmosdb sql role definition list \
  --account-name "$ACCOUNT_NAME" \
  --resource-group "$RG_NAME" \
  --query "[?roleName=='$DP_ROLE_NAME'].id | [0]" -o tsv)

echo "Assigning data-plane role '$DP_ROLE_NAME' to user '$UPN' on Cosmos DB account '$ACCOUNT_NAME'..."

az cosmosdb sql role assignment create \
  --account-name "$ACCOUNT_NAME" \
  --resource-group "$RG_NAME" \
  --scope "/" \
  --principal-id "$OBJECT_ID" \
  --role-definition-id "$DP_ROLE_ID" || echo "Data-plane role may already exist."

echo "Assigned Cosmos roles to $UPN ($OBJECT_ID)."
echo "==============================="