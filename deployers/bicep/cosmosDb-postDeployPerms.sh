
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

is_mfa_error() {
  printf '%s' "$1" | grep -qiE 'AADSTS50076|multi-factor authentication|claims challenge'
}

is_already_exists_error() {
  printf '%s' "$1" | grep -qiE 'already exists|RoleAssignmentExists|Conflict'
}

handle_role_assignment_result() {
  local description="$1"
  local command_output="$2"

  if is_already_exists_error "$command_output"; then
    echo "ℹ $description already exists."
    return 0
  fi

  if is_mfa_error "$command_output"; then
    echo "⚠ Azure CLI requires multi-factor authentication before it can complete $description." >&2
    echo "  Continuing with Cosmos DB key-based post-deployment configuration." >&2
    echo "  If you want the signed-in user to keep Cosmos DB access, run 'az login --scope https://management.azure.com//.default' and rerun the deployment later." >&2
    return 0
  fi

  echo "✗ ERROR: Failed to complete $description" >&2
  echo "$command_output" >&2
  exit 1
}

# Control-plane assignment
SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_NAME/providers/Microsoft.DocumentDB/databaseAccounts/$ACCOUNT_NAME"

ROLE_NAME="Contributor"
ROLE_ID=$(az role definition list --name "$ROLE_NAME" --query "[0].id" -o tsv)

echo "Assigning role '$ROLE_NAME' to user '$UPN' on scope '$SCOPE'..."
CONTROL_PLANE_OUTPUT=$(az role assignment create \
  --assignee-object-id "$OBJECT_ID" \
  --assignee-principal-type "User" \
  --role "$ROLE_ID" \
  --scope "$SCOPE" 2>&1) || handle_role_assignment_result "the control-plane role assignment" "$CONTROL_PLANE_OUTPUT"


# Data-plane assignment
DP_ROLE_NAME="Cosmos DB Built-in Data Contributor"
DP_ROLE_ID=$(az cosmosdb sql role definition list \
  --account-name "$ACCOUNT_NAME" \
  --resource-group "$RG_NAME" \
  --query "[?roleName=='$DP_ROLE_NAME'].id | [0]" -o tsv)

echo "Assigning data-plane role '$DP_ROLE_NAME' to user '$UPN' on Cosmos DB account '$ACCOUNT_NAME'..."

DATA_PLANE_OUTPUT=$(az cosmosdb sql role assignment create \
  --account-name "$ACCOUNT_NAME" \
  --resource-group "$RG_NAME" \
  --scope "/" \
  --principal-id "$OBJECT_ID" \
  --role-definition-id "$DP_ROLE_ID" 2>&1) || handle_role_assignment_result "the Cosmos DB data-plane role assignment" "$DATA_PLANE_OUTPUT"

echo "Assigned Cosmos roles to $UPN ($OBJECT_ID)."
echo "==============================="