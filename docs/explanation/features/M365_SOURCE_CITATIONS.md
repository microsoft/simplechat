# Microsoft 365 Source Citations (v0.261.303)

## Overview

An answer that uses SharePoint or OneDrive files, emails or calendar events now cites them the
way it cites workspace documents. Each item the answer mentions gets an inline citation chip,
and every cited item, plus every file whose content was read, is listed in the conversation's
**Documents** pane with an **Open online** link. Before this release an orchestrated SharePoint
answer ended with plain text such as "Source: *EVA Swab Tool…* (SharePoint file
**20170010188.pdf**)" with no chip and nothing in the Documents pane, and an email list changed
its layout from one answer to the next.

What changes for the reader:

- **Citation chips.** A file chip shows the file name and an email or event chip shows its
  subject, with an icon for the kind of item. Clicking a chip opens a source card with the
  item's details and an **Open in SharePoint**, **Open in OneDrive** or **Open in Outlook**
  link. The link opens the item where it lives, so the reader's own sign-in decides what they
  can see; nothing is downloaded or copied.
- **One email and event layout.** Email and event lists always use the same layout: a header
  line such as "10 most recent emails, all unread, newest first:", then one numbered line per
  item with the subject in bold, the sender or time span, and the citation chip. Times are
  shown in the reader's browser time zone.
- **Documents pane.** New **SharePoint & OneDrive**, **Email** and **Calendar** sections list the
  conversation's Microsoft 365 items with an **Open online** link. The workspace document list
  is unchanged.

The layout is a fixed text format that the model writes and the application cites, not a card
the application draws, so it reads the same in copied text, exports and both chat interfaces.

Implemented in version: **0.261.303**, tracked in `application/single_app/config.py`.

Dependencies:

- The Microsoft 365 Email, Calendar, SharePoint Online and OneDrive actions
  (`semantic_kernel_plugins/msgraph_plugin.py`, `functions_m365_retrieval.py`) and the legacy
  Microsoft Graph action, which shares the mail and calendar implementation.
- The plugin invocation logger (`semantic_kernel_plugins/plugin_invocation_logger.py`).
- Conversation citation tracking (`functions_citation_tracking.py`).

No setting, container, route or index is added. The feature is active wherever a Microsoft 365
action is.

## Technical specifications

### Architecture

`functions_m365_citations.py` owns the whole contract. It has no configuration or storage
imports, and it loads application logging only to report an item it could not cite, so the
plugin logger, the citation tracker and the routes can all use it.

1. **Citation records.** Each item becomes a bounded record with a deterministic id:
   `m365-` followed by the first 16 hex characters of a SHA-256 over the source and a stable
   key (`drive_id:item_id` for a file, `message:<Graph id>` for an email, `event:<Graph id>`
   for an event). Ids contain no underscore, because both browsers split workspace citation ids
   at the last underscore.

   | Kind | Fields |
   |---|---|
   | File | `citation_id`, `kind`, `source` (`spo` or `onedrive`), `title`, `file_name`, `mime_type`, `size_bytes`, `modified_at`, `modified_display`, `location_label`, `web_url` |
   | Email | `citation_id`, `kind`, `source` (`email`), `title` (or "(no subject)"), `from_name`, `from_address`, `received_at` (UTC), `received_display`, `is_read`, `importance`, `preview` (at most 280 characters), `web_url` |
   | Event | `citation_id`, `kind`, `source` (`calendar`), `title`, `start`, `end`, `time_zone`, `is_all_day`, `when_display`, `location`, `organizer_name`, `web_url` |

   Stored records add `cited` (whether the answer's text references the id), `content_read`
   for files that were captured or read, and `data_user_id`, the owner of the Microsoft 365
   data. `web_url` is kept only when it is an `https` URL taken from Microsoft Graph, never
   from model text. No record holds a message body, file content or excerpt.

2. **Citation values in tool results.** Microsoft 365 tool results carry a model-facing
   citation value in the existing marker grammar:
   `(Source: <title>, Location: SharePoint|OneDrive|Email|Calendar) [#<citation_id>]`. The
   title is made safe for both browsers' parsers: newlines, nested `(Source:`, square brackets
   and an embedded `, Location:` are removed or defused, and it is capped at 120 characters.

   - `get_my_messages` and `get_my_events` add `citation_id`, `citation` and a display string
     (`received_display` or `when_display`) to every item, and a top-level
     `citation_instructions`, `presentation` and `display_time_zone`.
   - The SharePoint and OneDrive file tools add `citation_id`, `citation` and
     `modified_display` to every file identity in `search_files`, `discover_files`,
     `prepare_file`, `read_file`, `read_file_chunk` and `analyze_file` results. This happens at
     the tool boundary, so captures saved before this release are cited too.

   The `presentation` value states the fixed layout:

   | Item | Line |
   |---|---|
   | Email header | `{count} {most recent\|matching} emails{, all unread}, newest first:` |
   | Email | `{n}. **{Subject}** — {Sender}, {received_display}{ · Unread}{ · High importance} {citation}`, plus one indented summary line only when the user asked about content |
   | Event header | `{count} {matching }events, {earliest\|latest} first:` |
   | Event | `{n}. **{Subject}** — {when_display}{ · Location}{ · Organizer: name} {citation}` |
   | File | `{n}. **{File name}** — {SharePoint\|OneDrive}, modified {date} {citation}`; in prose, the citation follows the claim |

   For 25 emails the annotation adds about 8 KB to the tool result. Annotation never fails a
   tool: an item that cannot be normalized, such as one whose date falls outside the supported
   range, is returned without a citation value, and the rest of the result is unchanged.

3. **Capture at invocation time.** The annotators return the tool result as an
   `M365CitedResult`, a dictionary that also carries the records made from the Graph data as an
   attribute the model never sees. The plugin invocation logger keeps exactly those records in
   `PluginInvocation.m365_items` before anything is serialized or truncated, and tool citations
   copy them as `m365_items`, so a result longer than the 20,000-character invocation limit is
   still cited completely. Records are never rebuilt from the shape of a result. Another tool,
   such as an HTTP fetch or an OpenAPI or MCP action, that returns JSON shaped like a Graph
   result cannot create a Microsoft 365 citation or link, or replace the link of a real one.

4. **Messages.** Every chat persistence path calls `_attach_m365_citations` next to
   `attach_m365_message_provenance`, which stores `m365_citations` on the assistant message
   with `cited` flags computed from the final text. Workflow answers do the same, and a workflow
   answer mirrored into another conversation brings its records along. A message keeps at most
   100 records; when a turn returns more, the cited items are kept first, then files whose
   content was read. The final event of every chat path (streaming, compatibility, document
   action, workflow result and saved analysis), the non-streaming response and a stopped reply's
   event include `m365_citations`. A reply that content checks remove keeps none, because
   `m365_citations` is one of the cleared answer fields.

5. **Orchestration.** Action and agent steps add a deterministic **Microsoft 365 sources** note
   listing each item's citation value and key details. The compose step is told to copy citation
   values verbatim and to follow the presentation layout whenever its inputs carry them, and the
   mixed-source handoff prompt asks for the same. The final answer collects records from every
   action and agent step's retained tool citations, and the message and the `orchestration_done`
   event carry `m365_citations`. When a run republishes its answer into a shared conversation,
   the shared copy takes the new records, and loses them if the republished answer is blocked.

6. **Conversation aggregate.** `used_m365_items` on the conversation lists every cited item and
   every file whose content was read, most recent first, with the message ids that used each
   item and `last_used_at`. It holds at most 200 items and drops the least recent first. It is
   merged after each chat and orchestrated turn and rebuilt with `used_documents` whenever a
   message is deleted, retried or forked. A shared conversation keeps none.

7. **Display time zone.** Email and event times are written in the browser's IANA time zone,
   which both chat interfaces now send as `time_zone`. Orchestrated steps use the turn's time
   zone when workflow proposals or results are configured. Without a known zone, times are
   shown in UTC and labelled UTC.

### API

`GET /api/conversations/<conversation_id>/metadata` returns `used_m365_items`, filtered to the
items whose `data_user_id` is the signed-in owner, without that field. Messages returned by
`GET /api/get_messages`, shared-conversation serializers and JSON exports carry
`m365_citations`. Markdown exports list cited items under **Microsoft 365 References**.

### Sharing a conversation

Before a private conversation is shared, `functions_m365_history.history_sources` treats any
message with `m365_citations` as Microsoft 365 data of that source, so the history-sharing
approval still applies even when the message's compact tool citations no longer name the source.

### File structure

| File | Change |
|---|---|
| `functions_m365_citations.py` | New: records, ids, citation values, layouts, trusted capture, aggregate and owner filter |
| `semantic_kernel_plugins/msgraph_plugin.py` | Annotates mail and event results |
| `functions_m365_retrieval.py` | Annotates file results at the tool boundary |
| `semantic_kernel_plugins/plugin_invocation_logger.py` | Keeps the records a Microsoft 365 plugin attached to its result as `m365_items` |
| `route_backend_chats.py` | Attaches `m365_citations`, merges `used_m365_items`, reads `time_zone`, carries the records in every final event |
| `functions_workflow_runner.py` | Attaches `m365_citations` to workflow answers and their mirrored copies |
| `functions_orchestration_adapters.py`, `functions_orchestration_execution.py`, `functions_orchestration_events.py`, `functions_orchestration_composition.py`, `functions_orchestration_collaboration.py` | Sources note, final message and done event, compose instruction, shared-copy refresh |
| `functions_citation_tracking.py`, `route_backend_conversations.py` | Aggregate rebuild and owner-only metadata |
| `functions_collaboration.py`, `collaboration_models.py`, `route_backend_collaboration.py`, `route_backend_conversation_export.py`, `functions_m365_history.py`, `functions_chat_content_checks.py` | Carry, export, sharing gate and retraction |
| `v2_ui/src/lib/m365Citations.ts`, `components/chat/M365CitationChip.tsx`, `components/chat/M365CitationContext.tsx` | New: V2 records, chips and source card |
| `v2_ui/src/lib/citations.ts`, `CitationChip.tsx`, `MessageList.tsx`, `ConversationDrawer.tsx`, `MessageInspector.tsx`, `chatStore.ts` | V2 chip kind, plumbing, Documents pane and Sources |
| `static/js/chat/chat-citations.js`, `chat-messages.js` | Classic links and time zone |

## Usage instructions

### Enable and configure

Nothing to enable. Add a Microsoft 365 Email, Calendar, SharePoint Online or OneDrive action to an
agent, or let orchestration use one, and its answers are cited.

### What the reader sees

1. Ask "What are my latest emails?" with an agent that has the Email action. The answer starts
   with a header line and lists one email per line, each ending with a chip showing its subject.
2. Click a chip. The source card shows From, Received, Read or Unread, importance and a preview,
   with **Open in Outlook**.
3. Open **Documents** in the conversation drawer. The **Email** section lists each cited email
   with the sender, received time and **Open online**.
4. Ask a question about a SharePoint document. The answer cites the file after each claim, and
   the **SharePoint & OneDrive** section lists it with its location and modified date.

A chip whose record is no longer on the message opens a card saying the source is no longer
available in this conversation. Neither interface calls the workspace citation endpoint for a
Microsoft 365 id. The classic chat shows the citation's title as a link to the item, or as text
when no `https` link was recorded.

## Testing and validation

- `functional_tests/test_m365_source_citations.py`: deterministic ids, marker parsing with the
  V2 and classic grammars (including the real JavaScript patterns), title sanitization,
  `https`-only links, display strings, mail, event and file annotation through the real plugins,
  the 25-email payload budget, capture past truncation, look-alike results from other tools
  producing no records, out-of-range dates and failing items never failing a tool, `cited`
  flags, the per-message limit keeping cited and read items, persistence sites and final events,
  workflow answers and their mirrored copies, the orchestration sources note, final message,
  done event and shared-copy refresh, the compose instruction, aggregate merge, cap, rebuild and
  owner filter, history-sharing detection, and collaboration and export carry.
- `ui_tests/test_v2_m365_source_citations.py`: V2 chips from a streamed answer, source cards
  and their links, the missing-record card, the request's time zone, the Documents pane sections
  at desktop and phone widths, and the classic chat's links, with no request to
  `/api/get_citation`.

### Known limitations

- Times use the browser time zone, not the mailbox time zone, because reading mailbox settings
  needs the Calendar action's permission and Outlook often names zones in a Windows format.
  Orchestrated answers use UTC unless workflow proposals or results are configured.
- An "Open in Outlook" link opens the owner's mailbox, so it only works for the owner. File links
  follow SharePoint and OneDrive permissions.
- Shared conversations show chips on messages but no Microsoft 365 items in the Documents pane.
- Follow-up questions about a saved workflow result are answered from the stored result rather
  than from Microsoft 365, so those answers carry no Microsoft 365 records of their own.
