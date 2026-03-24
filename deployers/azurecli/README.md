# Simple Chat - Deployment using AzureCLI + PowerShell

[Return to Main](../README.md)

## Runtime Startup Behavior

- This deployer configures Azure App Service to run the published **container image**.
- Gunicorn is already started by the container entrypoint in `application/single_app/Dockerfile`.
- You do **not** need to add anything to App Service Stack Settings Startup command when using this deployer.
- If you manually switch to a native Python App Service deployment instead of containers, deploy the `application/single_app` folder and use:

```bash
python -m gunicorn -c gunicorn.conf.py app:app
```