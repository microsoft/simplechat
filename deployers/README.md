# Deployers Overview

## Summary

The deployers folder has three different IaC technologies to choose from. You will only choose one of them.

The three options are:

1) Azure CLI with Powershell
2) BICEP
3) Terraform

Note: Terraform is the most robust and requires the least manual post-deployment actions at this time (when deploying to Azure Government).

Why three different deployers?

We wanted to create as much flexibility with the different preferred IaC technologies as possible for quick adoption.

## Option 1: Azure CLI with Powershell

All Azure resource provisioning happens with Azure CLI. Powershell is used for the control flow of the script only.

This script has been tested in Azure Government only, but should be compatible with other Azure platforms needing only minimal adjustments.

Always make sure to follow the guidance in the comments/notes.

## Option 2: BICEP

All Azure resource provisioning happens using BICEP.

This script has been tested in Azure Government only, but should be compatible with other Azure platforms needing only minimal adjustments.

Always make sure to follow the guidance in the comments/notes.

## Option 3: Hashicorp Terraform

All Azure resource provisioning happens using the latest version of Hashicorps Terraform.

This script has been tested in Azure Government only, but should be compatible with other Azure platforms needing only minimal adjustments.

Always make sure to follow the guidance in the comments/notes.
