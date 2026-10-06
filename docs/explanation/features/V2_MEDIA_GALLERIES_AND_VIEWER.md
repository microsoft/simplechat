# V2 Media Galleries and Viewer

Implemented in version: **0.261.260**

## Overview

Agents that pull evidence from a remote service answer with many images and clips: a dozen
camera stills and a couple of clips in one reply, each under a one-line caption, or a timeline
where every entry links a clip and shows a still. Until this version each image rendered as a
full-width card and each clip as a full-width player, so one such reply filled several screens.
The conversation drawer listed clips and recordings as plain text rows.

This version lays media out as compact tiles and adds one viewer for all of it:

- **Galleries in replies.** Two or more images or clips in a row become a gallery of tiles, three
  to a row, each with its caption underneath. In a list, the clip and still at the end of each
  item sit side by side under the item's text.
- **Clips play in their tile.** A clip tile shows the first frame, its length and a play mark.
  Pressing it plays the clip at tile size. **View larger** opens it in the viewer from the same
  point.
- **Media viewer.** Opening a tile shows the image or clip large. **Previous** and **Next**, or
  the arrow keys, move through the gallery. The viewer also offers Download and Open in a new
  tab, and shows the image at its actual size on request.
- **Drawer Media section.** The Documents drawer groups media into **Images**, **Videos** and
  **Audio**, with a count for each group. Images and clips are tiles that open one viewer
  stepping through all of them, and **Show in conversation** scrolls to the message an item came
  from. Recordings are full players with play, stop, seek, volume, speed, Download and Show in
  conversation.
- **Downloads.** Recordings, clips and images can be saved. When the file's host does not let
  the page read it, the file opens in a new tab instead, where the browser can save it.

Recordings never join a gallery. A recording plays from its own player bar, next to the text
that describes it.

### Dependencies

- The V2 markdown renderer (`react-markdown`, `remark-gfm`, `remark-breaks`) and the inline media
  players from [V2 Inline Media and Agent-Posted Messages](V2_INLINE_MEDIA_AND_AGENT_MESSAGES.md).
- The Documents drawer Media section from
  [V2 Shared Conversation Experience](V2_COLLABORATION_UX.md).
- `CSP_MEDIA_SRC_ORIGINS` must still allow a media host before its clips and recordings play.
- No new npm, CDN or Python dependency.

## Technical Specifications

### Finding galleries in a reply

`application/v2_ui/src/lib/mediaGallery.ts` is a rehype plugin, `rehypeMediaGallery`. It runs on
the parsed tree for the same reason `rehypeRichBlockIndex` does: paragraphs, hard and soft line
breaks and list items have already been decided there, and a text scanner would get them wrong.

Lines are split at line breaks, so one paragraph that alternates caption and media lines groups
the same way as separate paragraphs do.

| Where | What groups | Minimum |
| --- | --- | --- |
| Body of a reply, block quote | Images and clips each alone on a line, in a row. A line of 160 characters or fewer directly above a single image or clip, in the same paragraph, becomes its caption. | 2 |
| List item | The images and clips that end the item: a clip linked after the item's last sentence, and images or clips on the lines below it. The item's text is never taken as a caption. | 1 |

Rules that keep the grouping predictable:

- A line ending in a colon that introduces several images stays as text above the gallery
  ("Stills from both cameras:"). Over a single image it captions that image, without the colon.
- A clip linked mid-sentence ("compare [this clip](a.mp4) with [that one](b.mp4)") stays in the
  sentence.
- Recordings, images in tables, inline `data:` images and paths the app does not serve images
  from keep their existing rendering.
- A single image in the body of a reply keeps its full-width card.

The plugin only moves the `img` and `a` elements that markdown already produced into
`div > figure > figcaption` wrappers. It parses no HTML, raw HTML stays disabled, and
react-markdown's URL transform still runs on every image and link afterwards. Each media element
is marked with `dataMediaTile` (its position in the gallery) and the wrapper with
`dataMediaGallery`. `readMediaGallery` reads the transformed tree back into the gallery's items.
Plain-text titles drop citation and maths placeholders and show masked text as `[masked]`. The
rendered caption keeps its placeholders, so citations and redactions render as usual.

### Components

| File | Purpose |
| --- | --- |
| `components/chat/AssistantMarkdown.tsx` | Registers the plugin. `div` renders a gallery, `img` and `a` render a tile when they are in one, `figcaption` substitutes citations, masks and maths. |
| `components/chat/MediaGallery.tsx` | The three-column grid, its viewer, and `MediaGalleryTile`, which renders an image tile or a clip that plays in place with **View larger** |
| `components/chat/MediaTiles.tsx` | `ImageTile`, `VideoTile` (first frame, length, play mark) and the **Unavailable** state |
| `components/chat/MediaViewer.tsx` | The viewer, built on `Modal`: previous and next, arrow keys, actual size, Download, Open in a new tab, Show in conversation |
| `components/chat/useMediaDownload.ts` | Download with a toast for each outcome |
| `components/chat/DrawerAssets.tsx` | The drawer's Images, Videos and Audio groups |
| `components/chat/InlineAudioPlayer.tsx` | Adds Download, and Show in conversation when the drawer lists the recording |
| `components/chat/InlineMediaFallback.tsx` | Also describes an image the viewer cannot show |
| `components/chat/ConversationDrawer.tsx` | Passes Show in conversation to the Media section. Escape no longer closes the drawer while a dialog opened from it is showing. |
| `lib/mediaDownload.ts` | Saving a file, naming it, and opening it in a new tab |
| `lib/inlineMedia.ts` | `posterFrameUrl`, the still-frame address for a clip tile |

### Loading and playback

- A clip tile loads only the clip's metadata and first frame, and only once the tile is on screen
  (`IntersectionObserver`), so opening a long thread does not fetch every clip in it. The frame
  is requested with a `#t=0.1` media fragment, which never reaches the server, so a signed link's
  signature is unchanged.
- Starting any clip or recording pauses whichever one was playing, as before.
- Moving to another item in the viewer stops the clip that was showing.

### Downloads

`downloadMedia` fetches the file and saves it under the file name at the end of its URL, or under
its title with an extension for its type. The app's own image endpoints are fetched with the
session's credentials. Other hosts are fetched with no cookies, since a signed link carries its
own authority.

When the host does not let the page read the file (no CORS headers), or does not start answering
within four seconds, the file opens in a new tab and a notice says so. If the browser blocks that
tab, the notice offers **Open**. If the host answers with an error, as for an expired link, the
download reports the error instead of opening a tab that would show the same error.

### Configuration

No new settings. Clips and recordings from another host still need its origin in
`CSP_MEDIA_SRC_ORIGINS`, as described in
[V2 Inline Media and Agent-Posted Messages](V2_INLINE_MEDIA_AND_AGENT_MESSAGES.md).

## Usage

1. Ask an agent whose actions return images, clips or recordings for them, as before. A reply
   with several shows them as a gallery. A reply with one image still shows that image at full
   width.
2. Select an image tile to open the viewer, then use **Previous** and **Next** or the arrow keys
   to move through the gallery. Select **View at actual size** to inspect detail, and **Download**
   to keep a copy.
3. Select a clip tile to play it where it is. Select **View larger** in its corner to continue
   watching in the viewer.
4. Open the Documents drawer to find media again in a long conversation. **Images** and
   **Videos** open the viewer across every image and clip in the conversation. **Show in
   conversation** closes the viewer and scrolls to the message. Under **Audio**, play a recording
   in place, or expand it for Download and Show in conversation.

## Testing and Validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_media_gallery_logic.mjs` | The real plugin inside react-markdown on caption pairs, alternating lines, image paragraphs, colon labels, evidence lists, tight lists, mid-sentence clips, unsafe and `data:` sources, block quotes, tables, placeholders in captions and the URL transform; file naming and the still-frame address |
| `functional_tests/test_v2_media_gallery_wiring.py` | Runs the Node checks; renderer wiring; no raw HTML; every new media element and link uses `safeMediaUrl` or `resolveImageSource`; drawer groups and Escape guard; download credentials and fallback |
| `functional_tests/test_v2_inline_media_players.py` | Updated for the new image wiring |
| `functional_tests/test_v2_rich_rendering.py` | The pinned rehype plugin list now includes `rehypeMediaGallery` |
| `ui_tests/test_v2_media_galleries.py` | In Chromium with production CSS: three-column layout and captions, evidence-list rows, viewer navigation by buttons and keys, focus returning to the tile, a clip playing in its tile and opening larger, drawer groups, a recording playing and downloading, Show in conversation, Escape closing only the viewer, the new-tab fallback, and an expired link |
| `ui_tests/test_v2_collaboration_ux.py` | The drawer's Generated and Media sections, updated for clip tiles |

The UI tests play a WebM clip recorded by the browser under test and a WAV built by the test, so
no media files are committed.

### Known limitations

- Grouping follows the shape of the markdown. A caption written after its image, or several
  images on one line under one caption, is not captioned.
- The viewer steps through one gallery from a reply, or through all images and clips from the
  drawer. It does not move between galleries in different replies.
- A host that will not let the page read its files can't be saved directly. The file opens in a
  new tab instead, where the browser's own viewer can save it.
- The classic interface is unchanged.
