---
layout: page
title: "Upload documents in chat"
description: "Attach a local file directly to the current conversation for grounded chat."
section: "Guides"
audience: user
---

## What this does

Chat file upload adds a local file to the current conversation without first visiting a workspace document page. The upload starts automatically after you choose a file.

{% include media.html type="video"
                      title="Upload documents in chat walkthrough"
                      poster="video-posters/guide-upload-documents-in-chat.png"
                      capture="Recording planned. Show upload documents in chat end to end and explain why this task helps a user." %}

## Why you would use this

Use chat upload when you need to ask about a file in the moment: a PDF someone sent you, a spreadsheet you are checking, or a document that is not worth adding to a shared workspace yet. Use a workspace or File Sync source instead for material a team should reuse.

## Before you start

- Admins must enable `enable_chat_file_uploads`; they may also require `require_member_of_chat_file_upload_user`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- The file type must be in the accept list shown by the **File** button tooltip.
- The file must fit within `max_file_size_mb` on [General settings]({{ '/admin/general/' | relative_url }}).

## Steps

1. Open **Chat** and choose a conversation.
2. Select **File** in the chat toolbar.
3. Choose a supported local file; the button changes to the file name while upload starts.

{% include media.html src="guides/upload-documents-in-chat-step-3.png"
                      alt="Screenshot showing upload documents in chat step 3."
                      title="Upload documents in chat step 3"
                      capture="Capture the upload documents in chat task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Wait for upload progress to finish before asking detailed questions.
5. Type your question in **Type your message...** and select **Send Message**.

{% include media.html src="guides/upload-documents-in-chat-step-5.png"
                      alt="Screenshot showing upload documents in chat step 5."
                      title="Upload documents in chat step 5"
                      capture="Capture the upload documents in chat task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. Use the cancel icon on the **File** button if you selected the wrong file.

## Verify it worked

The response can reference the uploaded file when relevant. If enabled, **Open used documents** can show documents used by the conversation.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The **File** button is missing | Chat uploads are disabled or role-gated | Ask an admin to enable chat uploads and assign the role if required. |
| Image mode disables file controls | Image generation intentionally turns off source controls | Turn off **Image** before uploading. |

## Related

- [Use tags in chat]({{ '/guides/use-tags-in-chat/' | relative_url }})
- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
- [General settings]({{ '/admin/general/' | relative_url }})
