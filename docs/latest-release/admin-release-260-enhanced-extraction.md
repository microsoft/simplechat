---
layout: latest-release-feature
title: Enabling Azure AI Content Understanding Extraction
description: Admins can enable Enhanced extraction with Azure AI Content Understanding so users receive richer document and figure understanding.
section: Latest Release
generated_from_catalog: true
---

Current release version for Enabling Azure AI Content Understanding Extraction: **0.261.001**

Enhanced extraction now uses Azure AI Content Understanding prebuilt-documentSearch instead of Document Intelligence Layout, adding AI-generated descriptions for figures, charts, and diagrams. Auto mode upgrades when figures are present, existing Enhanced or Auto deployments are migrated on upgrade, and users see extraction engine badges with fallback reasons in workspaces.

## Why It Matters

This matters because admins can improve retrieval quality for visual documents while preserving controlled fallback visibility.

## How to Try It

1. Open Admin Settings > Document Extraction and enable the Enhanced extraction toggle for Azure AI Content Understanding.
2. Review existing Enhanced or Auto settings after upgrade to confirm the migration preserved the intended mode.
3. Tell workspace owners that users will see extraction engine badges and fallback reasons on processed documents.
4. Re-extract important documents with figures, charts, or diagrams so end users benefit from generated descriptions.

## Where to Find It

- **Open Document Extraction** &mdash; Enable and review Enhanced extraction configuration.
