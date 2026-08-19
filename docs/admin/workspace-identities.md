---
layout: page
title: "Global Identities Settings"
description: "Provides the administration surface for shared identity mappings used by workspace connectors and sync sources."
section: "Administration"
audience: admin
admin_tab: workspace-identities
---

## What this tab controls

Provides the administration surface for shared identity mappings used by workspace connectors and sync sources.

## Why it matters

Global identities exist so connectors and sync sources can reuse approved identity profiles instead of each source carrying its own credentials. The risk is concentrated: a misconfigured shared identity can grant every source that uses it access to the wrong external location.

{% include media.html src="admin-settings/global-identity.png" alt="Screenshot of the Global Identities settings tab showing shared identity mappings used by workspace connectors and file sync sources." title="Global Identities settings tab" %}

{% include media.html type="video" title="Global Identities settings walkthrough" poster="video-posters/admin-workspace-identities.png" capture="Recording planned. Walk through every setting on the Global Identities tab and explain when to change each one." %}

## Settings

This tab does not expose individual saved form fields in `admin_settings.html`; it is an operational surface for managing shared workspace identities.

## Before you change anything

- Inventory the managed identities or app registrations that sync sources are allowed to reuse.
- Confirm each identity has the minimum external permissions required by its sources.

## Common tasks

1. **Review reusable identities.**
    1. Open **Global Identities**.
    2. Review the identities available for workspace connectors and sync sources.
    3. Confirm owner, purpose, and external permissions outside SimpleChat.
    Outcome to verify: Only approved identities are reused by sources.

{% include media.html src="admin/workspace-identities-review-reusable-identities.png" alt="Screenshot of the Global Identities settings tab showing review reusable identities." title="Global Identities: Review reusable identities" capture="Capture the Global Identities tab while performing Review reusable identities. Show the relevant controls and redact secrets." %}

2. **Prepare an identity for File Sync.**
    1. Create or update the identity outside this tab.
    2. Return to File Sync and assign it to a source.
    3. Run the source test or a small sync.
    Outcome to verify: The source authenticates through the intended shared identity.

{% include media.html src="admin/workspace-identities-prepare-an-identity-for-file-sync.png" alt="Screenshot of the Global Identities settings tab showing prepare an identity for file sync." title="Global Identities: Prepare an identity for File Sync" capture="Capture the Global Identities tab while performing Prepare an identity for File Sync. Show the relevant controls and redact secrets." %}

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [File Sync]({{ '/admin/file-sync/' | relative_url }})
- [Security]({{ '/admin/security/' | relative_url }})
