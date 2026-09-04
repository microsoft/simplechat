---
layout: page
title: "Chat settings"
description: "Chat controls the conversation surface: file uploads, processing indicators, drawers, history, feedback, notifications, citations, and the default prompt."
section: "Administration"
audience: admin
admin_tab: chat
redirect_from:
  - /admin/citation/
---


# Chat settings

## What this group controls

Chat controls the conversation surface: file uploads, processing indicators, drawers, history, feedback, notifications, citations, and the default prompt.

## Why it matters

These choices affect how users inspect answers and preserve context. Citations and feedback improve reviewability, while upload and history limits decide how much evidence can enter a conversation directly.

{% include media.html src="admin-settings/citation.png" alt="Screenshot of the Chat group in Admin Settings." title="Chat settings" %}

{% include media.html type="video" title="Chat settings walkthrough" poster="video-posters/admin-chat.png" capture="Recording planned. Walk through each tab in the Chat group and explain when to change each setting." %}

## Before you change anything

- Decide whether chat uploads are allowed outside governed workspace intake.
- Confirm enhanced citation storage before enabling large citation features.
- Prepare a feedback review process before exposing thumbs controls.

## Chat Experience {#chat-experience}

### Processing Thoughts {#processing-thoughts-section}

The Processing Thoughts section belongs to the Chat Experience tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Chat File Uploads {#chat-file-uploads-section}

The Chat File Uploads section belongs to the Chat Experience tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Conversation Contents Drawer {#conversation-contents-drawer-section}

The Conversation Contents Drawer section belongs to the Chat Experience tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Workspace Scope Lock {#workspace-scope-lock-section}

The Workspace Scope Lock section belongs to the Chat Experience tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Conversation History {#conversation-history-section}

The Conversation History section belongs to the Chat Experience tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Default System Prompt {#default-system-prompt-section}

The Default System Prompt section belongs to the Chat Experience tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Fact Memory {#fact-memory-section}

Fact memory lets the assistant carry durable context between conversations, so users do not have to restate their role, preferences, or working style every time they open a new chat. Two kinds of entries are stored. Instruction memories are durable rules about how to respond, and are applied to every prompt. Fact memories are details about the user, and are recalled only when they are relevant to the current request.

This is a chat capability. It does not require agents or actions, and it does not depend on the Agents & Actions tab. Once it is on, standard chat recalls memories, users manage their own entries from Profile > Fact Memory, and the assistant saves or removes memories when a user asks it to in conversation.

Enable it when users repeatedly restate the same context, or when you want response preferences such as tone, format, or naming to persist without a custom agent. Leave it off in environments where per-user retained context is not acceptable. Existing entries are preserved while the setting is off, but they stay inactive and are not used in chat.

Memories are stored per user or per group and are only readable inside that scope. Because they persist, they are not an appropriate place for secrets or regulated data.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Processing Thoughts | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_thoughts`; capability toggle |
| Conversation History Limit | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 10 | `conversation_history_limit` |
| Default System Prompt | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `default_system_prompt` |
| Enable Chat File Uploads | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_chat_file_uploads`; capability toggle |
| Enable Conversation Contents Drawer | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_conversation_contents_drawer`; capability toggle |
| Collaborative conversations | Enables shared conversation records and collaboration endpoints so permitted users can create and participate in collaborative conversations instead of only single-user conversation threads. | On | `enable_collaborative_conversations`; no visible field in `admin_settings.html` |
| Require ChatFileUploadUser App Role | Requires the `ChatFileUploadUser` app role before users can use this capability or view. | Off | `require_member_of_chat_file_upload_user` |
| Enforce Workspace Scope Lock | Defines behavior for the related admin workflow; verify the affected feature after saving. | On | `enforce_workspace_scope_lock` |
| Enable Fact Memory | Lets standard chat recall a user's saved instruction and fact memories, and lets the assistant save, change, or remove them when the user asks. Works without agents or actions. | Off | `enable_fact_memory_plugin`; capability toggle |

## Feedback & Alerts {#feedback-alerts}

### User Feedback {#user-feedback-section}

The User Feedback section belongs to the Feedback & Alerts tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Desktop Conversation Notifications {#desktop-notifications-section}

Two ways of telling a user something happened while they were looking elsewhere. Desktop
notifications need the browser permission the user grants themselves, and the completion
sound is a short bundled audio cue played locally, with no Azure Speech resource involved.
Both are opt-in per user; these settings decide whether the option is offered at all.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable User Feedback (Thumbs Up/Down) | Shows thumbs up/down feedback controls on AI responses so users can submit response-level feedback for review. | On | `enable_user_feedback`; capability toggle |
| Enable Desktop Conversation Notifications | Allows browser desktop notifications for conversation events when the user grants browser permission. | Off | `enable_desktop_notifications`; capability toggle |
| AI response completion sounds | Lets users opt in to a short bundled sound when a response finishes while they are looking elsewhere. Played locally by the browser; no Azure Speech resource is involved. | Off | `enable_chat_completion_audio_cues`; capability toggle |
| Require FeedbackAdmin App Role | Requires the `FeedbackAdmin` app role before users can use this capability or view. | Off | `require_member_of_feedback_admin` |

## Citations {#citation}

### Standard {#standard-citations-section}

The Standard section belongs to the Citations tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Enhanced {#enhanced-citations-section}

The Enhanced section belongs to the Citations tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Enhanced Citations | Preserves source files for richer citation preview and source-document access in chat answers. | Off | `enable_enhanced_citations`; capability toggle |
| Enhanced Citations mount path | Enables use of the configured Enhanced Citations mount path for document-view routing when Enhanced Citations is on; the saved value is forced off unless Enhanced Citations is enabled. | Off | `enable_enhanced_citations_mount`; no visible field in `admin_settings.html` |
| Storage Account Authentication Type | Chooses whether SimpleChat authenticates to this service with a key, managed identity, or another supported method. | key | `office_docs_authentication_type` |
| Storage Account Connection String | Defines behavior for the related admin workflow; verify the affected feature after saving. | Empty | `office_docs_storage_account_url` |
| Storage Account Blob Service Endpoint | Provides the endpoint or route SimpleChat uses for this service. | Empty | `office_docs_storage_account_blob_endpoint` |
| Maximum File Size for Tabular Preview (MB) | Maximum blob size (in MB) allowed for tabular file previews (CSV, XLSX). Files larger than this will not be previewed. Increase for larger files if your compute has sufficient memory, or decrease to protect smaller insta | 200 | `tabular_preview_max_blob_size_mb` |
| Confirm very large row-level runs before starting | When a prompt includes an explicit large row count, users are asked to continue or narrow scope before the run starts. | On | `enable_tabular_durable_run_confirmation`; capability toggle |
| Confirmation Row Threshold | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 500 | `tabular_durable_run_confirmation_threshold_rows` |
| Confirmation Batch Threshold | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 75 | `tabular_durable_run_confirmation_threshold_batches` |
| Chunk Processing Model | Selects the deployment SimpleChat sends requests to for this capability. | current | `tabular_generated_output_chunk_model_mode` |
| Configured Chunk Model Deployment | Selects the deployment SimpleChat sends requests to for this capability. | Empty | `tabular_generated_output_chunk_model_deployment` |

## Common tasks

1. **Enable reviewable answers.** Enable citations, ask a document-grounded question, and open the cited source. Outcome to verify: Reviewers can inspect the source behind an answer.
2. **Tune conversation context.** Set history and drawer behavior, then reopen a long test conversation. Outcome to verify: Users can navigate prior turns without unexpected context loss.
3. **Collect response feedback.** Submit test feedback and check that reviewers can find it. Outcome to verify: Feedback reaches the review workflow.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Citation links do not open | Enhanced citation storage or mount settings do not match the running app. | Validate with a newly indexed document after correcting storage settings. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [AI Models settings]({{ '/admin/ai-models/' | relative_url }})
- [Appearance settings]({{ '/admin/appearance/' | relative_url }})
