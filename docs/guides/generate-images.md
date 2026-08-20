---
layout: page
title: "Generate images"
description: "Use the chat Image control to request AI-generated images."
section: "Guides"
audience: user
---

## What this does

**Image** switches the chat composer into image-generation mode for the current prompt. While it is active, other source controls are disabled so the request stays focused on image generation.

{% include media.html type="video"
                      title="Generate images walkthrough"
                      poster="video-posters/guide-generate-images.png"
                      capture="Recording planned. Show generate images end to end and explain why this task helps a user." %}

## Why you would use this

Use image generation for visual concepts, drafts, illustrations, and creative exploration where the output should be an image. It replaces leaving the app for a separate image tool, but it is wrong for grounded document analysis, web research, or prompts that require private source files.

## Before you start

- Admins must enable `enable_image_generation`; see [AI Models]({{ '/admin/ai-models/' | relative_url }}).
- Tenants using APIM may also configure `enable_image_gen_apim`.
- Prompts must comply with your organization's acceptable use policy.

## Steps

1. Open **Chat**.
2. Select **Image**.
3. Type a clear visual request with subject, style, setting, and constraints.

{% include media.html src="guides/generate-images-step-3.png"
                      alt="Screenshot showing generate images step 3."
                      title="Generate images step 3"
                      capture="Capture the generate images task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Select **Send Message**.
5. Review the generated image output.

{% include media.html src="guides/generate-images-step-5.png"
                      alt="Screenshot showing generate images step 5."
                      title="Generate images step 5"
                      capture="Capture the generate images task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. Turn **Image** off before returning to normal chat, web search, URL review, file upload, or workspace grounding.

## Verify it worked

The conversation contains generated image output rather than a text-only answer. Other source controls return when **Image** is off.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Image** is missing | Image generation is disabled | Ask an admin to enable `enable_image_generation`. |
| Source controls are disabled | Image mode intentionally disables them | Turn **Image** off. |

## Related

- [Use web search]({{ '/guides/use-web-search/' | relative_url }})
- [Upload documents in chat]({{ '/guides/upload-documents-in-chat/' | relative_url }})
- [AI Models]({{ '/admin/ai-models/' | relative_url }})
