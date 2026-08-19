---
layout: page
title: "Control Center Settings"
description: "Controls Control Center refresh scheduling and role-gated access to Control Center views."
section: "Administration"
audience: admin
admin_tab: control-center-config
---

## What this tab controls

Controls Control Center refresh scheduling and role-gated access to Control Center views.

## Why it matters

Control Center can show operational and management data that not every admin should inspect. Refresh scheduling affects background load; role requirements determine whether users need broad admin access or a narrower dashboard-reader role.

{% include media.html src="admin/control-center-config-overview.png" alt="Screenshot of the Control Center settings tab showing control center tab." title="Control Center tab" capture="Capture the Control Center tab for Control Center tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="Control Center settings walkthrough" poster="video-posters/admin-control-center-config.png" capture="Recording planned. Walk through every setting on the Control Center tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Daily Control Center Refresh | Controls how SimpleChat uses enable daily control center refresh on this tab. | On | `control_center_auto_refresh_enabled` |
| Refresh Time () | Controls how SimpleChat uses refresh time () on this tab. | 02:00 | `control_center_auto_refresh_time` |
| Require ControlCenterAdmin App Role | Requires the `ControlCenterAdmin` app role before users can use this capability or view. | Off | `require_member_of_control_center_admin` |
| Allow ControlCenterDashboardReader App Role | Requires the `Allow ControlCenterDashboardReader` app role before users can use this capability or view. | Off | `require_member_of_control_center_dashboard_reader` |

## Before you change anything

- Create `ControlCenterAdmin` and, if needed, `ControlCenterDashboardReader` app roles before enforcing access.
- Choose a refresh time that avoids peak user traffic.

## Common tasks

1. **Schedule Control Center refresh.**
    1. Enable **Enable Daily Control Center Refresh**.
    2. Set **Refresh Time**.
    3. Save and confirm the next refresh window.
    Outcome to verify: Control Center data refreshes on the intended cadence.

{% include media.html src="admin/control-center-config-schedule-control-center-refresh.png" alt="Screenshot of the Control Center settings tab showing schedule control center refresh." title="Control Center: Schedule Control Center refresh" capture="Capture the Control Center tab while performing Schedule Control Center refresh. Show the relevant controls and redact secrets." %}

2. **Restrict Control Center access.**
    1. Create the relevant app roles.
    2. Enable **Require ControlCenterAdmin App Role** for admin-only control.
    3. Enable **Allow ControlCenterDashboardReader App Role** if dashboard-only readers are allowed.
    4. Test with each role.
    Outcome to verify: Control Center access matches role policy.

{% include media.html src="admin/control-center-config-restrict-control-center-access.png" alt="Screenshot of the Control Center settings tab showing restrict control center access." title="Control Center: Restrict Control Center access" capture="Capture the Control Center tab while performing Restrict Control Center access. Show the relevant controls and redact secrets." %}

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Logging]({{ '/admin/logging/' | relative_url }})
- [Safety]({{ '/admin/safety/' | relative_url }})
