# Deployer Private Endpoint and DNS Fix (v0.261.333)

Fixed in version: **0.261.333**. Deployer version: **1.0.34**.
Related issue: [#1765](https://github.com/microsoft/simplechat/issues/1765).
The application version is recorded in `application/single_app/config.py`.

## Issue and Root Cause

Bicep deployed Redis without a private endpoint and left Managed Redis public. Video Indexer shared Cognitive Services DNS instead of its Commercial zone. Government Key Vault had an incorrect private zone. These gaps made private-network deployments look more complete than their actual data paths.

## Technical Changes

- Bicep passes the optional Redis resource ID, selects `redisEnterprise`/`redisCache`, and creates offering/cloud DNS and an endpoint. Redis remains public during bootstrap; AZD's final `postup` disables it with the appropriate API version after configuration/deployment succeeds.
- Video Indexer uses `privatelink.api.videoindexer.ai` in Commercial. Government remains excluded from PE creation. Terraform's association is corrected and CLI reconciles the supported endpoint's zone on redeployment.
- Government Key Vault uses `privatelink.vaultcore.usgovcloudapi.net` in all three deployers.
- Optional [AMPLS](../features/AZURE_MONITOR_PRIVATE_LINK.md) defaults off in both clouds.

## Validation and Impact

The existing private DNS functional suite covers cloud maps, generated wiring, AMPLS preflight, and Redis hooks. Bicep, Terraform, and PowerShell validation do not provision cloud resources. Live DNS resolution, Redis connectivity, ingestion, and queries need deployment validation. `azd provision`/`azd deploy` alone do not execute `postup`; separate workflows must perform equivalent lockdown. Later Managed Redis provisioning resets bootstrap access and requires final lockdown again.

The [networking guide](../../guides/enterprise-networking.md) distinguishes script-created greenfield defaults from compact enterprise reference tables in both clouds. User-owned Visio source files are not rewritten by this fix.
