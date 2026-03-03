---
layout: page
title: "Export Conversation"
description: "How to export conversations in JSON or Markdown format"
section: "Latest Release"
---

Export one or multiple conversations from the Chat page in JSON or Markdown format. A guided wizard walks you through format selection, packaging options, and download.

## Exporting a Single Conversation

Right-click or click the ellipsis menu on any conversation in the sidebar to access the **Export** option.

![Single conversation export via context menu]({{ '/images/feature-export_conversation-single.png' | relative_url }})

This opens the export wizard pre-loaded with the selected conversation.

## Exporting Multiple Conversations

To export several conversations at once:

1. Click **Select** from any conversation's ellipsis menu to enter selection mode
2. Check the conversations you want to export
3. Click the **export button** in the selection toolbar

![Multi-select export mode with 2 conversations selected]({{ '/images/feature-export_conversation-multi.png' | relative_url }})

## Export Wizard

The export wizard guides you through three steps.

### Step 1: Choose Format

Select between two export formats:

- **JSON** -- Structured data format, ideal for programmatic analysis or re-import
- **Markdown** -- Human-readable format, great for documentation and sharing

![Step 1 - Choose export format]({{ '/images/feature-export_conversation-step-01.png' | relative_url }})

### Step 2: Choose Packaging

Select how the exported file(s) should be packaged:

- **Single File** -- All selected conversations combined into one file
- **ZIP Archive** -- Each conversation as a separate file inside a ZIP

![Step 2 - Choose output packaging]({{ '/images/feature-export_conversation-step-02.png' | relative_url }})

### Step 3: Review and Download

Review your export settings and click **Download Export** to save the file.

The summary shows the number of conversations, chosen format, packaging type, and resulting file extension.

![Step 3 - Review settings and download]({{ '/images/feature-export_conversation-step-03.png' | relative_url }})

## Notes

- Sensitive internal metadata is automatically stripped from exported data for security
- Export is limited to conversations you own
- When exporting a single conversation, the selection review step is skipped and the wizard starts directly at the format step
