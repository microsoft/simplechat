---
layout: latest-release-feature
title: "Document Intelligence Auto Mode"
description: "How Read, Layout, and Auto extraction help PDF and image uploads balance speed with richer structure"
section: "Latest Release"
---

Document Intelligence Auto Mode lets admins choose how PDF and image uploads are extracted while giving workspace users clearer visibility into the extraction path used for each document.

## User Side

Workspace users can expand document rows to review Standard, Enhanced, Auto, and enhanced-citation badges, then use metadata or Change Extraction actions when a stored PDF needs a different processing path.

## Admin Side

Admins configure extraction behavior from **Admin Settings > Search & Extract**. The screenshot gallery shows the admin extraction-mode controls alongside the user document-details view so teams can connect the setting to the visible workspace experience.

## Why It Matters

Teams can keep fast extraction for simple files while still capturing tables, forms, and selection marks when a document needs richer layout understanding.

## How to Try It

1. Open **Admin Settings > Search & Extract** and review the Document Intelligence extraction mode.
2. Choose **Read** for fast OCR-style extraction, **Layout** for richer structure, or **Auto** when SimpleChat should sample the PDF before deciding.
3. Open a workspace document list and review extraction badges or PDF reprocess actions when source blobs are available.

## Notes

- Auto mode samples PDF pages and uses richer extraction when document structure suggests it is useful.
- Reprocessing depends on the original source blob still being available.
- Image and PDF extraction settings are managed by admins.
