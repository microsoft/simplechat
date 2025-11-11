targetScope = 'resourceGroup'

@description('Location for the deployment script')
param location string

@description('Azure AD Application (Client) ID')
param applicationId string

@description('Key Vault name where the secret will be stored')
param keyVaultName string

@description('Name of the secret to create in Key Vault')
param secretName string = 'enterprise-app-client-secret'

@description('Managed identity ID for the deployment script')
param managedIdentityId string

@description('Display name for the client secret in Azure AD')
param secretDisplayName string = 'Deployment-Generated-Secret'

@description('Number of months until the secret expires (max 24)')
@minValue(1)
@maxValue(24)
param secretExpirationMonths int = 12

resource createSecretScript 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'create-app-secret-${uniqueString(applicationId, secretName)}'
  location: location
  kind: 'AzureCLI'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    azCliVersion: '2.59.0'
    retentionInterval: 'PT1H'
    timeout: 'PT10M'
    cleanupPreference: 'OnSuccess'
    environmentVariables: [
      {
        name: 'APPLICATION_ID'
        value: applicationId
      }
      {
        name: 'KEY_VAULT_NAME'
        value: keyVaultName
      }
      {
        name: 'SECRET_NAME'
        value: secretName
      }
      {
        name: 'SECRET_DISPLAY_NAME'
        value: secretDisplayName
      }
      {
        name: 'EXPIRATION_MONTHS'
        value: string(secretExpirationMonths)
      }
    ]
    scriptContent: '''
      #!/bin/bash
      set -e
      
      echo "Creating client secret for Azure AD application: $APPLICATION_ID"
      
      # Calculate expiration date
      EXPIRATION_DATE=$(date -u -d "+${EXPIRATION_MONTHS} months" +"%Y-%m-%dT%H:%M:%SZ")
      
      # Create the client secret using Microsoft Graph API
      # Note: This requires the managed identity to have appropriate Microsoft Graph permissions
      echo "Creating client secret with expiration: $EXPIRATION_DATE"
      
      SECRET_RESPONSE=$(az rest \
        --method POST \
        --uri "https://graph.microsoft.com/v1.0/applications(appId='$APPLICATION_ID')/addPassword" \
        --body "{\"passwordCredential\": {\"displayName\": \"$SECRET_DISPLAY_NAME\", \"endDateTime\": \"$EXPIRATION_DATE\"}}" \
        --headers "Content-Type=application/json")
      
      # Extract the secret value from the response
      SECRET_VALUE=$(echo "$SECRET_RESPONSE" | jq -r '.secretText')
      
      if [ -z "$SECRET_VALUE" ] || [ "$SECRET_VALUE" = "null" ]; then
        echo "Failed to create client secret"
        exit 1
      fi
      
      echo "Client secret created successfully"
      
      # Store the secret in Key Vault
      echo "Storing secret in Key Vault: $KEY_VAULT_NAME"
      az keyvault secret set \
        --vault-name "$KEY_VAULT_NAME" \
        --name "$SECRET_NAME" \
        --value "$SECRET_VALUE" \
        --description "Client secret for Azure AD application $APPLICATION_ID (expires: $EXPIRATION_DATE)"
      
      echo "Secret stored successfully in Key Vault"
      
      # Output the secret URI (not the value)
      SECRET_URI=$(az keyvault secret show \
        --vault-name "$KEY_VAULT_NAME" \
        --name "$SECRET_NAME" \
        --query id -o tsv)
      
      echo "{\"secretUri\": \"$SECRET_URI\"}" > $AZ_SCRIPTS_OUTPUT_PATH
    '''
  }
}

output secretUri string = createSecretScript.properties.outputs.secretUri
