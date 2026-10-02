# V2 Inline Media and Agent-Posted Messages

Implemented in version: **0.261.222**

Related issue: [#1611](https://github.com/microsoft/simplechat/issues/1611)

## Overview

Agents increasingly return media: recordings, short camera clips, photographs and document scans,
usually as short-lived signed links from an OpenAPI action. The V2 chat now presents them in place:

- A markdown link to an **audio** file renders as a compact player. Collapsed, it shows play/pause,
  the title and elapsed/total time with a thin progress line. Pressing play or the chevron expands
  it to add a seek slider, stop, volume and mute, playback speed (1x, 1.25x, 1.5x, 2x) and an
  "open in a new tab" link.
- A link to a **video** file renders as a card with the browser's own controls (play, seek, volume,
  fullscreen) and the link text as its caption.
- A markdown **image** renders as a captioned card that opens the existing image lightbox.
- Starting one recording or clip pauses any other, so two never play over each other.
- Media that cannot play (an expired link, a host the policy does not allow, an unsupported format)
  falls back to a short notice and a link.

Messages an agent posts into a conversation through the Simple Chat action
(`add_conversation_message`) are marked as agent-authored markdown and render like the agent's
replies, so a briefing posted to a group conversation keeps its headings, tables, links, images and
players. Messages people type stay plain text.

### Dependencies

- `react-markdown` (already used by the V2 renderer), with raw HTML still disabled and the default
  URL transform unchanged.
- `lucide-react` icons. No new npm dependencies and no CDN assets.

## Technical Specifications

### Link classification

`application/v2_ui/src/lib/inlineMedia.ts`

- `inlineMediaKind(url)` returns `audio`, `video` or `null`, judged only by the extension at the
  end of the URL **path** (`.mp3`, `.wav`, `.m4a`, `.aac`, `.ogg`, `.oga`, `.opus`, `.flac`, `.weba`;
  `.mp4`, `.m4v`, `.webm`, `.mov`, `.ogv`). Query strings, such as signatures, are ignored.
- `safeMediaUrl(value)` accepts only `http:` and `https:` URLs and resolves root-relative paths
  against the page. Every media source and every link the players render passes through it.
- `safeMarkdownHref(value)` keeps the schemes react-markdown allows by default (web, mail, phone and
  chat, plus relative and fragment links) for ordinary links rendered by the new `a` component.
- `inlineMediaTitle(text, url)` removes action wording such as "Open audio:" from the link text.
- `claimPlayback(element)` pauses the previously playing media element.

### Components

| Component | Purpose |
| --- | --- |
| `components/chat/InlineAudioPlayer.tsx` | Expanding audio bar built from `span`, `button` and `input` elements so it is valid inside a paragraph or list item |
| `components/chat/InlineVideoCard.tsx` | Video card with native controls and caption |
| `components/chat/InlineImageCard.tsx` | Captioned image card; the lightbox is rendered through a portal |
| `components/chat/InlineMediaFallback.tsx` | Notice and link when media cannot play |
| `components/chat/AssistantMarkdown.tsx` | Adds `a` and `img` components that route media links and images to the components above |

### Agent-posted messages

- `functions_simplechat_operations.py` defines
  `AGENT_POSTED_MESSAGE_METADATA = {"posted_via": "agent_action", "content_format": "markdown"}`.
  `add_conversation_message_for_current_user` merges it into the message metadata on both the
  personal path (`_persist_personal_conversation_message`, new `extra_metadata` parameter) and the
  shared path (`persist_collaboration_message`, existing `extra_metadata` parameter).
- `lib/sharedMessage.ts` `isAgentPostedMessage(message)` recognises the marker on user messages.
- `components/chat/MessageList.tsx` renders those messages with `AssistantMarkdown` in the neutral
  bubble (tables and links are unreadable on the accent colour), keeps them on the sender's side of
  the thread, and labels them "posted through an agent".

### Configuration

| App setting | Default | Purpose |
| --- | --- | --- |
| `CSP_MEDIA_SRC_ORIGINS` | empty | Comma, space or JSON list of external `https://` origins whose audio and video may play inline. Appended to the `media-src 'self' blob:` directive. |

`application/single_app/csp_media_sources.py` validates each entry. Only bare `https://` origins are
accepted: a host with at least two labels, an optional leading `*.` label and an optional port.
Other schemes, paths, quotes, semicolons, keywords and a bare `*` are rejected and logged through
`log_event`, so the setting cannot widen the policy beyond media or inject another directive.

Prefer the narrowest origin that covers the host, for example the Container Apps environment's
domain (`https://*.<environment>.<region>.azurecontainerapps.io`) rather than the regional domain.

## Usage

1. Give an agent an action that returns media links (for example an OpenAPI action whose responses
   include signed audio or video URLs), and tell the agent to include those links in its reply.
2. If the media is served from the action's own host, add the host's origin to
   `CSP_MEDIA_SRC_ORIGINS` and restart the app.
3. Ask the agent. Audio links appear as players, video links as cards, and images as captioned cards.
4. When the agent posts into a group conversation through the Simple Chat action, the posted message
   renders the same way for every participant.

## Testing and Validation

- `functional_tests/test_v2_inline_media_players.py` covers CSP origin validation, the CSP wiring
  in `config.py`, the agent-posted marker on both persistence paths, the message rendering branch,
  the renderer's XSS boundaries, and runs the Node checks below.
- `functional_tests/test_v2_inline_media_logic.mjs` runs the real `inlineMedia.ts` helpers in Node:
  classification, URL safety, titles, time formatting and single-playback.
- `functional_tests/test_v2_rich_rendering.py` still confirms the policy keeps `default-src 'self'`
  and no CDN hosts.

### Known limitations

- Playback depends on the media host allowing the browser to stream it; signed links that expire
  fall back to the notice and link.
- Downloading an external image from the lightbox needs the host to allow cross-origin reads;
  opening it in a new tab always works.
- The classic interface is unchanged.
