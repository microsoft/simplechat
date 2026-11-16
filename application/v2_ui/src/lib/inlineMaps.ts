// inlineMaps.ts
// Reading the interactive maps an Azure Maps action attaches to an assistant reply.
//
// The map action does not put its map in the reply text. It returns a `map_payload` (a tile
// template, markers, paths, areas and a starting view) as its tool result, and that result is
// stored on the message under `agent_citations`. The classic chat draws every such result as a
// map card under the reply (static/js/chat/chat-inline-maps.js). This module reads the payload
// the same way, without touching the DOM, so it can be tested directly.
//
// The payload is data an action returned, so none of it is trusted as markup or as a place to
// load from: text is only ever rendered as text, a colour must look like a colour, a point must
// be a real longitude and latitude, tiles only ever come from SimpleChat's own tile proxy, and a
// marker's photo must be an absolute https link.

export const AZURE_MAPS_RENDER_TYPE = 'azure_maps_openlayers';

/** The Azure Maps plugin function whose results are maps. */
const MAP_FUNCTION_NAME = 'create_map_visualization';

/** SimpleChat's Azure Maps tile proxy (`AZURE_MAPS_TILE_PROXY_ROUTE` in functions_azure_maps.py). */
export const TILE_PROXY_PATH = '/api/azure-maps/tile';

/** A point as `[longitude, latitude]`, the order the action and OpenLayers both use. */
export type LonLat = [number, number];

/** A photo of a marked place, shown with the marker's details. */
export interface MapImage {
    /** An absolute https URL. */
    url: string;
    caption: string;
}

/** One labelled fact about a marked place, such as a reading's time or a transponder ID. */
export interface MapField {
    label: string;
    value: string;
}

export interface MapMarker {
    label: string;
    description: string;
    color: string;
    lonLat: LonLat;
    image: MapImage | null;
    fields: MapField[];
}

export interface MapPath {
    label: string;
    description: string;
    color: string;
    width: number;
    coordinates: LonLat[];
}

export interface MapArea {
    label: string;
    description: string;
    strokeColor: string;
    fillColor: string;
    /** A closed ring: the last point repeats the first. */
    coordinates: LonLat[];
}

export interface MapView {
    center: LonLat;
    zoom: number;
    maxZoom: number;
    fitToFeatures: boolean;
}

export interface InlineMap {
    title: string;
    summary: string;
    /** Root-relative tile proxy template with `{z}`, `{x}` and `{y}` placeholders. */
    tileUrlTemplate: string;
    attribution: string;
    provider: string;
    sourceActionName: string;
    markers: MapMarker[];
    paths: MapPath[];
    areas: MapArea[];
    view: MapView;
}

/** A map ready to draw, or a stored map whose full result has to be fetched first. */
export type MapCitation =
    | { key: string; map: InlineMap; artifactId?: undefined }
    | { key: string; map?: undefined; artifactId: string };

// The classic card's colours, so a map looks the same in both clients.
const MARKER_COLOR = '#0d6efd';
const PATH_COLOR = '#0b5ed7';
const AREA_STROKE_COLOR = '#b02a37';
const AREA_FILL_COLOR = 'rgba(176, 42, 55, 0.20)';
const PATH_WIDTH = 4;

/** Hex, rgb()/rgba() or a plain colour keyword. Anything else falls back to the default. */
const COLOR_PATTERN = /^(?:#[0-9a-f]{3,8}|rgba?\(\s*[\d.]+%?\s*(?:,\s*[\d.]+%?\s*){2,3}\)|[a-z]{3,20})$/i;

// The same limits the Azure Maps action applies when it builds the payload.
const IMAGE_URL_MAX_LENGTH = 2048;
const IMAGE_CAPTION_MAX_LENGTH = 200;
const FIELD_LIMIT = 12;
const FIELD_LABEL_MAX_LENGTH = 60;
const FIELD_VALUE_MAX_LENGTH = 300;

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
        return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
}

function text(value: unknown, fallback = ''): string {
    return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function color(value: unknown, fallback: string): string {
    const candidate = typeof value === 'string' ? value.trim() : '';
    return COLOR_PATTERN.test(candidate) ? candidate : fallback;
}

function clamp(value: number, low: number, high: number): number {
    return Math.min(high, Math.max(low, value));
}

function lonLat(longitude: unknown, latitude: unknown): LonLat | null {
    const lon = finiteNumber(longitude);
    const lat = finiteNumber(latitude);
    if (lon === null || lat === null || Math.abs(lon) > 180 || Math.abs(lat) > 90) {
        return null;
    }
    return [lon, lat];
}

function coordinatePair(raw: unknown): LonLat | null {
    return Array.isArray(raw) && raw.length >= 2 ? lonLat(raw[0], raw[1]) : null;
}

/** A coordinate list, unwrapping the outer ring when a polygon arrives as `[[[lon, lat], ...]]`. */
function coordinateList(raw: unknown): LonLat[] {
    let list = raw;
    if (Array.isArray(list) && Array.isArray(list[0]) && Array.isArray(list[0][0])) {
        list = list[0];
    }
    if (!Array.isArray(list)) {
        return [];
    }
    return list.map(coordinatePair).filter((pair): pair is LonLat => pair !== null);
}

function parseJson(value: unknown): unknown {
    if (typeof value !== 'string') {
        return value;
    }
    try {
        return JSON.parse(value);
    } catch {
        return null;
    }
}

/** The tool result inside a citation, which may be stored as an object or as JSON text. */
function citationResult(citation: unknown): UnknownRecord | null {
    if (!isRecord(citation)) {
        return null;
    }
    if (citation.render_type && citation.map_payload) {
        return citation;
    }
    const result = parseJson(citation.function_result);
    return isRecord(result) ? result : null;
}

/**
 * The tile template if it points at SimpleChat's tile proxy, otherwise null.
 *
 * Tiles are requested by the browser with the user's session, so a template naming any other
 * path or host is refused rather than loaded.
 */
export function safeTileTemplate(value: unknown): string | null {
    const template = typeof value === 'string' ? value.trim() : '';
    if (!template.startsWith(`${TILE_PROXY_PATH}?`)) {
        return null;
    }
    if (/[\s"'<>\\]/.test(template)) {
        return null;
    }
    return ['{z}', '{x}', '{y}'].every((placeholder) => template.includes(placeholder)) ? template : null;
}

/**
 * The image link if it is an absolute https URL, otherwise null.
 *
 * https is the only scheme the chat's image policy loads from another host. A relative path is
 * refused too: it would be requested from SimpleChat with the user's session.
 */
export function safeImageUrl(value: unknown): string | null {
    const candidate = typeof value === 'string' ? value.trim() : '';
    if (!candidate || candidate.length > IMAGE_URL_MAX_LENGTH || /[\s"'<>\\]/.test(candidate)) {
        return null;
    }
    try {
        const parsed = new URL(candidate);
        return parsed.protocol === 'https:' && parsed.hostname ? parsed.href : null;
    } catch {
        return null;
    }
}

function readImage(url: unknown, caption: unknown): MapImage | null {
    const safeUrl = safeImageUrl(url);
    return safeUrl ? { url: safeUrl, caption: text(caption).slice(0, IMAGE_CAPTION_MAX_LENGTH) } : null;
}

function readFields(raw: unknown): MapField[] {
    if (!Array.isArray(raw)) {
        return [];
    }
    const fields: MapField[] = [];
    for (const field of raw) {
        if (!isRecord(field)) {
            continue;
        }
        const value = typeof field.value === 'number' && Number.isFinite(field.value) ? String(field.value) : text(field.value);
        const label = text(field.label);
        if (label && value) {
            fields.push({ label: label.slice(0, FIELD_LABEL_MAX_LENGTH), value: value.slice(0, FIELD_VALUE_MAX_LENGTH) });
        }
        if (fields.length === FIELD_LIMIT) {
            break;
        }
    }
    return fields;
}

function readMarkers(raw: unknown): MapMarker[] {
    if (!Array.isArray(raw)) {
        return [];
    }
    return raw.flatMap((marker): MapMarker[] => {
        if (!isRecord(marker)) {
            return [];
        }
        const point = lonLat(marker.longitude ?? marker.lon ?? marker.lng, marker.latitude ?? marker.lat);
        if (!point) {
            return [];
        }
        return [{
            label: text(marker.label, 'Location'),
            description: text(marker.description),
            color: color(marker.color, MARKER_COLOR),
            lonLat: point,
            image: readImage(marker.image_url, marker.image_caption),
            fields: readFields(marker.fields),
        }];
    });
}

function readPaths(raw: unknown): MapPath[] {
    if (!Array.isArray(raw)) {
        return [];
    }
    return raw.flatMap((path): MapPath[] => {
        if (!isRecord(path)) {
            return [];
        }
        const coordinates = coordinateList(path.coordinates);
        if (coordinates.length < 2) {
            return [];
        }
        const width = finiteNumber(path.line_width ?? path.lineWidth ?? path.width);
        return [{
            label: text(path.label, 'Path'),
            description: text(path.description),
            color: color(path.stroke_color, PATH_COLOR),
            width: width === null ? PATH_WIDTH : clamp(width, 1, 12),
            coordinates,
        }];
    });
}

function readAreas(raw: unknown): MapArea[] {
    if (!Array.isArray(raw)) {
        return [];
    }
    return raw.flatMap((area): MapArea[] => {
        if (!isRecord(area)) {
            return [];
        }
        const coordinates = coordinateList(area.coordinates);
        if (coordinates.length < 3) {
            return [];
        }
        const [first] = coordinates;
        const last = coordinates[coordinates.length - 1];
        if (first[0] !== last[0] || first[1] !== last[1]) {
            coordinates.push([first[0], first[1]]);
        }
        return [{
            label: text(area.label, 'Area'),
            description: text(area.description),
            strokeColor: color(area.stroke_color, AREA_STROKE_COLOR),
            fillColor: color(area.fill_color, AREA_FILL_COLOR),
            coordinates,
        }];
    });
}

function readView(raw: unknown, markers: MapMarker[], paths: MapPath[], areas: MapArea[]): MapView {
    const view = isRecord(raw) ? raw : {};
    const fallbackCenter: LonLat = markers[0]?.lonLat ?? areas[0]?.coordinates[0] ?? paths[0]?.coordinates[0] ?? [0, 20];
    const zoom = finiteNumber(view.zoom);
    const maxZoom = finiteNumber(view.max_zoom);
    const onlyOnePoint = markers.length === 1 && paths.length === 0 && areas.length === 0;
    return {
        center: coordinatePair(view.center) ?? fallbackCenter,
        zoom: zoom === null ? (onlyOnePoint ? 14 : 10) : clamp(zoom, 0, 22),
        maxZoom: maxZoom === null ? 15 : clamp(maxZoom, 1, 22),
        fitToFeatures: view.fit_to_features !== false,
    };
}

/**
 * The map in one agent citation, or null when the citation is not a usable map.
 *
 * A map needs a tile template that points at the tile proxy and at least one marker, path or
 * area, matching the classic client, which draws nothing for an empty map.
 */
export function readInlineMap(citation: unknown): InlineMap | null {
    const result = citationResult(citation);
    if (!result || result.success === false || result.render_type !== AZURE_MAPS_RENDER_TYPE) {
        return null;
    }
    const payload = result.map_payload;
    if (!isRecord(payload)) {
        return null;
    }
    const tileUrlTemplate = safeTileTemplate(payload.tile_url_template);
    if (!tileUrlTemplate) {
        return null;
    }
    const markers = readMarkers(payload.markers);
    const paths = readPaths(payload.paths);
    const areas = readAreas(payload.areas);
    if (markers.length === 0 && paths.length === 0 && areas.length === 0) {
        return null;
    }
    return {
        title: text(payload.title, 'Interactive map'),
        summary: text(payload.summary) || text(result.summary),
        tileUrlTemplate,
        attribution: text(payload.tile_attribution),
        provider: payload.map_provider === 'azure_maps' ? 'Azure Maps' : 'Map',
        sourceActionName: text(payload.source_action_name),
        markers,
        paths,
        areas,
        view: readView(payload.view, markers, paths, areas),
    };
}

/**
 * The artifact holding a map's full result, when the message only stores a compact citation.
 *
 * Large tool results are moved out of the message into artifact records, leaving a citation
 * that names the function and the artifact. Only map functions are fetched, so a long list of
 * other tool calls does not turn into a request per call.
 */
function storedMapArtifactId(citation: unknown): string | null {
    if (!isRecord(citation) || citation.success === false) {
        return null;
    }
    const artifactId = text(citation.artifact_id);
    if (!artifactId) {
        return null;
    }
    const isMapFunction = text(citation.function_name) === MAP_FUNCTION_NAME
        || /azuremaps/i.test(text(citation.plugin_name));
    return isMapFunction ? artifactId : null;
}

/**
 * Every map attached to a message, in citation order.
 *
 * An action called twice with the same arguments returns the same map twice; it is drawn once.
 */
export function collectMapCitations(citations: unknown): MapCitation[] {
    if (!Array.isArray(citations)) {
        return [];
    }
    const seen = new Set<string>();
    const found: MapCitation[] = [];
    citations.forEach((citation, index) => {
        const key = `map-${index}`;
        const map = readInlineMap(citation);
        if (map) {
            const fingerprint = JSON.stringify({ ...map, tileUrlTemplate: '' });
            if (!seen.has(fingerprint)) {
                seen.add(fingerprint);
                found.push({ key, map });
            }
            return;
        }
        const artifactId = storedMapArtifactId(citation);
        if (artifactId) {
            found.push({ key, artifactId });
        }
    });
    return found;
}

/** Counts shown on the card, so the reader knows what the map holds before exploring it. */
export function describeMapContents(map: InlineMap): string[] {
    const counts: Array<[number, string, string]> = [
        [map.markers.length, 'marker', 'markers'],
        [map.paths.length, 'path', 'paths'],
        [map.areas.length, 'area', 'areas'],
    ];
    return counts
        .filter(([count]) => count > 0)
        .map(([count, one, many]) => `${count} ${count === 1 ? one : many}`);
}

/** The prefix of a legacy map block (`AZURE_MAPS_INLINE_BLOCK_PREFIX` in functions_azure_maps.py). */
const LEGACY_MAP_BLOCK_PREFIX = '{{map:';

/**
 * Where a legacy map block ends, or null when the text at `start` is not a complete block.
 *
 * A block is the prefix, a JSON object, then one closing brace. Braces inside JSON strings are
 * skipped, exactly as the server does when it reissues the block's tile token.
 */
function legacyMapBlockEnd(content: string, start: number): number | null {
    const payloadStart = start + LEGACY_MAP_BLOCK_PREFIX.length;
    if (content[payloadStart] !== '{') {
        return null;
    }
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = payloadStart; index < content.length; index += 1) {
        const character = content[index];
        if (inString) {
            if (escaped) {
                escaped = false;
            } else if (character === '\\') {
                escaped = true;
            } else if (character === '"') {
                inString = false;
            }
            continue;
        }
        if (character === '"') {
            inString = true;
        } else if (character === '{') {
            depth += 1;
        } else if (character === '}') {
            depth -= 1;
            if (depth === 0) {
                return content[index + 1] === '}' ? index + 2 : null;
            }
        }
    }
    return null;
}

/**
 * Message text without legacy `{{map:...}}` blocks.
 *
 * Older replies stored the map payload in their text as well as in the tool result. The map is
 * drawn from the tool result, so the block is removed rather than shown as raw JSON, as the
 * classic chat does. Text that only resembles a block is left alone.
 */
export function stripLegacyMapBlocks(content: string): string {
    if (typeof content !== 'string' || !content.includes(LEGACY_MAP_BLOCK_PREFIX)) {
        return content;
    }
    let remaining = '';
    let position = 0;
    let removed = false;
    for (;;) {
        const start = content.indexOf(LEGACY_MAP_BLOCK_PREFIX, position);
        if (start === -1) {
            remaining += content.slice(position);
            break;
        }
        const end = legacyMapBlockEnd(content, start);
        if (end === null) {
            // Not a complete block: keep the text and look for another one after it.
            const next = start + LEGACY_MAP_BLOCK_PREFIX.length;
            remaining += content.slice(position, next);
            position = next;
            continue;
        }
        remaining += content.slice(position, start);
        position = end;
        removed = true;
    }
    return removed ? remaining.replace(/\n{3,}/g, '\n\n').trim() : content;
}
