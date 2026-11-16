---
layout: page
title: "Browse latest features"
description: "Find out what changed in recent SimpleChat releases and jump to the page where each capability lives."
section: "Guides"
audience: user
---

## What this does

The **Latest Features** page lists the release announcements your administrators chose to share with users. Each announcement explains what changed, why it matters, and how to try it, with screenshots and shortcuts to the page where you use the capability.

{% include media.html src="guides/browse-latest-features.png"
                      alt="The V2 Latest Features page with a search box above the current release, one announcement opened to show its details, steps, screenshot, and shortcuts, and older releases collapsed below."
                      title="Latest Features in V2"
                      capture="Capture the V2 Latest Features page with one announcement opened and the Support menu visible in the navigation rail." %}

## Why you would use this

Use it after an upgrade, or when a colleague mentions a capability you have not seen, to learn what is new without reading release notes written for administrators. Administrators choose which announcements appear, so the page leaves out capabilities your deployment does not use.

## Before you start

- Admins must enable `enable_support_menu` and `enable_support_latest_features`, and share at least one announcement under **User-Facing Latest Features**; see [Help settings]({{ '/admin/help/' | relative_url }}).
- You need the User or Admin application role.

## Steps

1. In the navigation rail, open the **Support** menu. Your administrators may have given it another name.
2. Select **Latest Features**.
3. To find a capability, type part of its name or description in **Search announcements**. The search covers every release, including older ones.
4. Select **Details** on an announcement to read what changed, why it matters, and how to try it. Select a screenshot to enlarge it.
5. Under **Open the right page**, select a shortcut to go where the capability lives. Shortcuts with an arrow open the classic interface or another site; the rest stay in V2.
6. Open **Previous Release Features** or **Archive Release Features** to read older announcements.

In the classic interface, the same page opens from **Support** → **Latest Features** in the sidebar or top navigation. It shows the current release's announcements in full, with older releases behind their own buttons.

## Hide the Latest Features entry

The **Latest Features** entry in the navigation carries a **New** badge. To put it away until the next release, point at the entry and select the hide button beside it, or select **Hide for this version** on the Latest Features card under **User Settings** → **Preferences**. The entry comes back automatically after the next upgrade, or sooner if you select **Show again** on that card.

Hiding the entry does not remove the page. Both interfaces share the choice, so hiding it in one hides it in the other.

## Verify it worked

The page lists at least the current release, and a shortcut such as **Open Chat** takes you to that page without leaving V2.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Latest Features is not in the Support menu | You hid it for this version, the destination is off, or no announcements are shared | Select **Show again** under **User Settings** → **Preferences**, or ask an admin to share announcements. |
| The page says Latest Features is not available | The Support menu or its Latest Features destination is off | Ask an admin to turn on `enable_support_menu` and `enable_support_latest_features`. |
| The page says there are no announcements | Your administrators have not shared any yet | Check back after the next release, or ask an admin which announcements are shared. |
| A shortcut you expected is missing | The capability it opens is turned off in your deployment | Ask an admin whether the capability is enabled. |

## Related

- [Send feedback]({{ '/guides/send-feedback/' | relative_url }})
- [Update profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
- [Help settings]({{ '/admin/help/' | relative_url }})
