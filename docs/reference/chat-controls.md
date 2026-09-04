---
layout: page
title: "Chat interface controls"
description: "Reference for every documented control in the SimpleChat chat interface."
section: "Reference"
audience: user
---

## How to use this reference

Use this page when you can see a control in Chat but are not sure what it does or when to use it. The generated inventory lists 47 real controls plus 3 child sub-elements. The child elements `document-comparison-edit-btn-label`, `fork-conversation-button-label`, and `fork-conversation-button-spinner` are mentioned with their parent controls instead of receiving separate rows.

## Conversation list

{% include media.html src="reference/chat-controls-conversation-list.png" alt="Conversation list showing selection actions and the new-chat button." title="Conversation list" capture="Capture the conversation list with selection actions and the new-chat button visible. Redact conversation titles and user names." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `pin-selected-btn` | Pins the selected conversations so they stay prominent in the conversation list. | Use it when a project, incident, or recurring workflow needs to stay easy to find. | Always available |
| `hide-selected-btn` | Hides selected conversations from the normal feed without deleting them. | Use it to reduce noise while keeping conversations recoverable from hidden/history views. | Always available |
| `delete-selected-btn` | Starts deletion for selected conversations. If archiving is enabled, deletion can archive instead of immediately removing records. | Use it when old conversations should no longer appear in your active workspace. | Always available |
| `export-selected-btn` | Opens the export flow for selected conversations. | Use it when you need an offline copy for handoff, records, review, or migration. | Always available |
| `new-conversation-btn` | Creates a fresh chat thread and resets the active conversation context. | Use it when a new task should not inherit previous context, documents, or agent state. | Always available |

## Conversation header and status

{% include media.html src="reference/chat-controls-conversation-header.png" alt="Conversation header with title actions, scope lock, workflow activity, contents, and document buttons visible." title="Conversation header" capture="Capture the conversation header with title actions, scope lock, workflow activity, contents, and document buttons visible. Redact conversation title." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `workflow-activity-btn` | Opens the workflow activity view associated with the current conversation when a workflow run is linked. | Use it to inspect workflow progress, failures, and generated activity without leaving the chat context. | Always available |
| `conversation-info-btn` | Opens conversation details for the active chat. | Use it when you need ownership, timestamps, participants, or other conversation-level facts. | Always available |
| `conversation-contents-toggle` | Opens the conversation contents drawer for navigating messages and artifacts. | Use it in long chats when jumping to a section is faster than scrolling. | Always available |
| `conversation-documents-toggle` | Opens the used-documents drawer for files and sources referenced by the conversation. | Use it to audit what grounded an answer or to get back to a cited source. | Always available |
| `header-scope-lock-btn` | Shows that the conversation search/document scope is locked and opens the scope-lock modal. | Use it to confirm why a chat is constrained before asking broader questions. | Always available |
| `confirm-scope-lock-toggle-btn` | Confirms a scope-lock change from the scope-lock modal. | Use it when you intentionally want to lock or unlock the conversation scope after reviewing the warning. | Always available |

## Chat tools and composer

{% include media.html src="reference/chat-controls-composer-tools.png" alt="Message composer with quick tools, upload controls, URL review, web search, and send button visible." title="Chat tools and composer" capture="Capture the message composer with quick tools, upload controls, URL review, web search, and send button visible." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `image-generate-btn` | Adds image-generation intent to the chat flow so the assistant can create images from the prompt. | Use it for visual concepts, mockups, illustrations, or generated imagery rather than text-only answers. | [`enable_image_generation`]({{ '/admin/ai-models/' | relative_url }}) |
| `search-documents-btn` | Opens the grounded search panel for searching workspace documents from chat. | Use it when the answer should come from personal or group workspace content instead of general model knowledge. | [`enable_group_workspaces`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| `choose-file-btn` | Lets you select a supported local file and starts chat upload processing for the conversation. | Use it when the file is the immediate subject of the conversation and you do not want to visit Workspace first. | [`enable_chat_file_uploads`]({{ '/admin/workspaces/' | relative_url }}) |
| `upload-btn` | Adds the selected upload to the chat after file selection. | Use it to confirm an upload before asking questions about that file. | [`enable_web_search`]({{ '/admin/knowledge/' | relative_url }}) |
| `search-web-btn` | Sends the current message to an admin-configured Azure AI Foundry agent, which searches the public web through Grounding with Bing Search and returns results with citations. | Use it for current events, public facts, or external pages that are not in your workspaces. Only the message you type is sent externally, never conversation history or workspace content. | [`enable_web_search`]({{ '/admin/knowledge/' | relative_url }}) |
| `url-access-btn` | Opens review for URLs pasted into the message so they can be inspected by the chat flow. | Use it when pasted links should be fetched or reasoned over instead of treated as plain text. | [`enable_url_access`]({{ '/admin/knowledge/' | relative_url }}) |
| `source-review-btn` | Starts Deep Research so SimpleChat can inspect search results and linked source pages within configured crawl limits. | Use it for research tasks where source review and evidence collection matter more than a quick answer. | [`enable_source_review`]({{ '/admin/knowledge/' | relative_url }}) |
| `send-btn` | Sends the current composer message to the selected model or agent. | Use it once the prompt, files, scope, and optional tools are ready. | Always available |
| `scroll-to-bottom-btn` | Jumps the message pane to the newest message when you are scrolled upward. | Use it to return to an in-progress response or the latest turn. | Always available |
| `chat-mobile-tools-toggle` | Opens the mobile tools panel containing quick actions, voice controls, and selectors. | Use it on smaller screens when desktop toolbar controls move into the offcanvas panel. | Always available |
| `chat-tutorial-btn` | Launches the guided chat walkthrough. | Use it when onboarding users or when you want a reminder of the main chat workflow. | Always available |

## Prompt, model, agent, and reasoning selectors

{% include media.html src="reference/chat-controls-selectors.png" alt="Toolbar selectors showing saved prompts, model picker, agent picker, reasoning, and voice-response toggle." title="Prompt, model, agent, and reasoning selectors" capture="Capture toolbar selectors showing saved prompts, model picker, agent picker, reasoning, and voice-response toggle." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `search-prompts-btn` | Shows the saved-prompt picker button for finding prompts available from enabled workspaces and agents. | Use it when you want a reusable prompt instead of typing instructions from scratch. | [`enable_group_workspaces`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_public_workspaces`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }})<br>[`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| `prompt-dropdown-button` | Opens the searchable saved-prompt dropdown. | Use it to insert a prepared prompt for a common workflow, team standard, or public workspace task. | [`enable_group_workspaces`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_public_workspaces`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| `model-dropdown-button` | Opens the searchable model picker for the active chat. | Use it when you need a different approved model for cost, quality, modality, or policy reasons. | Always available |
| `enable-agents-btn` | Switches the chat toolbar toward agent selection when agents are enabled. | Use it when the task needs configured tools, instructions, or actions rather than a plain model response. | [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}) |
| `agent-dropdown-button` | Opens the searchable agent picker. | Use it to choose a specialized agent with approved instructions, actions, documents, or governance scope. | Always available |
| `reasoning-toggle-btn` | Opens reasoning-effort controls for models that support configurable reasoning. | Use it when a hard planning or analysis task needs more deliberate reasoning, or a simple task should be cheaper/faster. | Always available |
| `tts-autoplay-toggle-btn` | Toggles automatic spoken playback for AI responses. | Use it for hands-free review, accessibility, or listening while working in another window. | [`enable_text_to_speech`]({{ '/admin/knowledge/' | relative_url }}) |

## Grounded search and document scope

{% include media.html src="reference/chat-controls-grounded-search.png" alt="Grounded Search panel with action, scope, document, tags, filters, and comparison controls visible." title="Grounded search and document scope" capture="Capture the Grounded Search panel with action, scope, document, tags, filters, and comparison controls visible." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `scope-dropdown-button` | Chooses the workspace scope used by grounded search, such as all accessible content, personal, group, or public workspaces. | Use it when the same question should be limited to a team workspace, public workspace, or personal files. | Always available |
| `document-dropdown-button` | Chooses the specific documents used by grounded search, analysis, or comparison. | Use it when you know which file or small document set should ground the answer. | Always available |
| `tags-dropdown-button` | Filters grounded search by document tags. | Use it to narrow broad workspaces to a topic, project, lifecycle stage, or classification. | Always available |
| `clearFiltersBtn` | Clears selected grounded-search filters. | Use it when a search is too narrow or you want to return to the full chosen scope. | Always available |
| `document-comparison-edit-btn` | Reopens comparison setup for source/target document selections. The child label `document-comparison-edit-btn-label` supplies the visible text. | Use it when the wrong source or target document was selected for Compare. | Always available |

## Search within a conversation

{% include media.html src="reference/chat-controls-conversation-search.png" alt="Search-in-conversation modal with Search, Previous, Next, Clear Filters, and Clear History controls." title="Search within a conversation" capture="Capture the search-in-conversation modal with Search, Previous, Next, Clear Filters, and Clear History controls visible." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `performSearchBtn` | Runs the current search query against conversation content. | Use it to find a prior answer, pasted detail, citation, or decision inside a long conversation. | Always available |
| `searchPrevBtn` | Moves to the previous match in the conversation search results. | Use it to step backward through matches without closing the search panel. | Always available |
| `searchNextBtn` | Moves to the next match in the conversation search results. | Use it to scan every occurrence of a term or phrase in order. | Always available |
| `clearHistoryBtn` | Clears stored conversation search history. | Use it when old searches are no longer useful or should not appear as suggestions. | Always available |

## Export, fork, and delete dialogs

{% include media.html src="reference/chat-controls-export-fork-delete.png" alt="Conversation export, fork, and delete confirmation dialogs with navigation and confirmation buttons visible." title="Export, fork, and delete dialogs" capture="Capture conversation export, fork, and delete confirmation dialogs with navigation and confirmation buttons visible. Redact content." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `export-prev-btn` | Moves back to the previous step in the conversation export flow. | Use it to revise export choices before creating the output. | Always available |
| `export-next-btn` | Moves forward to the next step in the conversation export flow. | Use it to continue after choosing conversations and export options. | Always available |
| `confirm-fork-conversation-btn` | Confirms forking the conversation; `fork-conversation-button-label` supplies text and `fork-conversation-button-spinner` appears while the fork runs. | Use it when you want a separate branch of the same chat context for a different direction or experiment. | Always available |
| `confirm-delete-conversation-btn` | Confirms deletion for the active conversation. | Use it after reviewing the delete dialog and deciding the conversation should be removed or archived. | Always available |

## Collaboration and replies

{% include media.html src="reference/chat-controls-collaboration.png" alt="Collaboration dialog showing participant confirmation and reply cancellation controls." title="Collaboration and replies" capture="Capture the collaboration dialog showing participant confirmation and reply cancellation controls. Redact names and email addresses." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `collaboration-confirm-add-btn` | Confirms adding a participant to a collaborative conversation. | Use it when the selected person should join the shared conversation. | Always available |
| `collaboration-reply-cancel-btn` | Cancels the current reply-to-message state. | Use it when you started replying to a specific message but want the next message to be a normal conversation turn. | Always available |

## Voice input

{% include media.html src="reference/chat-controls-voice.png" alt="Composer voice input recording state with microphone, send recording, and cancel recording controls visible." title="Voice input" capture="Capture the composer voice input recording state with microphone, send recording, and cancel recording controls visible." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `speech-input-btn` | Starts voice input capture for speech-to-text in chat. | Use it to dictate longer prompts, work hands-free, or reduce typing. | [`enable_speech_to_text_input`]({{ '/admin/knowledge/' | relative_url }}) |
| `send-recording-btn` | Submits the captured recording for transcription and chat input. | Use it after recording a prompt you want SimpleChat to process. | Always available |
| `cancel-recording-btn` | Stops and discards the current voice recording. | Use it when you misspoke, captured background noise, or no longer want to send the dictated prompt. | Always available |

## Context references (V2 interface)

These controls exist only in the V2 interface, so they are not part of the generated inventory above, which is taken from the classic chat page. They replace the classic scope, tags, and documents dropdowns with one list of what the next message is pointed at. See [Chat Context Picker]({{ '/explanation/features/CHAT_CONTEXT_PICKER/' | relative_url }}) for the full description.

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Documents button | Opens a search panel above the composer listing your documents, tags, and workspaces grouped by workspace, with checkboxes. Its first row, **Search all my documents**, is the original on/off relevance search. | Use it to pick the specific documents an answer should come from, rather than hoping a relevance search surfaces them. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| `#` in the message box | Searches documents, tags, and workspaces across your personal workspace, your groups, and visible public workspaces, and inserts the chosen one as `#[Name]`. | Use it to name a document while writing, without leaving the sentence to open a menu. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| Context chips | Sit above the message box showing every reference the next message carries, grouped by workspace, each removable. Collapse to a per-workspace count once there are more than five. | Use them to confirm what an answer will be grounded in before you send, and to drop anything that should not be. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| Chat action on a tag | Opens the composer with that tag carried as a filter, so the message searches whatever holds the tag when it is sent. | Use it to ask questions of a whole grouping rather than of documents chosen one at a time. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
