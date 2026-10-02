---
layout: page
title: "Azure Maps OpenLayers"
description: "Reference for the Azure Maps OpenLayers SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: azure-maps-openlayers -->

{% include media.html src="reference/actions-azure-maps-openlayers-configuration.png" alt="The Configuration step of the Add Action wizard for Azure Maps, showing the built-in action notice, the Azure Maps subscription key field, and a Test Connection button." title="Azure Maps OpenLayers action configuration" capture="Capture the Azure Maps OpenLayers action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

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

## What people see in chat

The map appears under the agent's reply, in personal conversations and in group conversations
that receive the reply. In both the classic and the new chat it opens fitted to every marker, path
and area, and people can pan, zoom and click a point to read its label and description.

The new chat also shows a point's details on hover, has a **Full screen** button, and lists
everything on the map as text under **List what the map shows**. There the mouse wheel zooms only
with Ctrl (Cmd on a Mac), so scrolling a conversation never zooms a map by accident.

## Photos and facts on a point

A point can carry a photo of the place and labelled facts about it, so a reader sees the evidence
for a location where it sits on the map instead of matching it up from the reply text. An agent
sends them with each item in `locations_json`:

- `image_url`: an `https` link to the photo. Links that are not `https` are left out, and the
  action's result tells the agent how many it dropped.
- `image_caption`: what the photo shows, used as its caption and its alternative text.
- `fields`: a list of `{label, value}` pairs, such as a reading's time or a transponder ID.

The new chat shows the photo, caption and facts with the point's details, opens the photo full
size when it is clicked, and lists the facts and a thumbnail under **List what the map shows**.
The classic chat shows the point's label and description only.

Tiles load through SimpleChat, so the browser never receives the Azure Maps key. The tile link
stored with a reply expires after four hours and is reissued whenever the conversation is opened,
so maps in older replies keep loading.

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
