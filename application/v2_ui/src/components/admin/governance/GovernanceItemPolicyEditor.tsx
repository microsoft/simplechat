// GovernanceItemPolicyEditor.tsx
// Create, edit, or move one delegated item policy.
//
// The editor is a dialog because it is opened from several places on the page -- the
// Delegated Item Policies list, the MCP destination and Inbound MCP cards, the Inbound MCP
// shortcut, and an AI connection's access list -- and because it saves on its own the
// moment it is applied, unlike the settings around it, which wait for the Save bar.
//
// Editing a saved policy may change what it applies to. The policy keeps its ID and moves,
// rather than leaving a copy on the old target, which is what the governance API does when
// it is told the original target.

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, Info, Loader2, RotateCw } from 'lucide-react';
import {
    GOVERNANCE_ENTITY_TYPES,
    allowsNobody,
    buildMcpDestinationItemId,
    checkMcpDestinationPattern,
    defaultItemPolicyName,
    entityTypeDefinition,
    fetchActionTypeOptions,
    fetchGlobalActionOptions,
    fetchGlobalAgentOptions,
    fetchMcpDestinationCatalog,
    governanceErrorMessage,
    inboundSourceOptions,
    isMcpDestinationEntityType,
    parseMcpDestinationItemId,
    principalsForSave,
    saveItemPolicy,
    validateItemPolicyDraft,
    type GovernanceEntityType,
    type GovernanceItemSource,
    type ItemOption,
    type ItemPolicyDraft,
    type McpDestinationCatalog,
    type McpPatternCheck,
    type McpPatternParts,
} from '../../../lib/governance';
import { fetchModelConnections, providerLabel } from '../../../lib/modelConnections';
import type { Json } from '../../../lib/types';
import { toast } from '../../../stores/toastStore';
import { AdminModal } from '../AdminModal';
import { GlassButton, Toggle } from '../../ui/primitives';
import { McpDestinationPatternField } from './McpDestinationPatternField';
import { PrincipalListEditor } from './PrincipalListEditor';

const inputClass =
    'w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 placeholder:text-text-3 focus:border-accent focus:outline-none disabled:opacity-60';

/** Item lists change rarely, so one load serves every editor opened on the page. */
const optionCache = new Map<GovernanceItemSource, ItemOption[]>();
let catalogCache: McpDestinationCatalog | null = null;

async function loadItemOptions(source: GovernanceItemSource, signal: AbortSignal): Promise<ItemOption[]> {
    switch (source) {
        case 'connections': {
            const response = await fetchModelConnections(signal);
            return (response.endpoints ?? []).map((connection) => ({
                value: connection.id,
                label: connection.name || connection.id,
                detail: `${providerLabel(connection.provider)}${connection.enabled === false ? ' · disabled' : ''}`,
            }));
        }
        case 'global_agents':
            return fetchGlobalAgentOptions(signal);
        case 'global_actions':
            return fetchGlobalActionOptions(signal);
        case 'action_types':
            return fetchActionTypeOptions(signal);
        default:
            return [];
    }
}

function sameDraft(left: ItemPolicyDraft, right: ItemPolicyDraft): boolean {
    return JSON.stringify({ ...left, ...principalsForSave(left), original: undefined })
        === JSON.stringify({ ...right, ...principalsForSave(right), original: undefined });
}

function ItemPicker({
    source,
    value,
    settings,
    disabled,
    idPrefix,
    onChange,
}: {
    source: GovernanceItemSource;
    value: string;
    settings: Json;
    disabled?: boolean;
    idPrefix: string;
    onChange: (value: string, label: string) => void;
}) {
    // Inbound sources come from the settings on the page, so they are derived, not fetched.
    const inboundOptions = useMemo(
        () => (source === 'inbound_sources' ? inboundSourceOptions(settings) : null),
        [source, settings],
    );
    const [loaded, setLoaded] = useState<ItemOption[] | null>(() => optionCache.get(source) ?? null);
    const [error, setError] = useState<string | null>(null);
    const [filter, setFilter] = useState('');
    const [reload, setReload] = useState(0);

    useEffect(() => {
        if (source === 'inbound_sources') {
            return;
        }
        if (!reload && optionCache.has(source)) {
            setLoaded(optionCache.get(source) ?? []);
            return;
        }
        const controller = new AbortController();
        setLoaded(null);
        setError(null);
        void loadItemOptions(source, controller.signal)
            .then((options) => {
                if (!controller.signal.aborted) {
                    optionCache.set(source, options);
                    setLoaded(options);
                }
            })
            .catch((loadError) => {
                if (!controller.signal.aborted) {
                    setLoaded([]);
                    setError(governanceErrorMessage(loadError, 'The list could not be loaded.'));
                }
            });
        return () => controller.abort();
    }, [source, reload]);

    const options = inboundOptions ?? loaded;

    const visible = useMemo(() => {
        const needle = filter.trim().toLowerCase();
        if (!needle || !options) {
            return options ?? [];
        }
        return options.filter((option) => `${option.value} ${option.label} ${option.detail ?? ''}`.toLowerCase().includes(needle));
    }, [options, filter]);

    if (options === null) {
        return (
            <p className="flex items-center gap-1.5 py-2 text-xs text-text-3">
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                Loading…
            </p>
        );
    }

    const known = options.some((option) => option.value === value);

    return (
        <div className="space-y-2">
            {options.length > 12 ? (
                <input
                    type="search"
                    value={filter}
                    onChange={(event) => setFilter(event.target.value)}
                    placeholder="Filter by name or ID"
                    aria-label="Filter the items"
                    className={inputClass}
                />
            ) : null}
            <div className="flex items-center gap-2">
                <select
                    id={`${idPrefix}-item`}
                    aria-labelledby={`${idPrefix}-item-label`}
                    value={known ? value : ''}
                    disabled={disabled}
                    onChange={(event) => {
                        const option = options.find((entry) => entry.value === event.target.value);
                        onChange(event.target.value, option?.label ?? event.target.value);
                    }}
                    className={inputClass}
                >
                    <option value="">
                        {value && !known ? `${value} (no longer listed)` : options.length ? 'Choose…' : 'Nothing to choose yet'}
                    </option>
                    {visible.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.detail ? `${option.label} — ${option.detail}` : option.label}
                        </option>
                    ))}
                </select>
                {source !== 'inbound_sources' ? (
                    <GlassButton
                        type="button"
                        size="icon"
                        variant="subtle"
                        title="Reload the list"
                        aria-label="Reload the list"
                        disabled={disabled}
                        onClick={() => setReload((current) => current + 1)}
                    >
                        <RotateCw size={14} aria-hidden="true" />
                    </GlassButton>
                ) : null}
            </div>
            {error ? (
                <p role="alert" className="flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}

export function GovernanceItemPolicyEditor({
    initial,
    entityTypes,
    settings,
    onClose,
}: {
    initial: ItemPolicyDraft;
    entityTypes?: readonly GovernanceEntityType[];
    /** Settings with unsaved edits applied, for the inbound source list. */
    settings: Json;
    onClose: (saved: boolean) => void;
}) {
    const [draft, setDraft] = useState<ItemPolicyDraft>(initial);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    // Set by the first save attempt, so a blank destination is reported at the field
    // only once someone has tried to save it.
    const [attempted, setAttempted] = useState(false);
    const [confirmDiscard, setConfirmDiscard] = useState(false);
    // Whether this dialog is still on screen when its save settles.
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    const [catalog, setCatalog] = useState<McpDestinationCatalog | null>(catalogCache);
    const [catalogState, setCatalogState] = useState<'loading' | 'ready' | 'failed'>(catalogCache ? 'ready' : 'loading');
    const [patternParts, setPatternParts] = useState<McpPatternParts>(() =>
        initial.item_id
            ? parseMcpDestinationItemId(initial.item_id, initial.entity_type)
            : { kind: 'preconfiguration', value: '' },
    );

    const editing = Boolean(initial.original);
    const dirty = !sameDraft(draft, initial);
    const definition = entityTypeDefinition(draft.entity_type);
    const isMcp = isMcpDestinationEntityType(draft.entity_type);
    const allowedTypes = GOVERNANCE_ENTITY_TYPES.filter(
        (type) => !entityTypes?.length || entityTypes.includes(type.value),
    );
    const moved = editing && initial.original
        && (initial.original.entity_type !== draft.entity_type || initial.original.item_id !== draft.item_id);
    const prefix = 'governance-item-editor';

    useEffect(() => {
        if (!isMcp || catalogCache) {
            return;
        }
        const controller = new AbortController();
        void fetchMcpDestinationCatalog(controller.signal)
            .then((loaded) => {
                if (!controller.signal.aborted) {
                    catalogCache = loaded;
                    setCatalog(loaded);
                    setCatalogState('ready');
                }
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    setCatalogState('failed');
                }
            });
        return () => controller.abort();
    }, [isMcp]);

    useEffect(() => {
        if (!dirty) {
            return;
        }
        const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty]);

    const update = (changes: Partial<ItemPolicyDraft>) => {
        setError(null);
        setDraft((current) => ({ ...current, ...changes }));
    };

    const setEntityType = (entityType: GovernanceEntityType) => {
        const nextParts: McpPatternParts = { kind: 'preconfiguration', value: '' };
        setPatternParts(nextParts);
        update({ entity_type: entityType, item_id: '', resource_label: '' });
    };

    const setPattern = (parts: McpPatternParts) => {
        setPatternParts(parts);
        const itemId = buildMcpDestinationItemId(parts, draft.entity_type);
        update({ item_id: itemId, resource_label: itemId });
    };

    const patternCheck: McpPatternCheck = isMcp
        ? checkMcpDestinationPattern(
            patternParts,
            catalog?.transports,
            draft.entity_type === 'mcp_group_destination' && patternParts.groupId !== undefined,
        )
        : {};
    const validation = patternCheck.error ?? validateItemPolicyDraft(draft);

    // Escape, the backdrop, and the close button all land here. A save in flight keeps the
    // dialog open, as the disabled Cancel does, so its outcome is never lost.
    const requestClose = () => {
        if (saving) {
            return;
        }
        if (dirty) {
            setConfirmDiscard(true);
            return;
        }
        onClose(false);
    };

    const save = async () => {
        if (validation) {
            setAttempted(true);
            // A pattern problem is shown beside the pattern, so it is not repeated here.
            setError(patternCheck.error ? null : validation);
            return;
        }
        setSaving(true);
        setError(null);
        try {
            await saveItemPolicy(draft);
            toast.success(editing ? 'Policy saved.' : 'Policy created.');
            onClose(true);
        } catch (saveError) {
            const message = governanceErrorMessage(saveError, 'The policy could not be saved.');
            if (mounted.current) {
                setError(message);
            } else {
                // Another dialog replaced this one while it saved, so there is no field left
                // to show the error beside.
                toast.error(message);
            }
        } finally {
            setSaving(false);
        }
    };

    const footer = confirmDiscard ? (
        <>
            <span className="mr-auto text-sm text-text-2">Discard your changes to this policy?</span>
            <GlassButton type="button" size="sm" variant="ghost" onClick={() => setConfirmDiscard(false)}>
                Keep editing
            </GlassButton>
            <GlassButton type="button" size="sm" variant="danger" onClick={() => onClose(false)}>
                Discard
            </GlassButton>
        </>
    ) : (
        <>
            <span className="mr-auto hidden text-xs text-text-3 sm:inline">Saves now, separately from the Save bar.</span>
            <GlassButton type="button" size="sm" variant="ghost" disabled={saving} onClick={requestClose}>
                Cancel
            </GlassButton>
            <GlassButton type="button" size="sm" variant="primary" disabled={saving || (editing && !dirty)} onClick={() => void save()}>
                {saving ? 'Saving…' : editing ? 'Save policy' : 'Create policy'}
            </GlassButton>
        </>
    );

    return (
        <AdminModal
            title={editing ? 'Edit delegated item policy' : 'New delegated item policy'}
            description={definition?.hint}
            size="lg"
            onClose={requestClose}
            footer={footer}
        >
            <div className="@container space-y-5">
                <div className="grid gap-3 @min-[40rem]:grid-cols-2">
                    <div>
                        <label htmlFor={`${prefix}-type`} className="mb-1 block text-xs font-medium text-text-2">
                            Applies to
                        </label>
                        <select
                            id={`${prefix}-type`}
                            value={draft.entity_type}
                            disabled={saving || allowedTypes.length < 2}
                            onChange={(event) => setEntityType(event.target.value as GovernanceEntityType)}
                            className={inputClass}
                        >
                            {allowedTypes.map((type) => (
                                <option key={type.value} value={type.value}>{type.label}</option>
                            ))}
                        </select>
                    </div>
                    <div>
                        <label htmlFor={`${prefix}-name`} className="mb-1 block text-xs font-medium text-text-2">
                            Policy name
                        </label>
                        <input
                            id={`${prefix}-name`}
                            type="text"
                            value={draft.policy_name}
                            disabled={saving}
                            maxLength={200}
                            onChange={(event) => update({ policy_name: event.target.value })}
                            placeholder={defaultItemPolicyName(draft.entity_type, draft.item_id, draft.resource_label)}
                            className={inputClass}
                        />
                    </div>
                </div>

                <div>
                    <p className="mb-1 text-xs font-medium text-text-2" id={`${prefix}-item-label`}>
                        {isMcp ? 'Destination' : draft.entity_type === 'inbound_mcp_source' ? 'Source' : 'Item'}
                    </p>
                    {isMcp ? (
                        <McpDestinationPatternField
                            key={draft.entity_type}
                            entityType={draft.entity_type}
                            parts={patternParts}
                            onChange={setPattern}
                            catalog={catalog}
                            catalogState={catalogState}
                            disabled={saving}
                            showIncomplete={attempted}
                            idPrefix={`${prefix}-pattern`}
                        />
                    ) : definition ? (
                        <ItemPicker
                            key={definition.source}
                            source={definition.source}
                            value={draft.item_id}
                            settings={settings}
                            disabled={saving}
                            idPrefix={prefix}
                            onChange={(itemId, label) => update({ item_id: itemId, resource_label: itemId ? label : '' })}
                        />
                    ) : null}
                    {moved ? (
                        <p className="mt-2 flex items-start gap-1.5 text-xs text-text-2">
                            <Info size={12} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                            Saving moves this policy to the new target. It keeps its policy ID.
                        </p>
                    ) : null}
                    {draft.entity_type === 'inbound_mcp_source' ? (
                        <p className="mt-2 text-xs text-text-3">
                            The source comes from the configured request header. It identifies a client rather
                            than proving who sent the request, unless a trusted gateway sets it.
                        </p>
                    ) : null}
                </div>

                <section aria-labelledby={`${prefix}-allowed-title`} className="space-y-3">
                    <h3 id={`${prefix}-allowed-title`} className="text-sm font-semibold text-text-1">Who may use it</h3>
                    <Toggle
                        label="Allow everyone"
                        description="Everyone who passes the matching feature policy may use it, unless blocked below."
                        checked={draft.allow_all}
                        disabled={saving}
                        onChange={(next) => update({ allow_all: next })}
                    />
                    {!draft.allow_all ? (
                        <div className="grid gap-4 @min-[40rem]:grid-cols-2">
                            <PrincipalListEditor
                                kind="users"
                                title="Allowed people"
                                tone="allow"
                                ids={draft.allowed_users}
                                onChange={(next) => update({ allowed_users: next })}
                                emptyText="No people listed."
                                idPrefix={`${prefix}-allowed-users`}
                                disabled={saving}
                            />
                            <PrincipalListEditor
                                kind="groups"
                                title="Allowed groups"
                                tone="allow"
                                ids={draft.allowed_groups}
                                onChange={(next) => update({ allowed_groups: next })}
                                emptyText="No groups listed. A group or public workspace here stands for its members."
                                idPrefix={`${prefix}-allowed-groups`}
                                disabled={saving}
                            />
                        </div>
                    ) : null}
                    {allowsNobody(draft) ? (
                        <p role="status" className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn/5 px-3 py-2 text-xs text-text-2">
                            <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                            Nobody passes this policy. To refuse only some people, allow everyone and add
                            them to the block list instead.
                        </p>
                    ) : null}
                </section>

                <section aria-labelledby={`${prefix}-blocked-title`} className="space-y-3">
                    <h3 id={`${prefix}-blocked-title`} className="text-sm font-semibold text-text-1">Who is blocked</h3>
                    <div className="grid gap-4 @min-[40rem]:grid-cols-2">
                        <PrincipalListEditor
                            kind="users"
                            title="Blocked people"
                            tone="block"
                            ids={draft.denied_users}
                            onChange={(next) => update({ denied_users: next })}
                            emptyText="Nobody blocked."
                            idPrefix={`${prefix}-denied-users`}
                            disabled={saving}
                        />
                        <PrincipalListEditor
                            kind="groups"
                            title="Blocked groups"
                            tone="block"
                            ids={draft.denied_groups}
                            onChange={(next) => update({ denied_groups: next })}
                            emptyText="No groups blocked."
                            idPrefix={`${prefix}-denied-groups`}
                            disabled={saving}
                        />
                    </div>
                    <p className="text-xs text-text-3">
                        A block here refuses the person even when this policy, or another policy on the same
                        item, would let them through.
                    </p>
                </section>

                {error ? (
                    <p role="alert" className="flex items-start gap-1.5 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger">
                        <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                        {error}
                    </p>
                ) : null}
            </div>
        </AdminModal>
    );
}
