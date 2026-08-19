---
layout: page
title: "Azure Maps OpenLayers"
description: "Reference for the Azure Maps OpenLayers SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: azure-maps-openlayers -->

{% include media.html src="reference/actions-azure-maps-openlayers-configuration.png" alt="Azure Maps OpenLayers action setup or assignment UI." title="Azure Maps OpenLayers action" capture="Capture the Azure Maps OpenLayers action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Creates inline OpenLayers map payloads and proxies Azure Maps raster tiles through SimpleChat.

## Why and when to use it

Use it when an agent needs to turn known locations, areas, or paths into a map inside chat. Do not use it for general GIS editing or broad geocoding.

## Before you start

- Azure Maps subscription key; key auth; agents enabled with `enable_semantic_kernel`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Use common setup, then provide **Subscription Key** and test the Azure Maps connection.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
