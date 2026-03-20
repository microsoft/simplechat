# Manual Deployment Notes

Use this path when deploying SimpleChat to **native Python Azure App Service** instead of the repo's container-based deployers.

## Native Python App Service Startup Command

Set the App Service Stack Settings Startup command explicitly.

If App Service starts in `application/single_app`:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

If App Service starts from the repo root:

```bash
python -m gunicorn -c application/single_app/gunicorn.conf.py --chdir application/single_app app:app
```

## Important Distinction

- Native Python App Service needs the Startup command above.
- The repo-provided `azd`, Bicep, Terraform, and Azure CLI deployers do not need this because they deploy a container image whose entrypoint already launches Gunicorn.
