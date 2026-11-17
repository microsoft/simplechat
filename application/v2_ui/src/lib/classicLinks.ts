// classicLinks.ts
// Where V2 and the classic interface meet in the address bar. Pure functions over the page route
// registry the server also reads (generated/uiRouteMap.ts), so they run without a browser.
//
// Two jobs.
//
// 1. A classic URL is redirected to V2 by the server (functions_ui_redirect.py), which maps the path
//    and the query string. A server never sees the part after `#`, but a browser keeps it across a
//    redirect, so `/workspace#documents-tab` arrives here as `/v2/workspace#documents-tab`.
//    `translateClassicFragment` says which V2 address that fragment names, and answers null for any
//    fragment the registry does not list, so the app replaces the address once and leaves the rest alone.
//
// 2. "Open this page in classic" needs the classic address of the V2 page on screen.
//    `classicHrefFor` is the TypeScript twin of `resolve_classic_target` in ui_routing.py, and
//    functional_tests/test_v2_classic_links.py holds the two to the same answers, row by row.
//    `withClassicEscape` adds `ui=classic`, which tells the server's redirect to serve the classic page
//    instead of sending the visitor straight back.
//
// Every address built here is a same-site absolute path made from registry data and validated path
// segments. Nothing the address bar supplies is echoed except encoded query values and segments that
// passed the same checks the server applies.

import {
    UI_ROUTE_MAP,
    UI_ROUTE_RESOLVABLE_STATUSES,
    UI_ROUTE_V2_BASE_PATH,
    type UiRouteEntry,
    type UiRouteQueryRule,
    type UiRouteStatus,
} from './generated/uiRouteMap';
import { classicChatHref } from './conversationUrl';

/** The query pair that asks the server to serve the classic page. */
export const CLASSIC_ESCAPE_PARAM = 'ui';
export const CLASSIC_ESCAPE_VALUE = 'classic';

const MAX_PATH_LENGTH = 2048;
const MAX_SEGMENT_LENGTH = 256;
const MAX_QUERY_LENGTH = 4096;
const MAX_QUERY_FIELDS = 64;
const MAX_QUERY_VALUE_LENGTH = 1024;
const MAX_FRAGMENT_LENGTH = 256;

const CLASSIC_TOKEN_RE = /<(?:[a-z_]+:)?([A-Za-z_][A-Za-z0-9_]*)>/g;
const FRAGMENT_KEY_RE = /^[A-Za-z0-9_.:~-]{1,128}$/;
/** A path segment this module is willing to copy: unreserved characters and percent escapes. */
const SAFE_SEGMENT_RE = /^(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+$/;
/** Escapes that change what a path means once decoded: dot, slash, backslash and controls. */
const FORBIDDEN_ESCAPE_RE = /%(?:2e|2f|5c|[01][0-9a-f]|7f)/i;

interface V2Pattern {
    segments: ReadonlyArray<{ param: boolean; text: string }>;
    literalCount: number;
    paramCount: number;
}

interface ReverseQueryRule {
    classicKey: string;
    /** V2 value to classic value. Absent when the key is carried as it is. */
    values?: ReadonlyMap<string, string>;
    localPath: boolean;
}

type ReverseSuffix =
    | { segments: readonly string[]; kind: 'hash'; fragment: string }
    | { segments: readonly string[]; kind: 'query'; key: string; value: string };

interface IndexedRoute {
    order: number;
    entry: UiRouteEntry;
    /** The classic rule's placeholders, in order. */
    classicParams: readonly string[];
    /** The main V2 route first, then its subroutes. */
    patterns: readonly V2Pattern[];
    reverseQuery: ReadonlyMap<string, ReverseQueryRule>;
    reverseSuffixes: readonly ReverseSuffix[];
    reverseHashQueries: ReadonlyArray<{ required: ReadonlyArray<readonly [string, string]>; fragment: string }>;
}

export interface ClassicTarget {
    /** The classic address: path, query string and fragment. */
    path: string;
    key: string;
    status: UiRouteStatus;
}

export interface V2Location {
    /** Relative to the router's /v2 basename, as `useLocation().pathname` reads. */
    pathname: string;
    /** Empty, or a query string with its leading `?`. */
    search: string;
}

// ---------------------------------------------------------------------------
// Input hygiene (the twin of the helpers in ui_routing.py)
// ---------------------------------------------------------------------------

function hasControl(text: string): boolean {
    for (let index = 0; index < text.length; index += 1) {
        const code = text.charCodeAt(index);
        if (code < 0x20 || code === 0x7f) return true;
    }
    return false;
}

/** The path when it is a plain same-site path this module may act on, else null. */
function cleanRequestPath(path: unknown): string | null {
    if (typeof path !== 'string' || path.length === 0 || path.length > MAX_PATH_LENGTH) return null;
    if (path[0] !== '/' || path.startsWith('//')) return null;
    if (path.includes('\\') || path.includes('?') || path.includes('#') || hasControl(path)) return null;
    if (FORBIDDEN_ESCAPE_RE.test(path)) return null;
    if (path !== '/') {
        const dotSegment = path.slice(1).split('/').some((segment) => segment === '' || segment === '.' || segment === '..');
        if (dotSegment) return null;
    }
    return path;
}

function isSafeSegment(value: unknown): value is string {
    return typeof value === 'string'
        && value.length > 0
        && value.length <= MAX_SEGMENT_LENGTH
        && value !== '.'
        && value !== '..'
        && SAFE_SEGMENT_RE.test(value)
        && !FORBIDDEN_ESCAPE_RE.test(value);
}

/** Final check on every address returned: one leading '/', no backslash, no controls, no spaces. */
function isSafeOutput(path: string): boolean {
    return path.startsWith('/')
        && path[1] !== '/'
        && path[1] !== '\\'
        && !path.includes('\\')
        && !hasControl(path)
        && !path.includes(' ');
}

/** A router path from either a router path or a full `/v2/...` path, without a trailing slash. */
function normalizeV2Path(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    let text = value;
    if (text === UI_ROUTE_V2_BASE_PATH || text.startsWith(`${UI_ROUTE_V2_BASE_PATH}/`)) {
        text = text.slice(UI_ROUTE_V2_BASE_PATH.length) || '/';
    }
    if (text.length > 1 && text.endsWith('/')) text = text.slice(0, -1);
    return cleanRequestPath(text);
}

function splitPath(path: string): string[] {
    return path === '/' ? [] : path.slice(1).split('/');
}

/** The first value of each query key, in order; null when the query is unusable. */
function parseQuery(search: string): Map<string, string> | null {
    const text = search.startsWith('?') ? search.slice(1) : search;
    if (text.length > MAX_QUERY_LENGTH) return null;
    const first = new Map<string, string>();
    if (!text) return first;
    if (text.split('&').length > MAX_QUERY_FIELDS) return null;
    for (const [key, value] of new URLSearchParams(text)) {
        if (!first.has(key)) first.set(key, value);
    }
    return first;
}

function cleanQueryValue(value: string, localPath: boolean): string | null {
    if (!value || value.length > MAX_QUERY_VALUE_LENGTH || hasControl(value)) return null;
    if (localPath && (!value.startsWith('/') || value[1] === '/' || value[1] === '\\' || value.includes('\\'))) {
        return null;
    }
    return value;
}

/** Percent-encoding exactly as Python's `urllib.parse.quote` does it, so both sides write one address. */
function quote(text: string): string {
    return encodeURIComponent(text).replace(
        /[!'()*]/g,
        (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
    );
}

function encodePairs(pairs: ReadonlyMap<string, string>): string | null {
    try {
        return [...pairs].map(([key, value]) => `${quote(key)}=${quote(value)}`).join('&');
    } catch {
        // A lone surrogate cannot be encoded; an address like that is not one this module writes.
        return null;
    }
}

/** The name a `hash_map` entry is looked up by; empty when the fragment is not a usable name. */
function cleanFragment(hash: unknown): string {
    if (typeof hash !== 'string') return '';
    const text = hash.startsWith('#') ? hash.slice(1) : hash;
    if (!text || text.length > MAX_FRAGMENT_LENGTH) return '';
    let decoded = text;
    if (decoded.includes('%')) {
        try {
            decoded = decodeURIComponent(decoded);
        } catch {
            return '';
        }
    }
    return FRAGMENT_KEY_RE.test(decoded) ? decoded : '';
}

// ---------------------------------------------------------------------------
// The registry, indexed once
// ---------------------------------------------------------------------------

function parsePattern(text: string): V2Pattern {
    const segments = splitPath(text).map((segment) => (
        segment.startsWith(':') ? { param: true, text: segment.slice(1) } : { param: false, text: segment }
    ));
    return {
        segments,
        literalCount: segments.filter((segment) => !segment.param).length,
        paramCount: segments.filter((segment) => segment.param).length,
    };
}

function indexRoute(entry: UiRouteEntry, order: number): IndexedRoute {
    const classicParams = [...entry.classic.matchAll(CLASSIC_TOKEN_RE)].map((match) => match[1]);
    const patterns = entry.v2 === null
        ? []
        : [entry.v2, ...(entry.v2_subroutes ?? [])].map(parsePattern);

    const reverseQuery = new Map<string, ReverseQueryRule>();
    for (const [classicKey, spec] of Object.entries(entry.query_map ?? {})) {
        const rule: UiRouteQueryRule = typeof spec === 'string' ? { to: spec } : spec;
        if (rule.path !== undefined || rule.to === undefined || reverseQuery.has(rule.to)) continue;
        let values: Map<string, string> | undefined;
        if (rule.values !== undefined) {
            values = new Map();
            for (const [classicValue, v2Value] of Object.entries(rule.values)) {
                if (!values.has(v2Value)) values.set(v2Value, classicValue);
            }
        }
        reverseQuery.set(rule.to, { classicKey, values, localPath: rule.local_path === true });
    }

    const reverseSuffixes: ReverseSuffix[] = [];
    const reverseHashQueries: Array<{ required: Array<readonly [string, string]>; fragment: string }> = [];
    for (const [fragment, rule] of Object.entries(entry.hash_map ?? {})) {
        if (rule.path !== undefined) {
            reverseSuffixes.push({ segments: splitPath(rule.path), kind: 'hash', fragment });
        } else if (rule.query !== undefined) {
            reverseHashQueries.push({ required: Object.entries(rule.query), fragment });
        }
    }
    for (const [classicKey, spec] of Object.entries(entry.query_map ?? {})) {
        if (typeof spec === 'string' || spec.path === undefined) continue;
        for (const [classicValue, suffix] of Object.entries(spec.path)) {
            reverseSuffixes.push({ segments: splitPath(suffix), kind: 'query', key: classicKey, value: classicValue });
        }
    }

    return { order, entry, classicParams, patterns, reverseQuery, reverseSuffixes, reverseHashQueries };
}

let routeIndexCache: readonly IndexedRoute[] | null = null;

function routeIndex(): readonly IndexedRoute[] {
    if (routeIndexCache === null) {
        routeIndexCache = UI_ROUTE_MAP.map(indexRoute);
    }
    return routeIndexCache;
}

function isResolvable(route: IndexedRoute): boolean {
    return route.entry.v2 !== null && UI_ROUTE_RESOLVABLE_STATUSES.includes(route.entry.status);
}

/** Whole-path match of a V2 pattern; returns the parameter values, or null. */
function matchPattern(
    pattern: V2Pattern,
    segments: readonly string[],
    reserved: UiRouteEntry['v2_reserved'],
): Record<string, string> | null {
    if (pattern.segments.length !== segments.length) return null;
    const values: Record<string, string> = {};
    for (let index = 0; index < segments.length; index += 1) {
        const { param, text } = pattern.segments[index];
        const segment = segments[index];
        if (!param) {
            if (segment !== text) return null;
            continue;
        }
        if (!isSafeSegment(segment) || (reserved?.[text] ?? []).includes(segment)) return null;
        values[text] = segment;
    }
    return values;
}

function renderRoutePath(pattern: V2Pattern, values: Readonly<Record<string, string>>, suffix: string): string {
    // Validated segments only hold unreserved characters and existing percent escapes, so they are
    // copied as they are: encoding them again would turn `%20` into `%2520`.
    const parts = pattern.segments.map((segment) => (segment.param ? values[segment.text] : segment.text));
    const routePath = (parts.length ? `/${parts.join('/')}` : '') + suffix;
    return routePath || '/';
}

function renderClassicPath(entry: UiRouteEntry, values: Readonly<Record<string, string>>): string {
    return entry.classic.replace(CLASSIC_TOKEN_RE, (_token, name: string) => values[name]);
}

// ---------------------------------------------------------------------------
// V2 -> classic
// ---------------------------------------------------------------------------

interface BestRoute {
    rank: readonly [number, number, number];
    route: IndexedRoute;
    classicValues: Record<string, string>;
}

/**
 * The classic version of a V2 address, or null when it has no classic page.
 *
 * `pathname` is a router path (`/groups/abc/members`) or the same path under `/v2`. It may be deeper
 * than a row's main route: a row lists the other V2 routes that are the same classic page in
 * `v2_subroutes`, and anything else under a page's prefix is not guessed at. The result's `path` is the
 * classic address with its query string and fragment, for example `/workspace#documents-tab`.
 *
 * Alias rows only go forward (`/profile?tab=groups` is the classic address of that V2 page, not
 * `/my_groups`), rows that do not resolve have no V2 page to come from, and V2-only pages such as
 * `/groups/directory` have no answer. `hash` is accepted for symmetry with the server resolver and
 * ignored: V2 addresses sections with paths and query keys, never fragments.
 */
export function classicHrefFor(pathname: string, search = '', hash = ''): ClassicTarget | null {
    void hash;
    const clean = normalizeV2Path(pathname);
    if (clean === null) return null;
    const segments = splitPath(clean);

    let best: BestRoute | null = null;
    for (const route of routeIndex()) {
        if (!isResolvable(route) || route.entry.status === 'alias') continue;
        for (const pattern of route.patterns) {
            const values = matchPattern(pattern, segments, route.entry.v2_reserved);
            if (values === null) continue;
            const classicValues: Record<string, string> = {};
            let complete = true;
            for (const classicName of route.classicParams) {
                const v2Name = route.entry.path_params?.[classicName];
                const value = v2Name === undefined ? undefined : values[v2Name];
                if (value === undefined) {
                    complete = false;
                    break;
                }
                classicValues[classicName] = value;
            }
            if (!complete) continue;
            const rank = [pattern.literalCount, -pattern.paramCount, -route.order] as const;
            if (best === null || compareRank(rank, best.rank) > 0) {
                best = { rank, route, classicValues };
            }
        }
    }
    if (best === null) return null;
    const { route, classicValues } = best;

    const v2Pairs = parseQuery(search);
    if (v2Pairs === null) return null;
    const classicPairs = new Map<string, string>();
    for (const [v2Key, value] of v2Pairs) {
        const rule = route.reverseQuery.get(v2Key);
        if (rule === undefined) continue;
        let cleaned = cleanQueryValue(value, rule.localPath);
        if (cleaned === null) continue;
        if (rule.values !== undefined) {
            const translated = rule.values.get(cleaned);
            if (translated === undefined) continue;
            cleaned = translated;
        }
        if (!classicPairs.has(rule.classicKey)) classicPairs.set(rule.classicKey, cleaned);
    }

    const tail = segments.slice(route.patterns[0].segments.length);
    let suffix: ReverseSuffix | null = null;
    for (const candidate of route.reverseSuffixes) {
        const matches = candidate.segments.every((segment, index) => tail[index] === segment);
        if (matches && (suffix === null || candidate.segments.length > suffix.segments.length)) {
            suffix = candidate;
        }
    }
    let classicFragment = '';
    if (suffix !== null) {
        if (suffix.kind === 'hash') {
            classicFragment = suffix.fragment;
        } else if (!classicPairs.has(suffix.key)) {
            classicPairs.set(suffix.key, suffix.value);
        }
    }
    if (!classicFragment) {
        const named = route.reverseHashQueries.find(
            ({ required }) => required.every(([key, value]) => v2Pairs.get(key) === value),
        );
        if (named !== undefined) classicFragment = named.fragment;
    }

    let path = renderClassicPath(route.entry, classicValues);
    if (classicPairs.size) {
        const encoded = encodePairs(classicPairs);
        if (encoded === null) return null;
        path += `?${encoded}`;
    }
    if (classicFragment) path += `#${classicFragment}`;
    if (!isSafeOutput(path)) return null;
    return { path, key: route.entry.key, status: route.entry.status };
}

function compareRank(left: readonly number[], right: readonly number[]): number {
    for (let index = 0; index < left.length; index += 1) {
        if (left[index] !== right[index]) return left[index] - right[index];
    }
    return 0;
}

/**
 * A classic address with the escape pair added, so the server serves the classic page.
 *
 * Without it, a server that has selected the modern interface answers the classic address with a
 * redirect straight back to V2. The classic interface ignores the pair, so adding it is always safe.
 * Any `ui` pair already in the query is replaced, and the fragment stays where it is.
 *
 * Only a same-site absolute path is ever extended. Anything else (a scheme, a protocol-relative
 * address, a backslash, a control character) becomes the classic chat page, so no caller can make
 * this a way to put a foreign address in an anchor.
 */
export function withClassicEscape(href: string): string {
    const safe = typeof href === 'string' && isSafeOutput(href) ? href : classicChatHref(null);
    const hashIndex = safe.indexOf('#');
    const fragment = hashIndex === -1 ? '' : safe.slice(hashIndex);
    const beforeFragment = hashIndex === -1 ? safe : safe.slice(0, hashIndex);
    const queryIndex = beforeFragment.indexOf('?');
    const path = queryIndex === -1 ? beforeFragment : beforeFragment.slice(0, queryIndex);
    const query = queryIndex === -1 ? '' : beforeFragment.slice(queryIndex + 1);
    const kept = query.split('&').filter((pair) => pair !== '' && pair.split('=')[0] !== CLASSIC_ESCAPE_PARAM);
    kept.push(`${CLASSIC_ESCAPE_PARAM}=${CLASSIC_ESCAPE_VALUE}`);
    return `${path}?${kept.join('&')}${fragment}`;
}

/**
 * Where "Back to classic UI" goes from the V2 page on screen.
 *
 * The chat page carries the open conversation across, as the link always has, since both interfaces
 * read the same parameter and crossing over otherwise lands on the conversation list. Any other page
 * that has a classic counterpart goes to it (a settings tab to `/profile?tab=...`, a group to its
 * manage page, a workspace section to its tab); a page with none, such as the group directory, falls
 * back to the classic chat page with the open conversation, as before. Every address carries the
 * escape pair.
 */
export function classicBackHref(
    pathname: string,
    search: string,
    hash: string,
    activeConversationId: string | null,
): string {
    const clean = normalizeV2Path(pathname);
    if (clean !== '/chat') {
        const target = classicHrefFor(pathname, search, hash);
        if (target !== null) return withClassicEscape(target.path);
    }
    return withClassicEscape(classicChatHref(activeConversationId));
}

// ---------------------------------------------------------------------------
// Classic fragment -> V2
// ---------------------------------------------------------------------------

/**
 * The V2 address a classic fragment names for the V2 page at `pathname`, or null.
 *
 * Only a fragment listed in the page's `hash_map` counts, and only on the row's main route (a deeper
 * route already says which section it is). A fragment that names a route segment appends it
 * (`#documents-tab` on `/workspace` opens `/workspace/documents`); one that names query values sets
 * them over any value the address already had (`#m365-chat-connection` on `/settings` opens
 * `/settings?tab=preferences&section=m365-chat-connection`). The answer never carries a fragment, so
 * replacing the address with it is done once.
 */
export function translateClassicFragment(pathname: string, search: string, hash: string): V2Location | null {
    const fragment = cleanFragment(hash);
    if (!fragment) return null;
    const clean = normalizeV2Path(pathname);
    if (clean === null) return null;
    const segments = splitPath(clean);

    for (const route of routeIndex()) {
        if (!isResolvable(route) || !Object.hasOwn(route.entry.hash_map ?? {}, fragment)) continue;
        const rule = route.entry.hash_map?.[fragment];
        const values = matchPattern(route.patterns[0], segments, route.entry.v2_reserved);
        if (rule === undefined || values === null) continue;

        const pairs = parseQuery(search);
        if (pairs === null) return null;
        for (const [key, value] of Object.entries(rule.query ?? {})) pairs.set(key, value);
        const encoded = encodePairs(pairs);
        if (encoded === null) return null;
        const location = {
            pathname: renderRoutePath(route.patterns[0], values, rule.path ?? ''),
            search: encoded ? `?${encoded}` : '',
        };
        return isSafeOutput(location.pathname) ? location : null;
    }
    return null;
}
