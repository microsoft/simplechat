// RedisExplorer.tsx
// A read-only browser for Redis keys, inline in the Redis Metrics card.
//
// It answers "what is actually in the cache" while troubleshooting: page through keys with
// Redis SCAN, filter by substring, and open one to see its type, TTL, memory and a
// sanitized preview. SimpleChat recognises its own keys -- the shared settings record, DAI
// scope markers and payloads -- and says what each one is, which a bare hashed key name
// never would.
//
// Previews are sanitized and size-limited by the server, and restricted outright for
// session, token, cookie, credential, password and secret-like keys. Nothing here writes to
// Redis. It loads when opened, not with the page.

import { useCallback, useEffect, useState } from 'react';
import { clsx } from 'clsx';
import { ChevronLeft, ChevronRight, Search, ShieldAlert } from 'lucide-react';
import { ApiError, api } from '../../lib/apiClient';
import { inputClass } from './fields';
import { OpsButton, OpsEmptyState, OpsMessage, OpsNote, Readout, ReadoutGrid } from './OperationalReadouts';
import { formatBytes, formatCount, formatTtl, humanizeStatus, type ToneText } from '../../lib/scaleFormat';
import {
    REDIS_EXPLORER_PAGE_SIZES,
    describePreviewSanitization,
    describeResolutionEntity,
    describeResolutionLabel,
    readRedisExplorerError,
    type RedisExplorerDetailField,
    type RedisExplorerKey,
    type RedisExplorerKeysResponse,
    type RedisExplorerValueResponse,
} from '../../lib/scaleRedis';

const KEYS_PATH = '/api/admin/settings/redis-explorer/keys';
const VALUE_PATH = '/api/admin/settings/redis-explorer/value';

const KEYS_FAILED = 'Failed to load Redis keys.';
const PREVIEW_FAILED = 'Failed to load the key preview.';
const KEYS_DETAIL_FIELDS: readonly RedisExplorerDetailField[] = ['last_error'];
// The classic page reads `preview` only; `last_error` follows it so an unreachable Redis is
// named rather than reported with the generic line.
const PREVIEW_DETAIL_FIELDS: readonly RedisExplorerDetailField[] = ['preview', 'last_error'];

function explorerError(
    error: unknown,
    detailFields: readonly RedisExplorerDetailField[],
    fallback: string,
): string {
    if (error instanceof ApiError) {
        return readRedisExplorerError(error.payload, detailFields, fallback);
    }
    return error instanceof Error ? error.message || fallback : fallback;
}

export function RedisExplorer() {
    const [filterText, setFilterText] = useState('');
    const [appliedFilter, setAppliedFilter] = useState('');
    const [pageSize, setPageSize] = useState<number>(25);
    const [cursor, setCursor] = useState('0');
    const [history, setHistory] = useState<string[]>([]);
    const [page, setPage] = useState<{ keys: RedisExplorerKey[]; nextCursor: string; hasMore: boolean } | null>(null);
    const [loadingKeys, setLoadingKeys] = useState(false);
    const [message, setMessage] = useState<ToneText | null>(null);
    const [selectedKey, setSelectedKey] = useState<string | null>(null);
    const [preview, setPreview] = useState<RedisExplorerValueResponse | null>(null);
    const [loadingPreview, setLoadingPreview] = useState(false);

    const loadKeys = useCallback(
        async (request: { cursor: string; filter: string; pageSize: number }) => {
            setLoadingKeys(true);
            setMessage(null);
            setSelectedKey(null);
            setPreview(null);
            try {
                const query = new URLSearchParams({
                    cursor: request.cursor,
                    page_size: String(request.pageSize),
                    filter: request.filter,
                });
                const response = await api.get<RedisExplorerKeysResponse>(`${KEYS_PATH}?${query.toString()}`);
                if (response.success === false) {
                    throw new Error(readRedisExplorerError(response, KEYS_DETAIL_FIELDS, KEYS_FAILED));
                }
                setPage({
                    keys: response.keys ?? [],
                    nextCursor: String(response.next_cursor ?? '0'),
                    hasMore: Boolean(response.has_more),
                });
            } catch (error) {
                setPage({ keys: [], nextCursor: '0', hasMore: false });
                setMessage({ text: explorerError(error, KEYS_DETAIL_FIELDS, KEYS_FAILED), tone: 'danger' });
            } finally {
                setLoadingKeys(false);
            }
        },
        [],
    );

    // Opening the explorer is the request to browse; there is nothing to show until then.
    useEffect(() => {
        void loadKeys({ cursor: '0', filter: '', pageSize: 25 });
    }, [loadKeys]);

    const startOver = (filter: string, size = pageSize) => {
        setAppliedFilter(filter);
        setCursor('0');
        setHistory([]);
        void loadKeys({ cursor: '0', filter, pageSize: size });
    };

    const goNext = () => {
        if (!page?.hasMore) {
            return;
        }
        setHistory((previous) => [...previous, cursor]);
        setCursor(page.nextCursor);
        void loadKeys({ cursor: page.nextCursor, filter: appliedFilter, pageSize });
    };

    const goPrevious = () => {
        const previousCursor = history[history.length - 1] ?? '0';
        setHistory((previous) => previous.slice(0, -1));
        setCursor(previousCursor);
        void loadKeys({ cursor: previousCursor, filter: appliedFilter, pageSize });
    };

    const openKey = async (key: string) => {
        setSelectedKey(key);
        setLoadingPreview(true);
        setMessage(null);
        try {
            const value = await api.post<RedisExplorerValueResponse>(VALUE_PATH, { key });
            if (value.success === false) {
                throw new Error(readRedisExplorerError(value, PREVIEW_DETAIL_FIELDS, PREVIEW_FAILED));
            }
            setPreview(value);
            if (value.truncated) {
                setMessage({ text: 'The preview is truncated to the safe display limit.', tone: 'warn' });
            }
        } catch (error) {
            setPreview(null);
            setMessage({ text: explorerError(error, PREVIEW_DETAIL_FIELDS, PREVIEW_FAILED), tone: 'danger' });
        } finally {
            setLoadingPreview(false);
        }
    };

    const scope = appliedFilter ? `Filter “${appliedFilter}”` : 'All keys';
    const pageNumber = history.length + 1;

    return (
        <div className="space-y-3" data-testid="redis-explorer">
            <OpsNote icon={ShieldAlert}>
                Read-only. Previews are sanitized, and restricted for session, token, cookie,
                credential, password and secret-like keys. Use it to troubleshoot cache behavior, not
                to export data.
            </OpsNote>

            <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                    event.preventDefault();
                    startOver(filterText.trim());
                }}
            >
                <div className="min-w-48 flex-1">
                    <label htmlFor="redis-explorer-filter" className="mb-1 block text-xs text-text-2">
                        Key filter
                    </label>
                    <input
                        id="redis-explorer-filter"
                        type="search"
                        value={filterText}
                        onChange={(event) => setFilterText(event.target.value)}
                        placeholder="Substring, case sensitive, e.g. APP_SETTINGS_STATE_V2"
                        autoComplete="off"
                        spellCheck={false}
                        className={clsx(inputClass, 'font-mono text-xs')}
                    />
                </div>
                <div>
                    <label htmlFor="redis-explorer-page-size" className="mb-1 block text-xs text-text-2">
                        Page size
                    </label>
                    <select
                        id="redis-explorer-page-size"
                        value={pageSize}
                        onChange={(event) => {
                            const size = Number(event.target.value);
                            setPageSize(size);
                            startOver(appliedFilter, size);
                        }}
                        className={clsx(inputClass, 'w-24')}
                    >
                        {REDIS_EXPLORER_PAGE_SIZES.map((size) => (
                            <option key={size} value={size}>
                                {size}
                            </option>
                        ))}
                    </select>
                </div>
                <OpsButton type="submit" icon={Search} tone="primary" busy={loadingKeys}>
                    Apply filter
                </OpsButton>
                <OpsButton
                    disabled={loadingKeys}
                    onClick={() => {
                        setFilterText('');
                        startOver('');
                    }}
                >
                    Browse all
                </OpsButton>
            </form>

            <OpsMessage message={message} />

            <div className="grid min-w-0 overflow-hidden rounded-xl border border-edge-strong bg-surface-solid @3xl:h-[clamp(22rem,56vh,36rem)] @3xl:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
                <div className="flex min-h-0 min-w-0 flex-col border-b border-edge-strong @3xl:border-r @3xl:border-b-0">
                    <div className="flex items-center justify-between gap-2 border-b border-edge px-3 py-2 text-xs text-text-3">
                        <span className="min-w-0 truncate">
                            {scope} · Page {pageNumber}
                        </span>
                        <span className="shrink-0 tabular-nums">
                            {page ? `${formatCount(page.keys.length)} key${page.keys.length === 1 ? '' : 's'}${page.hasMore ? ' · more' : ''}` : ''}
                        </span>
                    </div>
                    <ul aria-label="Redis keys" className="max-h-[22rem] min-h-0 flex-1 divide-y divide-edge overflow-y-auto @3xl:max-h-none">
                        {page && !page.keys.length && !loadingKeys ? (
                            <li className="px-3 py-4 text-xs text-text-3">
                                No keys on this page{appliedFilter ? ' match the filter' : ''}. SCAN order is decided
                                by Redis, so the next page may still have matches.
                            </li>
                        ) : null}
                        {(page?.keys ?? []).map((item) => {
                            const selected = item.key === selectedKey;
                            const resolution = describeResolutionLabel(item.resolution);
                            return (
                                <li key={item.key}>
                                    <button
                                        type="button"
                                        aria-pressed={selected}
                                        onClick={() => void openKey(item.key)}
                                        className={clsx(
                                            'block w-full px-3 py-2 text-left transition-colors',
                                            selected ? 'bg-accent-soft' : 'hover:bg-surface-2',
                                        )}
                                    >
                                        <span className="block font-mono text-xs break-all text-text-1">
                                            {item.key || '(empty key)'}
                                        </span>
                                        <span className="mt-0.5 block text-[0.6875rem] text-text-3">
                                            {humanizeStatus(item.type || 'unknown')} · TTL {formatTtl(item.ttl_seconds)}
                                            {item.preview_restricted ? ' · restricted' : ''}
                                        </span>
                                        {resolution ? (
                                            <span className="mt-0.5 block text-[0.6875rem] text-accent">{resolution}</span>
                                        ) : null}
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                    <div className="flex items-center justify-between gap-2 border-t border-edge px-3 py-2">
                        <OpsButton icon={ChevronLeft} disabled={!history.length || loadingKeys} onClick={goPrevious}>
                            Previous
                        </OpsButton>
                        <OpsButton disabled={!page?.hasMore || loadingKeys} onClick={goNext}>
                            Next
                            <ChevronRight size={13} aria-hidden="true" />
                        </OpsButton>
                    </div>
                </div>

                <div className="min-h-0 min-w-0 space-y-3 overflow-y-auto p-3" aria-live="polite">
                    {!selectedKey ? (
                        <OpsEmptyState title="Select a key">
                            Its type, TTL, memory and a sanitized preview appear here.
                        </OpsEmptyState>
                    ) : loadingPreview ? (
                        <p className="text-xs text-text-3">Loading the preview…</p>
                    ) : preview ? (
                        <>
                            <p className="font-mono text-xs break-all text-text-1">{preview.key || selectedKey}</p>
                            <ReadoutGrid className="@4xl:grid-cols-4">
                                <Readout label="Type" value={humanizeStatus(preview.type || 'unknown')} />
                                <Readout label="TTL" value={formatTtl(preview.ttl_seconds)} />
                                <Readout label="Memory" value={formatBytes(preview.memory_usage_bytes)} />
                                <Readout label="Sanitization" value={describePreviewSanitization(preview)} />
                            </ReadoutGrid>
                            {preview.resolution ? (
                                <div className="rounded-lg border border-edge bg-surface-1 px-3 py-2 text-xs">
                                    <p className="font-semibold text-text-1">
                                        {preview.resolution.label || humanizeStatus(preview.resolution.kind)}
                                    </p>
                                    <p className="mt-0.5 text-text-2">{describeResolutionEntity(preview.resolution)}</p>
                                    {preview.resolution.scope_key || preview.resolution.cache_hash || preview.resolution.scope_hash ? (
                                        <p className="mt-0.5 font-mono break-all text-text-3">
                                            {preview.resolution.scope_key ||
                                                preview.resolution.cache_hash ||
                                                preview.resolution.scope_hash}
                                        </p>
                                    ) : null}
                                    {preview.resolution.note ? (
                                        <p className="mt-1 text-text-3">{preview.resolution.note}</p>
                                    ) : null}
                                </div>
                            ) : null}
                            <div>
                                <p className="mb-1 text-xs text-text-2">Sanitized preview</p>
                                <pre
                                    tabIndex={0}
                                    aria-label="Sanitized preview"
                                    className="max-h-80 overflow-auto rounded-lg border border-edge bg-surface-sunken p-3 font-mono text-xs break-all whitespace-pre-wrap text-text-1"
                                >
                                    {preview.preview || 'No preview available.'}
                                </pre>
                            </div>
                        </>
                    ) : null}
                </div>
            </div>
        </div>
    );
}
