# Terraform Deployment Notes

The current Terraform deployer in this repo provisions a **container-based Azure Linux Web App**.

## Current Behavior

- Terraform sets the App Service to run the published container image.
- Gunicorn startup is already handled by the container entrypoint in `application/single_app/Dockerfile`.
- You do **not** need to configure App Service Stack Settings Startup command for the current Terraform deployment.

## If You Switch Terraform to Native Python Later

If you change the Terraform deployment model away from containers and into native Python App Service, then the Startup command should be:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```

or, if the site starts from the repo root:

```bash
python -m gunicorn -c application/single_app/gunicorn.conf.py --chdir application/single_app app:app
```
