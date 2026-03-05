# Docker Customization

## Custom Certificate Authorities

Add custom certification authorities to the `docker-customization/custom-ca-certificates/` directory in the repository root, and they will be pulled into the system CAs during docker build. Must be in `.crt` format.

## Custom pip conf
Add customization as needed to the `docker-customization/pip.conf` file in the repository root. This will be used during docker build.