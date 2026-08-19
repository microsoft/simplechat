---
layout: page
title: "General Settings"
description: "Controls branding, home page copy, navigation defaults, user notices, health checks, support menu entries, external links, and global app behavior."
section: "Administration"
audience: admin
admin_tab: general
---

## What this tab controls

Controls branding, home page copy, navigation defaults, user notices, health checks, support menu entries, external links, and global app behavior.

## Why it matters

This tab shapes the experience every user sees before they ever open a workspace: the app name, landing page, navigation, legal notices, access-denied copy, support links, and upload/session limits. A branding change is low risk, but health-check exposure, Terms of Use frequency, idle timeout, and maximum file size can affect monitoring, sign-in flows, compliance evidence, and whether large uploads or long-running chats succeed.

{% include media.html src="admin-settings/general.png" alt="Screenshot of the General settings tab showing branding, home page, navigation, notices, support links, and health check settings available to administrators." title="General settings tab" %}

{% include media.html type="video" title="General settings walkthrough" poster="video-posters/admin-general.png" capture="Recording planned. Walk through every setting on the General tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Application Title | Controls the user-facing copy or name shown for application title. | Simple Chat | `app_title` |
| Show Logo | Controls how SimpleChat uses show logo on this tab. | Off | `show_logo` |
| Hide Application Title | Controls the user-facing copy or name shown for hide application title. | Off | `hide_app_title` |
| Main Page Logo Size | Controls how SimpleChat uses main page logo size on this tab. | 100 | `landing_page_logo_scale_percent` |
| Markdown Alignment | Choose how the landing page markdown is aligned on the home page. | left | `landing_page_alignment` |
| Enable Markdown Editor | Makes markdown editor available in the product when its required service and access policy are configured. | Off | `enable_landing_page_editor`; capability toggle |
| Landing Page Text | Controls the user-facing copy or name shown for landing page text. | You can add text here and it supports Markdown. | `landing_page_text` |
| Enable Dark Mode by Default | Makes dark mode by default available in the product when its required service and access policy are configured. | Off | `enable_dark_mode_default`; capability toggle |
| Enable Left Nav by Default | Makes left nav by default available in the product when its required service and access policy are configured. | On | `enable_left_nav_default`; capability toggle |
| Enable /external/healthcheck | Makes /external/healthcheck available in the product when its required service and access policy are configured. | Off | `enable_external_healthcheck`; capability toggle |
| Enable /external/healthcheckz | Makes /external/healthcheckz available in the product when its required service and access policy are configured. | Off | `enable_no_auth_external_healthcheck`; capability toggle |
| Enable Swagger/OpenAPI Documentation (/swagger) | Makes swagger/openapi documentation (/swagger) available in the product when its required service and access policy are configured. | On | `enable_swagger`; capability toggle |
| Enable Classification Banner | Controls how SimpleChat uses enable classification banner on this tab. | Off | `classification_banner_enabled` |
| Banner Text | Controls the user-facing copy or name shown for banner text. | Empty | `classification_banner_text` |
| Banner Color | Controls how SimpleChat uses banner color on this tab. | #000000 | `classification_banner_color` |
| Banner Text Color | Controls the user-facing copy or name shown for banner text color. | #ffffff | `classification_banner_text_color` |
| Show a custom AI notice below the chat input | Makes show a custom ai notice below the chat input available in the product when its required service and access policy are configured. | Off | `enable_ai_notice`; capability toggle |
| Notice Text | Plain text only. Line breaks are preserved. | Empty | `ai_notice_message` |
| Display Behavior | Changing the notice text or display behavior creates a new message version and shows it again. | non_dismissible | `ai_notice_frequency` |
| Require terms of use | Makes require terms of use available in the product when its required service and access policy are configured. | Off | `enable_terms_of_use`; capability toggle |
| Popup Title | Controls the user-facing copy or name shown for popup title. | Terms of Use | `terms_of_use_title` |
| Show Frequency | Changing the title, message, or frequency creates a new terms version that users must accept again. | once | `terms_of_use_frequency` |
| Terms of Use Message | Plain text is shown to users with line breaks preserved. | Empty | `terms_of_use_message` |
| Cancel Redirect URL | Use a local path such as / or an admin-approved HTTP(S) URL. Signed-in users are locally logged out before this redirect. | / | `terms_of_use_decline_redirect_url` |
| Accept Button Text | Controls the user-facing copy or name shown for accept button text. | Accept and continue | `terms_of_use_accept_button_text` |
| Cancel Button Text | Controls the user-facing copy or name shown for cancel button text. | Cancel | `terms_of_use_decline_button_text` |
| Enable Support Menu for End Users | Makes support menu for end users available in the product when its required service and access policy are configured. | Off | `enable_support_menu`; capability toggle |
| Menu Name | This name will appear in user navigation as the Support menu title. | Support | `support_menu_name` |
| Enable Send Feedback Destination | Makes send feedback destination available in the product when its required service and access policy are configured. | On | `enable_support_send_feedback`; capability toggle |
| Support Recipient Email | User Send Feedback drafts will be addressed to this internal email address. | Empty | `support_feedback_recipient_email` |
| Enable Latest Features Destination | Makes latest features destination available in the product when its required service and access policy are configured. | On | `enable_support_latest_features`; capability toggle |
| Show Simple Chat Documentation Guide Links | When enabled, user-facing Latest Features cards can show public guide buttons in addition to the direct in-app shortcuts. | Off | `enable_support_latest_feature_documentation_links`; capability toggle |
| Setting | Controls visibility for an individual latest-feature entry rendered dynamically by the admin template. | Not specified in defaults | Runtime UI control |
| Enable External Links in Navigation | Makes external links in navigation available in the product when its required service and access policy are configured. | Off | `enable_external_links`; capability toggle |
| Menu Name | This name will appear in the navigation bar as the menu title. | External Links | `external_links_menu_name` |
| Force Menu Display | When enabled, external links will always display as a dropdown menu. When disabled, 1-2 links show as top-level nav items, 3+ links show as a dropdown menu. | Off | `external_links_force_menu` |
| Maximum File Size (MB) | Caps or schedules maximum file size (mb) so the feature stays within expected capacity. | 150 | `max_file_size_mb` |
| Conversation History Limit | Caps or schedules conversation history limit so the feature stays within expected capacity. | 10 | `conversation_history_limit` |
| Enable Idle Session Timeout and Warning | Makes idle session timeout and warning available in the product when its required service and access policy are configured. | Off | `enable_idle_timeout`; capability toggle |
| Idle Logout Timeout (Minutes) | Users are logged out locally after this many minutes of inactivity. Minimum value: 10 minutes. | 30 | `idle_timeout_minutes` |
| Idle Warning Time (Minutes) | Show the warning modal after this many minutes of inactivity. Set this equal to the logout timeout to disable the warning dialog window. | 28 | `idle_warning_minutes` |
| Idle Warning Message | Custom text shown at the top of the idle warning dialog. | You've been inactive for a while. | `idle_warning_message` |
| Default System Prompt | Controls how SimpleChat uses default system prompt on this tab. | Empty | `default_system_prompt` |
| Access Denied Message | Shown to signed-in users who lack the required roles. Use Enter for line breaks. | You are logged in but do not have the required permissions to access this application. Please contact an administrator for access. | `access_denied_message` |

### Terms of use

Enable this when users must acknowledge local terms before continuing. Changing the title, message, or frequency creates a new version, so previously accepted users may be prompted again. Configure the decline redirect before enabling it so users who cancel land somewhere intentional.

### Idle session timeout

Idle timeout is a local app logout control. Set the warning time lower than the logout timeout if users should have a chance to keep working; set it equal to the timeout only when you intentionally do not want a warning window.

## Before you change anything

- Have approved public-facing text for the landing page, access-denied message, Terms of Use, AI notice, and support links.
- If enabling unauthenticated `/external/healthcheckz`, confirm the monitoring system and security team expect a no-auth endpoint.
- If enabling Terms of Use, decide whether users must accept once, every session, or after text changes.
- If changing idle timeout, choose values that leave enough warning time before local logout.

## Common tasks

1. **Publish tenant branding.**
    1. Set **Application Title**.
    2. Enable **Show Logo** and upload light and dark logos if the app should use custom branding.
    3. Adjust **Main Page Logo Size** and **Markdown Alignment**.
    4. Save and verify the landing page, top navigation, and dark mode.
    Outcome to verify: The home page shows the approved name, logo, and landing-page copy.

{% include media.html src="admin/general-publish-tenant-branding.png" alt="Screenshot of the General settings tab showing publish tenant branding." title="General: Publish tenant branding" capture="Capture the General tab while performing Publish tenant branding. Show the relevant controls and redact secrets." %}

2. **Require a Terms of Use acknowledgement.**
    1. Enable **Require terms of use**.
    2. Set **Popup Title**, **Terms of Use Message**, **Show Frequency**, and button text.
    3. Set **Cancel Redirect URL**.
    4. Save and sign in with a test user.
    Outcome to verify: The test user sees the terms prompt at the configured frequency.

{% include media.html src="admin/general-require-a-terms-of-use-acknowledgement.png" alt="Screenshot of the General settings tab showing require a terms of use acknowledgement." title="General: Require a Terms of Use acknowledgement" capture="Capture the General tab while performing Require a Terms of Use acknowledgement. Show the relevant controls and redact secrets." %}

3. **Configure support navigation.**
    1. Enable **Enable Support Menu for End Users**.
    2. Set **Menu Name**.
    3. Enable **Send Feedback Destination** and enter **Support Recipient Email** if feedback should be routed.
    4. Enable **Latest Features Destination** if users should see release cards.
    Outcome to verify: The Support menu appears with only the enabled destinations.

{% include media.html src="admin/general-configure-support-navigation.png" alt="Screenshot of the General settings tab showing configure support navigation." title="General: Configure support navigation" capture="Capture the General tab while performing Configure support navigation. Show the relevant controls and redact secrets." %}

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Custom Pages]({{ '/admin/custom-pages/' | relative_url }})
- [Send Feedback]({{ '/admin/send-feedback/' | relative_url }})
- [Latest Features New]({{ '/admin/latest-features/' | relative_url }})
