---
layout: latest-release-feature
title: "Multi Inline Image Generation"
description: "Chat can now create multiple inline images from one request, and model responses can propose useful images during an answer for you to approve before generation."
section: "Latest Release"
---

Current release version: **0.250.001**

Application version when added to the user feature catalog: **0.250.034**

Image generation now supports richer conversational workflows. You can ask for several images in a single prompt, and models can suggest images that would help explain or complete an answer while keeping generation behind an approval step.

## User Side

Chat can now create multiple inline images from one request, and model responses can propose useful images during an answer for you to approve before generation.

## Admin Side

Availability may depend on tenant settings, governance policies, workspace scope, action configuration, image-generation model setup, or admin-managed identities. If you do not see this capability, contact your SimpleChat admin.

## Screenshot Placeholder

Replace `/images/latest-release/release_250_multi_inline_image_gen.png` with a screenshot showing multi inline image generation and approval in chat.

## Why It Matters

This matters because image creation can become part of the conversation flow without forcing users to send one image request at a time or accept unapproved generated media.

## How to Try It

1. Ask Chat to create multiple related images in one request when you need a set of options, variations, or supporting visuals.
2. Review proposed images from assistant responses before approving generation.
3. Use inline image cards to inspect generated images directly in the conversation.

## Notes

- This guide is part of the SimpleChat 0.250.001 latest-feature set.
- Added to the user feature catalog in application version 0.250.034.
