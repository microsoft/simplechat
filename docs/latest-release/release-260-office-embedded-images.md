---
layout: latest-release-feature
title: "Pictures Inside Word and PowerPoint Are Now Searchable"
description: "Images embedded in Word and PowerPoint files, including SmartArt, Visio drawings, and chart graphics, are now analyzed and cited with the correct page or slide."
section: "Latest Release"
---

Current release version for Pictures Inside Word and PowerPoint Are Now Searchable: **0.260.001**

SimpleChat now pulls images out of DOCX, PPTX, and the legacy DOC and PPT formats, including EMF and WMF metafile diagrams that older Office documents use. Each image is indexed as its own citable chunk with proper page or slide attribution, duplicate images are collapsed, and figures stay in the same chunk as the text around them instead of being dumped at the end of the document.

## User Side

Images embedded in Word and PowerPoint files, including SmartArt, Visio drawings, and chart graphics, are now analyzed and cited with the correct page or slide.

## Admin Side

Admins decide whether Pictures Inside Word and PowerPoint Are Now Searchable is available in your environment. If you cannot find Open Personal Workspace and Open Chat, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Screenshot Placeholder

The v0.260.001 app catalog currently provides branded placeholder captures for Pictures Inside Word and PowerPoint Are Now Searchable. Replace these copied documentation images when final screenshots are ready:

- `/images/latest-release/release_260_office_embedded_images_1.png`
- `/images/latest-release/release_260_office_embedded_images_2.png`
- `/images/latest-release/release_260_office_embedded_images_3.png`

## Why It Matters

This matters because architecture diagrams, org charts, and process flows are often the whole point of a deck, and citations now point at the slide those visuals actually live on.

## How to Try It

1. Upload a Word document or PowerPoint deck that contains diagrams, SmartArt, or embedded charts.
2. Let processing finish, then open the document details to see the extracted image chunks.
3. Confirm each image chunk reports the page or slide number it came from.
4. Open Chat and ground a conversation on that document.
5. Ask about something that only appears in a diagram, such as a process step or a box in an org chart.
6. Open the citation on the answer and confirm it points at the correct slide or page.
7. For documents uploaded before this release, use Change Extraction or re-upload so figures land in the right chunk.

## Notes

- The Pictures Inside Word and PowerPoint Are Now Searchable guide belongs to the SimpleChat 0.260.001 latest-feature set.
- The gallery for this page uses `release_260_office_embedded_images_1.png`, `release_260_office_embedded_images_2.png`, `release_260_office_embedded_images_3.png` from the app Latest Features catalog.
