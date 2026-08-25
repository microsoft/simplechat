---
layout: latest-release-feature
title: "Sharper Document Extraction with Figure Descriptions"
description: "Enhanced extraction now reads charts, diagrams, and figures inside your documents and writes searchable descriptions of them, so answers can draw on pictures instead of skipping past them."
section: "Latest Release"
---

Current release version for Sharper Document Extraction with Figure Descriptions: **0.261.001**

When your admins turn on Enhanced extraction, SimpleChat uses Azure AI Content Understanding to describe figures, charts, and diagrams as it processes a file. Those descriptions become searchable text, so a question about a chart can be answered from the chart itself. Workspace document rows show a badge naming which extraction engine actually ran, and why it fell back if a different one was used.

## User Side

Enhanced extraction now reads charts, diagrams, and figures inside your documents and writes searchable descriptions of them, so answers can draw on pictures instead of skipping past them.

## Admin Side

Admins decide whether Sharper Document Extraction with Figure Descriptions is available in your environment. If you cannot find Open Personal Workspace and Open Chat, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Why It Matters

This matters because a large share of the meaning in reports, decks, and scanned documents lives in pictures, and until now that content was effectively invisible to search.

## How to Try It

1. Open Personal Workspace and upload a document that contains charts, diagrams, or scanned figures.
2. Wait for processing to finish, then expand the document row to see the extraction badge.
3. Hover the badge to see which engine ran, and the fallback reason if a different engine was used.
4. Open the document details to read the generated figure descriptions alongside the extracted text.
5. Go to Chat, ground on that document, and ask a question that can only be answered from a figure or chart.
6. If an older document was uploaded before this change, use Change Extraction to reprocess it with the newer engine.
7. If you do not see the option, ask your admin whether Enhanced extraction is enabled for your environment.

## Notes

- The Sharper Document Extraction with Figure Descriptions guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_enhanced_extraction_1.png`, `release_260_enhanced_extraction_2.png`, `release_260_enhanced_extraction_3.png` from the app Latest Features catalog.
