---
layout: page
title: "Chat interface controls"
description: "Reference for every documented control in the SimpleChat chat interface."
section: "Reference"
audience: user
version: "0.261.236"
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

The conversation details dialog includes a paginated **Microsoft 365 sharing
and analysis acknowledgements** section. It shows the recorded source, decision,
effective duration, and approval reference without exposing credentials or
private profile preferences.

### React V2 navigation on narrow screens

Since **0.261.113**, **Expand navigation** opens the navigation rail above the
chat on screens narrower than 768 pixels. **Collapse navigation**, Escape, or
the shaded **Close navigation** backdrop closes it. Choosing a destination or
conversation also closes the mobile rail. These actions do not change the
desktop navigation preference.

Conversation drawers overlay the chat below the wide-desktop breakpoint rather
than leaving the message pane too narrow to read. **Close panel** returns to the
chat; wide result tables keep their scrolling inside the table.

### React V2 conversation list scrolling

Since **0.261.236**, the V2 navigation rail on the chat page scrolls as one panel
between **New chat** and the theme and account controls. As you read down the
conversation list, the navigation and any **External Links** or **Custom Pages**
groups move up out of view. **Search chats** stays right under **New chat**, along
with the selection actions when conversations are selected. The list gets nearly
the whole rail, which matters most on shorter screens or with several links
configured. Scroll back up to reach the navigation again. The collapsed icon strip
and other pages don't scroll this way.

### React V2 notification bell

Since **0.261.195**, the V2 navigation rail has a notification bell beside the
application's name. It shows the unread count, or a dot when the rail is collapsed,
and opens a panel where you can follow, mark read, or dismiss notifications without
leaving the chat. On narrow screens the bell is on the collapsed strip and in the
open navigation, and Escape closes the panel before the navigation. Since
**0.261.236**, a workflow alert that needs attention pops up from the bell as well.
See [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }}).

### Foundry sign-in requests

From version **0.261.093**, when a called Foundry agent needs delegated sign-in
or consent, the chat error notice offers **Sign in or grant Foundry access**.
The link opens an authenticated, same-app preparation request before redirecting
to Entra, so the OAuth callback receives the required scopes even when the error
arrived during streaming. After granting access, send the message again.

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

Microsoft 365 agents can pause for a source-sharing or deeper-analysis decision.
The local approval dialog offers only the durations permitted by the action.
The same request is available in **Approvals** and notifications; declining a
source keeps unrelated tools available. See [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }}).

**Connect Microsoft 365** appears on a paused request when the selected source
needs delegated sign-in or consent. It opens Microsoft's authorization flow
for that request's sources and returns to the same conversation to resume it.
It does not send you to Profile, approve data sharing, or create a workflow
Run as binding. Connection failures stay visible in the request instead of
being presented as a model answer that no documents exist.

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

## Microsoft 365 outgoing action cards

Implemented in version: **0.261.038** (`application/single_app/config.py`).
Manual and delayed email/invitation tools display a saved review card separately
from the agent's text and citations. Cards remain available after reload and
through **Approvals** and workflow activity.

| Control | Purpose and limits |
| --- | --- |
| Send | Sends a manually prepared message or invitation after checking the current owner, permissions, and reviewed revision. |
| Send now | Claims an eligible delayed action before its scheduled delivery. It is not a retry for an uncertain remote outcome. |
| Cancel | Stops an unclaimed delivery without mailbox authentication. It leaves Outlook drafts and does not recall sent messages. |
| Full review | Loads the complete owner-only body when the initial preview is truncated. Send stays unavailable until that detail is loaded. |
| Reconnect | Renews sign-in and returns to the same saved card. It does not resend the agent request or automatically confirm the action. |
| Refresh | Retrieves current server state after an interrupted request or a change in another tab. It never sends merely by refreshing. |

Only the data owner receives send/cancel controls and private body/recipient
details. Shared viewers get a read-only summary. The countdown is informational;
loading an overdue card never submits a send. Check Outlook before preparing a
replacement when delivery has an unknown outcome. Immediate operations keep
their existing tool-result receipts without a second Send button.

For email, Send submits the reviewed content and leaves the original Outlook
draft. **Do not send the retained draft again.** See
[Microsoft 365 Email]({{ '/reference/actions/m365-email/' | relative_url }}).
## Generated image editor

From version **0.261.107**, the image editor uses the selected global image model's
provider-qualified capabilities, not the text-chat model or the application's cloud.

| Control or state | What it does | Why you would use it |
| --- | --- | --- |
| Region selection | Sends a transparent PNG mask with the current image when the model/API supports uploaded masks | Guide a change to a particular area; masks are not pixel-exact preservation guarantees |
| Reference-image editing | Sends the current image and an instruction without a mask | Refine an image with supported MAI, FLUX, GPT Image, or direct OpenAI image-tool operations |
| Whole-image regeneration | Generates a replacement from the prompt instead of sending the current image as a reference | Start over or apply generation-only rendering options |
| Model-specific rendering controls | Offers only the selected profile's dimensions, quality, and background options | Avoid sending GPT-only parameters to another provider |
| Provider/cloud and capability information | Explains which service and image operations are selected and where availability is unknown | Distinguish an approved commercial endpoint from the cloud hosting SimpleChat |
| Unavailable model state | Disables new inference while retaining revision-history access | Review or restore an existing image without requiring a working generation service |

Unsupported or stale masks/options are rejected rather than silently changed into a
different operation. See [Generate images]({{ '/guides/generate-images/' | relative_url }}).

## Uploaded and reference images (V2 interface)

From version **0.261.192**, images you upload are shown in the conversation and can be sent to
the image model as visual references. These controls exist only in the V2 interface, so they are
not part of the generated inventory above. See
[Generate images]({{ '/guides/generate-images/' | relative_url }}) and
[Upload documents in chat]({{ '/guides/upload-documents-in-chat/' | relative_url }}).

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Uploaded image card | Draws an uploaded PNG, JPG, BMP, or TIFF image in the thread at the image's own size, the same way a generated image is drawn, shows **Processing image…** until the workspace is ready, and opens the full-size viewer when selected. HEIC is drawn only in Safari. Since **0.261.210**, its actions appear when you point at or tab to the image, as a generated image's do. | See what was asked about instead of a file name, and check that the right picture was attached. | [`enable_chat_file_uploads`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| Show sources (uploaded image) | Since **0.261.210**, opens a panel under the upload showing what ingestion extracted from it: the engine that read it and why, the AI vision analysis (description, objects, visible text, contextual analysis), the title and summary from metadata extraction, and the indexed text that search and chat read. It warns when nothing from the file was indexed. | Check what the assistant can actually know about a picture before relying on its answers, or find out why an image is not being cited. | Same as Uploaded image card |
| Message details (uploaded image) | Since **0.261.210**, shows the diagnostics recorded for the upload message in the same panel. | Confirm which conversation and workspace the upload belongs to. | Same as Uploaded image card |
| Open file preview | Opens **Uploaded file** with the same extraction results as **Show sources**. Before **0.261.210**, a workspace-backed upload showed **File content not found** here. | Read the extraction in a larger view. | Same as Uploaded image card |
| Cited image | Since **0.261.210**, a citation of an image opens the image with **What was extracted from this image** beneath it: the passage the assistant was given, including any recognized text and the image's description. | See why an image was cited, since a picture has no page to point to. | [`enable_enhanced_citations`]({{ '/admin/chat/' | relative_url }}) |
| Attach a reference image | With **Image** on, uploads, pastes, or drops a PNG, JPG, BMP, or TIFF picture that is sent to the image model with your prompt. HEIC is refused with a conversion hint. | Base a new image on a real picture: your house, your face, or a map. | [`enable_image_generation`]({{ '/admin/ai-models/' | relative_url }}) and an image model that can use references |
| Documents (in Image mode) | Lists only workspace images, most recent first, and adds the ones you pick as references. Search by name to reach an older image. | Reuse a picture already stored in a workspace without uploading it again. | Same as Attach a reference image, plus a workspace |
| Reference count | Shows how many references are attached and how many the image model accepts, for example **2 / 10 reference images**, or explains why references are unavailable. | Stay within the model's limit before sending. | Same as Attach a reference image |
| Use as reference | Adds an uploaded or generated image from the conversation to the next image request and turns **Image** on. Also offered in the full-size viewer. The reference is dropped if you open another conversation. | Iterate on an earlier result or reuse an upload without attaching it again. | Same as Attach a reference image |
| Edit on an uploaded image | Opens the image editor as **Create image from reference**. You describe a change, optionally select a region on masking-capable models, and select **Create new image**. The upload itself is never changed. | Make a new version of your own picture, such as a watercolor of a photo. | Same as Attach a reference image |
| Reference images on a sent message | Shows thumbnails of the references a message used, under **Reference images**. | Confirm which pictures shaped a generated image when you revisit the conversation. | Same as Attach a reference image |

Shared conversations don't offer reference images. In Orchestrate, attached and referenced images
are offered to planned image steps instead of being sent directly.

## Ask AI in editors (V2 interface)

From version **0.261.200**, the **Ask AI** tab of the diagram, chart and image editors and the
**Ask planner** tab of the plan editor share one conversation thread. Your message joins it the
moment you send it, so you can see the request running instead of waiting on a full input box.
These controls exist only in the V2 interface, so they are not part of the generated inventory
above. See [Generate images]({{ '/guides/generate-images/' | relative_url }}) and
[Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Send (Enter) | Moves your message into the thread and clears the input at once, then asks for the change. Ctrl+Enter and ⌘+Enter also send, and Shift+Enter adds a line. Only one request runs at a time. | Describe a change to the item in front of you without adding messages to the main conversation. | The editor itself: any diagram or chart, [`enable_image_generation`]({{ '/admin/ai-models/' | relative_url }}) for images, and [`enable_chat_orchestration`]({{ '/admin/orchestration/' | relative_url }}) for plans |
| Working… | Stands in for the reply while the request runs, with the seconds elapsed. | Tell a slow request from a stuck one. | Same as Send |
| Cancel | Stops waiting for the reply. In the plan editor it also discards the pending change on the server. In the other editors a change the server had already started may still be applied; if it is, the editor recognises it as yours and shows the latest version. | Drop a request you no longer want, or one taking too long. | Same as Send |
| Retry | Sends a failed or cancelled message again. A change that had already gone through isn't made twice. | Recover from a dropped connection or a temporary error without retyping. | Same as Send |
| Edit and resend | Takes a failed or cancelled message out of the thread and puts its text back in the input. | Reword a request before trying again. | Same as Send |
| Character counter | Shows the message's length against the 2,000-character limit. Past the limit it turns red, says how much to remove, and sending is blocked. | Shorten a long request yourself, instead of losing its end to a silent cut. | Same as Send |
| Earlier changes to this image | Lists the recent instructions stored for the image, above the thread. The thread itself keeps only this visit's exchanges and isn't saved. | Recall what was already asked of the image. | [`enable_image_generation`]({{ '/admin/ai-models/' | relative_url }}) |

These inputs don't offer uploads, `/` saved prompts or `@` mentions; the main composer still does.
Only **Ask planner** offers `#` documents and tags, described next. The diagram, chart and image
editors don't.

### Documents and tags in Ask planner

From version **0.261.201**, you can point the planner at the documents and tags a plan should use.
Picked documents and tags limit the plan's document searches to what you picked, the same way chips
in the main composer limit a message's search. The server checks every pick for you when the
request arrives, so a document you can no longer read is refused rather than quietly dropped.

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `#` in Ask planner | Searches the documents and tags you can read in your personal, group and public workspaces, and inserts the one you choose as `#[Name]` with a chip. Whole workspaces aren't offered. The arrow keys move through the list, Enter or Tab picks, and Escape closes the list without closing the editor. | Name the exact file the plan should work from, such as last quarter's pricing sheet, instead of hoping a search finds it. | [`enable_chat_orchestration`]({{ '/admin/orchestration/' | relative_url }}). A pick is accepted only from a workspace type that's turned on: [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}), [`enable_group_workspaces`]({{ '/admin/workspaces/' | relative_url }}) or [`enable_public_workspaces`]({{ '/admin/workspaces/' | relative_url }}) |
| Add context | Opens a search panel of the same documents and tags. A pick becomes a chip without changing your text. Escape closes the panel first and returns you to the input. | Pick several documents, or browse for one whose name you don't remember. | Same as `#` in Ask planner |
| Chips in the input | Show what the next request will carry. Removing a chip before you send means it isn't sent. | Drop a document you picked by mistake without rewriting the request. | Same as `#` in Ask planner |
| Chips in your turn | Show, under your message in the thread, the documents and tags it was sent with, as the server named them. | Check afterwards what the planner was given. | Same as `#` in Ask planner |
| Search notice | Appears under the planner's reply when that revision first limited the plan's searches to what you attached. | Know that the plan no longer searches everything you can read. | Same as `#` in Ask planner |
| Refused document or tag | A document that was deleted, is still processing, or is no longer readable by you, or a tag that no longer exists, fails the request before the planner runs. The reply names it by the label you picked, and the plan stays as it was. **Edit and resend** brings back your text and chips so you can remove it. | Fix a stale pick without retyping the request. | Same as `#` in Ask planner |

If the planner replies without changing the plan, your chips go back into the input with a note,
so you can send them again or remove them. At most 20 documents and tags can go with one request.

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

Since **0.261.104**, both interfaces use the selected model's declared reasoning
levels rather than guessing from its configuration ID. Unsupported saved choices
are adjusted visibly to a supported application default. For GPT-5.6 Luna,
Minimal becomes Low; None and XHigh remain valid choices. When support is unknown
or the parameter is unsupported, the request uses **Model default** instead of
advertising invented options. Explicit **None** is distinct from omitting the
parameter. Plans and answer metadata retain compatibility adjustments.

Since **0.261.137**, the V2 interface restores the model you last chose when you
return to chat, rather than the model that was selected when the page first loaded.
Orchestrate keeps its own model choice; see
[Orchestration approval](#orchestration-approval-v2-interface).

## Grounded search and document scope

{% include media.html src="reference/chat-controls-grounded-search.png" alt="Grounded Search panel with action, scope, document, tags, filters, and comparison controls visible." title="Grounded search and document scope" capture="Capture the Grounded Search panel with action, scope, document, tags, filters, and comparison controls visible." %}

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `scope-dropdown-button` | Chooses the workspace scope used by grounded search, such as all accessible content, personal, group, or public workspaces. | Use it when the same question should be limited to a team workspace, public workspace, or personal files. | Always available |
| `document-dropdown-button` | Chooses the specific documents used by grounded search, analysis, or comparison. | Use it when you know which file or small document set should ground the answer. | Always available |
| `tags-dropdown-button` | Filters grounded search by document tags. | Use it to narrow broad workspaces to a topic, project, lifecycle stage, or classification. | Always available |
| `clearFiltersBtn` | Clears selected grounded-search filters. | Use it when a search is too narrow or you want to return to the full chosen scope. | Always available |
| `document-comparison-edit-btn` | Reopens comparison setup for source/target document selections. The child label `document-comparison-edit-btn-label` supplies the visible text. | Use it when the wrong source or target document was selected for Compare. | Always available |

## Saved Analyze results (both interfaces)

Implemented in version **0.261.109**. These response-specific controls appear in
classic chat and React V2 when an assistant message has a saved Analyze result.
They are rendered with the response rather than added to the always-visible
toolbar. See [Read and discuss saved Analyze results]({{ '/guides/analyze-results/' | relative_url }}).

The answer remains the readable overview, even after a supporting export finishes.
The overview and download previews are not the full findings set. Ordinary
narrative requests such as “Explain the risks in these documents” do not require
a report schema, scoring setup, or configuration interview.

| Control or notice | What it does | Why you would use it | Available when |
| --- | --- | --- | --- |
| **Saved analysis** | Identifies the saved result and shows displayed-versus-total record counts, separate source counts, and its validation notice. | Distinguish a readable overview or one page from the full saved findings set. | The assistant message carries a saved result; an unavailable result shows a notice instead of result controls |
| **Findings and limitations** | Expands accepted findings and any **Limitations and validation issues**, loading up to 25 complete records at a time. | Inspect details without downloading a file or displaying the whole result at once. | The saved result is available |
| **Previous findings** / **Next findings** | Reads the preceding or following page of the same saved result. | Review records outside the currently displayed range. A page's source count may be smaller than the result's total source count. | A corresponding page exists and the current page has loaded |
| **Evidence for finding …** | Loads that finding's saved supporting passages and any saved filename, page, or chunk location. The label includes the finding's identifier. | Understand what supports a finding without treating it as independently verified. | The finding has saved evidence references |
| **Ask about this analysis** | Selects this saved result for the next message and focuses the composer. | Ask for an explanation of these findings instead of another original-source pass. | The saved result is available |
| **View diagnostics (JSON)** | Opens a separate, bounded diagnostic-data response in a new tab; `next_offset` identifies further byte pages. | Audit processing details without mixing them into findings, reports, or model input. | The saved result is available and its current source access is confirmed |
| **Saved analysis selected.** | Shows the composer notice: “Explaining the saved analysis — not running a new pass over the original sources.” A completed result can select this context automatically. | Confirm what the next ordinary follow-up will discuss. | Saved-analysis context is selected |
| **Remove saved analysis context** | The accessible label of the notice's close button; removes the saved-result selection without deleting the result or draft. | Leave explanation mode before choosing a different task or source pass. | The saved-analysis composer notice is present |
| **Downloads** | Expands the existing generated-file cards and their format-specific actions, such as **Download CSV**. | Obtain a supporting output after reviewing the answer and findings. | The available saved result has generated outputs; existing output readiness and approval rules still apply |
| **Retry findings** / **Retry evidence** | Repeats a failed read of saved data, not the original analysis. | Recover from a temporary loading failure without requesting another source pass. | A findings or evidence request has a retryable loading error |

With the saved-analysis notice present, an ordinary follow-up explains saved data;
it does not invoke document Analyze/Search or Orchestrate source retrieval.
Removing the notice, starting or changing conversations, or explicitly choosing a
new source action clears that selection. Refreshing the message feed does not
override an explicit removal or new source choice in the open conversation.

**Structural checks passed.** does not establish factual correctness or
exhaustiveness. **Partial analysis**, **Validation pending**, **Validation failed**,
and **Not validated** remain distinct notices; execution completion does not turn
them into successful validation. Saved evidence and explanations do not imply a
new independent check of the original sources.

For results produced by this feature, losing access to any contributing source
blocks new reads and reuse of the whole original result, its evidence, saved
derived explanations, and original exports—even if the conversation remains
accessible. An unavailable or stale notice must not be interpreted as zero
findings. Already explicitly published workspace copies retain the destination
workspace's permissions and lifecycle; saving a result in chat is not publication.

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
| Documents button | Opens a search panel listing documents, tags, and workspaces with checkboxes. Selections add context chips without changing your message text. Its first row, **Search all my documents**, is the original on/off relevance search. | Use it to pick what should ground an answer while keeping your question free of inserted document names. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| `#` in the message box | Searches documents, tags, and workspaces and inserts the chosen one as `#[Name]`. This is the way to intentionally add an inline reference; an existing chip is reused. | Use it to name a document within a sentence, for example when comparing two contracts. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| Context chips | Show the next message's context above the message box, grouped by workspace and individually removable. Independently selected chips survive message edits, including deletion of a later inline mention. More than five collapse to per-workspace counts. | Use them to confirm what an answer will be grounded in and remove context without rewriting your question. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |
| Chat action on a tag | Opens the composer with that tag as a context chip and search filter, without inserting text. The message searches whatever holds the tag when it is sent. | Use it to ask questions of a whole grouping rather than of documents chosen one at a time. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }}) |

## Shared conversations (V2 interface)

These controls exist only in the V2 interface, so they are not part of the generated inventory above, which is taken from the classic chat page. They make a conversation with several people and agents readable at a glance: who a message is for, which agents are working, and what the conversation has produced. See [V2 shared conversation experience]({{ '/explanation/features/V2_COLLABORATION_UX/' | relative_url }}) for the full description.

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| `@` in the message box | Opens the mention menu. Picking a person or an agent removes the `@query` you typed and adds a chip above the message box instead of inserting the name. | Use it to address the message to people and ask an agent, without the names crowding the sentence you are writing. | [`enable_collaborative_conversations`]({{ '/admin/chat/' | relative_url }}) |
| Mention chips | Show who the message is for: any number of people and at most one model or agent. Picking a second agent replaces the first, and each chip has a remove button. When you send, the names are placed in front of the message, which is how the server, the classic interface and the assistant read them. A message of chips alone is sent as a ping. | Use them to check who will be notified and which agent will answer before sending. | [`enable_collaborative_conversations`]({{ '/admin/chat/' | relative_url }}) |
| Mention pills on a message | Show the agent that was asked and the people who were named as pills above the message text, with your own name highlighted. The `@Name` text is removed from what is displayed, including where a reply quotes the message; the stored message keeps it. | Use them to see at a glance who a message was for, the same way a reply shows what it answers. | [`enable_collaborative_conversations`]({{ '/admin/chat/' | relative_url }}) |
| Agent activity line | Shows one slim line at the end of the thread for each running request: which agent, who asked, how long it has been running, and what it is doing in plain words, such as "Looking up order status", "Asking Data Analyst" or "Writing the answer". Everyone in the conversation sees it, several can run at once, and it replaces the large "Thinking" bubble in shared conversations. | Use it to know an agent is still working, and on what, without the thread filling with placeholders. | [`enable_collaborative_conversations`]({{ '/admin/chat/' | relative_url }}) |
| Generated (Documents drawer) | Lists the documents agents created in this conversation with the SimpleChat upload actions. Markdown opens in a preview, and Download appears only when the workspace's download rules allow it for you. | Use it to open or save a briefing or report an agent produced without hunting for it in a workspace. | [`allow_group_workspace_file_downloads`]({{ '/admin/workspaces/' | relative_url }}) for group documents<br>[`allow_personal_workspace_file_downloads`]({{ '/admin/workspaces/' | relative_url }}) for personal documents |
| Media (Documents drawer) | Gathers every image, video and audio clip shown in the conversation, including signed links an action fetched from a remote service, grouped as **Images**, **Videos** and **Audio** with a count for each. Images and clips open one viewer that steps through all of them, with **Show in conversation** to scroll to the message. Recordings play in place and can be downloaded. | Use it to find a photo, clip or recording again in a long thread. | Always available |

## Media in replies (V2 interface)

These controls exist only in the V2 interface, so they are not part of the generated inventory above, which is taken from the classic chat page. They keep a reply that returns many images and clips readable: two or more in a row show as tiles, three to a row, instead of one full-width card each. See [V2 media galleries and viewer]({{ '/explanation/features/V2_MEDIA_GALLERIES_AND_VIEWER/' | relative_url }}) for the full description.

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Gallery image tile | Opens the media viewer on that image, with the rest of the gallery a step away. The tile shows **Unavailable** when its link has expired. | Use it to look at a still or scan at full size without losing your place in the thread. | Always available |
| Gallery clip tile | Shows the clip's first frame and length. Pressing it plays the clip where it is, at tile size, with the browser's own controls. | Use it to glance at a short clip next to the text about it. | Always available; another host's clips need [`CSP_MEDIA_SRC_ORIGINS`]({{ '/explanation/features/V2_INLINE_MEDIA_AND_AGENT_MESSAGES/' | relative_url }}) |
| View larger | Opens a clip in the media viewer, continuing from where it had reached in its tile. | Use it when a clip needs more detail than the tile shows. | Same as the clip tile |
| Media viewer: Previous, Next and arrow keys | Move through the images and clips in the gallery, or through every image and clip when opened from the drawer. The header shows the position, such as "3 of 15". | Use them to review a set of stills and clips in order without closing and reopening each. | Always available |
| Media viewer: View at actual size | Shows an image at its natural size, scrolling to pan; selecting the image does the same. | Use it to read a plate, a document or other fine detail. | Always available |
| Media viewer and recording: Download | Saves the image, clip or recording under the file name in its link. When its host does not allow a direct download, it opens in a new tab instead, where the browser can save it. | Use it to keep a copy of evidence outside the conversation. | Always available |
| Show in conversation | Closes the viewer and scrolls to the message the item appears in, highlighting it briefly. Offered from the Documents drawer. | Use it to read what an agent said about an image, clip or recording you found in the drawer. | Always available |

## Attached prompts (V2 interface)

These controls exist only in the V2 interface, so they are not part of the generated inventory above, which is taken from the classic chat page. A saved prompt picked in V2 is attached to the message you are writing rather than pasted into the box, so the two stay separate until you send. See [Prompt composer card]({{ '/explanation/features/PROMPT_COMPOSER_CARD/' | relative_url }}) for the full description.

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Attached prompt card | Sits above the message box carrying the prompt you picked, showing its name, workspace, and how many of its variables are still unfilled. The message box below stays yours to type in. | Use it to see what instructions the assistant is being given while you write the request itself, instead of scrolling through pasted text to find your own words. | [`enable_user_workspace`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_group_workspaces`]({{ '/admin/workspaces/' | relative_url }})<br>[`enable_public_workspaces`]({{ '/admin/workspaces/' | relative_url }}) |
| Expand on the card | Opens the scrollable prompt preview independently of the visible variable fields. | Use it to inspect the resolved instructions without hiding the fields you are completing. | Same as the card |
| Edit on the card | Turns the prompt text into an editable box and marks the card **Edited**, with a Reset that restores the saved wording. | Use it to adjust wording for one message. The change never reaches the saved prompt, so a one-off tweak does not alter it for everyone else using it. | Same as the card |
| Remove on the card | Takes the prompt off the message. | Use it when you have changed your mind. Nothing you typed is disturbed, because the prompt was never in the message box. | Same as the card |
| `/` in the message box | Searches your saved prompts and attaches the one you pick, consuming the `/query` token you typed. | Use it to reach a prompt by name while writing, without leaving the sentence. | Same as the card |
| Prompt card on a sent message | Keeps the prompt snapshot above your own words, with the same expandable, scrollable presentation after a reload. | Use it to see which instructions produced a reply without burying the actual question. | Same as the card |
| Insert variable | Explains built-ins and adds a custom field with an optional default at the cursor in either V2 prompt editor. | Use it to make a reusable template without memorizing placeholder syntax. | Same as the card |
| Find in knowledge / Fill missing fields | Retrieves values for one or all unanswered custom fields from selected knowledge. AI-filled values include Sources and Undo. | Use it to complete a prompt from document evidence instead of copying values between screens. | Same as the card; requires configured search and model services |
| Search all accessible knowledge for AI fill | Explicitly widens the variable lookup without changing the chat message's document selection. | Use it when the selected sources do not contain the value you need. | Same as knowledge fill |
| Unanswered-variable warning | Offers Review fields, Fill missing fields, or an explicit Send anyway that retains literal placeholders. | Use it to catch omissions while retaining control over whether to send. | Same as the card |

The variable picker, knowledge fill, and persistent card enhancements were implemented
in **0.261.096**. See [Use prompts in chat]({{ '/guides/use-prompts-in-chat/' | relative_url }})
for the complete workflow.

## Orchestration approval (V2 interface)

Since **0.261.126**, Orchestrate has an **Orchestration model** picker.
**Auto - choose per step** asks the server to choose an authorized connected model
for each model-backed step; a specific model remains pinned. Planned and completed
steps show model attribution and the selection reason. This picker is distinct
from the **Auto** approval choice below. Ordinary V2 chat and classic chat remain
manual-only, and switching modes retains the normal-chat model. See
[Choose models for orchestration]({{ '/guides/model-catalog-routing/' | relative_url }}).

Since **0.261.137**, the picker sits in the normal model picker's place under
**Manual controls** instead of above the message box, so the toolbar keeps its shape
when Orchestrate is switched on. **Auto - choose per step** is the default wherever a
connected model has a catalog profile rated for general answering; otherwise a specific
model is used and Auto is not offered. Your choice, Auto or a pinned model, is saved to your
account, so it stays in place when you leave the chat, open a new chat, reload, or
sign in elsewhere. A model pinned here does not change the model normal chat uses.
When an administrator hides Manual controls, the picker is unavailable and Orchestrate
uses Auto (or the default model when Auto cannot be used), ignoring any saved pin.
Sending an orchestrated message waits until your saved choice has loaded.

In Orchestrate, selected Document Search, Web Search, Deep Research, and eligible
URL Access controls are positive requirements, not the complete list of permitted
tools. Unchecked controls are neutral. The planner may choose other enabled,
authorized capabilities, while selected documents, agents, workspaces, and filters
retain their intended constraints. Deep Research can be selected without also
selecting Web Search. Since **0.261.132**, **Image** works differently in Orchestrate:
rather than sending your prompt to the image model, it combines with every other
control and shapes the plan. Since **0.261.138**, Image is treated as a request for
images, which the plan generates as its own tasks when it runs. Suggested images
remain approval cards that generate only when you approve them.

Every Orchestrate request now invokes the planner, even a short question or
acknowledgment. The planner may choose a direct answer; no topic rule forces
research. See [Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

Account-level approval persistence was fixed in **0.261.101**. These controls appear
while Orchestrate is active and the administrator allows users to change approval
modes. The saved choice applies across chats and future visits; it does not alter
plans that already exist. An administrator can enforce the deployment default
without deleting your saved preference.

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Approval mode | Saves **Auto**, **After Ns**, or **Review** to your account without requiring a message to be sent. Auto runs the plan when ready, After Ns allows the displayed countdown to expire, and Review waits for explicit approval. | Keep the amount of review you want instead of choosing it again each time you return to chat. | `enable_chat_orchestration` and `chat_orchestration_allow_user_approval_override` |
| Retry loading approval preference | Loads your account preferences again after a failure, retaining the draft. Orchestration submission waits until the preference is known. | Recover without accidentally running a plan under a different approval mode. Ordinary chat remains available with Orchestrate off. | Same as Approval mode; shown after a preference-loading failure |

The composer reports an unsuccessful save rather than claiming the new mode was
remembered. Choose the mode again to retry. If no choice has been saved, the current
deployment default applies. See [Orchestration settings]({{ '/admin/orchestration/' | relative_url }}).

Since **0.261.212**, a plan that starts one of your saved workflows always waits for
you to approve it, whichever mode you saved. See **Workflow runs** below.

## Visuals in orchestrated answers (V2 interface)

Since **0.261.132**, an orchestrated answer can include the same visuals as ordinary
chat. You do not need a control for most of them; the planner and answer decide from
the request.

| Control or output | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Image (in Orchestrate) | Asks the plan for images and shows "Orchestrate will plan the images you ask for and generate them when the plan runs." while it is on. Each requested image is generated as a planned task, shown in the answer, and embedded in DOCX, PDF, or PPTX files when the file source uses it. Since **0.261.192**, pictures you attach, select, or add with **Use as reference** can be used as reference images for those tasks when the image model supports references. Suggested images remain approval cards generated only when you approve them. | Make sure a request that would benefit from pictures gets them, even when the wording does not say "image". | `enable_image_generation` and `enable_chat_orchestration` |
| Inline charts | Charts numeric results. When data comes from an action, the chart is drawn from the exact retrieved rows; long series show up to 200 points and keep each segment's highest and lowest value. | Plot telemetry, metrics, or other series without copying values into a prompt. | `enable_chat_orchestration` |
| Mermaid diagrams | Draws flows, architectures, sequences, and relationships the gathered information describes. | Get an editable, accessible diagram instead of a picture of one. | `enable_chat_orchestration` |

Saved Instruction memories shape these visuals. For example, "I don't like charts"
stops charts you did not ask for, and "make my diagrams red" styles the diagrams you
get. An explicit request in your current message still wins. Preferences saved as
facts are background context and may not be applied.

The exclusion must be chosen again for a later message. URL Access eligibility
uses the full resolved message, including attached prompts. Removing its URL
clears only that selection; other requirements remain intact.

## Inline follow-up questions (V2 interface)

Implemented in **0.261.096**. These controls appear when chat orchestration needs more
information before it can plan the request. They use the composer's editing capabilities
without adding another model, agent, or execution toolbar. See
[Chat Orchestration](https://github.com/microsoft/simplechat/blob/main/docs/explanation/features/CHAT_ORCHESTRATION.md).

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Suggested choices | Uses radio buttons for one choice and checkboxes for several. File suggestions retain actual source identities rather than just filenames. | Choose the intended options quickly, while retaining the ability to supply a different file for a file question. | `enable_chat_orchestration` |
| Inline answer / Additional details | Accepts text, `#` references, and `/` saved prompts. An optional answer can accompany selected choices. | Explain a qualification or supply missing context without starting another chat message. | `enable_chat_orchestration`, with the existing workspace and prompt permissions |
| Attach a file | Uploads a supported file for this answer and shows its processing state. | Supply a source omitted from the original request, whether tabular or another supported file type. | `enable_chat_orchestration`, `enable_chat_file_uploads`, and the existing upload role policy |
| Upload Retry / Remove | Retries an unsuccessful attachment or removes it from the answer without discarding other selections. Removing a reference does not delete an already uploaded file. | Recover from upload failure or correct a mistaken selection before continuing. | Same as Attach a file |
| Clear suggested selections | Clears chosen file suggestions without clearing the answer editor. | Use your own referenced or uploaded file when none of the suggestions is right. | `enable_chat_orchestration` |
| Back / Next / Finish | Keeps each page's answer while navigating; Finish submits the answers for the same request and waits for required answers and ready uploads. | Complete a multi-question clarification without losing drafts or continuing with unfinished files. | `enable_chat_orchestration` |
| Decline / Cancel | Sends no answer text, selected references, or attached-prompt metadata. | Decline to provide the requested information or abandon the current answer. | `enable_chat_orchestration` |

## Plan editing (V2 interface)

Implemented in **0.261.102**. These controls refine an unexecuted orchestration
plan rather than editing the main chat message. See
[Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Review | Opens the plan drawer with step details and narrowing-only controls. | Inspect the proposed sources and work, or remove something unnecessary. | `enable_chat_orchestration` |
| Edit | Opens the full-screen plan editor and holds the plan for manual approval, stopping its countdown. | Change the proposed approach before it runs. | Same as Review; the plan must not have started |
| Ask planner | Sends a change request to the planner for a validated revision, or answers its scoped clarification. Since **0.261.201**, the request can carry `#` documents and tags; see **Documents and tags in Ask planner** above. | Add a permitted step, remove work, or refine the task without duplicating the main conversation. | Same as Edit; existing capability and source permissions apply |
| History and restore | Shows previous plan versions and creates a newly validated current version when restoring one. | Return to an earlier approach without deleting later history. | Same as Edit |
| Run after editing | Executes the saved current revision only after explicit approval. Closing the editor does not approve it. | Start the work once its steps and sources match your intent. | Same as Edit; no revision or clarification may be pending |
| Run task switch (Gather / Reason / Render plans) | Skips or restores an eligible task without deleting its declared inputs or outputs. Required producers identify their consumers and cannot be silently disabled. | Remove independent work, or learn which consumers must change through Ask planner first. | A Gather / Reason / Render plan that has not started; the final-response step cannot be disabled |
| Prepared output schema | Expands the server-declared schema for a named structured result. | Check the intended shape before approving composition; this is a retained result, not a download. | A Gather / Reason / Render task with an output schema |
| Server file format reference | Shows only a supplied shared export catalog, including source kinds and profiles. Its option-rule and default-limit disclosures are read-only. | Check the server's format descriptions before requesting a validated planner revision. | A Gather / Reason / Render view with a server-provided catalog; absent otherwise |
| Load server file format reference | Retrieves the shared catalog using the selected plan's authorized run context. A failed read leaves formats unadvertised. | Inspect available format descriptions when they were not included with the current view. | A Gather / Reason / Render plan view without a loaded catalog |
| Reference image chips (Generate image tasks) | Since **0.261.192**, lists the pictures a planned image will be based on, each with a thumbnail and name. In Review, removes a reference from the task or restores it; with every reference removed, the image is generated from its prompt alone. | Check that the plan uses the right pictures, such as the photo of your house, before it runs. | `enable_chat_orchestration` and `enable_image_generation`, with an image model that can use references and **Image** on when you attached the pictures |

Version-aware inspection was implemented in **0.261.127** (Refs:
microsoft/simplechat#1509; `application/single_app/config.py`). Gather / Reason /
Render are roles, not global phase buckets: consecutive groups preserve the
server's actual dependency order, including repeated roles. Plans created by an earlier orchestration version show the stable message that they can't be opened or rerun. Named input descriptions identify the producer,
output, and whether partial data is allowed. The server remains authoritative
for binding compatibility, capability admission, source access, and limits.

## Orchestration failure recovery (V2 interface)

Implemented in **0.261.105**. A failed run keeps an explanation in the conversation
and Run view instead of silently cancelling the answering step. Recovery uses the
saved effective plan, not the current composer selections or a new planner call.

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Retry from failed step | Creates a linked attempt that restores valid completed-step results and executes the incomplete work. | Recover after a failure without repeating successful plan steps or duplicating the question. | `enable_chat_orchestration`, current access, and recoverable saved checkpoints; not a substitute for individual file recovery |
| Confirm retry / Cancel | Confirms the possible external effects of retrying a failed agent/action, or dismisses the confirmation without executing it. Since **0.261.212** it also appears for a step that starts a saved workflow; its retry never starts the workflow twice, and links the run when the plan already started it. | Decide whether it is safe to repeat the failed step's internal tool activity. | A recoverable attempt that requires external-effect confirmation |
| Run prepared retry | Starts a recovery attempt that was already prepared but has not executed. | Continue after preparation was saved but execution was interrupted by navigation or connection loss. | An unstarted saved recovery attempt |
| Review saved attempt | Opens the selected attempt in the Plan/Run view. | Inspect the failure, completed steps, and remaining work without editing or rerunning history. | A saved orchestration attempt |
| View current attempt / View previous attempt | Opens a linked execution attempt rather than starting another one. | Follow recovery history and avoid retrying an older attempt that already has a successor. | Linked recovery attempts |
| Check saved status | Reconciles the displayed state with the existing server execution, without running or retrying work. | Check a waiting computation, or find out whether work finished after connection loss. | A waiting attempt, execution-status error, or recovery-detail error |
| Stop execution | Requests server cancellation of the potentially active attempt. | Stop work even when it is waiting for retained computation or its stream was interrupted. | A waiting or interrupted connection with a tracked in-flight attempt |

Steps restored from checkpoints show **Reused saved result**. Retry is always
manual, including when normal approval is Auto or timed. An older attempt cannot
create a competing retry after a newer attempt has been prepared.

Since **0.261.127**, **Waiting for required results** keeps the same producing
attempt active. Reload and status checks do not execute it again, and waiting
does not expose a run-retry button or a completed-file link. File-specific
publication and retry controls require the server's separate output lifecycle.

Stop requests cancellation on the server. A connection loss instead requires
checking the existing execution; it must not automatically start another one.
When a checkpoint or source is unavailable, the interface explains why recovery
is blocked rather than turning Retry into a full-plan replay. See
[Review, edit, and recover plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }}).

## Orchestration file outputs (V2 interface)

Implemented in **0.261.127** (Refs: microsoft/simplechat#1509;
`application/single_app/config.py`). These response and Run-view controls require
server-provided output lifecycle records; a planned filename or native waiting
state does not enable them.

| Control or state | What it does | Why you would use it | Available when |
| --- | --- | --- | --- |
| Check saved file status | Reads the same run's individual file states without starting work. | Recover current progress after navigation, reload, or a lost response, including when the run already reports partial completion or failure. | The server has advertised individual outputs |
| Retry file | Requests only the selected file from its retained source; producer tasks and sibling files are not replayed. | Recover an eligible file independently of files that already succeeded. | The server marks that failed file retryable under current access |
| Retry same request | Reuses the uncertain retry action's saved identifier instead of creating another action. | Confirm a file retry after a network or server error without duplicating it. | An unconfirmed action remains and the server still permits that file retry |
| Automatic retry scheduled | Shows the server's next retry time and automatic-attempt count/limit. | Distinguish backoff from a stalled browser; refreshing does not submit another attempt. | The file is awaiting a server-scheduled retry |
| Download | Uses the existing generated-artifact card and authorized chat download path. | Retrieve a committed file while other files are still pending or failed. | Matching committed artifact metadata is present and the file is available |
| Unavailable | Withholds that file's download and retry controls while retaining its recorded outcome and safe reason. | Understand a source-access, screening, or deletion restriction without losing unrelated ready files. | The server marks the output unavailable, or the run is no longer accessible |

Waiting, Rendering, Completed, Failed, and Cancelled remain distinct file states.
Automatic-attempt exhaustion alone never enables manual retry. Retry identities
survive reload in the same browser tab, but reloading never posts a retry or
reruns the original plan. An expired sign-in or a conflict requires checking
saved state before another request.

Generated-file history entries are informational, not uploaded-file previews or
download receipts. Unavailable history entries show a safe explanation and close
any cached preview. Empty TXT and MD files can still be downloaded; zero counts
do not make a completed file unavailable.

Restored access can return the original committed download on the next saved-status
check without rendering again. A network or server failure during a status check
keeps the last known progress and shows a refresh error, not a source-denial state.

## Workflow proposals (V2 interface)

Implemented in **0.261.207** (Refs: microsoft/simplechat#1547). When chat
orchestration proposes a personal workflow, a **Proposed workflow** card follows
the answer. The card is the only place a proposal appears: it isn't listed with
the answer's files, and nothing is created until you choose. See
[Create a workflow from chat]({{ '/guides/create-a-workflow/' | relative_url }}#create-a-workflow-from-chat).

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Instructions | Expands a task to show, as plain text, the full instructions it's given on every run. | Check exactly what the workflow will do before you let it run on its own. | `enable_chat_orchestration`, `allow_user_workflows` and `enable_chat_orchestration_workflows`, in a conversation that's private to you |
| Create & start | Creates the workflow and turns it on. | Start the recurring work when the card matches what you want. | Same as Instructions, while the proposal waits for a decision |
| Create paused | Creates the workflow turned off. | Review or adjust it in Workflows before it runs. | Same as Create & start |
| Create | Creates a manual workflow. It runs only when you start it from Workflows. | Keep a repeatable task ready without a schedule. | Same as Create & start, for a manual workflow |
| Edit | Opens the proposal in the workflow editor. Save creates the workflow as edited. | Change the name, schedule, tasks or runner before anything is created. | Same as Create & start |
| Deny | Declines the proposal after you confirm. Nothing is created. | Say you don't want this workflow. | Same as Instructions, until the proposal is decided or expires |
| Create again | Creates the workflow again, paused, after you deleted it. | Bring back a workflow you removed, from the same proposal. | Same as Instructions, until the proposal expires |
| Open workflow | Opens the created workflow in Workflows. | Run, edit or turn on the workflow the proposal created. | The workflow exists |
| Next run | Shows when the created workflow runs next, with the time zone's name, or **Due now** once that time has passed. | Know when the recurring work happens without opening Workflows. | The workflow exists and is turned on |
| Last run | Shows the newest run's status and when it ran, or **No runs yet**. A status V2 doesn't recognize reads **Status unavailable** rather than a guess. | See whether the workflow's latest run worked. | The workflow exists |
| Open latest results | Opens the newest completed or partly completed run in the workflow's run history. | Read what the workflow last produced. | The workflow has a completed or partly completed run |
| Follow up | Opens a new chat about the newest run chat can answer from, as **Ask in chat** does in Workflows. | Ask what the workflow found without copying its output into chat. | `enable_chat_workflow_results`, for a completed or partly completed run that isn't a structured run |
| Check again | Reads the proposal's status again after automatic checking stops. | Confirm the result when creating the workflow takes longer than expected. | The proposal is still being created |
| Try again | Reloads the proposals after a failed read. | Recover the card after a network or server error. | The proposals couldn't be loaded |

While a proposal is being created, the card checks its status every few seconds
for up to two minutes, and waits while the browser tab is hidden. When
Microsoft 365 isn't connected for workflows, the card links to the connection in
your profile, and while a run waits for Run as approval, it links to Approvals.

Since **0.261.251**, a created card reads the workflow and its recent runs once
to show **Next run** and **Last run**. It doesn't keep checking, so open the
chat again to see a newer run. If that read fails, the card says "Run details
aren't available right now."

{% include media.html src="reference/chat-controls-workflow-proposal-run-summary.png" alt="A created workflow proposal card showing Next run and Last run, with Open latest results and Follow up." title="Created workflow card" capture="Capture a created workflow proposal card for a scheduled workflow that has run, showing Next run with its time zone, Last run with its status, and the Open latest results and Follow up buttons. Redact the workflow name." %}

## Workflow hand-offs (V2 interface)

Implemented in **0.261.277** (Refs: microsoft/simplechat#1549). Some requests are
too big for one chat plan, such as "review every contract in my Legal workspace
and list the renewal terms". When **Hand Off Large Work From Chat**
(`enable_chat_orchestration_workflow_handoff`) and the settings it requires are on,
the plan can prepare a one-time workflow that reviews each document and then writes
one report. Approving the plan only prepares it. A **Workflow hand-off** card follows
the answer, and nothing is created or run until you accept it there. Hand-offs are
offered only in a conversation that's private to you. See
[Hand large work off to a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }}#hand-large-work-off-to-a-workflow).

{% include media.html src="reference/chat-controls-workflow-handoff-card.png" alt="Workflow hand-off card under a plan answer, showing what the workflow covers, its two tasks, when the offer expires, and the Accept, Edit and Decline buttons." title="Workflow hand-off card" capture="Capture a pending Workflow hand-off card under a plan answer, showing its Covers and Workspaces lines, the two tasks with what each runs on, the sentence saying when you can decide until, and the Accept, Edit and Decline buttons. Redact the conversation title, workflow name and workspace names." %}

| Control or state | What it does | Why you would use it | Available when |
| --- | --- | --- | --- |
| Hand-off notice | On the plan card, says the plan hands work off to a one-time workflow, so it always waits for your approval, and that approving it only prepares the workflow. | Know that approving the plan starts nothing. A countdown or Auto never approves a hand-off plan. | `enable_chat_orchestration_workflow_handoff` and the settings it requires, for a plan with a hand-off step |
| Hand off large work (Run view) | Puts the hand-off step in words: the workflow's name, what it reviews, for example "3 named documents" or "a search of 2 workspaces, the 50 best matches", and its task titles. The tasks' instructions and the document references aren't shown. | Check what the step prepares before you approve the plan. | Same as Hand-off notice |
| Workflow hand-off card | Shows the workflow's name and description, what it covers, for example "200 documents" or "up to 500 best-matching documents", the workspaces a search reads, that it runs once and isn't scheduled, the Info alert it sends, and each task with the model or agent it runs on. While the hand-off waits, the card says when the offer expires. | See exactly what the workflow will review before anything is created. | Your own private conversation, under an answer whose plan prepared a hand-off |
| Status label | Reads **Awaiting your decision**, **Creating**, **Workflow created**, **Run queued**, **Declined**, **Expired**, **Unavailable**, **Can't be used** or **Workflow deleted**, with a sentence on what that means. For a hand-off that can't be used, the sentence gives the reason, for example that the request covers more documents than one hand-off can review. | Know whether the hand-off still needs you and, if it can't go ahead, why. | Always, on the card |
| Accept | Asks you to confirm, repeating what the workflow covers, then creates the workflow turned off, so it never runs on a schedule, and starts its one run. | Start the review when the card matches what you asked for. | The hand-off is waiting for your decision |
| Edit | Opens the prepared workflow in the workflow editor. **Save** asks you to confirm, then creates the workflow as edited and starts its one run. An edit must keep the manual trigger and the For each over documents or a workspace search, and its tasks can use only your own local agents. URL Access and Run as aren't available. If the edit is refused, the editor stays open with your draft and says why. | Change the name, a task's wording or what it runs on before anything is created. | Same as Accept |
| Decline | Asks you to confirm, then declines the hand-off. Nothing is created. | Say you don't want this work done. You can ask again in chat at any time. | The hand-off is waiting for your decision, or it can't be used and hasn't expired |
| Start its run | Asks you to confirm, then starts the one run of the workflow the hand-off already created. | Finish an accept that created the workflow but couldn't start its run. | The workflow exists but its run hasn't started |
| Open workflow | Opens the created workflow in Workflows. | Look at the workflow the hand-off created. | The workflow exists and the card isn't showing its run |
| Handed-off workflow | Shows the run like a run on the **Started workflows** card: its status, the step it's on and the time elapsed, with **Cancel run**, **Retry**, **Review and approve**, **Reconnect Microsoft 365**, **Open run** and **Results posted below** as they apply. Until the run is first checked, or when runs aren't tracked, it shows the run's status as of when the message loaded, with **Open run**. | Follow the review without leaving the chat. The run's outcome is posted in the chat when it ends. | You accepted the hand-off and its run was queued. Runs are tracked while `allow_user_workflows` and `enable_chat_orchestration_workflow_runs` are both on |
| Check now | Reads this chat's runs again straight away. The card then shows when they were last checked. | Get the run's latest status without waiting for the next automatic check. | Runs are tracked and the hand-off's run was queued |
| Check again | Reads the hand-off's status again after automatic checking stops. | Confirm the result when creating the workflow takes longer than expected, for example after you accepted it in another tab. | The hand-off is still being created |
| Try again | Retries an accept that can still succeed, such as one that created the workflow but couldn't queue its run, which queues that same run. On a failed read, it loads the hand-offs again. | Recover from a busy or temporary failure without asking again in chat. | The accept was refused in a way that can succeed, or the hand-offs couldn't be loaded |

The card offers only what the hand-off allows at that moment. A hand-off that's
declined, expired or whose run was queued offers nothing, and an offer expires 14
days after the plan prepared it. Each hand-off workflow created in the last 24
hours counts toward a daily limit your administrator sets, until it's deleted; at
the limit, Accept says "You reached the daily limit for workflow hand-offs. Try
again later." If your administrator turns hand-offs off, an earlier answer keeps
its card, which then says the hand-off isn't available.

A search for every matching document pauses before it reviews any if, when the
run starts, more documents match than one hand-off can review. The run's row
shows **Needs you** and "Paused before reviewing any documents because more
matched than one hand-off can review. Cancel it, then ask again with a narrower
request." It offers **Cancel run** and **Open run**, because the workflow can't be
resumed.

An answer whose plan handed work off shows the hand-off card instead of the
**Proposed workflow** and **Started workflows** cards. A plan can't both hand work
off and propose or start a workflow, so nothing is hidden, and the run shows only
once.

## Workflow runs (V2 interface)

Implemented in **0.261.212** (Refs: microsoft/simplechat#1551). When you ask chat
orchestration to run one of your saved workflows now, such as "run my weekly digest",
the plan can start it. Only workflows with durable execution on can be started this way,
and only from a conversation that's private to you. See
[Run a workflow from chat]({{ '/guides/trigger-a-workflow/' | relative_url }}#run-a-workflow-from-chat).

{% include media.html src="reference/chat-controls-workflow-run-card.png" alt="Started workflows card under a plan answer, showing a running run's step and elapsed time with Cancel run, Open run and Check now, and a running spinner beside the chat in the chat list." title="Workflow run card" capture="Capture a plan answer's Started workflows card with one running run (step, elapsed time, Cancel run, Open run, Check now and its Checked time) and the running spinner beside that chat in the chat list. Redact conversation titles and workflow names." %}

| Control or state | What it does | Why you would use it | Available when |
| --- | --- | --- | --- |
| Saved workflows notice | Says the plan always waits for you to approve it, and lists each workflow it would start with its trigger. A workflow that's turned off shows **Paused**. A paused workflow still runs once when you start it here, and starting it doesn't turn it back on. | Check which workflows will start before you approve. A countdown or Auto never starts one. | `enable_chat_orchestration`, `allow_user_workflows` and `enable_chat_orchestration_workflow_runs`, in a conversation that's private to you |
| Workflow (Run view) | Shows the name of the workflow a step starts, with **Paused** when it's turned off. | Match each step to the workflow it starts. | A plan with a step that starts a saved workflow |
| Started workflows | Lists, under the answer, each workflow the plan started with its run's status. While runs are tracked, the status stays current: **Queued**, **Running**, **Needs you**, **Completed**, **Partly completed**, **Failed**, **Timed out** or **Cancelled**, with the step the run is on, the time elapsed, why it's waiting and where its results went. Otherwise, and until a run is first checked, the status is as of when the message loaded: **Queued**, **Running**, **Waiting**, **Completed**, **Partly completed**, **Failed**, **Cancelled** or **Skipped**. A status V2 can't read with certainty shows **Status unavailable** and only **Open run**. | See at a glance whether the work you started is still going, without leaving the chat. | Your own private conversation, after a plan started a workflow. Runs are tracked while `allow_user_workflows` and `enable_chat_orchestration_workflow_runs` are both on |
| Open run | Opens the workflow in Workflows with its run history open at that run. | Follow the run's progress and read its results. | The workflow and its run still exist |
| Unavailable | Replaces **Open run** with the reason the run can't be opened, for example because the workflow was deleted or the run is no longer in its history. | Understand why a link is missing without losing the rest. | The run can't be opened, or starting workflows from chat was turned off |
| Try again | Reloads the started workflows after a failed read. | Recover the links after a network or server error. | The started workflows couldn't be loaded |
| Check now | Reads this chat's runs again straight away. The card shows when they were last checked, for example "Checked 9:07 AM". | Get the latest status without waiting for the next automatic check. | Runs are tracked and the answer started at least one |
| Cancel run | Asks you to confirm, then asks the run to stop. Anything it already did stays done, and a cancelled run can't be retried. | Stop a run you no longer need. | Runs are tracked, and the run is queued, running or waiting and can still be cancelled |
| Retry | Resumes the same failed run, reusing the steps that already finished. It never starts a new run. If the run can't be resumed, the card says why, for example because the workflow changed after the run started. | Recover from a failure without asking the plan again. | Runs are tracked, the run failed and can still be resumed, and starting workflows from chat is still on |
| Review and approve | Opens the run in Workflows, where the step's approval prompt and choices are shown. Nothing is approved from the chat. | Decide on the step the run is waiting for. | The run is waiting for your approval |
| Reconnect Microsoft 365 | Opens the Microsoft 365 connection in your profile. | Let a run that's waiting for you to sign in continue. | The run is waiting for a Microsoft 365 sign-in |
| Results posted below | Scrolls to the message the run posted in this chat. | Jump from the run to its results. | The run's results were posted to this chat and that message is loaded |
| Running tag | Shows a small spinner beside the chat in the chat list, labelled with the workflow's name, for example "Running Weekly digest", or "Running 2 workflows" when there are several. | See which chats are waiting on a workflow, from any page. | Runs are tracked, a run started from that chat is still going or its results are being posted, and the chat has no unread reply |

The answer itself lists what happened to each workflow: started, already started for
this request, or not started with the reason. Stopping the plan doesn't stop a
workflow it already started; use **Cancel run** or cancel the run in Workflows.

A run takes one action at a time. While its **Cancel run** or **Retry** is waiting
on the server, that run's **Cancel run**, **Retry** and **Review and approve** stay
in place but do nothing, on the card and on the run's note in the chat.

Runs are tracked since **0.261.251**. While a tracked run is in flight, V2
checks on it from any page, so the chat list and the bell stay current: first
after 15 seconds, then less often, up to every 5 minutes. It pauses while the
browser tab is hidden, unless desktop notifications are on, and stops checking
once nothing is in flight.

### Results posted to the chat

Implemented in **0.261.227**, with V2's controls in **0.261.251** (Refs:
microsoft/simplechat#1546). When **Use Workflow Results In Chat**
(`enable_chat_workflow_results`) is also on, a run started from chat posts its
result, or a short note when it failed, was cancelled or can't be shown, back
into the chat that started it. The chat is marked unread, the bell gets one
notification, and if you've turned on desktop notifications, one shows while
you aren't looking at the page. The message starts with a line such as
"Results from `Weekly digest` · you asked on Sun Jan 4, 2026, 9:30 PM EST". If
the chat was deleted or shared before the run finished, a workflow notification
opens the run instead. Without that setting, results arrive where the workflow
already sends them, such as its conversation or alerts.

{% include media.html src="reference/chat-controls-workflow-posted-result.png" alt="A workflow result posted into the chat that started it, with its Results from label and the Follow up and Open run buttons below it." title="Results posted to the chat" capture="Capture a workflow result posted into the chat that started it, showing its Results from label and the Follow up and Open run buttons. Redact the conversation title, workflow name and result content." %}

| Control | What it does | Why you would use it | Available when |
| --- | --- | --- | --- |
| Follow up | Makes the run's result the source of your next question in this chat, then puts the cursor in the message box. | Ask about what the run found without opening a new chat. | A posted result or saved analysis, with `enable_chat_workflow_results` on and the result still available |
| Retry workflow run | Resumes the same failed run, as the card's **Retry** does. It never starts a new run. | Recover from a failure from the note itself. | A note that the run failed, while runs are tracked and the run can still be resumed |
| Open run | Opens the run in Workflows. | See the run's details, steps and full output. | Any posted message, with `allow_user_workflows` on |

The chat's own **Retry** isn't offered on a posted message, and the server
refuses Retry and Edit for one: run the workflow again from Workflows, or ask a
new question instead.

## Workflow results in chat (V2 interface)

Implemented in **0.261.214** (Refs: microsoft/simplechat#1546). You can ask chat
about the stored result of a finished run of one of your personal workflows. The
answer uses only that run's saved output, the workflow isn't run again, and the
answer ends with a line that names the run. See
[Ask about workflow results]({{ '/guides/ask-about-workflow-results/' | relative_url }}).

| Control | What it does | Why you would use it | Enabled by |
| --- | --- | --- | --- |
| Ask in chat | On a run in a personal workflow's run history, opens a new chat with that run selected. | Ask what a run found without copying its output into chat or running the workflow again. | `allow_user_workflows` and `enable_chat_workflow_results`, plus the `WorkflowUser` role while `require_member_of_workflow_user` is on, for a completed or partially completed run that isn't a structured run |
| Ask about this | In the full workflow alert, under **Show more**, opens a new chat with the alert's run selected. The alert closes and stays unread. | Go straight from an alert to asking what the run found. | The same settings, for a personal workflow's alert about a completed or partially completed run |
| Workflow result notice | Names the run your next question is about, for example "Answering from the Weekly digest run of Mon, Jun 2, 9:02 AM — not re-running the workflow". While it's shown, every other source and **Orchestrate** are off, and the message box reads "Ask about the workflow results…". | Confirm which result the answer will use before you send. | A run selected with Ask in chat or Ask about this, or inherited from the chat's latest answer |
| Remove workflow result context | Removes the notice, so the next question is an ordinary chat question. | Go back to normal chat in the same conversation. | The notice is shown |
| Unavailable answer | Shows "This answer is unavailable because access to the workflow result it used could not be confirmed." in place of an answer that used a workflow result. Your question stays. | Know that an answer relied on a result you can no longer read, such as a deleted run's. | The result is no longer available to you, or the chat was shared or converted to a collaboration |

Choosing documents or another source, uploading a file, turning on
**Orchestrate** or opening another chat also removes the notice. When a run's
result can't be asked about as selected, for example because it changed or the
run was deleted, the notice is removed and a message says why. Retry and Edit
aren't available on a question about a workflow result or its answer, and the
server refuses them; ask the question again instead. Once a chat is shared or
converted to a collaboration, its Follow up answers are hidden for everyone, you
included. The original chat's stored messages are unchanged. The
collaboration's copies are stored with these answers withheld, and the chat's
saved summary is cleared on both chats.

### Saved workflow results in a plan

Implemented in **0.261.217** (Refs: microsoft/simplechat#1546). With
**Orchestrate** on, a plan can read the stored result of a finished run of one
of your personal workflows, for example when you ask "what did my weekly digest
find on Monday?". You don't select the run first: the plan finds the run you
describe, and the workflow isn't run again. See
[Ask Orchestrate about workflow results]({{ '/guides/ask-about-workflow-results/' | relative_url }}#ask-orchestrate-about-workflow-results).

| Control or state | What it does | Why you would use it | Available when |
| --- | --- | --- | --- |
| Workflow (Run view) | Shows the name of the saved workflow whose result a step reads, or **Workflow details unavailable** when the name can't be shown. | Match each step to the workflow it reads. | `enable_chat_orchestration`, `allow_user_workflows` and `enable_chat_workflow_results`, plus the `WorkflowUser` role while `require_member_of_workflow_user` is on, in a conversation that's private to you, for a plan with a step that reads a saved workflow's result |
| Run (Run view) | Shows which run the step reads, in words, such as **Latest run**, **Latest completed run** or **Run finished on 2025-06-02**. The day is your local day. | Check that the plan reads the run you meant before it runs. | Same as Workflow |

The answer ends with **Saved workflow results:**, a note the server writes. It
has a line for each run the answer used, such as "This answer uses the stored
result of the Weekly digest run of Mon Jun 2, 2025, 9:02 AM PDT. The workflow
was not re-run.", and a line for each result that wasn't read, with the reason.
The answer uses a result as notes, not as a cited source. It's withheld like a
Follow up answer once a result it used is no longer available to you, or the
chat is shared or converted to a collaboration.
