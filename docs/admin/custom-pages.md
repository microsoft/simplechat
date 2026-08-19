---
layout: page
title: "Custom Pages Settings"
description: "Controls whether admin-authored custom pages appear in navigation and how they are grouped."
section: "Administration"
audience: admin
admin_tab: custom-pages
---

## What this tab controls

Controls whether admin-authored custom pages appear in navigation and how they are grouped.

## Why it matters

Custom pages are how admins add tenant-specific guidance inside SimpleChat navigation. They are useful for policies, onboarding, and support instructions, but forcing every page into top-level navigation can make the app harder to scan.

{% include media.html src="admin/custom-pages-overview.png" alt="Screenshot of the Custom Pages settings tab showing custom pages tab." title="Custom Pages tab" capture="Capture the Custom Pages tab for Custom Pages tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Custom Pages settings walkthrough" poster="video-posters/admin-custom-pages.png" capture="Recording planned. Walk through every setting on the Custom Pages tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Custom Pages | Makes published custom pages available in SimpleChat navigation. | Off | `enable_custom_pages`; capability toggle |
| Menu Name | This name appears when custom pages are grouped into a menu. | Custom Pages | `custom_pages_menu_name` |
| Force Menu Display | When disabled, 1-2 custom pages show as top-level nav items and 3+ pages show as a menu. | Off | `custom_pages_force_menu` |

## Before you change anything

- Create or plan the custom pages before enabling their navigation entry.
- Decide whether one or two pages should appear as top-level links or be grouped into a menu.

## Common tasks

1. **Enable custom pages in navigation.**
    1. Enable **Enable Custom Pages**.
    2. Set **Menu Name**.
    3. Save and refresh navigation.
    Outcome to verify: Published custom pages appear in the configured navigation location.

{% include media.html src="admin/custom-pages-enable-custom-pages-in-navigation.png" alt="Screenshot of the Custom Pages settings tab showing enable custom pages in navigation." title="Custom Pages: Enable custom pages in navigation" capture="Capture the Custom Pages tab while performing Enable custom pages in navigation. Show the relevant controls and redact secrets." %}

2. **Choose menu behavior.**
    1. Leave **Force Menu Display** off when one or two pages should appear as top-level links.
    2. Enable it when custom pages should always be grouped.
    3. Save and verify navigation with the expected number of pages.
    Outcome to verify: Navigation is grouped or flattened intentionally.

{% include media.html src="admin/custom-pages-choose-menu-behavior.png" alt="Screenshot of the Custom Pages settings tab showing choose menu behavior." title="Custom Pages: Choose menu behavior" capture="Capture the Custom Pages tab while performing Choose menu behavior. Show the relevant controls and redact secrets." %}

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [General]({{ '/admin/general/' | relative_url }})
