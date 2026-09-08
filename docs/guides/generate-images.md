---
layout: page
title: "Generate images"
description: "Use the chat Image control to request AI-generated images."
section: "Guides"
audience: user
version: "0.261.102"
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
- The selected resource or API Management route must support the image operation.
  Not every GPT or Responses deployment can generate images, even when ordinary
  chat works.
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

The available edit actions depend on the configured image model. Responses-backed
generation supports whole-image regeneration in SimpleChat; masked editing requires
an existing compatible direct Images model/API. Image-input support alone does not
provide either generation or masked editing.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Image** is missing | Image generation is disabled | Ask an admin to enable `enable_image_generation`. |
| Source controls are disabled | Image mode intentionally disables them | Turn **Image** off. |
| Changing the chat model does not change generated images | Chat and image defaults are independent | Ask an admin to review the image default if a different image model is needed. |
| The image model is unavailable | Its shared connection/model was deleted, disabled, or no longer published for images | Ask an admin to choose a compatible replacement in AI Connections. The application does not silently substitute another model. |
| A GPT model does not return an image | The resource may lack image-tool access, a required image backend/default, or the matching gateway operation | Ask an admin to verify image readiness on the selected resource. Rewording the prompt cannot repair a missing service capability. |
| Images fail after an administrator clears the default | An imported/shared default is authoritative | Ask an admin to select a new image default; old endpoint settings are not automatically restored. |
| Only regeneration is offered | The selected route does not support SimpleChat's masked-edit workflow | Regenerate the whole image, or ask an admin whether an approved edit-capable image deployment is available. |

## Related

- [Use web search]({{ '/guides/use-web-search/' | relative_url }})
- [Upload documents in chat]({{ '/guides/upload-documents-in-chat/' | relative_url }})
- [AI Models]({{ '/admin/ai-models/' | relative_url }})
- [Configure AI connections]({{ '/guides/configure-ai-connections/' | relative_url }})
