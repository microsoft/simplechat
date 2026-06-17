---
layout: showcase-page
title: "Create Custom Pages"
permalink: /how-to/custom_pages/
menubar: docs_menu
accent: teal
eyebrow: "Developer How-To"
description: "Custom Pages developer guidance is maintained in the SimpleChat app so the in-app guide and source documentation stay aligned."
hero_icons:
  - bi-window-plus
  - bi-filetype-html
  - bi-terminal
hero_pills:
  - Static HTML fragments
  - Static HTML/CSS/JS pages
  - Python-backed Jinja and API pages
hero_links:
  - label: "Canonical Markdown"
    url: ../../application/single_app/docs/how-to/custom_pages.md
    style: primary
  - label: "Feature explanation"
    url: /explanation/features/CUSTOM_PAGES/
    style: secondary
---

# Create Custom Pages

The canonical Custom Pages developer guide is maintained inside the application at:

[application/single_app/docs/how-to/custom_pages.md](../../application/single_app/docs/how-to/custom_pages.md)

Admin Settings > Custom Pages > Developer Guide renders that same Markdown in-app. Keeping the maintained copy inside `application/single_app` ensures the guide ships with non-container deployments, ACR-built containers, and any deployment process that sends only the app artifact.

Use the linked source as the maintained guide for:

- Simple HTML custom pages
- Static HTML/CSS/JS custom pages
- Python-backed Jinja custom pages with backend API operations

Do not duplicate the full guide in this docs page. This page exists only to route developers to the same source the app renders.