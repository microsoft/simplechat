# Simple Chat - Cosmos DB Configuration Scripts

This folder contains scripts (not apps) that will allow you to create the correct RBAC constructs inside the data plane for a Managed Identity, as well as setup of the Database and Containers (both in Az CLI and Azure PowerShell). These need to be run in a cloud shell in the correct subscription context, or logged into Azure at an Az CLI command line or Azure PowerShell and context set to the correct subscription.

*PLEASE NOTE*: Cosmos DB Configuration Scripts are *sample scripts* including those in this file, and require edits to supplement your own variables or ensure suitability for your environment.


## Prerequisites:
This ReadMe and the accompanying scripts assume you have access to Cloud Shell in the Azure Portal, or have either the latest version of Az CLI, or PowerShell 7 or above installed with Azure Module in Windows.


## STEP 1: Log in via Cloud Shell or Desktop Prompt 

This can be performed by running either the managed_identity_cosmos_rbac.sh from Bash, or managed_identity_cosmos_rbac.ps1 from a PowerShell prompt.

*Cloud shell* can be used (select either Bash or PowerShell), but ensure that the correct subscription context is set: 
Bash:
az account show                                             # shows current context - if correct, stop here and prepare and run scripts
az account list --output table                              # lists available subscriptions - retrieve name or id of correct subscription
az account set --subscription <subscription-name-or-id>     # substitute your subscription name or id (and do not include the brackets <>) to set the correct context

PowerShell:
Get-AzContext                                               # shows current context - if correct, stop here and prepare and run scripts
Get-AzContext -ListAvailable                                # lists available subscriptions - retrieve name or id of correct subscription
Set-AzContext -Subscription <subscription-name-or-id>       # substitute your subscription name or id (and do not include the brackets <>) to set the correct context


To use Az CLI or PowerShell from *Desktop Prompts*, implement the following steps to login prior to the steps above:
Bash:
az cloud list --output table                                # shows True for the cloud that is currently set to connect to - default is AzureCloud - you will also see all other available valid options 
az cloud set --name AzureUSGovernment                       # example here shows changing from AzureCloud default to AzureUSGovernment - change to option required by your scenario
az login                                                    # begins interactive login that will move into your browser

PowerShell:
Get-AzEnvironment                                           # shows available valid options - default is AzureCloud
Connect-AzAccount -Environment AzureUSGovernment            # example here shows changing from AzureCloud default to AzureUSGovernment - change to option required by your scenario

Ensure correct subscription context (az account set or Set-AzContext -Subscription) before continuing.

## Step 2: Assign Cosmos DB Built-in Data Contributor to your System-Assigned Managed Identity

If using Azure CLI, modify the managed_identity_cosmos_rbac.sh file with the correct values and then copy/paste into a Cloud Shell (Bash) in the Azure Portal or command prompt in Windows (after the log-in steps above).

If using Azure PowerShell, modify the managed_identity_cosmos_rbac.ps1 file with the correct values and then copy/paste into Cloud Shell (PowerShell) in the Azure Portal or PowerShell in Windows (after the log-in steps above).


## STEP 3: Execute Scripts to Create the SimpleChat Database and All Required Containers

If using Azure CLI, modify database_and_container_creation.sh with the correct variable values and upload the file to a Cloud Shell (Bash) in Azure Portal.  You will need to run "chmod +x database_and_container_creation.sh" to allow for execution of the script, and then run "./database_and_container_creation.sh" to run the script.

Detailed explanation on executing the bash script locally is beyond the scope of this article, as it requires a bash shell or Windows Subsystem for Linux to be installed on Windows. The general steps are to install WSL from Windows features, navigate via /mnt/c/ to your script location, perform az login as above, and then execute the file with ./database_and_container_creation.sh after supplying your variable values in the script. 

If using Azure PowerShell, modify database_and_container_creation.ps1 with the correct variable values and then copy/paste into a Cloud Shell (PowerShell) in Azure Portal or navigate to the directory of the script in PowerShell in Windows (after the log-in steps above) and execute the file with ./database_and_container_creation.ps1.