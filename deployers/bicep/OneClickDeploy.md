# Simple Chat One-Click Deployer to Azure

This project provides a one-click deployment for Simple Chat to Azure Commercial.

## BEFORE YOU DEPLOY MAKE SURE YOU READ THE README.md File

There are pre-deploy manual steps that must be completed first.

After you have deployed, there are additional manual steps that will need to be completed as well.

If you plan to enable private networking and reuse an existing VNet, review the private networking guidance in [README.md](README.md) before starting. In that scenario:

- You must provide an existing VNet resource ID.
- You must also provide both an existing App Service integration subnet ID and an existing private endpoint subnet ID.
- The deployment does not create subnets in a customer-managed VNet.
- If you reuse or centrally manage private DNS zones, make sure you understand the `privateDnsZoneConfigs` parameter and whether VNet links already exist.

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Fsimplechat%2Frefs%2Fheads%2Fmain%2Fdeployers%2Fbicep%2Fmain.json)

[![Deploy to Azure](https://aka.ms/deploytoazuregovbutton)](https://portal.azure.us/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Fsimplechat%2Frefs%2Fheads%2Fmain%2Fdeployers%2Fbicep%2Fmain.json)

## How to Use

1. Click the "Deploy to Azure" button above to deploy.
2. You will be redirected to the Azure portal and will login.
3. Provide argument values for the given parameters.
4. Review the settings and click "Create" to deploy.
