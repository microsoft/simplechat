// McpDestinationPatternField.tsx
// Builds the destination pattern an MCP destination policy stores as its item.
//
// The classic editor took the pattern as free text with examples beside it, so a typo saved
// without complaint and then quietly allowed nothing: `transport:streamable-http`, which the
// classic examples suggested, never matches, because transports are stored with an
// underscore. Here the kind of pattern is chosen first, ids and transports are picked from
// what the server actually loads, and the stored value is shown before it is saved.

import { useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, AlertTriangle, Info, Loader2, Search } from 'lucide-react';
import {
    buildMcpDestinationItemId,
    checkMcpDestinationPattern,
    mcpScopeOf,
    searchPrincipals,
    type GovernanceEntityType,
    type McpDestinationCatalog,
    type McpPatternKind,
    type McpPatternParts,
    type PrincipalEntry,
} from '../../../lib/governance';
import { usePrincipalLabels } from './usePrincipalLabels';

const KIND_OPTIONS: { value: McpPatternKind; label: string; hint: string }[] = [
    {
        value: 'preconfiguration',
        label: 'A preconfigured server',
        hint: 'One template from the MCP catalog. Enterprise templates only appear when a policy names them this way.',
    },
    { value: 'host', label: 'A host name', hint: 'Every endpoint on a host. * matches any run of characters.' },
    { value: 'url', label: 'A URL prefix', hint: 'One endpoint, or every path under it when the URL ends in *.' },
    { value: 'preset', label: 'A server preset', hint: 'Every server built from one preset, such as the generic preset.' },
    { value: 'transport', label: 'A transport', hint: 'Every server reached over one transport.' },
    { value: 'any', label: 'Any remote server (*)', hint: 'Everything in this scope. Use it sparingly.' },
];

const inputClass =
    'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none disabled:opacity-60';

function GroupTargetPicker({
    groupId,
    onChange,
    disabled,
}: {
    groupId: string;
    onChange: (next: string) => void;
    disabled?: boolean;
}) {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<PrincipalEntry[] | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [searching, setSearching] = useState(false);
    const labels = usePrincipalLabels('groups', groupId ? [groupId] : []);
    const lookup = groupId ? labels.lookup(groupId) : undefined;

    useEffect(() => {
        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            setSearching(true);
            void searchPrincipals('groups', query, controller.signal)
                .then((page) => {
                    if (!controller.signal.aborted) {
                        // Group destinations govern group workspace actions, so a public
                        // workspace is not a meaningful target here.
                        setResults(page.entries.filter((entry) => entry.kind !== 'public_workspace'));
                        setError(null);
                    }
                })
                .catch(() => {
                    if (!controller.signal.aborted) {
                        setResults([]);
                        setError('Groups could not be searched.');
                    }
                })
                .finally(() => {
                    if (!controller.signal.aborted) {
                        setSearching(false);
                    }
                });
        }, 300);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [query]);

    return (
        <div className="space-y-2">
            <p className="text-xs text-text-2">
                {groupId ? (
                    <>
                        Applies to{' '}
                        <span className="font-medium text-text-1">
                            {lookup?.status === 'found' ? lookup.entry.name || groupId : groupId}
                        </span>
                        {lookup?.status === 'missing' ? <span className="text-warn"> (not found)</span> : null}
                    </>
                ) : (
                    'Choose the group this policy applies to.'
                )}
            </p>
            <div className="relative">
                <Search size={14} aria-hidden="true" className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-text-3" />
                <input
                    type="search"
                    value={query}
                    disabled={disabled}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search groups by name or ID"
                    aria-label="Search groups for this destination policy"
                    className={clsx(inputClass, 'pl-8')}
                />
            </div>
            {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
            {searching && results === null ? (
                <p className="flex items-center gap-1.5 text-xs text-text-3">
                    <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                    Loading groups…
                </p>
            ) : null}
            {results && results.length ? (
                <ul className="max-h-40 divide-y divide-edge overflow-y-auto rounded-lg border border-edge" aria-label="Matching groups">
                    {results.map((entry) => (
                        <li key={entry.id}>
                            <button
                                type="button"
                                disabled={disabled}
                                aria-pressed={entry.id === groupId}
                                onClick={() => onChange(entry.id)}
                                className={clsx(
                                    'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors',
                                    entry.id === groupId ? 'bg-accent-soft text-accent' : 'text-text-1 hover:bg-surface-2',
                                )}
                            >
                                <span className="min-w-0 flex-1 truncate">{entry.name || entry.id}</span>
                                <span className="shrink-0 font-mono text-[11px] text-text-3">{entry.id.slice(0, 8)}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            ) : null}
            {results && !results.length && !error ? (
                <p className="text-xs text-text-3">{query.trim() ? `No groups match “${query.trim()}”.` : 'No groups exist yet.'}</p>
            ) : null}
        </div>
    );
}

export function McpDestinationPatternField({
    entityType,
    parts,
    onChange,
    catalog,
    catalogState,
    disabled,
    showIncomplete = false,
    idPrefix,
}: {
    entityType: GovernanceEntityType;
    parts: McpPatternParts;
    onChange: (next: McpPatternParts) => void;
    catalog: McpDestinationCatalog | null;
    catalogState: 'loading' | 'ready' | 'failed';
    disabled?: boolean;
    /** Report a blank value or unpicked group too, once a save has been attempted. */
    showIncomplete?: boolean;
    idPrefix: string;
}) {
    const isGroupScope = entityType === 'mcp_group_destination';
    // `groupId` undefined means every group; an empty string means "one group, not picked yet",
    // which the check reports so the policy cannot be saved for every group by accident.
    const groupSpecific = isGroupScope && parts.groupId !== undefined;
    const scope = mcpScopeOf(entityType);
    const transports = catalog?.transports ?? [];
    const check = checkMcpDestinationPattern(parts, transports.length ? transports : undefined, groupSpecific);
    const stored = buildMcpDestinationItemId(parts, entityType);
    const kindOption = KIND_OPTIONS.find((option) => option.value === parts.kind) ?? KIND_OPTIONS[0];
    // A blank value or an unpicked group is the starting state, not a mistake: the inputs already
    // ask for them, and they are reported here once a save has been attempted. Something entered
    // that cannot match is flagged as it is typed.
    const incomplete = (parts.kind !== 'any' && !parts.value.trim()) || (groupSpecific && !parts.groupId?.trim());
    const fieldError = incomplete && !showIncomplete ? undefined : check.error;

    const preconfigurations = useMemo(
        () => (catalog?.preconfigurations ?? []).filter(
            (entry) => !scope || !entry.scopes.length || entry.scopes.includes(scope),
        ),
        [catalog, scope],
    );
    const selectedPreconfiguration = catalog?.preconfigurations.find((entry) => entry.id === parts.value);

    const setKind = (kind: McpPatternKind) => onChange({ ...parts, kind, value: '' });
    const setValue = (value: string) => onChange({ ...parts, value });

    const catalogSelect = (
        options: { id: string; label: string }[],
        placeholder: string,
        ariaLabel: string,
    ) => {
        if (catalogState === 'loading') {
            return (
                <p className="flex items-center gap-1.5 py-2 text-xs text-text-3">
                    <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                    Loading the MCP catalog…
                </p>
            );
        }
        if (catalogState === 'failed' || !options.length) {
            // The id can still be typed when the catalog is unavailable.
            return (
                <input
                    type="text"
                    value={parts.value}
                    disabled={disabled}
                    onChange={(event) => setValue(event.target.value)}
                    placeholder={placeholder}
                    aria-label={ariaLabel}
                    className={clsx(inputClass, 'font-mono')}
                />
            );
        }
        const known = options.some((option) => option.id === parts.value);
        return (
            <select
                value={known ? parts.value : ''}
                disabled={disabled}
                onChange={(event) => setValue(event.target.value)}
                aria-label={ariaLabel}
                className={inputClass}
            >
                <option value="">{parts.value && !known ? `${parts.value} (not in the catalog)` : 'Choose…'}</option>
                {options.map((option) => (
                    <option key={option.id} value={option.id}>
                        {option.label} ({option.id})
                    </option>
                ))}
            </select>
        );
    };

    return (
        <div className="space-y-3">
            <div>
                <label htmlFor={`${idPrefix}-kind`} className="mb-1 block text-xs font-medium text-text-2">
                    What this policy allows
                </label>
                <select
                    id={`${idPrefix}-kind`}
                    value={parts.kind}
                    disabled={disabled}
                    onChange={(event) => setKind(event.target.value as McpPatternKind)}
                    className={inputClass}
                >
                    {KIND_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                </select>
                <p className="mt-1 text-xs text-text-3">{kindOption.hint}</p>
            </div>

            {parts.kind === 'preconfiguration' ? (
                <div>
                    {catalogSelect(
                        preconfigurations.map((entry) => ({ id: entry.id, label: entry.label })),
                        'microsoft_learn',
                        'Preconfigured server',
                    )}
                    {selectedPreconfiguration?.requires_endpoint_review ? (
                        <p className="mt-1 flex items-start gap-1.5 text-xs text-text-2">
                            <Info size={12} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                            This template also needs a host or URL policy for your organization&apos;s own endpoint.
                        </p>
                    ) : null}
                </div>
            ) : null}

            {parts.kind === 'preset' ? catalogSelect(catalog?.presets ?? [], 'generic', 'Server preset') : null}

            {parts.kind === 'transport' ? (
                <select
                    value={transports.includes(parts.value) ? parts.value : ''}
                    disabled={disabled}
                    onChange={(event) => setValue(event.target.value)}
                    aria-label="Transport"
                    className={inputClass}
                >
                    <option value="">{parts.value && !transports.includes(parts.value) ? `${parts.value} (never matches)` : 'Choose…'}</option>
                    {transports.map((transport) => (
                        <option key={transport} value={transport}>{transport}</option>
                    ))}
                </select>
            ) : null}

            {parts.kind === 'host' ? (
                <input
                    type="text"
                    value={parts.value}
                    disabled={disabled}
                    onChange={(event) => setValue(event.target.value)}
                    placeholder="*.contoso.com"
                    aria-label="Host pattern"
                    className={clsx(inputClass, 'font-mono')}
                />
            ) : null}

            {parts.kind === 'url' ? (
                <input
                    type="url"
                    value={parts.value}
                    disabled={disabled}
                    onChange={(event) => setValue(event.target.value)}
                    placeholder="https://mcp.contoso.com/mcp*"
                    aria-label="URL pattern"
                    className={clsx(inputClass, 'font-mono')}
                />
            ) : null}

            {isGroupScope ? (
                <div className="rounded-lg border border-edge p-3">
                    <label className="flex cursor-pointer items-start gap-2 text-sm text-text-1">
                        <input
                            type="checkbox"
                            className="mt-0.5 accent-[var(--accent)]"
                            checked={groupSpecific}
                            disabled={disabled}
                            onChange={(event) => onChange({ ...parts, groupId: event.target.checked ? '' : undefined })}
                        />
                        <span>
                            Only for one group
                            <span className="block text-xs text-text-3">
                                Off applies to every group workspace. On limits this destination to one group.
                            </span>
                        </span>
                    </label>
                    {groupSpecific ? (
                        <div className="mt-2">
                            <GroupTargetPicker
                                groupId={parts.groupId ?? ''}
                                disabled={disabled}
                                onChange={(groupId) => onChange({ ...parts, groupId })}
                            />
                        </div>
                    ) : null}
                </div>
            ) : null}

            {stored && !incomplete ? (
                <div className="text-xs">
                    <span className="text-text-3">Stored as </span>
                    <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-1 break-all">
                        {stored}
                    </code>
                </div>
            ) : null}

            {fieldError ? (
                <p role="alert" className="flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {fieldError}
                </p>
            ) : check.warning && !incomplete ? (
                <p className="flex items-start gap-1.5 text-xs text-warn">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {check.warning}
                </p>
            ) : null}
        </div>
    );
}
