---
layout: page
title: "Appearance settings"
description: "Appearance controls the public-facing identity of SimpleChat: branding, landing copy, banners, user notices, terms, custom pages, and external navigation links."
section: "Administration"
audience: admin
admin_tab: appearance
redirect_from:
  - /admin/general/
  - /admin/custom-pages/
---


# Appearance settings

## What this group controls

Appearance controls the public-facing identity of SimpleChat: branding, landing copy, banners, user notices, terms, custom pages, and external navigation links.

## Why it matters

These settings shape trust before a user asks a question. A wrong title, stale terms message, or unapproved external link can confuse users or move them outside approved support and compliance paths.

{% include media.html src="admin-settings/general.png" alt="Screenshot of the Appearance group in Admin Settings." title="Appearance settings" %}

{% include media.html type="video" title="Appearance settings walkthrough" poster="video-posters/admin-appearance.png" capture="Recording planned. Walk through each tab in the Appearance group and explain when to change each setting." %}

## Before you change anything

- Have approved logo assets, landing-page copy, and notice text ready.
- Review legal wording for Terms of Use and user agreements before publishing.
- Approve external destinations before making them visible in navigation.

## Branding {#branding}

### Branding {#branding-section}

The Branding section belongs to the Branding tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Home Page Text {#home-page-text-section}

The Home Page Text section belongs to the Branding tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Appearance {#appearance-section}

The Appearance section belongs to the Branding tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Application Title | Provides displayed text that users see in the affected interface. | Simple Chat | `app_title` |
| Show Logo | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `show_logo` |
| Hide Application Title | Provides displayed text that users see in the affected interface. | Off | `hide_app_title` |
| Main Page Logo Size | Defines behavior for the related admin workflow; verify the affected feature after saving. | 100 | `landing_page_logo_scale_percent` |
| Markdown Alignment | Choose how the landing page markdown is aligned on the home page. | left | `landing_page_alignment` |
| Enable Markdown Editor | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_landing_page_editor`; capability toggle |
| Landing Page Text | Provides displayed text that users see in the affected interface. | You can add text here and it supports Markdown. | `landing_page_text` |
| Enable Dark Mode by Default | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_dark_mode_default`; capability toggle |
| Enable Left Nav by Default | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_left_nav_default`; capability toggle |

## Notices & Agreements {#notices}

### Classification Banner {#classification-banner-section}

The Classification Banner section belongs to the Notices & Agreements tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Chat AI Notice {#ai-notice-section}

The Chat AI Notice section belongs to the Notices & Agreements tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Terms of Use {#terms-of-use-section}

The Terms of Use section belongs to the Notices & Agreements tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### User Agreement {#user-agreement-section}

The User Agreement section belongs to the Notices & Agreements tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Classification Banner | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `classification_banner_enabled` |
| Banner Text | Provides displayed text that users see in the affected interface. | Empty | `classification_banner_text` |
| Banner Color | Defines behavior for the related admin workflow; verify the affected feature after saving. | #000000 | `classification_banner_color` |
| Banner Text Color | Provides displayed text that users see in the affected interface. | #ffffff | `classification_banner_text_color` |
| Show a custom AI notice below the chat input | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_ai_notice`; capability toggle |
| Notice Text | Plain text only. Line breaks are preserved. | Empty | `ai_notice_message` |
| Display Behavior | Changing the notice text or display behavior creates a new message version and shows it again. | non_dismissible | `ai_notice_frequency` |
| Require terms of use | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_terms_of_use`; capability toggle |
| Popup Title | Provides displayed text that users see in the affected interface. | Terms of Use | `terms_of_use_title` |
| Show Frequency | Changing the title, message, or frequency creates a new terms version that users must accept again. | once | `terms_of_use_frequency` |
| Terms of Use Message | Plain text is shown to users with line breaks preserved. | Empty | `terms_of_use_message` |
| Cancel Redirect URL | Use a local path such as / or an admin-approved HTTP(S) URL. Signed-in users are locally logged out before this redirect. | / | `terms_of_use_decline_redirect_url` |
| Accept Button Text | Provides displayed text that users see in the affected interface. | Accept and continue | `terms_of_use_accept_button_text` |
| Cancel Button Text | Provides displayed text that users see in the affected interface. | Cancel | `terms_of_use_decline_button_text` |
| Enable User Agreement | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_user_agreement`; capability toggle |
| Personal Workspaces | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `user_agreement_apply_personal` |
| Group Workspaces | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `user_agreement_apply_group` |
| Public Workspaces | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `user_agreement_apply_public` |
| Chat | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `user_agreement_apply_chat` |
| Agreement Text * (Markdown supported) | Provides displayed text that users see in the affected interface. | Empty | `user_agreement_text` |
| Allow users to accept once per day | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_user_agreement_daily`; capability toggle |

## Pages & Links {#custom-pages}

### Static Pages {#custom-pages-section}

The Static Pages section belongs to the Pages & Links tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### External Links {#external-links-section}

The External Links section belongs to the Pages & Links tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Custom Pages | Makes published custom pages available in SimpleChat navigation. | Off | `enable_custom_pages`; capability toggle |
| Menu Name | This name appears when custom pages are grouped into a menu. | Custom Pages | `custom_pages_menu_name` |
| Force Menu Display | When disabled, 1-2 custom pages show as top-level nav items and 3+ pages show as a menu. | Off | `custom_pages_force_menu` |
| Enable External Links in Navigation | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_external_links`; capability toggle |
| Menu Name | This name will appear in the navigation bar as the menu title. | External Links | `external_links_menu_name` |
| Force Menu Display | When enabled, external links will always display as a dropdown menu. When disabled, 1-2 links show as top-level nav items, 3+ links show as a dropdown menu. | Off | `external_links_force_menu` |

## Common tasks

1. **Publish tenant identity.** Update Branding and Home Page Text, then verify the landing page in light and dark mode. Outcome to verify: Users see the approved name, logo, and message.
2. **Require terms acknowledgement.** Configure the Terms of Use prompt and test with a new sign-in. Outcome to verify: The user is prompted at the configured frequency.
3. **Publish managed navigation.** Enable static pages or external links, add an approved item, and reload navigation. Outcome to verify: Only approved pages and links appear.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A notice keeps appearing | The notice or terms content changed and created a new version. | Confirm the frequency and communicate the refreshed acknowledgement. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
- [Help settings]({{ '/admin/help/' | relative_url }})
