---
layout: page
title: "Generate images"
description: "Use the chat Image control to request AI-generated images."
section: "Guides"
audience: user
version: "0.261.192"
---

## What this does

**Image** switches the chat composer into image-generation mode for the current prompt. While it
is active, web search, URL review, and Deep Research are turned off so the request stays focused
on image generation. From version **0.261.192**, file upload and **Documents** stay available in
Image mode when the image model can use reference images: the pictures you attach are sent to the
image model as visual input, not only described in text.

Images use the administrator's global image default from **AI Connections**, not the
model currently selected for text chat. The image default can share a connection with
chat or use a separate image-only resource. There is no second model picker in chat.

{% include media.html type="video"
                      title="Generate images walkthrough"
                      poster="video-posters/guide-generate-images.png"
                      capture="Recording planned. Show generate images end to end and explain why this task helps a user." %}

## Why you would use this

Use image generation for visual concepts, drafts, illustrations, and creative exploration where the output should be an image. It replaces leaving the app for a separate image tool. Attach a picture when the result should be based on something real: a cartoon of your house from a photo, a new portrait that keeps your face, or an architectural diagram drawn from a landscape map. Image generation is the wrong tool for grounded document analysis or web research, because the image model does not search your workspaces or the web.

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

6. Turn **Image** off before returning to normal chat, web search, URL review, or workspace grounding.

## Create an image from your own pictures (V2)

From version **0.261.192**, the V2 interface can send your images to the image model as
references. The model sees the picture itself, so it can keep a face, follow the layout of a
house, or trace the shapes on a map.

1. Select **Image**.
2. Add one or more pictures:
   - Select **Attach a reference image**, paste an image, or drop it on the message box.
   - Select **Documents** to pick images already in a workspace. In Image mode the list shows only
     images.
   - Select **Use as reference** under an image already in the conversation, or in its full-size
     viewer. This also turns **Image** on.
3. Check the count under the message box, for example **2 / 10 reference images**. The second
   number is how many references the selected image model accepts.
4. Describe the result, for example "Make a cartoon of this house at sunset" or "Use image 1 for
   the face and image 2 for the background". References are numbered in the order you attached
   them.
5. Select **Send Message**. Your sent message shows the reference thumbnails, and the new image
   follows it.

References can be PNG, JPG, BMP, or TIFF files. HEIC and HEIF photos (the iPhone default) are
refused; convert them to JPG or PNG first. A reference added with **Use as reference** applies
only to the conversation it came from and is dropped if you open another conversation.

How many references a model accepts depends on the model:

| Image model | References per request |
| --- | --- |
| GPT Image (OpenAI or Azure OpenAI) | Up to 10 (the SimpleChat limit) |
| FLUX.2 flex | Up to 10 |
| FLUX.2 pro | Up to 8 |
| MAI Image, FLUX Kontext | 1 |
| Generation-only models, such as DALL·E 3 | None; attaching is disabled |

With GPT Image 1 and 1.5, SimpleChat also asks the model to preserve the reference's details
closely, which helps with faces. Provider safety systems can still refuse some requests, for
example edits of real people.

### Edit an uploaded picture into a new image

Select **Edit** under an image you uploaded. The editor opens as **Create image from
reference**. Describe the change, optionally select a region when the model supports masking,
and select **Create new image**. The result is a new image in the conversation; your upload is
not changed.

### Use your pictures in an orchestrated plan

With **Orchestrate** and **Image** both on, the pictures you attach, select, or add with **Use as
reference** are offered to the plan's image tasks instead of being sent straight to the image
model. Ask for the whole task, for example "research craftsman architecture and create a cartoon
of my house in that style". The plan's **Generate image** task shows each reference it will use,
and in Review you can remove a reference before approving. See
[Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

## Verify it worked

The conversation contains generated image output rather than a text-only answer. When you
attached references, your sent message shows their thumbnails under **Reference images**, and
the response progress reports how many reference images were used. Web search, URL review, and
Deep Research return when **Image** is off. A text description of a proposed picture is not
successful image generation.

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
| Web search, URL review, or Deep Research are disabled | Image mode intentionally turns them off | Turn **Image** off. |
| File upload and **Documents** are disabled in Image mode | The selected image model can't use reference images, or the conversation is shared | Describe the image in text, or ask an admin about an edit-capable image model. Reference images aren't available in shared conversations. |
| "HEIC images can't be used as reference images yet" | HEIC and HEIF photos aren't converted | Export the photo as JPG or PNG and attach that instead. |
| "The selected image model accepts at most N reference images" | More references than the model allows | Remove references until the count is within the limit shown under the message box. |
| A reference is reported as not found | It was deleted, you lost access to it, or it belongs to another conversation | Attach the image again from this conversation or from a workspace you can open. |
| Orchestrate says "The configured image model cannot use reference images" | The image model was changed to one without reference support after the page loaded | Reload the page, or remove the references and describe the image in text. |
| Orchestrate says "A reference image could not be opened" | A referenced picture was deleted, you lost access to it, or it isn't a supported image | Attach the picture again as PNG, JPG, BMP, or TIFF, then resend. |
| The retry of an edited region changed the whole image | The selected region isn't saved with the message | Use **Edit** on the upload again and reselect the region. |
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
