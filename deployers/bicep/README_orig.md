# Simple Chat - Deployment using BICEP

[Return to Main](../README.md)

## Manual Pre-Requisites (Critically Important)

Create Entra ID App Registration:

Go to Azure portal > Microsoft Entra ID > App registrations > New registration.

- Provide a name (e.g., $appRegistrationName from the script's logic).
- Supported account types: Usually "Accounts in this organizational directory only."
- Do not configure Redirect URI yet. You will get these from the Bicep output.
- Once created, note down the Application (client) ID (this is appRegistrationClientId parameter).
- Go to "Certificates & secrets" > "New client secret" > Create a secret and copy its Value immediately (this is appRegistrationClientSecret parameter).
- **** NO **** Go to "Token configuration" and enable "ID tokens" and "Access tokens" for implicit grant and hybrid flows if needed by your app (the script attempts az ad app update --enable-id-token-issuance true --enable-access-token-issuance true).
- The script also adds API permissions for Microsoft Graph and attempts to add owners. These should be configured manually on the App Registration.
  - User.Read, Delegated
  - profile, Delegated
  - email, Delegated
  - Group.Read.All, Delegated
  - offline_access, Delegated
  - openid, Delegated
  - People.Read.All, Delegated
  - User.ReadBasic.All, Delegated
- The script also references appRegistrationRoles.json. If your application defines app roles, configure these in the App Registration manifest.
- Obtain the Object ID of the Service Principal associated with this App Registration: az ad sp show --id <Your-App-Registration-Client-ID> --query id -o tsv. This will be the appRegistrationSpObjectId parameter.

Create Entra ID Security Groups: If your application relies on the security groups ($global_EntraSecurityGroupNames), create them manually in Entra ID.

Azure Container Registry (ACR): Ensure the ACR specified by acrName exists and the image imageName is pushed to it.

Azure OpenAI Access: If useExistingOpenAiInstance is true, ensure the specified existing OpenAI resource exists and you have its name and resource group. If false, ensure your subscription is approved for Azure OpenAI and the chosen SKU and region support it.

## Deploy

(Optional) Create a resource group if you don't have one: az group create --name MySimpleChatRG --location usgovvirginia

Deploy the Bicep file.

### azure cli

#### validate before deploy

az bicep build --file main.bicep

az deployment group validate `
--resource-group MySimpleChatRG `
--template-file main.bicep `
--parameters main.json

az deployment group create `
--resource-group MySimpleChatRG `
--template-file main.bicep `
--parameters main.bicepparam `
--parameters appRegistrationClientSecret="YOUR_APP_REG_SECRET_VALUE"

## Post-Deployment Manual Steps (from Bicep outputs and script)

### App Registration

- Manage > Authentication

    Web Redirect Url example:

      <https://web-8000.azurewebsites.us/.auth/login/aad/callback>

      <https://web-8000.azurewebsites.us/getAToken>

    Front-channel logout URL: <https://web-8000.azurewebsites.us/logout>

    Implicit grant and hyrbid flows:

    Access tokens: Check this

    ID tokens: Check this

    Supported account types: Accounts in this organization directly only

    Advanced Settings > Allow public client flows > Enable the following mobile and desktop flows: No

- Manage > Certificates & secrets
  
  You will see 2 secrets here in the end. One created by you pre-deployment and one created when you add Authentication to the App Service.

- Manage > Token configuration: Nothing to do here. Leave empty.

- Manage > API Permissions: Click "Grant Admin Consent for tenant" to all deletgated permissions

- Manage > Expose an API: Nothing to do here. Leave empty.

- Manage > App Roles: You should see the following app roles: [FeedbackAdmin, Safety Violation Admin, Create Group, Users, Admins]

### Entra Security Groups

- Assignments: If you created security groups, assign them to the corresponding Enterprise Application application roles and add members to the security groups.

### App Service

- Authentication
  
  Identity Provider: Microsoft

  Choose a tenant for your application and its users: Workforce configuration (current tenant)

  Pick an existing app registration in this directory: Select the app registration you created pre-deployment

  Client secret expiration: Recommended 180 days

  *** Leave all other values default

  Note: Check App Setting "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET" for a secret value created by configuring the Authentication. This secret will be added to your App Registration as well.

- Deployment Center > Registry Settings (These sometimes get screwed up during a deploy. Make sure these values are correct.)

  The deployer can get messed up here. Make sure the correct values are being displayed for your registry settings.

  Container Type: Single Container

  Registry source: Azure Container Registry

  Subscription Id: [Your subscription]

  Authentication: Managed Identity

  Identity: Managed identity deployer deployed

  Registry: [Name of the ACR: e.g. SomeRegistry]

  Image: simplechat

  Tag: 2025-05-29_1

  Startup file or command: [Blank]

- Restart & Test: Restart the App Service and test the Web UI.

- Open Monitoring > Log stream and make sure the container has loaded and is ready.

### Azure AI Search

- Manually create 2 Indexes: Deploy your search index schemas (ai_search-index-group.json, ai_search-index-user.json) using Index as Json in the Azure portal.

  Note: These files can be found in GitHub repository folder /deployers/bicep/artifacts

### Existing Open AI (Option)

- Make sure the Managed Idenity and the Entra App Registration have been added to the Open AI Instance IAM with RBAC Roles [Cognitive Services Contributor, Cognitive Services OpenAI User, Cognitive Services User]

### Admin center in Web UI application

- Open a browser and navigate to the url of the Azure App Service default domain.

- Once you have logged into the application, navigate to "Admin" and configure the settings.

  Note: If you cannot login or see the Admin link, make sure you have added yourself to the Enterprise Application (Assigned users and groups) users for the App Registration you created. Make sure you have assigned your user account to the "Admin" app role.
