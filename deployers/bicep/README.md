# Deploying SimpleChat with AZD

>Strongly encourage administrators to use Visual Studio Code and Dev Containers for this deployment type.

## Table of Contents</br>
- [Deployment Variables](##Deployment_Variables)
- [Deployment Process](##Deployment_Process)
    - [Pre-Configuration](###Pre-Configuration)
        - [Create the application registration](####Create_the_application_registration)
    - [Deployment Process](###Deployment_Process)
        - [Configure AZD Environment](####Configure_AZD_Environment)
        - [Deployment Prompts](####Deployment_Prompts)
    - [Post Deployment Tasks](###Post_Deployment_Tasks)
- [Cleanup / Deprovision](##Cleanup_/_Deprovisioning)
- [Workarounds](##Workarounds)

---

## Deployment Variables
The folloiwng variables will be used within this document:

- *\<appName\>* - This will become the beginning of each of the objects created.  Minimum of 3 characters, maximum of 12 characters.  No Spaces or special characters.
- *\<environment\>* - This will be used as part of the object names as well as with the AZD environments.  **Example:** *dev/qa/prod*.
- *\<cloudEnvironment\>* - Options will be *AzureCloud | AzureUSGovernment*
- *\<imageName\>* - Should be presented in the form *imageName:label* **Example:** *simple-chat:latest*


## Deployment Process

The below steps cover the process to deploy the Simple Chat application to an Azure Subscription.  It is assumed the user has administrative rights to the subscription for deployment.  If the user does not also have permissions to create an Application Registration in Entra, a stand-alone script can be provided to an administrator with the correct permissions.

### Pre-Configuration:

The following procedure must be completed with a user that has permissions to create an application registration in the users Entra tenanat.  If this procedure is to be completed by a different user, the following files should be provided:

`./deployers/Initialize-EntraApplication.ps1`</br>
`./deployers/azurecli/appRegistrationRoles.json`

#### Create the application registration:

`cd ./deployers`</br>
`.\Initialize-EntraApplication.ps1 -AppName "<appName>" -Environment "<environment>"  -AppRolesJsonPath "./azurecli/appRegistrationRoles.json"`

This script will create an Entra Enterprise Application, with an App Registration named *\<appName\>*-*\<environment\>*-ar for the web service called *\<appName\>*-*\<environment\>*-app.  The web service name may be overriden with the `-AppServceName` parameter. A user can also specify a different expiration date for the secret which defaults to 180 days with the `-SecretExpirationDays` parameter.

>**Note**: If the script was provided to a different administrator, the -AppRolesJsonPath will need to be edited to the location of the appRegistrationRoles.json file.

The powershell script will report the following information on successful completion.  

>**Be sure to save this information as it will not be available after the window is closed.**

```========================================
App Registration Created Successfully!
========================================
Application Name:       <registered application name>
Client ID:              <clientID>
Tenant ID:              <tenantID>
Service Principal ID:   <servicePrincipalId>
Client Secret:          <clientSecret>
Secret Expiration:      <yyyy-mm-dd>
```

In addition, the script will note additional steps that must be taken for the app registration step to be completed.

1.  Grant Admin Consent for API Permissions:

    - Navigate to Azure Portal > Entra ID > App registrations
    - Find app: *\<registered application name\>*
    - Go to API permissions
    - Click 'Grant admin consent for [Tenant]'

1.  Assign Users/Groups to Enterprise Application:
    - Navigate to Azure Portal > Entra ID > Enterprise applications
    - Find app: *\<registered application name\>*
    - Go to Users and groups
    - Add user/group assignments with appropriate app roles

1.  Store the Client Secret Securely:
    - Save the client secret in Azure Key Vault or secure credential store
    - The secret value is shown above and will not be displayed again

### Deployment Process

After the application registration has been successfully completed the following deployment may begin:

#### Configure AZD Environment

Using the bash terminal in Visual Studio Code

`cd ./deployers`

`azd config set cloud.name AzureCloud` - If you work with other Azure clouds, you may need to update your cloud like `azd config set cloud.name AzureUSGovernment` - more information here - [Use Azure Developer CLI in sovereign clouds | Microsoft Learn](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/sovereign-clouds)

`azd auth login` - this will open a browser window that the user with Owner level permissions to the target subscription will need to authenticate with.

`azd env new <environment>` - Use the same value for the \<environment\> that was used in the application registration.

`azd env select <environment>` - select the new environment

`azd up` - This step will begin the deployment process.  

#### Deployment Prompts
> For each of the following parameters ensure the value noted in *\<parameter\>* matches settings as noted above.


- Select an Azure Subscription to use: *\<select from available list\>*
- Enter a value for the 'appName' infrastructure parameter: *\<appName\>*
- Enter a value for the 'authenticationType' infrastructure parameter: *\<authType\>*
- Enter a vaule for the 'cloudEnvironment' infrastructure parameter: *\<AzureCloud | AzureUSGovernment\>*
- Enter a value for the 'configureApplicationPermissions' infrastructure parameter: \<true | false\>*
- Enter a value for the 'deployContentSafety' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deployRedisCache' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deploySpeechService' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'deployVideoIndexerService' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'enableDiagLogging' infrastructure parameter: *\<true | false\>*
- Enter a value for the 'enterpriseAppClientId' infrastructure parameter: *\<clientID\>*
- Enter a value for the 'enterpriseAppClientSecret' infrastructure secured parameter: *\<clientSecret\>*
- Enter a value for the 'environment' infrastructure parameter: *\<environment\>*
- Enter a value for the 'imageName' infrastructure parameter: *\<imageName\>*
- Enter a value for the 'location' infrastructure parameter: *\<select from the list provided\>*

Provisioning may take between 10-40 minutes depending on the options selected.

On the completion of the deployment, a URL will be presented, the user may use to access the site.

---

### Post Deployment Tasks:

Once logged in to the newly deployed application with admin credentials, the application will need to be set up with several configurations:

1. AI Models > GPT Configuration & Embeddings Configuration.  Application is pre-configured with the chosen security model (key / managed identity).  Select "Test GPT Connection" and "Test Embedding Connection" to verify connection.

    > Known Bug:  User will be unable to Fetch GPT or Embedding models. </br>
Workaround:  Set configurations in CosmosDB.  For details see [Workarounds](##Workarounds) below.

1. Logging > Application Insights Logging  > "Enable Application Insights Global Logging - Set to "ON"
1. Citations > Ehnahced Citations > "Enable Enhanced Citations" - Set to "ON"
    -  Configure "All Filetypes"
        - "Storage Account Authentication Type" = Managed Identity
        - "Storage Account Blob Endpoint" = "https://\<appName\>\<environment\>sa.blob.core.windows.net" (or appropiate domain if in Azure Gov.)
1. Safety > Conversation Archiving > "Enable Conversation Archiving" - Set to "ON"
1. Search & Extract > Azure AI Search 
    - "Search Endpoint" = "https://\<appName\>-\<environment\>-search.search.windows.net" (or appropiate domain if in Azure Gov.)
    > Known Bug:  Unable to configure "Managed Identity" authentication type.  Must use "Key"
    - "Authentication Type" - Key
    - "Search Key" - *Pre-populated from key vault value*.
    - At the top of the Admin Page you'll see warning boxes indicating Index Schema Mismatch.
        - Click "Create user Index"
        - Click "Create group Index"
        - Click "Create public Index"    
1. Search & Extract > Document Intelligence
    - "Document Intelligence Endpoint" = "https://\<appName\>-\<environment\>-docintel.cognitiveservices.azure.com/" (or appropiate domain if in Azure Gov.)
    - "Authentication Type" - Managed Identity

User shoud now be able to fully use Simple Chat application.

---
## Cleanup / Deprovisioning

> This is a destructive process.  Use with caution.

`cd ./deployers`</br>
`azd down --purge` - This will delete all deployed resource for this solution and purge key vault, document intelligence, OpenAI services.


---
## Workarounds

- Fetching GPT and Embedding Models.
    - Grant the current user data access to Cosmos DB from a BASH command shell
    - `PRINCIPAL_ID=$(az ad signed-in-user show --query id --output tsv)`
    - `az cosmosdb sql role assignment create --account-name <appName>-<environment>-cosmos --resource-group <appName>-<environment>-rg --principal-id $PRINCIPAL_ID --scope "/" --role-definition-id 00000000-0000-0000-0000-000000000002`
    - Open CosmosDB in Azure Portal and connect to the `<appName>-<environment>-cosmos` service.
    - Data Explorer > SimpleChat > settings > items
        - Replace the following values:
        ```
        "gpt_model": {
            "selected": [],
            "all": []
        },
        ```

        with 

        ```
        "gpt_model": {
            "selected": [
                {
                    "deploymentName": "gpt-4o",
                    "modelName": "gpt-4o"
                }         
            ],
            "all": [
                {
                    "deploymentName": "gpt-4o",
                    "modelName": "gpt-4o"
                }         
            ]
        },
        ```

        and

        ```
        "embedding_model": {
            "selected": [],
            "all": []
        },
        ```

        with 

        ```
        "embedding_model": {
            "selected": [
                "deploymentName": "text-embedding-3-small",
                "modelName": "text-embedding-3-small"
            ],
            "all": [
                "deploymentName": "text-embedding-3-small",
                "modelName": "text-embedding-3-small"
            ]
        },
        ```

    - Update settings in the Cosmos UI and click Save.
    - Refresh web page and you shound now be able to Test the GPT and Embedding models.

