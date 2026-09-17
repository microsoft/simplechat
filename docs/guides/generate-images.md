---
layout: page
title: "Generate images"
description: "Use the chat Image control to request AI-generated images."
section: "Guides"
audience: user
version: "0.261.107"
---

## What this does

**Image** switches the chat composer into image-generation mode for the current prompt. While it is active, other source controls are disabled so the request stays focused on image generation.

Images use the administrator's global image default from **AI Connections**, not the
model currently selected for text chat. The image default can share a connection with
chat or use a separate image-only resource. There is no second model picker in chat.

{% include media.html type="video"
                      title="Generate images walkthrough"
                      poster="video-posters/guide-generate-images.png"
                      capture="Recording planned. Show generate images end to end and explain why this task helps a user." %}

## Why you would use this

Use image generation for visual concepts, drafts, illustrations, and creative exploration where the output should be an image. It replaces leaving the app for a separate image tool, but it is wrong for grounded document analysis, web research, or prompts that require private source files.

## Before you start

- Admins must enable image generation and select a supported image default; see
  [Configure AI connections]({{ '/guides/configure-ai-connections/' | relative_url }}).
  This does not require enabling **Use AI Connections for chat**.
- The selected resource or gateway must support the image operation. Azure OpenAI
  and Foundry use dedicated image models in SimpleChat. GPT-based image tools are
  available through compatible direct OpenAI **Custom** connections, not by
  selecting an Azure GPT chat deployment.
- Prompts must comply with your organization's acceptable use policy.

## Steps

1. Open **Chat**.
2. Select **Image**.
3. Type a clear visual request with subject, style, setting, and constraints.

{% include media.html src="guides/generate-images-step-3.png"
                      alt="The chat composer with Image mode active and its tooltip showing, an image prompt typed in the message box, and the other source controls greyed out."
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

The conversation contains generated image output rather than a text-only answer. Other
source controls return when **Image** is off. A text description of a proposed picture
is not successful image generation.

## Edit an image or create a replacement

The image editor uses the administrator's selected image model, not the text-chat
model. Its capability information explains which changes are possible:

| Operation | What is sent | When to use it |
| --- | --- | --- |
| Masked edit | The current image, your instruction, and the selected region | Change a particular area using a supported GPT Image or direct OpenAI image-tool operation |
| Whole-image reference edit | The current image and your instruction, without a mask | Refine an image with an edit-capable MAI Image or FLUX model, or edit a GPT image without selecting a region |
| Whole-image regeneration | A revised prompt, not the current image as a reference | Create a replacement or change generation-only rendering options |

Masking is guidance, not a guarantee that every pixel outside the region stays
identical. MAI and FLUX reference editing does not imply an uploaded-mask interface,
so those models do not offer region selection. Controls reflect the selected
operation; GPT quality/background choices are not sent to MAI or FLUX.

If the image default becomes unavailable, new generation/edit actions are disabled.
Existing revision history can still be reviewed and restored. An unsupported or
stale mask is rejected rather than silently turning the request into regeneration.

Provider and cloud labels describe the configured model endpoint. A SimpleChat
installation in Azure Government can use an approved commercial endpoint; that does
not make the image service Government-resident. An unknown availability label means
the reviewed provider documentation does not establish availability in that cloud,
not that all Government-hosted installations must disable images.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Image** is missing | Image generation is disabled | Ask an admin to enable `enable_image_generation`. |
| Source controls are disabled | Image mode intentionally disables them | Turn **Image** off. |
| Changing the chat model does not change generated images | Chat and image defaults are independent | Ask an admin to review the image default if a different image model is needed. |
| The image model is unavailable | Its shared connection/model was deleted, disabled, or no longer published for images | Ask an admin to choose a compatible replacement in AI Connections. The application does not silently substitute another model. |
| An Azure GPT model is no longer an image choice | SimpleChat offers dedicated image models on Azure/Foundry rather than GPT image-tool orchestration | Ask an admin to select GPT Image, MAI Image, or a supported Foundry FLUX deployment. Direct OpenAI tool generation belongs in a Custom connection. |
| Images fail after an administrator clears the default | An imported/shared default is authoritative | Ask an admin to select a new image default; old endpoint settings are not automatically restored. |
| Reference edits are available but no region selector appears | The model's image API does not document an uploaded-mask operation | Describe a whole-image change, or use an approved mask-capable model when precise region guidance is needed. |
| Only regeneration is offered | The selected operation does not support source-image editing | Create a new image from the prompt, or ask an admin about an approved edit-capable model. |

## Related

- [Use web search]({{ '/guides/use-web-search/' | relative_url }})
- [Upload documents in chat]({{ '/guides/upload-documents-in-chat/' | relative_url }})
- [AI Models]({{ '/admin/ai-models/' | relative_url }})
- [Configure AI connections]({{ '/guides/configure-ai-connections/' | relative_url }})
