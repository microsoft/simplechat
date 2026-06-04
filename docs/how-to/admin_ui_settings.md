---
layout: showcase-page
title: "Configure Branding, Home Page, and Support Settings"
permalink: /how-to/admin_ui_settings/
menubar: docs_menu
accent: teal
eyebrow: "Admin How-To"
description: "Use Admin Settings to brand Simple Chat, customize the home page, expose support links, enable health checks, and publish API documentation for operators and integrators."
version: "0.241.134"
keywords:
  - branding
  - custom logo
  - application title
  - home page text
  - landing page markdown
  - health check
  - swagger
  - api documentation
  - classification banner
  - support menu
  - send feedback
  - external links
  - system settings
hero_icons:
  - bi-palette
  - bi-house-gear
  - bi-life-preserver
hero_pills:
  - Branding and home page copy
  - Health checks and Swagger
  - Support and external navigation
hero_links:
  - label: "Admin configuration overview"
    url: /admin_configuration/
    style: primary
  - label: "API reference"
    url: /reference/api_reference/
    style: secondary
---

Use this guide when an admin needs to make the deployed application feel like the organization's product: name it, upload the logo, explain the home page, show data classification, expose help links, and decide which operational endpoints should be visible.

Documented for version **0.241.134**.

<section class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--blue">
        <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
                <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-palette"></i></span>
                <span class="latest-release-card-badge">Brand</span>
            </div>
            <h2>Branding and home page</h2>
            <p class="latest-release-card-summary">Set the title, logo, favicon, home page markdown, and home page logo size from the General tab.</p>
        </div>
    </article>
    <article class="latest-release-card latest-release-accent--emerald">
        <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
                <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-heart-pulse"></i></span>
                <span class="latest-release-card-badge">Operate</span>
            </div>
            <h2>Health and API docs</h2>
            <p class="latest-release-card-summary">Enable external health probes and Swagger/OpenAPI only when the environment should expose those operational routes.</p>
        </div>
    </article>
    <article class="latest-release-card latest-release-accent--orange">
        <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
                <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-link-45deg"></i></span>
                <span class="latest-release-card-badge">Guide users</span>
            </div>
            <h2>Support and links</h2>
            <p class="latest-release-card-summary">Expose Support, Latest Features, Send Feedback, and external resource links from the navigation users already know.</p>
        </div>
    </article>
</section>

## Open the right settings area

1. Sign in with an account that has the **Admin** role.
2. Open **Admin Settings**.
3. Select **General**.
4. Make changes in the relevant card and use **Save Settings**.
5. Open the affected user page in a new browser tab or private window to verify the saved configuration.

Most items in this guide live in **General** because they affect the shell of the application rather than a single workspace, model, or feature pack.

## Branding

Use **General > Branding** when you want the app header and landing experience to match the organization.

| Setting | What it controls | Notes |
| :--- | :--- | :--- |
| **Application Title** | Browser title and visible app naming | Keep it short enough for navigation and browser tabs. |
| **Show Logo** | Whether the app displays the configured logo in the interface | Enable this after uploading a logo. |
| **Hide Application Title** | Whether the header shows text next to the logo | Use this only when the logo itself includes the product or organization name. |
| **Main Page Logo Size** | Logo scale on the home page only | This does not change the top navigation or sidebar logo size. |
| **Upload Custom Logo (Light Mode)** | Logo used in light mode | PNG or JPG/JPEG is accepted. The app stores the image at up to 500 pixels tall. |
| **Upload Custom Logo (Dark Mode)** | Logo used in dark mode | If you skip this, the light-mode logo is reused. |
| **Upload Custom Favicon** | Browser tab icon | PNG, JPG/JPEG, or ICO is accepted. 16x16 or 32x32 pixels works best. |

After saving, check both light and dark themes. Logos that look crisp on a white background can disappear on dark mode if they use transparent dark text.

## Home Page Text

Use **General > Home Page Text** to control the copy users see before entering the app.

1. Choose **Markdown Alignment**: left, center, or right.
2. Enable **Markdown Editor** when you want to edit the landing page content in the admin page.
3. Edit the **landing page text** using Markdown.
4. Use the preview to check links, headings, and line breaks.
5. Save and open the home page to confirm the final rendering.

Good home page text usually answers three questions: who the app is for, what data handling expectations apply, and where users can get help. If you link to policy pages or internal guidance, use full URLs or application-relative paths that work in the deployed environment.

## Health Checks

Use **General > Health Check** when an uptime monitor, load balancer, or platform probe needs a lightweight endpoint.

| Endpoint | Toggle | Response shape | When to use |
| :--- | :--- | :--- | :--- |
| `/external/healthcheck` | **Enable /external/healthcheck** | Plain timestamp text | Internal monitoring tools that can reach a protected application route. |
| `/external/healthcheckz` | **Enable /external/healthcheckz** | JSON object with `status: "ok"` and `time` | Health probes that cannot sign in and only need availability. |

Keep the unauthenticated endpoint behind trusted network paths when possible. It is intentionally small, but it still tells a caller that the app is reachable.

## API Documentation

Use **General > API Documentation** to control the live Swagger/OpenAPI route browser.

1. Enable **Swagger/OpenAPI Documentation (/swagger)**.
2. Save settings.
3. Open `/swagger` in the deployed environment.
4. Use `/swagger.json` or `/swagger.yaml` when a tool needs the OpenAPI document.

Disable Swagger in environments where live route inspection should not be exposed to normal users. The repository-side OpenAPI artifact can still be used during review when a live environment is not available.

## Classification Banner

Use **General > Classification Banner** when every page should carry a visible sensitivity label.

1. Enable **Classification Banner**.
2. Enter the **Banner Text**, such as `Internal Use Only` or the label your organization requires.
3. Pick the **Banner Color** and **Banner Text Color**.
4. Check the preview for contrast before saving.
5. Save and verify the banner on the home page, chat page, workspace pages, and admin pages.

The banner is a visual reminder. It does not replace RBAC, workspace permissions, content safety, or data loss prevention controls.

## Support Menu

Use **General > Support** when users should have a predictable place for help, feedback, and release guidance.

| Setting | What it does |
| :--- | :--- |
| **Enable Support Menu for End Users** | Adds the Support menu to user navigation. |
| **Menu Name** | Renames the menu if your organization uses a different support label. |
| **Enable Send Feedback Destination** | Lets users prepare a feedback email from the app. |
| **Support Recipient Email** | Sets the internal recipient for user feedback drafts. |
| **Enable Latest Features Destination** | Shows user-facing Latest Features under Support. |
| **Show Simple Chat Documentation Guide Links** | Adds public documentation buttons to Latest Features cards. |
| **User-Facing Latest Features** | Lets admins choose which feature announcements are visible to end users. |

If **Send Feedback** is enabled, provide a real recipient address before saving. If the recipient is blank or invalid, the app disables the feedback destination and warns the admin.

## External Links

Use **General > External Links** when you want the app navigation to point to policy pages, prompt guides, help desks, training, or other internal resources.

1. Enable **External Links in Navigation**.
2. Set the **Menu Name**.
3. Decide whether to enable **Force Menu Display**.
4. Add each link with a label and URL.
5. Save and verify the links in the main navigation.

When **Force Menu Display** is off, one or two links can appear as top-level navigation items and three or more links become a dropdown. When it is on, links always appear under the external links menu.

## System Settings

Use **General > System Settings** for application-wide behavior that affects many workflows.

| Setting | What it affects | Default |
| :--- | :--- | :--- |
| **Maximum File Size (MB)** | Upload validation for document and chat file workflows | 150 MB |
| **Conversation History Limit** | Recent conversation turns sent into chat context | 10 |
| **Default System Prompt** | Baseline instruction inserted when a conversation does not already have a general system prompt | Blank |

Increasing file size or history limits can improve user flexibility, but it can also increase processing time, token use, and service cost. Change these deliberately and validate with a representative upload or chat workflow.

## Validation checklist

- Search the docs home page for the terms users are likely to type, such as `branding`, `home page text`, `health check`, `Swagger`, `classification banner`, `support menu`, and `external links`.
- Open the home page after branding and landing page changes.
- Check light and dark mode after logo changes.
- Call the enabled health endpoint from the monitoring network path, not only from your workstation.
- Open `/swagger` only in environments where API documentation should be visible.
- Sign in as a normal user to verify Support and external link navigation.
- Keep internal links, support email addresses, and classification labels aligned with your organization's policy language.

## Related pages

- [Admin Configuration]({{ '/admin_configuration/' | relative_url }})
- [Admin Configuration Reference]({{ '/reference/admin_configuration/' | relative_url }})
- [API Reference]({{ '/reference/api_reference/' | relative_url }})
- [Support Menu]({{ '/latest-release/support-menu/' | relative_url }})
- [Send Feedback]({{ '/latest-release/send-feedback/' | relative_url }})