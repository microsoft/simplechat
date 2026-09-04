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

Answers that involve searching workspaces, calling an action, or running an agent
can take a while, and without any indication of progress they look like the
application has stalled. Processing thoughts shows the steps as they happen —
which documents were searched, which web queries ran, which agent was called —
and stores them alongside the message so the same trace can be reopened later
from the stars icon on any response.

The stored trace is what makes an answer auditable after the fact. Turn this on
where reviewers need to see how an answer was reached, not just what it said.
Turn it off where the extra detail is noise, or where the step list would expose
source names to users who should only see the final answer.

### Chat File Uploads {#chat-file-uploads-section}

Workspaces are the governed path for documents: they are indexed, classified, and
retained under policy. Chat file uploads are the ungoverned shortcut — a user
attaches a file to one conversation and asks about it directly, without it
entering a workspace at all.

That is the right trade-off for a quick one-off question and the wrong one for
anything that needs to be discoverable or retained. Where uploads should exist
but not for everyone, the `ChatFileUploadUser` app role narrows them to assigned
users without turning the capability off. Assign the role in the Enterprise App
before requiring it, or every user loses the ability to upload at once. Files
already attached to conversations stay visible either way; the requirement only
governs new uploads.

### Conversation Contents Drawer {#conversation-contents-drawer-section}

Long conversations are hard to navigate by scrolling, because the thing a user
wants to return to is usually their own earlier question rather than a specific
answer. The drawer lists the prompts in a conversation and jumps to the one
selected.

This is a navigation aid with no effect on what the model sees. Users who do not
want it can turn it off for their own account in their profile, so enabling it
sets the default rather than forcing it.

### Workspace Scope Lock {#workspace-scope-lock-section}

Once a conversation has searched a workspace, that workspace is where its context
comes from. Scope lock keeps it there: after the first search, the conversation
stays bound to the workspaces that produced results, so a later question cannot
quietly pull in a different data source and mix it with what has already been
discussed.

Leave this enforced where cross-contamination between data sources is a
compliance concern. Turn it off to let users deliberately unlock a conversation
and widen it mid-thread, which is convenient for exploratory work and removes the
guarantee that a conversation drew on one set of sources.

### Conversation History {#conversation-history-section}

Every request carries some of the conversation back to the model, because the
model has no memory between calls. The history limit decides how many previous
messages travel with each request. A higher limit preserves more context and
costs more tokens on every turn; a lower one is cheaper and starts losing the
thread of long conversations.

The two summarization options change what happens to the messages that fall
outside that limit and what the search sees, rather than raising the limit
itself:

- **Summarizing beyond the limit** replaces dropped messages with a running
  summary, so older context survives in compressed form instead of disappearing.
  Use it for long working sessions where the early part of the conversation still
  matters.
- **Summarizing for search** rewrites the document-search query using recent
  turns, so a follow-up like "what about the second one?" still retrieves the
  right sources. Without it, a query that only makes sense in context retrieves
  poorly. The message count controls how much recent conversation feeds that
  summary; twice that many messages are read to produce it.

Both cost an extra model call per affected turn, which is why they are off by
default.

### Default System Prompt {#default-system-prompt-section}

The default system prompt is the instruction applied to conversations that do not
carry one of their own. It is where organisation-wide expectations belong — tone,
formatting conventions, what to do when the answer is not known, and any standing
constraint that should apply whether or not a user picked an agent.

Agents and conversations with their own prompt are unaffected, so this sets the
floor rather than the ceiling. Leaving it empty is a valid choice, and means
conversations run on the model's own defaults.

### Fact Memory {#fact-memory-section}

Fact memory lets the assistant carry durable context between conversations, so
users do not have to restate their role, preferences, or working style every time
they open a new chat. Two kinds of entries are stored. Instruction memories are
durable rules about how to respond, and are applied to every prompt. Fact
memories are details about the user, and are recalled only when they are relevant
to the current request.

This is a chat capability. It does not require agents or actions, and it does not
depend on the Agents & Actions tab. Once it is on, standard chat recalls memories,
users manage their own entries from Profile > Fact Memory, and the assistant saves
or removes memories when a user asks it to in conversation.

Enable it when users repeatedly restate the same context, or when you want
response preferences such as tone, format, or naming to persist without a custom
agent. Leave it off in environments where per-user retained context is not
acceptable. Existing entries are preserved while the setting is off, but they stay
inactive and are not used in chat.

Memories are stored per user or per group and are only readable inside that scope.
Because they persist, they are not an appropriate place for secrets or regulated
data.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Processing Thoughts | Shows the steps taken while answering and stores them for later review. | On | `enable_thoughts`; capability toggle |
| Conversation History Limit | How many previous messages are carried into each new request. | 10 | `conversation_history_limit` |
| Summarize Messages Beyond the History Limit | Replaces messages outside the limit with a running summary instead of dropping them. | Off | `enable_summarize_content_history_beyond_conversation_history_limit`; capability toggle |
| Summarize Conversation History for Search | Summarizes recent turns into the document-search query so context-dependent follow-ups retrieve correctly. | Off | `enable_summarize_content_history_for_search`; capability toggle |
| Historical Messages to Summarize | How many recent messages feed the search summary. Twice this many are read to build it. | 10 | `number_of_historical_messages_to_summarize` |
| Default System Prompt | The instruction applied to conversations that do not set their own. | Empty | `default_system_prompt` |
| Enable Chat File Uploads | Lets users attach files to a conversation without adding them to a workspace. | On | `enable_chat_file_uploads`; capability toggle |
| Require ChatFileUploadUser App Role | Restricts new chat uploads to holders of the `ChatFileUploadUser` app role. | Off | `require_member_of_chat_file_upload_user` |
| Enable Conversation Contents Drawer | Adds a drawer listing a conversation's prompts for navigation. | On | `enable_conversation_contents_drawer`; capability toggle |
| Collaborative conversations | Enables shared conversation records and collaboration endpoints so permitted users can create and participate in collaborative conversations instead of only single-user conversation threads. | On | `enable_collaborative_conversations`; no visible field in `admin_settings.html` |
| Enforce Workspace Scope Lock | Keeps a conversation bound to the workspaces that produced its first search results. | On | `enforce_workspace_scope_lock` |
| Enable Fact Memory | Lets standard chat recall a user's saved instruction and fact memories, and lets the assistant save, change, or remove them when the user asks. Works without agents or actions. | Off | `enable_fact_memory_plugin`; capability toggle |

## Feedback & Alerts {#feedback-alerts}

### User Feedback {#user-feedback-section}

Thumbs up and down controls on AI responses are the cheapest signal available
about answer quality, because they cost the user one click at the moment they
have an opinion. Ratings are routed to the feedback review workflow, where
reviewers can see the conversation that produced them.

Enable this once someone is actually reviewing the results. Collecting ratings
nobody reads trains users to stop giving them.

### Desktop Conversation Notifications {#desktop-notifications-section}

Long answers encourage users to switch tabs while they wait, and then forget to
come back. Two settings here close that gap, and both are opt-in per user, so
enabling either offers the capability rather than imposing it.

A desktop notification requires browser permission, only fires when the
SimpleChat tab is hidden or unfocused, and stops entirely once the tab is closed.
Users can turn it off in their profile.

The completion sound is a short bundled audio cue the browser plays locally. No
Azure Speech resource is involved, which is why it sits here rather than with the
voice settings under Knowledge.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable User Feedback (Thumbs Up/Down) | Shows thumbs up/down feedback controls on AI responses so users can submit response-level feedback for review. | On | `enable_user_feedback`; capability toggle |
| Enable Desktop Conversation Notifications | Allows browser desktop notifications for conversation events when the user grants browser permission. | Off | `enable_desktop_notifications`; capability toggle |
| AI response completion sounds | Lets users opt in to a short bundled sound when a response finishes while they are looking elsewhere. Played locally by the browser; no Azure Speech resource is involved. | Off | `enable_chat_completion_audio_cues`; capability toggle |
| Require FeedbackAdmin App Role | Requires the `FeedbackAdmin` app role before users can use this capability or view. | Off | `require_member_of_feedback_admin` |

## Citations {#citation}

### Standard {#standard-citations-section}

Standard citations are always on, for personal and group workspaces alike, and
have nothing to configure. When an answer draws on an indexed document, the
citation exposes the text of the chunk that was used, so a user can read the
passage behind a claim without leaving the conversation.

This is the baseline everything else builds on: it needs no storage account and
no extra configuration, because the text is already in the search index.

### Enhanced {#enhanced-citations-section}

Standard citations can only show text that was extracted into the index. Enhanced
citations keep the original file in an Azure Storage account as well, so a
citation can open the source document itself — the actual spreadsheet, the actual
page — rather than a paragraph lifted out of it. That is the difference between
checking a number and checking it in context.

The cost is an Azure Storage account that SimpleChat must reach, authenticated
either with a connection string or with the application's managed identity.
Startup deliberately does not verify that account, so a storage outage cannot
prevent the application from booting, which also means a wrong credential is not
reported until a citation fails to open. Use **Test storage connection** after
changing these values: it confirms the account is reachable and reports any
expected container that does not yet exist. Missing containers are usually
harmless, because they are created on demand during upload when permissions
allow it.

Storage credentials are write-only in the admin interface. A configured value is
shown as saved and hidden rather than displayed, and can be replaced or cleared
but not read back.

**Tabular preview and run limits.** Enhanced citations is also what makes CSV and
XLSX sources previewable, so the limits governing that work live here. The preview
size cap protects the host from loading a very large spreadsheet into memory to
render a preview; raise it when the host has memory to spare and lower it on
smaller instances. The large-run confirmation catches the other failure mode: a
prompt that implies thousands of rows of work, which is better confirmed than
started by accident. The row and batch thresholds decide when that confirmation
appears. Chunk work normally reuses whichever model the user selected; pointing it
at a dedicated deployment keeps bulk row processing off the interactive model's
quota.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Enhanced Citations | Stores original files in Azure Storage so citations can open the source document, not just quoted text. | Off | `enable_enhanced_citations`; capability toggle |
| Enhanced Citations mount path | Enables use of the configured Enhanced Citations mount path for document-view routing when Enhanced Citations is on; the saved value is forced off unless Enhanced Citations is enabled. | Off | `enable_enhanced_citations_mount`; no visible field in `admin_settings.html` |
| Storage Account Authentication Type | Whether SimpleChat authenticates to the storage account with a connection string or a managed identity. | key | `office_docs_authentication_type` |
| Storage Account Connection String | Credential used for connection string authentication. Stored write-only. | Empty | `office_docs_storage_account_url` |
| Storage Account Blob Service Endpoint | Blob endpoint used for managed identity authentication. Stored write-only. | Empty | `office_docs_storage_account_blob_endpoint` |
| Maximum File Size for Tabular Preview (MB) | CSV and XLSX files above this size are not previewed, which protects the host from loading very large spreadsheets into memory. | 200 | `tabular_preview_max_blob_size_mb` |
| Confirm very large row-level runs before starting | When a prompt includes an explicit large row count, users are asked to continue or narrow scope before the run starts. | On | `enable_tabular_durable_run_confirmation`; capability toggle |
| Confirmation Row Threshold | Row count at or above which the confirmation is shown. | 500 | `tabular_durable_run_confirmation_threshold_rows` |
| Confirmation Batch Threshold | Batch count at or above which the confirmation is shown. | 75 | `tabular_durable_run_confirmation_threshold_batches` |
| Chunk Processing Model | Whether per-chunk work reuses the user's selected model or a deployment set aside for it. | current | `tabular_generated_output_chunk_model_mode` |
| Configured Chunk Model Deployment | Deployment name used when chunk work runs on its own model. | Empty | `tabular_generated_output_chunk_model_deployment` |

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
