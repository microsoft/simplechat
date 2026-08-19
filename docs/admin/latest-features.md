---
layout: page
title: "Latest Features New Settings"
description: "Provides a feature-rollout review surface and mirrors a small set of related controls from other tabs."
section: "Administration"
audience: admin
admin_tab: latest-features
---

## What this tab controls

Provides a feature-rollout review surface and mirrors a small set of related controls from other tabs.

## Why it matters

This tab is a rollout surface for recent capabilities and a shortcut to a few supporting settings owned elsewhere. It helps admins discover new features, but final operational ownership still belongs to the source tabs such as Citations, AI Models, Scale, and General.

{% include media.html src="admin/latest-features-overview.png" alt="Screenshot of the Latest Features New settings tab showing latest features new tab." title="Latest Features New tab" capture="Capture the Latest Features New tab for Latest Features New tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Latest Features New settings walkthrough" poster="video-posters/admin-latest-features.png" capture="Recording planned. Walk through every setting on the Latest Features New tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Enhanced Citations | Preserves source files for richer citation preview and source-document access in chat answers. | Off | Mirrors `enable_enhanced_citations` |
| Storage Account Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | Mirrors `office_docs_authentication_type` |
| Storage Account Connection String | Controls how SimpleChat uses storage account connection string on this tab. | Empty | Mirrors `office_docs_storage_account_url` |
| Storage Account Blob Service Endpoint | Points SimpleChat to the storage account blob service endpoint used by this feature. | Empty | Mirrors `office_docs_storage_account_blob_endpoint` |
| Maximum File Size for Tabular Preview (MB) | Mirror of the Citations setting. Larger values support bigger previews but increase runtime memory pressure. | 200 | Mirrors `tabular_preview_max_blob_size_mb` |
| Enable Processing Thoughts | Makes processing thoughts available in the product when its required service and access policy are configured. | On | Mirrors `enable_thoughts` |
| Enable Redis Cache | Uses Redis for shared cache/session scenarios so multiple app instances can share cached state. | Off | Mirrors `enable_redis_cache` |
| Redis Server Host Name | Controls how SimpleChat uses redis server host name on this tab. | Empty | Mirrors `redis_url` |
| Redis Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | Empty | Mirrors `redis_auth_type` |
| Key Vault Secret Name Redis Access Key | Provides the secret credential used when the selected authentication mode requires one. | Empty | Mirrors `redis_key` |

### Mirrored controls

The controls shown here mirror owning settings from Citations, AI Models, and Scale. Use them for rollout convenience, then verify the owning tab before documenting the change.

## Before you change anything

- Treat mirrored controls as shortcuts and verify final values on the owning tab after saving.
- If users should see Latest Features through Support, enable the Support menu on General.

## Common tasks

1. **Review a new feature rollout.**
    1. Open **Latest Features New**.
    2. Read the feature cards and rollout notes.
    3. Use any in-tab shortcut only when ready to enable the supporting setting.
    4. Verify final values on the owning tab.
    Outcome to verify: The feature is reviewed before rollout.

{% include media.html src="admin/latest-features-review-a-new-feature-rollout.png" alt="Screenshot of the Latest Features New settings tab showing review a new feature rollout." title="Latest Features New: Review a new feature rollout" capture="Capture the Latest Features New tab while performing Review a new feature rollout. Show the relevant controls and redact secrets." %}

2. **Enable mirrored supporting settings.**
    1. Change the mirrored citation, processing thoughts, or Redis setting shown on this tab.
    2. Save settings.
    3. Open the owning tab such as Citations, AI Models, or Scale.
    4. Confirm the same value is shown there.
    Outcome to verify: The shortcut changed the underlying setting.

{% include media.html src="admin/latest-features-enable-mirrored-supporting-settings.png" alt="Screenshot of the Latest Features New settings tab showing enable mirrored supporting settings." title="Latest Features New: Enable mirrored supporting settings" capture="Capture the Latest Features New tab while performing Enable mirrored supporting settings. Show the relevant controls and redact secrets." %}

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [General]({{ '/admin/general/' | relative_url }})
- [Citations]({{ '/admin/citation/' | relative_url }})
- [Scale]({{ '/admin/scale/' | relative_url }})
