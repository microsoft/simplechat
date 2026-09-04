// AdminSettingsPage.tsx
// Admin settings, reimagined as a search-first surface.
//
// The server-rendered page nests 14 groups -> 46 tabs -> 96 sections, which means finding
// one toggle can take several clicks through two levels of tabs. Here the same structure
// (still sourced from admin_settings_nav.py, so it cannot drift) is flattened: a slim
// category rail, a single scrollable pane, and a search box that matches across every
// section and every setting at once.
//
// Two sources feed the controls:
//
// `field_schema`
//     Sections described in `admin_settings_fields.py` render real controls -- text,
//     selects, colours, ranges, uploads and repeatable lists -- driven entirely by the
//     declaration. This is the path new work should take.
//
// the `enable_*` fallback
//     Sections not described yet are still discovered by scanning the settings document
//     for booleans and matching them to a section by word stems. That is how the whole
//     page used to work; it stays so undescribed groups keep functioning, and it retires
//     one group at a time as each is described.
//
// Edits are buffered into a draft and saved together. Terms of Use and the AI notice
// derive a content version from their text, and a new version re-prompts every user, so
// saving per keystroke would mint a version per character.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { Loader2, Search, ShieldAlert, TriangleAlert } from 'lucide-react';
import { ApiError, api } from '../lib/apiClient';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassButton, GlassPanel, Skeleton, Toggle } from '../components/ui/primitives';
import { AdminModal } from '../components/admin/AdminModal';
import { AdminMarkdown } from '../components/admin/AdminMarkdown';
import { AppRoleRoster } from '../components/admin/AppRoleRoster';
import { AssignmentPicker } from '../components/admin/AssignmentPicker';
import { BrandingImageField } from '../components/admin/BrandingImageField';
import { CustomPagesTable } from '../components/admin/CustomPagesTable';
import { ExternalLinksEditor } from '../components/admin/ExternalLinksEditor';
import { GlobalIdentitiesList } from '../components/admin/GlobalIdentitiesList';
import { GroupAssignmentField } from '../components/admin/GroupAssignmentField';
import { SaveBar } from '../components/admin/SaveBar';
import { SettingField } from '../components/admin/fields';
import {
    ClassificationBannerPreview,
    UserAgreementPreview,
} from '../components/admin/previews';
import {
    asBoolean,
    asNumber,
    asString,
    collectAppRoleEntries,
    extractFieldErrors,
    fieldSearchText,
    humanizeKey,
    isFieldVisible,
    readFieldValue,
    type AdminField,
    type AdminSettingsPatchResponse,
    type AdminSettingsResponse,
    type BrandingAssets,
    type BrandingUploadResponse,
} from '../lib/adminFields';
import { toast } from '../stores/toastStore';
import type { AdminNavGroup, Json } from '../lib/types';

/** One fallback row: an `enable_*` key with no declared field. */
interface CapabilityRow {
    key: string;
    label: string;
    groupId: string;
    groupLabel: string;
    tabLabel: string;
    sectionId: string;
    sectionLabel: string;
}

/** A section as rendered: its declared fields, plus any fallback capability rows. */
interface RenderedSection {
    sectionId: string;
    label: string;
    groupId: string;
    groupLabel: string;
    tabLabel: string;
    fields: AdminField[];
    capabilities: CapabilityRow[];
}

/** Synthetic field definitions used to read a sibling's current value for a preview. */
const READ_ONLY_REF = (key: string): AdminField => ({ key, type: 'text', label: '' });

/**
 * Associate each undeclared `enable_*` setting with a section.
 *
 * The navigation definition names sections but does not enumerate which settings keys
 * belong to them, so keys are matched to the section whose id shares the most leading
 * word stems. Anything with no reasonable match is collected under "Other capabilities"
 * rather than being hidden, because a silently missing toggle is worse than a misfiled one.
 */
function buildCapabilityIndex(
    nav: AdminNavGroup[],
    settings: Json,
    declaredKeys: Set<string>,
): CapabilityRow[] {
    const capabilityKeys = Object.keys(settings)
        .filter(
            (key) =>
                key.startsWith('enable_') &&
                typeof settings[key] === 'boolean' &&
                // A key with a proper field is rendered by the schema path; rendering it
                // here as well would put two controls on one value.
                !declaredKeys.has(key),
        )
        .sort();

    const sections = nav.flatMap((group) =>
        group.tabs.flatMap((tab) =>
            tab.sections.map((section) => ({
                groupId: group.id,
                groupLabel: group.label,
                tabLabel: tab.label,
                sectionId: section.id,
                sectionLabel: section.label,
                tokens: new Set(
                    section.id
                        .replace(/-section$/, '')
                        .split('-')
                        .filter((token) => token.length > 2),
                ),
            })),
        ),
    );

    return capabilityKeys.map((key) => {
        const keyTokens = key
            .replace(/^enable_/, '')
            .split('_')
            .filter((token) => token.length > 2);

        let best: (typeof sections)[number] | null = null;
        let bestScore = 0;

        for (const section of sections) {
            let score = 0;
            for (const token of keyTokens) {
                if (section.tokens.has(token)) {
                    score += 1;
                }
            }
            if (score > bestScore) {
                bestScore = score;
                best = section;
            }
        }

        return {
            key,
            label: humanizeKey(key),
            groupId: best?.groupId ?? '__other',
            groupLabel: best?.groupLabel ?? 'Other',
            tabLabel: best?.tabLabel ?? '',
            sectionId: best?.sectionId ?? '__other',
            sectionLabel: best?.sectionLabel ?? 'Other capabilities',
        };
    });
}

export function AdminSettingsPage() {
    const isAdmin = useBootstrapStore((state) => Boolean(state.data?.user?.is_admin));

    /**
     * Re-read the bootstrap payload once a save lands.
     *
     * The settings edited here are also what the shell draws itself from -- the
     * classification banner, the sidebar logo and title, the feature flags -- and that
     * payload is otherwise fetched only at startup. Without this a saved change is
     * invisible until the browser is reloaded.
     */
    const refreshBootstrap = useBootstrapStore((state) => state.refresh);

    const [data, setData] = useState<AdminSettingsResponse | null>(null);
    const [brandingAssets, setBrandingAssets] = useState<BrandingAssets>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [activeGroup, setActiveGroup] = useState<string | null>(null);

    const [draft, setDraft] = useState<Json>({});
    const [saving, setSaving] = useState(false);
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
    const [fieldWarnings, setFieldWarnings] = useState<Record<string, string>>({});
    const [pendingAck, setPendingAck] = useState<AdminField | null>(null);

    const searchRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (!isAdmin) {
            setLoading(false);
            return;
        }

        let cancelled = false;
        void (async () => {
            try {
                const response = await api.get<AdminSettingsResponse>('/api/v2/admin/settings');
                if (!cancelled) {
                    setData(response);
                    setBrandingAssets(response.branding_assets ?? {});
                    setLoading(false);
                }
            } catch (fetchError) {
                if (!cancelled) {
                    setError(
                        fetchError instanceof Error
                            ? fetchError.message
                            : 'Failed to load settings.',
                    );
                    setLoading(false);
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [isAdmin]);

    // "/" focuses search from anywhere on the page, which is the whole point of a
    // search-first surface. Ignored while typing so it can still be typed into a field.
    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement | null;
            const typingInField =
                target?.tagName === 'INPUT' ||
                target?.tagName === 'TEXTAREA' ||
                target?.tagName === 'SELECT';
            if (event.key === '/' && !typingInField) {
                event.preventDefault();
                searchRef.current?.focus();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, []);

    const settings = useMemo<Json>(() => data?.settings ?? {}, [data]);
    const schema = useMemo(() => data?.field_schema ?? {}, [data]);

    const declaredKeys = useMemo(() => {
        const keys = new Set<string>();
        for (const fields of Object.values(schema)) {
            for (const field of fields) {
                if (field.key) {
                    keys.add(field.key);
                }
            }
        }
        return keys;
    }, [schema]);

    const capabilityRows = useMemo(
        () => (data ? buildCapabilityIndex(data.admin_nav, data.settings, declaredKeys) : []),
        [data, declaredKeys],
    );

    /** Every section that has something to show, in navigation order. */
    const sections = useMemo<RenderedSection[]>(() => {
        if (!data) {
            return [];
        }

        const capabilitiesBySection = new Map<string, CapabilityRow[]>();
        for (const row of capabilityRows) {
            const existing = capabilitiesBySection.get(row.sectionId);
            if (existing) {
                existing.push(row);
            } else {
                capabilitiesBySection.set(row.sectionId, [row]);
            }
        }

        const rendered: RenderedSection[] = [];
        for (const group of data.admin_nav) {
            for (const tab of group.tabs) {
                for (const section of tab.sections) {
                    const fields = schema[section.id] ?? [];
                    const capabilities = capabilitiesBySection.get(section.id) ?? [];
                    capabilitiesBySection.delete(section.id);
                    if (!fields.length && !capabilities.length) {
                        continue;
                    }
                    rendered.push({
                        sectionId: section.id,
                        label: section.label,
                        groupId: group.id,
                        groupLabel: group.label,
                        tabLabel: tab.label,
                        fields,
                        capabilities,
                    });
                }
            }
        }

        // Anything the stem match could not place still has to be reachable.
        for (const [sectionId, capabilities] of capabilitiesBySection) {
            rendered.push({
                sectionId,
                label: capabilities[0]?.sectionLabel ?? 'Other capabilities',
                groupId: capabilities[0]?.groupId ?? '__other',
                groupLabel: capabilities[0]?.groupLabel ?? 'Other',
                tabLabel: capabilities[0]?.tabLabel ?? '',
                fields: [],
                capabilities,
            });
        }

        return rendered;
    }, [data, schema, capabilityRows]);

    const visibleSections = useMemo(() => {
        const needle = query.trim().toLowerCase();

        return sections
            .map((section) => {
                if (!needle) {
                    return activeGroup && section.groupId !== activeGroup ? null : section;
                }

                const location =
                    `${section.label} ${section.tabLabel} ${section.groupLabel}`.toLowerCase();
                if (location.includes(needle)) {
                    return section;
                }

                // Search spans keys, labels and help text, so both "retention" and
                // "data lifecycle" find the same setting.
                const fields = section.fields.filter((field) =>
                    fieldSearchText(field).includes(needle),
                );
                const capabilities = section.capabilities.filter((row) =>
                    `${row.key} ${row.label}`.toLowerCase().includes(needle),
                );
                return fields.length || capabilities.length
                    ? { ...section, fields, capabilities }
                    : null;
            })
            .filter((section): section is RenderedSection => section !== null);
    }, [sections, query, activeGroup]);

    const settingCount = declaredKeys.size + capabilityRows.length;

    /**
     * App role requirements, for the roster that mirrors them into Security.
     *
     * Built from the navigation and the schema together so each entry can say which tab
     * really owns it, and so the order matches the rest of the page.
     */
    const appRoleEntries = useMemo(
        () => (data ? collectAppRoleEntries(data.admin_nav, schema) : []),
        [data, schema],
    );

    const appRoleValues = useMemo(() => {
        const values: Record<string, boolean> = {};
        for (const entry of appRoleEntries) {
            values[entry.key] = asBoolean(
                Object.prototype.hasOwnProperty.call(draft, entry.key)
                    ? draft[entry.key]
                    : settings[entry.key],
            );
        }
        return values;
    }, [appRoleEntries, draft, settings]);

    /**
     * Keys that gate a save rather than being stored.
     *
     * They ride along in the draft so they reach the PATCH, but they are not changes an
     * administrator made and must not be counted as such.
     */
    const acknowledgementKeys = useMemo(() => {
        const keys = new Set<string>();
        for (const fields of Object.values(schema)) {
            for (const field of fields) {
                if (field.requires_acknowledgement) {
                    keys.add(field.requires_acknowledgement.key);
                }
            }
        }
        return keys;
    }, [schema]);

    const dirtyKeys = useMemo(
        () => Object.keys(draft).filter((key) => !acknowledgementKeys.has(key)),
        [draft, acknowledgementKeys],
    );

    const setValue = useCallback((key: string, value: unknown) => {
        setDraft((current) => ({ ...current, [key]: value }));
        setFieldErrors((current) => {
            if (!(key in current)) {
                return current;
            }
            const next = { ...current };
            delete next[key];
            return next;
        });
    }, []);

    /**
     * Apply a switch change, intercepting capabilities that require an acknowledgement.
     *
     * Custom Pages does not take full effect until the App Service restarts, so an
     * administrator has to be told before the toggle can be turned on.
     */
    const onSwitchChange = useCallback(
        (field: AdminField, next: boolean) => {
            if (!field.key) {
                return;
            }
            const acknowledgement = field.requires_acknowledgement;
            const alreadyOn = asBoolean(settings[field.key]);

            if (acknowledgement && next && !alreadyOn) {
                setPendingAck(field);
                return;
            }

            if (acknowledgement && !next) {
                // Turning the capability back off before saving must not leave a stale
                // acknowledgement behind for the next time it is switched on.
                const fieldKey = field.key;
                setDraft((current) => {
                    const updated = { ...current, [fieldKey]: false };
                    delete updated[acknowledgement.key];
                    return updated;
                });
                return;
            }

            setValue(field.key, next);
        },
        [settings, setValue],
    );

    const discard = useCallback(() => {
        setDraft({});
        setFieldErrors({});
        setFieldWarnings({});
    }, []);

    const save = useCallback(async () => {
        if (!Object.keys(draft).length) {
            return;
        }
        setSaving(true);
        setError(null);
        setFieldErrors({});

        try {
            const response = await api.patch<AdminSettingsPatchResponse>(
                '/api/v2/admin/settings',
                { settings: draft },
            );

            setData((current) =>
                current
                    ? { ...current, settings: { ...current.settings, ...response.settings } }
                    : current,
            );
            setFieldWarnings(response.warnings ?? {});
            setDraft({});
            void refreshBootstrap();

            const warningCount = Object.keys(response.warnings ?? {}).length;
            toast.success(
                warningCount
                    ? `Saved with ${warningCount} warning${warningCount === 1 ? '' : 's'}.`
                    : `Saved ${response.updated_keys.length} setting${
                          response.updated_keys.length === 1 ? '' : 's'
                      }.`,
            );
        } catch (saveError) {
            const errors =
                saveError instanceof ApiError ? extractFieldErrors(saveError.payload) : {};
            if (Object.keys(errors).length) {
                // Keep the draft so the rejected values stay on screen next to their errors.
                setFieldErrors(errors);
                toast.error('Some settings could not be saved.');
            } else {
                setError(
                    saveError instanceof Error ? saveError.message : 'Failed to save settings.',
                );
            }
        } finally {
            setSaving(false);
        }
    }, [draft, refreshBootstrap]);

    const onBrandingUploaded = useCallback(
        (target: string, result: BrandingUploadResponse) => {
            setBrandingAssets((current) => ({
                ...current,
                [target]: { present: true, version: result.version, url: result.url },
            }));
            // An upload is written to the settings document immediately rather than being
            // held until Save, so the rail would otherwise keep drawing the previous logo
            // -- and its URL is version-stamped, so only a refetch busts the cache.
            void refreshBootstrap();
            toast.success('Image uploaded.');
        },
        [refreshBootstrap],
    );

    /** Read another field's current value, preferring an unsaved edit. */
    const readSibling = (key: string, fallback = '') =>
        asString(readFieldValue(READ_ONLY_REF(key), settings, draft), fallback);

    /** Render one declared field, dispatching the types the page owns. */
    const renderField = (field: AdminField) => {
        if (!isFieldVisible(field, settings, draft)) {
            return null;
        }

        const key = field.key ?? field.component ?? field.label;
        const value = readFieldValue(field, settings, draft);
        const error = field.key ? fieldErrors[field.key] : undefined;
        const warning = field.key ? fieldWarnings[field.key] : undefined;

        if (field.type === 'image') {
            return (
                <BrandingImageField
                    key={key}
                    field={field}
                    asset={field.upload_target ? brandingAssets[field.upload_target] : undefined}
                    scalePercent={asNumber(
                        readFieldValue(
                            READ_ONLY_REF('landing_page_logo_scale_percent'),
                            settings,
                            draft,
                        ),
                        100,
                    )}
                    onUploaded={onBrandingUploaded}
                />
            );
        }

        if (field.type === 'link_list') {
            return (
                <ExternalLinksEditor
                    key={key}
                    field={field}
                    value={value}
                    error={error}
                    onChange={(next) => field.key && setValue(field.key, next)}
                />
            );
        }

        if (field.type === 'id_list') {
            return (
                <AssignmentPicker
                    key={key}
                    field={field}
                    value={value}
                    error={error}
                    disabled={saving}
                    onChange={(next) => field.key && setValue(field.key, next)}
                />
            );
        }

        if (field.type === 'group_picker') {
            return (
                <GroupAssignmentField
                    key={key}
                    field={field}
                    value={value}
                    error={error}
                    disabled={saving}
                    onChange={(next) => field.key && setValue(field.key, next)}
                />
            );
        }

        if (field.type === 'component') {
            switch (field.component) {
                case 'custom-pages-table':
                    return <CustomPagesTable key={key} help={field.help} />;
                case 'global-identities-list':
                    return <GlobalIdentitiesList key={key} help={field.help} />;
                case 'app-role-requirements-roster':
                    return (
                        <AppRoleRoster
                            key={key}
                            entries={appRoleEntries}
                            values={appRoleValues}
                            help={field.help}
                            disabled={saving}
                            onChange={setValue}
                        />
                    );
                case 'classification-banner-preview':
                    return (
                        <ClassificationBannerPreview
                            key={key}
                            text={readSibling('classification_banner_text')}
                            color={readSibling('classification_banner_color', '#ffc107')}
                            textColor={readSibling(
                                'classification_banner_text_color',
                                '#ffffff',
                            )}
                        />
                    );
                case 'user-agreement-preview':
                    return (
                        <UserAgreementPreview
                            key={key}
                            text={readSibling('user_agreement_text')}
                        />
                    );
                default:
                    return null;
            }
        }

        const control = (
            <SettingField
                field={field}
                value={value}
                error={error}
                warning={warning}
                disabled={saving}
                onChange={(next) => {
                    if (field.type === 'switch') {
                        onSwitchChange(field, asBoolean(next));
                    } else if (field.key) {
                        setValue(field.key, next);
                    }
                }}
            />
        );

        // Markdown fields show what the saved copy will look like, which is the only way
        // to judge alignment and formatting without leaving the page.
        if (field.markdown) {
            const align =
                field.key === 'landing_page_text'
                    ? (readSibling('landing_page_alignment', 'left') as
                          | 'left'
                          | 'center'
                          | 'right')
                    : 'left';
            return (
                <div key={key}>
                    {control}
                    <div className="mb-3 rounded-lg border border-edge bg-surface-1 p-3">
                        <span className="mb-1.5 block text-xs font-medium text-text-3">
                            Preview
                        </span>
                        <AdminMarkdown content={asString(value)} align={align} />
                    </div>
                </div>
            );
        }

        return <div key={key}>{control}</div>;
    };

    if (!isAdmin) {
        return (
            <>
                <PageHeader title="Admin settings" />
                <div className="flex flex-1 items-center justify-center p-6">
                    <GlassPanel className="flex max-w-md items-start gap-3 p-5">
                        <ShieldAlert size={20} className="mt-0.5 shrink-0 text-warn" />
                        <div>
                            <p className="font-medium text-text-1">Administrator access required</p>
                            <p className="mt-1 text-sm text-text-3">
                                Your account does not hold the Admin role.
                            </p>
                        </div>
                    </GlassPanel>
                </div>
            </>
        );
    }

    // Only groups that still rely on the fallback scan should point at the classic page.
    const activeGroupUsesFallback = sections.some(
        (section) =>
            section.capabilities.length > 0 && (!activeGroup || section.groupId === activeGroup),
    );

    return (
        <>
            <PageHeader
                title="Admin settings"
                description={
                    data
                        ? `${settingCount} settings across ${data.admin_nav.length} groups`
                        : undefined
                }
            />

            <div className="flex min-h-0 flex-1">
                <aside className="hidden w-56 shrink-0 overflow-y-auto border-r border-edge p-3 lg:block">
                    <button
                        type="button"
                        onClick={() => setActiveGroup(null)}
                        className={clsx(
                            'w-full rounded-lg px-3 py-2 text-left text-sm transition-colors',
                            activeGroup === null
                                ? 'bg-accent-soft font-medium text-accent'
                                : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                        )}
                    >
                        All settings
                    </button>
                    {(data?.admin_nav ?? []).map((group) => (
                        <button
                            key={group.id}
                            type="button"
                            onClick={() => setActiveGroup(group.id)}
                            className={clsx(
                                'w-full rounded-lg px-3 py-2 text-left text-sm transition-colors',
                                activeGroup === group.id
                                    ? 'bg-accent-soft font-medium text-accent'
                                    : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                            )}
                        >
                            {group.label}
                        </button>
                    ))}
                </aside>

                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="shrink-0 border-b border-edge p-4">
                        <div className="relative mx-auto max-w-2xl">
                            <Search
                                size={16}
                                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-3"
                            />
                            <input
                                ref={searchRef}
                                type="search"
                                value={query}
                                onChange={(event) => setQuery(event.target.value)}
                                placeholder="Search every setting…  (press / to focus)"
                                aria-label="Search settings"
                                className={clsx(
                                    'w-full rounded-xl border border-edge bg-surface-1 py-2.5 pr-3 pl-9',
                                    'text-sm text-text-1 placeholder:text-text-3',
                                    'focus:border-accent focus:outline-none',
                                )}
                            />
                        </div>
                    </div>

                    <div className="min-h-0 flex-1 overflow-y-auto p-4">
                        <div className="mx-auto max-w-3xl space-y-4">
                            {error && (
                                <GlassPanel
                                    elevation="flat"
                                    className="flex items-start gap-2 p-3 text-sm text-danger"
                                >
                                    <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                                    {error}
                                </GlassPanel>
                            )}

                            {loading && (
                                <div className="space-y-3">
                                    {Array.from({ length: 5 }).map((_, index) => (
                                        <Skeleton key={index} className="h-24 w-full" />
                                    ))}
                                </div>
                            )}

                            {!loading && visibleSections.length === 0 && (
                                <p className="py-12 text-center text-sm text-text-3">
                                    No settings match “{query}”.
                                </p>
                            )}

                            {visibleSections.map((section) => (
                                <GlassPanel key={section.sectionId} edge className="p-4">
                                    <div className="mb-1">
                                        <h2 className="text-sm font-semibold text-text-1">
                                            {section.label}
                                        </h2>
                                        <p className="text-xs text-text-3">
                                            {section.groupLabel}
                                            {section.tabLabel ? ` · ${section.tabLabel}` : ''}
                                        </p>
                                    </div>

                                    <div className="divide-y divide-edge">
                                        {section.fields.map(renderField)}

                                        {section.capabilities.map((row) => (
                                            <div key={row.key} className="py-1">
                                                <Toggle
                                                    label={row.label}
                                                    description={row.key}
                                                    checked={asBoolean(
                                                        Object.prototype.hasOwnProperty.call(
                                                            draft,
                                                            row.key,
                                                        )
                                                            ? draft[row.key]
                                                            : settings[row.key],
                                                    )}
                                                    disabled={saving}
                                                    onChange={(next) => setValue(row.key, next)}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                </GlassPanel>
                            ))}

                            {!loading && activeGroupUsesFallback && (
                                <p className="pb-6 text-center text-xs text-text-3">
                                    Settings in this group that need more than a switch —
                                    endpoints, keys, prompts and connection tests — are still on
                                    the{' '}
                                    <a href="/admin/settings" className="text-accent underline">
                                        classic admin page
                                    </a>
                                    .
                                </p>
                            )}

                            <SaveBar
                                dirtyCount={dirtyKeys.length}
                                saving={saving}
                                onSave={() => void save()}
                                onDiscard={discard}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {pendingAck?.requires_acknowledgement ? (
                <AdminModal
                    title={pendingAck.requires_acknowledgement.title}
                    onClose={() => setPendingAck(null)}
                    footer={
                        <>
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => setPendingAck(null)}
                            >
                                Cancel
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="primary"
                                size="sm"
                                onClick={() => {
                                    const field = pendingAck;
                                    const acknowledgement = field.requires_acknowledgement;
                                    if (field.key && acknowledgement) {
                                        const fieldKey = field.key;
                                        setDraft((current) => ({
                                            ...current,
                                            [fieldKey]: true,
                                            [acknowledgement.key]: true,
                                        }));
                                    }
                                    setPendingAck(null);
                                }}
                            >
                                I understand, enable it
                            </GlassButton>
                        </>
                    }
                >
                    <p className="text-sm leading-relaxed text-text-2">
                        {pendingAck.requires_acknowledgement.message}
                    </p>
                </AdminModal>
            ) : null}

            {saving ? (
                <div className="pointer-events-none fixed inset-0 z-40 flex items-end justify-center pb-24">
                    <span className="flex items-center gap-2 rounded-full bg-surface-solid px-3 py-1.5 text-xs text-text-2 shadow">
                        <Loader2 size={13} className="animate-spin" />
                        Saving…
                    </span>
                </div>
            ) : null}
        </>
    );
}
