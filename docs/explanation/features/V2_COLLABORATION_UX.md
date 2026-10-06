# V2 Shared Conversation Experience

## Overview

Four changes to how the V2 (React) interface shows a conversation shared by several people and
agents:

- **Mentions as pills.** A message names the agent that was asked and the people who were
  mentioned as pills above its text, the way a reply shows its quote, instead of repeating
  `@Name` inside the sentence.
- **Mention chips in the composer.** Picking from the `@` menu adds a removable chip above the
  message box instead of inserting the name: any number of people, and one model or agent.
- **Agent activity lines.** Each running AI request shows as one slim line at the end of the
  thread, for every participant, with who asked, the elapsed time and the latest step. Several
  can run at once. It replaces the large "Thinking" bubble in shared conversations.
- **Generated documents and media in the drawer.** The Documents drawer lists the documents
  agents generated in the conversation, with a Markdown preview and a download that follows the
  workspace's own download rules, and gathers every image, video and audio clip the thread shows,
  including signed links fetched from remote services.

**Implemented in version:** 0.261.255

## Dependencies

- Collaborative conversations (`enable_collaborative_conversations`).
- The Simple Chat action's upload functions (`upload_markdown_document`, `upload_word_document`,
  `upload_powerpoint_document`) for generated documents.
- The workspace download settings `allow_group_workspace_file_downloads`,
  `allow_personal_workspace_file_downloads` and `require_group_assignment_for_file_downloads`,
  and a group's own `disable_file_downloads`.

No new npm, CDN or Python dependency.

## Technical specifications

### Mention pills and composer chips

The stored message is unchanged: it keeps the `@Name` text, `metadata.mentioned_participants`
and `metadata.ai_invocation_target`. The server, the classic interface and the assistant all
read mentions from that text, so the composer puts the chips' names in front of the message when
it sends (`prefixComposerMentions` in `lib/mentions.ts`). A chip-only message is sent as a ping,
as typing `@Name` alone always was. With a saved prompt attached, the names count as typed text,
so a prompt that uses `{{composer}}` receives them and the server's prompt metadata check still
holds.

On display, `readMessageMentionPills` (`lib/sharedMessage.ts`) reads the stored metadata, and
`stripMentionText` (`lib/mentions.ts`) removes the matching `@Name` text, longest names first so
"@Ada Lovelace" is not mistaken for "@Ada". A name used to address someone takes its comma or
colon with it, and when it began a sentence the next word takes the capital, so
"New York. @Sam, start with the vehicle." reads "New York. Start with the vehicle." Whitespace is
tidied only when something was removed, and blank lines between paragraphs are kept. Nothing is
removed from a masked message, because mask ranges are offsets into the stored text, or from a
message an agent posted. Because the names move to the pills, a message that gives different
people different tasks no longer says which task is whose.

A reply's quotation of a message reads the same way (`buildReplyPreview` in
`lib/sharedMessage.ts`), so an agent's answer quotes its request without the agent's `@Name`.
A quotation of an answer or of a message an agent posted also drops the markdown markers, so it
reads "Answer The shipment arrived at 08:47" rather than "## Answer The shipment arrived at
**08:47**". A person's own text is quoted as typed, and a message that was only mentions keeps
them, so its quotation is not empty.

The composer keeps chips in the draft (`ComposerDraft.mentions`). A second agent replaces the
first, a person is never added twice, and chips are cleared when the conversation changes. The
message shown while sending carries the same metadata the server stores, so its pills appear at
once.

### Agent activity events

`CollaborationAiActivity` (`route_backend_collaboration.py`) brackets each request made through
`POST /api/collaboration/conversations/<id>/stream` with events on the conversation's event
stream:

| Event | Payload `run` | When |
| --- | --- | --- |
| `collaboration.ai.started` | `run_id`, `display_name`, `target_type`, `requested_by` (`user_id`, `display_name`), `request_message_id`, `started_at` | Before the request runs |
| `collaboration.ai.progress` | `run_id`, `step` | Each new progress step, in plain words, trimmed to 140 characters |
| `collaboration.ai.finished` | `run_id`, `status` (`completed`, `cancelled` or `failed`) | Once, in a `finally` block, so also when the requester disconnects |

Thoughts are written for whoever debugs a request, so `describe_ai_activity_step`
(`functions_collaboration_ai_activity.py`) describes each stream event before it is broadcast and
never sends a plugin, function or model name, an argument or a timing:

| Stream event | Step |
| --- | --- |
| Conversation history prepared | Reading the conversation |
| Request sent to the model | Thinking |
| Tool call starts | The function in words: `getOrderStatus` reads "Looking up order status", `listInvoices` "Reviewing invoices"; document search reads "Searching documents" and map tools "Updating the map" |
| Tool call finishes | Reviewing what it found |
| Call to another agent | Asking Data Analyst, then Reviewing Data Analyst's reply |
| Web search, web page, data analysis | Searching the web, Reading a web page, Analyzing the data |
| First text of the answer | Writing the answer |
| Model finished | Finishing up |

Anything else, including a failed tool call, leaves the line on its previous step. Publishing
never raises; a failure is logged and the answer is unaffected.

The client (`lib/aiActivity.ts`) keeps the running requests in `collaborationStore.aiRuns`.
Unlike every other event, these are also applied when replayed on attaching, so a request already
running when someone opens the conversation shows up; a run that never reports finishing expires
after 15 minutes, and an answer replying to the request also ends its line. The requester's own
line is drawn from their stream until the broadcast arrives, without a step, and never twice.

### Generated documents

| Route | Purpose |
| --- | --- |
| `GET /api/collaboration/conversations/<id>/generated-documents` | Lists `document_id`, `file_name`, `workspace_scope`, `preview`, `message_id`, `created_at` and `can_download` |
| `GET /api/collaboration/conversations/<id>/generated-documents/<document_id>/download` | Returns the file as an attachment |

Both require an accepted participant (`assert_user_can_view_collaboration_conversation` with
`allow_pending=False`). Documents are read from the conversation's own upload citations
(`functions_collaboration_generated_documents.py`): only a successful upload with a valid id and a
`group` or `personal` scope counts, each document is listed once, and a fully masked message's
documents are not listed. The list does not include group ids.

The download only serves a document the conversation produced, and then applies the workspace's
download rules for the reader, whichever group they currently have active:

- **Group document:** group workspaces enabled, a role of Owner, Admin or DocumentManager in that
  group (the roles the group workspace's own download route requires), downloads allowed for the
  group, and the document belonging to the group.
- **Personal document:** personal workspaces enabled, personal downloads allowed, and the reader
  owning the document. Other participants cannot download someone's personal document.

The Markdown preview fetches the same route and renders it with `PlainMarkdown`, which does not
render raw HTML. Word and PowerPoint files download only.

### Media

`collectConversationMedia` (`lib/conversationMedia.ts`) lists images from image messages and from
`![caption](url)` in replies and agent-posted messages, and audio and video linked in them (judged
by the file extension, as the inline players are). Each file appears once. Code samples, masked
spans, fully masked messages and messages replaced by a workflow reply are skipped, as is anything
a person typed as plain text. An image whose signed link has expired shows as unavailable.

Since 0.261.260 the section groups media into Images, Videos and Audio. Images and clips are tiles
that open one viewer, which steps through all of them and can scroll to an item's message.
Recordings are players with Download. See
[V2 Media Galleries and Viewer](V2_MEDIA_GALLERIES_AND_VIEWER.md).

### Files

| File | Change |
| --- | --- |
| `application/single_app/route_backend_collaboration.py` | Activity events; generated document routes |
| `application/single_app/functions_collaboration_generated_documents.py` | New: reading upload citations and authorizing downloads |
| `application/single_app/functions_collaboration_ai_activity.py` | New: plain-language activity steps |
| `application/v2_ui/src/lib/mentions.ts`, `sharedMessage.ts`, `composerDraft.ts` | Strip, pills and chips |
| `application/v2_ui/src/lib/aiActivity.ts`, `collaborationEvents.ts`, `stores/collaborationStore.ts`, `stores/chatStore.ts` | Activity state and events |
| `application/v2_ui/src/lib/conversationMedia.ts`, `collaboration.ts` | Media list; generated document API |
| `application/v2_ui/src/components/chat/MentionPills.tsx`, `DrawerAssets.tsx` | New components |
| `application/v2_ui/src/components/chat/MessageList.tsx`, `Composer.tsx`, `ComposerEditor.tsx`, `ConversationDrawer.tsx` | Wiring |

## Usage

1. In a shared conversation, type `@` and pick people and an agent. They appear as chips above
   the message box; remove one with its button.
2. Send. The message shows the chips as pills, and an activity line shows the agent working for
   you until its answer arrives. Other participants see the same line.
3. Open the Documents drawer. **Generated** lists what agents created in the conversation, with
   Preview for Markdown and Download where permitted. **Media** shows every image and clip.

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_collaboration_mention_pills_logic.mjs` | Strip, pills, reply quotes, chips, prefixing, prompt submission |
| `functional_tests/test_v2_collaboration_ai_activity_logic.mjs` | Activity bookkeeping, replay, local line, dispatch |
| `functional_tests/test_v2_drawer_media_logic.mjs` | Media list rules |
| `functional_tests/test_collaboration_ai_activity_events.py` | Event lifecycle, plain-language steps and route wiring |
| `functional_tests/test_collaboration_generated_documents.py` | Citation reading and download authorization |
| `ui_tests/test_v2_collaboration_ux.py` | Pills, chips and sending, activity lines, drawer sections in Chromium |

### Known limitations

- Generated documents are listed for shared conversations only.
- Activity lines cover requests made in the conversation. A workflow run that posts into a
  conversation afterwards does not show one.
