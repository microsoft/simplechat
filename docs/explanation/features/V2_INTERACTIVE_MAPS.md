# V2 Interactive Maps

Implemented in version: **0.261.223**

Related issue: [#1609](https://github.com/microsoft/simplechat/issues/1609)

## Overview

The Azure Maps action (`create_map_visualization` in the `azure_maps_openlayers` plugin) returns
a map as its tool result: a tile template, markers, ordered paths, shaded areas and a starting
view. The classic chat has always drawn that result as an interactive map under the reply. The
V2 chat had no map renderer, so a reply that relied on a map showed only its text.

The V2 chat now draws the same map under the reply:

- It opens fitted to everything on the map. Drag to pan, use the **+** and **-** buttons,
  double-click, pinch, or **Ctrl + scroll** (**Cmd + scroll** on a Mac) to zoom. A plain
  scroll still scrolls the conversation, so a long thread with maps stays easy to read.
- Hovering a marker, path or area shows its label and description. Clicking keeps the details
  open until you click elsewhere on the map or press **Escape**.
- The **Full screen** button expands the map to the whole screen.
- **List what the map shows** opens a text list of every marker, path and area, for keyboard and
  screen reader users and for reading labels without hunting for points.
- The header names the map, repeats the action's summary and counts what the map holds; the
  footer names the provider, the action and the tile attribution.

Maps appear wherever the reply appears: in a personal conversation, and in a group conversation
that received a workflow's reply.

### Dependencies

- OpenLayers 10.6.1, vendored into `application/v2_ui/public/vendor/openlayers-10.6.1/`. It is
  the same build the classic chat loads from `static/js/openlayers/`, byte-identical to the
  published `ol@10.6.1` package, with its BSD 2-Clause licence. It is not an npm dependency and
  is downloaded only when a reply has a map.
- The existing Azure Maps tile proxy, `/api/azure-maps/tile`, which keeps the Azure Maps key on
  the server.
- `lucide-react` icons. No CDN assets; the Content-Security-Policy is unchanged.

## Technical Specifications

### Reading the map

`application/v2_ui/src/lib/inlineMaps.ts` has no DOM access, so it is tested directly in Node.

- `readInlineMap(citation)` reads one agent citation. The tool result may be an object or JSON
  text, or the payload itself when it was fetched from an artifact. A result is a map only when
  it succeeded, has `render_type: 'azure_maps_openlayers'`, a tile template that passes
  `safeTileTemplate`, and at least one marker, path or area.
- `safeTileTemplate(value)` accepts only a root-relative template on `/api/azure-maps/tile?` that
  has `{z}`, `{x}` and `{y}` placeholders and no whitespace, quotes or angle brackets. Tiles are
  requested with the user's session, so a template naming another path or host is refused.
- Markers need a real longitude (-180 to 180) and latitude (-90 to 90); paths need two points
  and areas three, and an open area ring is closed. A colour is used only if it is a hex value,
  `rgb()`/`rgba()` or a colour keyword; otherwise the classic chat's default colour is used.
- The starting view follows the classic rules: the payload's centre, or the first feature; zoom
  14 for a single marker and 10 otherwise; a maximum zoom of 15; fit to features unless the
  payload turns it off.
- `collectMapCitations(citations)` returns every map on a message in citation order. A map
  repeated with only a different tile token is drawn once. A compact citation, whose full result
  was moved to an artifact record, is returned by artifact ID when its function is
  `create_map_visualization` or its plugin is the Azure Maps plugin, so other tool calls never
  cause a request.
- `stripLegacyMapBlocks(content)` removes legacy `{{map:...}}` blocks that older replies stored
  in their text, matching braces outside JSON strings the way the server does. The classic chat
  removes them too; the map itself comes from the tool result.

### Drawing the map

`application/v2_ui/src/components/chat/InlineMapCard.tsx`

- `InlineMapCards` renders under an assistant reply in `MessageList.tsx`, after the reply text,
  whenever no part of the message is masked. A compact map citation is fetched once through
  `fetchAgentCitation` (`GET /api/conversation/<conversation_id>/agent-citation/<artifact_id>`),
  which works for personal and collaborative conversations.
- `InlineMapCard` loads OpenLayers through `loadOpenLayers()` in `vendorAssets.ts` and draws
  areas, then paths, then markers, so a marker is never hidden under an area.
- Every title, label and description is action output and is written only as text. React renders
  the card, and the popup is built with `document.createElement` and filled with `textContent`.
  OpenLayers' own attribution control writes its strings as HTML, so it is turned off and the
  attribution is shown as text in the footer.
- The mouse wheel zooms only with the platform modifier key, through `MouseWheelZoom` with
  `platformModifierKeyOnly`.
- Tiles are requested with `crossOrigin: 'anonymous'` in the default same-origin deployment,
  which still sends the session cookie, and `use-credentials` when the API is on another origin.
- If OpenLayers cannot load, the card says so and the list of what the map shows still works.

### Tile tokens in older messages

Tile proxy tokens expire after 240 minutes. The classic message route already reissued them when
a conversation was opened; the endpoints V2 reads did not, so a map in an older reply or in a
group conversation drew markers on blank tiles.

- `refresh_azure_maps_message_citations(messages)` in `functions_azure_maps.py` reissues the token
  in every stored map citation and returns new message objects. Messages and citations that are
  not maps are returned unchanged.
- `GET /api/get_messages` (`route_backend_conversations.py`) and
  `GET /api/collaboration/conversations/<conversation_id>/messages`
  (`route_backend_collaboration.py`) both call it. The collaborative route already checks that
  the caller can view the conversation before any message is read.
- `refresh_azure_maps_function_result` no longer parses JSON-text tool results that cannot be
  maps, because these endpoints now pass every citation through it.

### Tile tokens in stored tool results

Added in 0.261.224. Tool results are redacted before they are stored as a reply's citations,
and that redaction used to replace the map's tile token with `***REDACTED***`. Every stored map
then drew on blank tiles, in both chats. `sanitize_plugin_invocation_value` now keeps the
`token=` value that directly follows `/api/azure-maps/tile?`, and nothing else. That token is
encrypted with the app's secret key, expires, and only works on SimpleChat's signed-in tile
proxy. See [Azure Maps Tile Token Redaction Fix](../fixes/AZURE_MAPS_TILE_TOKEN_REDACTION_FIX.md).

### Configuration

There is nothing to configure. A map appears when an agent with the Azure Maps action returns
one.

## Usage

1. Give an agent the Azure Maps action and ask it to map known locations, a route or an area.
2. The reply shows the map under its text. Hover a point for its details, click to keep them
   open, and use **Full screen** for a closer look.
3. Open **List what the map shows** to read every label and description as text.

## Testing and Validation

- `functional_tests/test_v2_inline_maps.py`: OpenLayers vendored byte-identical to the published
  package; no HTML sink in the card or the reader; the attribution control off; tiles only
  through the proxy; the card wired under replies; both message endpoints refreshing tokens; the
  refresh helper reissuing expired tokens in object and JSON-text results without mutating its
  input.
- `functional_tests/test_v2_inline_maps_logic.mjs`: the reading rules above, run in Node against
  the real module.
- `functional_tests/test_v2_rich_rendering.py`: OpenLayers added to the vendored-library and
  forbidden npm dependency checks.
- `ui_tests/test_v2_inline_maps.py`: the real `MessageList` and card in Chromium with production
  CSS. It covers tiles from the proxy, the expand control, no HTML attribution control, the legacy
  block hidden, hover details, click to pin, Escape, a compact citation fetched and drawn, the
  text list, and the fallback when OpenLayers cannot load.

### Known limitations

- Classic chat still shows details on click only; hover tooltips are V2-only for now.
- A map is drawn only in the chat. Exported conversations do not include a map image.
- A tile token issued when the conversation was opened lasts 240 minutes; reopen the conversation
  to reissue it.
- Maps stored before 0.261.224 have a redacted tile token that cannot be reissued, so they show
  their markers, paths and areas without tiles. Running the request again produces a working map.
- An agent that calls the map action twice with different data shows two maps, as the classic
  chat does.
