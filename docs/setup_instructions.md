---
layout: page
title: "Setup Instructions"
description: "Complete guide to deploying and configuring Simple Chat"
section: "tutorials"
nav_links:
  next:
    title: "Manual Setup"
    url: /setup_instructions_manual/
---

# Simple Chat - Setup Instructions

## Summary

The deployers folder has three different IaC technologies to choose from. You will only choose one of them.

The options are:
- [Manual Deployment](#manual-deployment)
- [Azure CLI with Powershell](#azure-cli-with-powershell)
- [BICEP](#bicep)
- [Terraform](#hashicorp-terraform)

**Note:** Terraform is the most robust and requires the least manual post-deployment actions at this time.

Why three different deployment technologies?
We wanted to create as much flexibility with the different preferred IaC technologies as possible for quick adoption.

In addition, this section covers additional configuration items such as 
- [Special Deployment Scenarios](#special-deployment-scenarios)

## Manual Deployment

This is the step by step process required to deploy the infrastructure and configurations needed to run the Simple Chat solution.  This method is discouraged in favor of any of the IaC deployment solutions, however it does contain information that may be useful in debugging configuration difficulties.

[Link to manual deployment steps](./setup_instructions_manual.md)

## Azure CLI with Powershell

All Azure resource provisioning happens with Azure CLI. Powershell is used for the control flow of the script only.

This script has been tested in Azure Government only, but should be compatible with other Azure platforms needing only minimal adjustments.

Always make sure to follow the guidance in the comments/notes.

[Link to Powershell readme](../deployers/azurecli/README.md)

## BICEP

All Azure resource provisioning happens using BICEP.

This script has been tested in Azure Government only, but should be compatible with other Azure platforms needing only minimal adjustments.

Always make sure to follow the guidance in the comments/notes.

[Link to BICEP readme](../deployers/bicep/README.md)

## Hashicorp Terraform

All Azure resource provisioning happens using the latest version of HashiCorp Terraform.

This script has been tested in Azure Government only, but should be compatible with other Azure platforms needing only minimal adjustments.

Always make sure to follow the guidance in the comments/notes.

[Link to Terraform readme](../deployers/terraform/README.md)

## Special Deployment Scenarios

The below sections will cover special scenarios outside of the primary solution deployment.

This includes topics such as:
- Azure Commericial vs Azure Government deployments
- Managed Identitity configurations
- Enterprise Networking Requirements

[Link to special deployment configurations](./setup_instructions_special.md)