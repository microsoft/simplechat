---
layout: showcase-page
title: "Docker Customization"
permalink: /how-to/docker_customization/
menubar: docs_menu
accent: slate
eyebrow: "How-To Guide"
description: "Customize the container image when you need private trust anchors, enterprise TLS compatibility, or pip configuration changes during Docker build."
hero_icons:
  - bi-box-seam
  - bi-shield-lock
  - bi-tools
hero_pills:
  - Container builds only
  - Private CA support
  - pip configuration override
hero_links:
  - label: "AZD deployment"
    url: /reference/deploy/azd-cli_deploy/
    style: primary
  - label: "Special setup scenarios"
    url: /setup_instructions_special/
    style: secondary
---

Use Docker customization when the default container image is correct for the application but not quite correct for the network or package-install environment you need to run inside.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-shield-lock"></i></div>
        <h2>Private certificate authorities</h2>
        <p>Add internal root or intermediate certificates when outbound HTTPS calls rely on enterprise PKI or TLS interception infrastructure.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-box-seam"></i></div>
        <h2>Rebuild the image</h2>
        <p>Changes in the customization folders only take effect after the Simple Chat container image is rebuilt and redeployed.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-download"></i></div>
        <h2>Customize pip behavior</h2>
        <p>Use the repo-level pip configuration when package installation needs custom indexes, mirrors, or enterprise network settings during build.</p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-check2-square"></i></div>
        <h2>Validate from the container</h2>
        <p>Confirm the trust bundle and network behavior from inside the running container instead of assuming the image build succeeded.</p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>This guide applies to container-based deployments</h2>
    <p>The certificate and pip-customization steps here affect images built from the repo Dockerfile. Native Python App Service deployments need different host- or app-level configuration for certificate trust and package resolution.</p>
</div>

## Custom Certificate Authorities

Simple Chat supports adding private, self-signed, or enterprise-issued certificate authorities to the container image during Docker build. This is useful when the app or Semantic Kernel plugins need to make TLS-validated outbound connections to internal HTTPS endpoints that are not signed by a public CA.

Common cases include:
- Internal HTTPS APIs called by HTTP or OpenAPI-based plugins
- Private Azure OpenAI or other model endpoints presented through enterprise TLS inspection or internal PKI
- SQL gateways, reverse proxies, or service endpoints that present certificates chaining to a private root or intermediate CA
- Internal services used behind private DNS, firewalls, or corporate network boundaries

### Where to place certificates

Put each CA certificate file in the repository folder below before building the container:

```text
docker-customization/custom-ca-certificates/
```

Requirements:
- Use `.crt` file extensions
- Use PEM-encoded certificates
- Add the CA certificate, not the leaf/server certificate, unless your trust model explicitly requires it
- Include any required intermediate CA certificates if your internal chain is not complete

Example:

```text
docker-customization/custom-ca-certificates/
  corp-root-ca.crt
  corp-intermediate-ca.crt
```

### What happens during container build

The application Docker build copies everything from `docker-customization/custom-ca-certificates/` into the container trust anchor location and then refreshes the system CA bundle.

The current build in `application/single_app/Dockerfile` does the following:
- Copies certificate files into `/etc/pki/ca-trust/source/anchors`
- Runs `update-ca-trust enable` and `update-ca-trust extract`
- Carries the resulting trust store into the final runtime image
- Sets `SSL_CERT_FILE`, `SSL_CERT_DIR`, and `REQUESTS_CA_BUNDLE` so Python HTTPS clients can use the updated CA bundle

This means outbound TLS checks from the container can trust your added CAs when the underlying client library uses the system or Python certificate bundle.

### Typical admin workflow

1. Export the required CA certificate chain from your internal PKI or security team.
2. Convert or save the certificate files as PEM `.crt` files.
3. Place the files in `docker-customization/custom-ca-certificates/`.
4. Rebuild the Simple Chat container image.
5. Redeploy the updated container.
6. Re-test the plugin or outbound integration that previously failed TLS validation.

### Building with custom CAs

If you build locally with Docker, the certificate files only take effect after a rebuild.

Example:

```bash
docker build -f application/single_app/Dockerfile -t simplechat:custom-ca .
```

If you deploy with the repo's container-based Azure deployment flow, ensure the updated files are present in the repo before the image build triggered by your deployment pipeline.

### How this helps plugin and outbound connection scenarios

This customization is intended for container-based deployments where Simple Chat makes outbound TLS connections to services that chain to private trust anchors.

It commonly helps with:
- HTTP, OpenAPI, and REST-style Semantic Kernel plugins that call internal HTTPS endpoints
- Azure OpenAI or other HTTPS AI endpoints reached through enterprise PKI, private networking, or TLS interception infrastructure
- Python-based outbound requests made by application code or plugin code that rely on the container trust store

It may also help with SQL-related integrations when the database driver or gateway validates certificates through the operating system or Python trust bundle. Some database drivers also support their own explicit CA configuration, so certificate-store updates and driver-level SSL settings should be treated as complementary, not interchangeable.

### Verify the certificate is present in the container

After rebuilding and deploying, validate from inside the running container when possible.

Useful checks include:

```bash
ls /etc/pki/ca-trust/source/anchors
```

```bash
python -c "import os; print(os.environ.get('SSL_CERT_FILE')); print(os.environ.get('REQUESTS_CA_BUNDLE'))"
```

```bash
python -c "import requests; print(requests.get('https://your-internal-endpoint/health', timeout=15).status_code)"
```

If the endpoint still fails certificate validation, confirm:
- The CA file is PEM-encoded and ends in `.crt`
- The correct root and intermediate certificates were included
- The server is presenting the expected certificate chain
- Hostname resolution matches the certificate subject or SAN
- The failing client library actually uses the system/Python trust store

### Important limitations

- This only affects container-based deployments built from the repo Dockerfile. Native Python App Service deployments need certificate trust configured at the host or app level separately.
- Adding a CA certificate does not fix DNS, firewall, private endpoint, routing, or proxy issues.
- Trusting a private CA expands what the container will trust. Only add certificates from sources your organization explicitly approves.

## Custom pip conf
Add customization as needed to the `docker-customization/pip.conf` file in the repository root. This will be used during docker build.
