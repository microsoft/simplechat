---
layout: page
title: "Manual Deployment Notes"
description: "Use the native Python Azure App Service deployment path when container deployers are not the right fit"
section: "Reference"
---

# Manual Deployment Notes

Use this path when deploying SimpleChat to **native Python Azure App Service** instead of the repo's container-based deployers.

For the combined native-vs-container decision guide, see [../../how-to/upgrade_paths.md](../../how-to/upgrade_paths.md).

## Native Python App Service Startup Command

Set the App Service Stack Settings Startup command explicitly.

Do **not** leave the Startup command empty during an upgrade. Validate it before or during the release.

Deploy and run the `application/single_app` folder in App Service.

Use this Startup command:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

## Native Python Upgrade Checklist

Use this checklist when updating an existing native Python App Service deployment.

1. Confirm the deployment model is **native Python App Service**, not container-based App Service.
2. Confirm the `application/single_app` folder is the deployment unit and the Startup command is present and correct.
3. Choose an upgrade method:
    - **VS Code deployment** when you want the simplest manual update path.
    - **Azure CLI ZIP deploy** when you want a repeatable package-and-deploy path.
    - **Deployment slots** when you want validation and rollback for production.
4. If you use ZIP deploy, confirm `SCM_DO_BUILD_DURING_DEPLOYMENT=true` so App Service installs dependencies from `requirements.txt`.
5. Validate the site after deployment.

## Native Python Upgrade Methods

### Visual Studio Code Deployment

Deploy the updated code from VS Code by right-clicking the existing App Service and selecting **Deploy to Web App...**.

### Azure CLI ZIP Deploy

Package the updated application into a deployment ZIP, then deploy it:

```bash
az webapp deploy \
  --resource-group <Your-Resource-Group-Name> \
  --name <Your-App-Service-Name> \
  --src-path ../deployment.zip \
  --type zip
```

This is an upgrade method, not only an initial deployment method.

## Important Distinction

- Native Python App Service needs the Startup command above.
- The repo-provided `azd`, Bicep, Terraform, and Azure CLI deployers do not need this because they deploy a container image whose entrypoint already launches Gunicorn.
