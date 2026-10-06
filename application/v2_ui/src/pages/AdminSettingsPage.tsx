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
import { Loader2, Network, PanelLeftClose, PanelLeftOpen, Search, ShieldAlert, TriangleAlert, type LucideIcon } from 'lucide-react';
import { ApiError, api } from '../lib/apiClient';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';
import { PageHeader } from '../components/layout/PageHeader';
import { GlassButton, GlassPanel, Skeleton, Toggle } from '../components/ui/primitives';
import { AdminModal } from '../components/admin/AdminModal';
import { AdminMarkdown } from '../components/admin/AdminMarkdown';
import { AppRoleRoster } from '../components/admin/AppRoleRoster';
import { AssignmentPicker } from '../components/admin/AssignmentPicker';
import { BrandingImageField } from '../components/admin/BrandingImageField';
import { ChatDefaultModel } from '../components/admin/ChatDefaultModel';
import { CapabilityModelPicker } from '../components/admin/CapabilityModelPicker';
import { ChatModeNotice } from '../components/admin/ChatModeNotice';
import { ConnectionTest } from '../components/admin/ConnectionTest';
import { ControlCenterAccessMatrix } from '../components/admin/ControlCenterAccessMatrix';
import { CustomPagesTable } from '../components/admin/CustomPagesTable';
import { EndpointLinks } from '../components/admin/EndpointLinks';
import { EnhancedCitationsStorageTest } from '../components/admin/EnhancedCitationsStorageTest';
import { EnhancedExtractionEngine } from '../components/admin/EnhancedExtractionEngine';
import { EntryListEditor } from '../components/admin/EntryListEditor';
import { ExternalLinksEditor } from '../components/admin/ExternalLinksEditor';
import { FileProcessingLogCleanup } from '../components/admin/FileProcessingLogCleanup';
import { FrontDoorRedirectPreview } from '../components/admin/FrontDoorRedirectPreview';
import { GlobalIdentitiesList } from '../components/admin/GlobalIdentitiesList';
import { GroupAssignmentField } from '../components/admin/GroupAssignmentField';
import { InboundMcpNotice } from '../components/admin/InboundMcpNotice';
import { KeyVaultReminders } from '../components/admin/KeyVaultReminders';
import { LoggingTimerStatus } from '../components/admin/LoggingTimerStatus';
import { ModelConnectionsManager } from '../components/admin/ModelConnectionsManager';
import { ModelCatalogManager } from '../components/admin/ModelCatalogManager';
import { ModelPicker } from '../components/admin/ModelPicker';
import { ScreeningWorkspaceControls } from '../components/screening/ScreeningWorkspaceControls';
import { ScreeningPolicyEditor } from '../components/screening/ScreeningPolicyEditor';
import { ResourceIdBuilder } from '../components/admin/ResourceIdBuilder';
import { ModelSelectionPicker } from '../components/admin/ModelSelectionPicker';
import { OrchestrationCard } from '../components/admin/OrchestrationCard';
import { OrchestrationPlannerModelPicker } from '../components/admin/OrchestrationPlannerModelPicker';
import { PromotedAgentsEditor } from '../components/admin/PromotedAgentsEditor';
import { RefreshScheduleStatus } from '../components/admin/RefreshScheduleStatus';
import { RelatedSectionLink } from '../components/admin/RelatedSectionLink';
import { RestartStatus } from '../components/admin/RestartStatus';
import { SectionGuide, hasSectionGuide } from '../components/admin/guides/sectionGuides';
import { AgentDelegationManager } from '../components/agents/AgentDelegationManager';
import { GLOBAL_DELEGATION_SCOPE } from '../lib/agentDelegation';
import { SaveBar } from '../components/admin/SaveBar';
import { SecretField } from '../components/admin/SecretField';
import { SettingsSection } from '../components/admin/SettingsSection';
import { SettingsIndex, type SettingsIndexEntry } from '../components/admin/SettingsIndex';
import { agentSectionAppearances } from '../components/admin/agentSectionAppearance';
import { ALL_SETTINGS_ICON, resolveAdminNavIcon } from '../components/admin/adminSectionIcons';
import { SettingField } from '../components/admin/fields';
import {
    ClassificationBannerPreview,
    UserAgreementPreview,
} from '../components/admin/previews';
import {
    applyEnableEffect,
    asBoolean,
    asNumber,
    asString,
    buildFieldIndex,
    collectAppRoleEntries,
    extractFieldErrors,
    fieldSearchText,
    humanizeKey,
    isFieldVisible,
    isRequirementSatisfied,
    isSectionVisible,
    readFieldValue,
    readStoredFieldValue,
    type AdminField,
    type AdminSectionGuide,
    type AdminSettingsPatchResponse,
    type AdminSettingsResponse,
    type AdminUpdateStatusResponse,
    type ApplicationUpdateStatus,
    type BrandingAssets,
    type BrandingUploadResponse,
} from '../lib/adminFields';
import { CONTROL_CENTER_ACCESS_KEYS, findNavLocation } from '../lib/adminOperations';
import { toast } from '../stores/toastStore';
import { computeSectionStatus, type SectionStatus } from '../lib/adminSections';
import {
    CONTENT_UNDERSTANDING_SUPPORTED_FLAG,
    resolveEnhancedExtractionEngine,
} from '../lib/enhancedExtraction';
import { hasUnsavedDiscoveryEdits } from '../lib/modelSelection';
import { PLANNER_MODEL_KEYS } from '../lib/orchestrationPlannerModel';
import { modelConnectionsChanged, requestConnectionFocus } from '../stores/modelConnectionsStore';
import type { CatalogConnectionTarget } from '../lib/modelCatalog';
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
    /** The Bootstrap icon name the navigation declares for the section. */
    icon?: string;
    /** The fields to draw. A search narrows these to the matches. */
    fields: AdminField[];
    /** Every visible field, which status and field nesting are read from. */
    allFields: AdminField[];
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
 *
 * `suppressed` names keys that must not be drawn at all -- derived values and staged
 * rollout flags, which would render a switch that appears to save and then reverts.
 */
function buildCapabilityIndex(
    nav: AdminNavGroup[],
    settings: Json,
    declaredKeys: Set<string>,
    suppressedKeys: Set<string>,
): CapabilityRow[] {
    const capabilityKeys = Object.keys(settings)
        .filter(
            (key) =>
                key.startsWith('enable_') &&
                typeof settings[key] === 'boolean' &&
                // A key with a proper field is rendered by the schema path; rendering it
                // here as well would put two controls on one value.
                !declaredKeys.has(key) &&
                !suppressedKeys.has(key),
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
    const bootstrapVersion = useBootstrapStore((state) => state.data?.version);
    // The categories rail's icons-only state is its own per-user preference, so making room
    // here leaves the workspace and shell rails as they are.
    const railCollapsed = useUserSettingsStore((state) => state.settings.v2AdminRailCollapsed === true);
    const updateUserSettings = useUserSettingsStore((state) => state.update);

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
    const [updateStatus, setUpdateStatus] = useState<ApplicationUpdateStatus | null>(null);
    const [checkingForUpdates, setCheckingForUpdates] = useState(true);
    const [query, setQuery] = useState('');
    const [activeGroup, setActiveGroup] = useState<string | null>(null);
    const [delegationDirty, setDelegationDirty] = useState(false);

    const [draft, setDraft] = useState<Json>({});
    const [saving, setSaving] = useState(false);
    const [screeningConfigurationVersion, setScreeningConfigurationVersion] = useState(0);
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
    const [fieldWarnings, setFieldWarnings] = useState<Record<string, string>>({});
    const [pendingAck, setPendingAck] = useState<AdminField | null>(null);
    const [pendingScroll, setPendingScroll] = useState<string | null>(null);
    const [openGuide, setOpenGuide] = useState<AdminSectionGuide | null>(null);

    const searchRef = useRef<HTMLInputElement>(null);
    /** The pane the cards scroll inside; the page index watches it to mark the current section. */
    const scrollRef = useRef<HTMLDivElement>(null);

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

    // The release check is requested beside the settings rather than inside them. On a
    // cache miss the server fetches the GitHub releases page, and waiting on that would
    // hold every setting behind the version banner.
    useEffect(() => {
        if (!isAdmin) {
            setCheckingForUpdates(false);
            return;
        }

        let cancelled = false;
        setCheckingForUpdates(true);
        void (async () => {
            try {
                const response = await api.get<AdminUpdateStatusResponse>(
                    '/api/v2/admin/update-status',
                );
                if (!cancelled) {
                    setUpdateStatus(response.update_status ?? null);
                }
            } catch {
                // An empty status is reported as an unavailable check. The settings load
                // separately, so they are unaffected.
            } finally {
                if (!cancelled) {
                    setCheckingForUpdates(false);
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
    const runtimeFlags = useMemo(() => data?.runtime_flags ?? {}, [data]);
    const sectionStatus = useMemo(() => data?.section_status ?? {}, [data]);

    /**
     * The in-app guide a section's header offers, if the UI has one by that id.
     *
     * A guide the server names but this build cannot draw is left off rather than shown as
     * a button that opens nothing.
     */
    const guideFor = useCallback(
        (sectionId: string): AdminSectionGuide | undefined => {
            const guide = data?.section_guides?.[sectionId];
            return guide && hasSectionGuide(guide.id) ? guide : undefined;
        },
        [data],
    );

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

    // A gate may live inside a nested settings object, so resolving a dependency
    // needs the schema rather than the key alone.
    const fieldsByKey = useMemo(() => buildFieldIndex(schema), [schema]);

    const suppressedKeys = useMemo(
        () => new Set(data?.suppressed_capabilities ?? []),
        [data],
    );

    const capabilityRows = useMemo(
        () =>
            data
                ? buildCapabilityIndex(
                      data.admin_nav,
                      data.settings,
                      declaredKeys,
                      suppressedKeys,
                  )
                : [],
        [data, declaredKeys, suppressedKeys],
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
                    const capabilities = capabilitiesBySection.get(section.id) ?? [];
                    capabilitiesBySection.delete(section.id);

                    // A section can be conditional on a settings key or a runtime
                    // flag -- workspace agent permissions only exist while Workspace
                    // Mode is on, and Inbound MCP only while its App Service setting
                    // is present. The server-rendered page already honours this; V2
                    // used to draw the section regardless.
                    if (!isSectionVisible(section.condition, settings, draft, runtimeFlags, fieldsByKey)) {
                        continue;
                    }

                    // Fields whose own dependencies are unmet are dropped here rather
                    // than at render time, so a section left with nothing to show
                    // disappears instead of leaving an empty titled panel behind.
                    const fields = (schema[section.id] ?? []).filter((field) =>
                        isFieldVisible(field, settings, draft, fieldsByKey, runtimeFlags),
                    );

                    if (!fields.length && !capabilities.length) {
                        continue;
                    }
                    rendered.push({
                        sectionId: section.id,
                        label: section.label,
                        groupId: group.id,
                        groupLabel: group.label,
                        tabLabel: tab.label,
                        icon: section.icon,
                        fields,
                        allFields: fields,
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
                allFields: [],
                capabilities,
            });
        }

        return rendered;
    }, [data, schema, capabilityRows, settings, draft, runtimeFlags, fieldsByKey]);

    const visibleSections = useMemo(() => {
        const needle = query.trim().toLowerCase();

        return sections
            .map((section) => {
                if (!needle) {
                    return activeGroup && section.groupId !== activeGroup ? null : section;
                }

                const location =
                    `${section.label} ${section.tabLabel} ${section.groupLabel} ${
                        guideFor(section.sectionId)?.label ?? ''
                    }`.toLowerCase();
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
    }, [sections, query, activeGroup, guideFor]);

    const settingCount = declaredKeys.size + capabilityRows.length;

    /**
     * Each section's status, read from the whole section rather than a search's matches.
     *
     * The card chip and the page index both show this, so they cannot disagree, and
     * narrowing the page with a search does not change what a section reports.
     */
    const statusBySection = useMemo(() => {
        const statuses = new Map<string, SectionStatus>();
        for (const section of sections) {
            statuses.set(
                section.sectionId,
                computeSectionStatus(
                    section.allFields,
                    settings,
                    draft,
                    sectionStatus[section.sectionId],
                    fieldsByKey,
                ),
            );
        }
        return statuses;
    }, [sections, settings, draft, sectionStatus, fieldsByKey]);

    /** The page index follows the same filters as the cards. */
    const indexEntries = useMemo<SettingsIndexEntry[]>(
        () =>
            visibleSections.map((section) => ({
                sectionId: section.sectionId,
                label: section.label,
                groupId: section.groupId,
                groupLabel: section.groupLabel,
                Icon:
                    agentSectionAppearances[section.sectionId]?.Icon ??
                    resolveAdminNavIcon(section.icon),
                status: statusBySection.get(section.sectionId) ?? 'none',
            })),
        [visibleSections, statusBySection],
    );

    /**
     * App role requirements, for the roster that mirrors them into Security.
     *
     * Built from the navigation and the schema together so each entry can say which tab
     * really owns it, and so the order matches the rest of the page. The server registry
     * is merged in for the Entra role value and the before/after description, which the
     * field schema has nowhere to put.
     */
    const appRoleEntries = useMemo(
        () =>
            data
                ? collectAppRoleEntries(data.admin_nav, schema, data.app_role_requirements)
                : [],
        [data, schema],
    );

    const appRoleValues = useMemo(() => {
        const values: Record<string, boolean> = {};
        const read = (key: string) =>
            asBoolean(
                Object.prototype.hasOwnProperty.call(draft, key) ? draft[key] : settings[key],
            );
        for (const entry of appRoleEntries) {
            values[entry.key] = read(entry.key);
            // The capability each requirement guards, so the roster can say when one is
            // enforced but currently doing nothing.
            if (entry.dependsOn) {
                values[entry.dependsOn] = read(entry.dependsOn);
            }
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
     *
     * A switch may also declare `on_enable` companions. Turning Enhanced extraction on
     * moves the extraction mode from Standard to Auto in the draft, so the administrator
     * sees the mode that will be saved rather than learning about it afterwards.
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
            if (field.on_enable) {
                setDraft((current) => applyEnableEffect(current, settings, field, next, fieldsByKey));
            }
        },
        [settings, setValue, fieldsByKey],
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
            if (response.updated_keys.includes('enable_content_screening')) {
                setScreeningConfigurationVersion((version) => version + 1);
            }
            void refreshBootstrap();

            // Enabling connections carries the classic chat endpoint into the connection
            // list server-side. That write happens here rather than in the connections
            // section, so nothing else would tell it, or the default model picker, that
            // the list they are showing is no longer what is stored.
            if (
                response.updated_keys.includes('model_endpoints') ||
                response.updated_keys.includes('enable_multi_model_endpoints')
            ) {
                modelConnectionsChanged();
            }

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

    /**
     * A switch's value, saved or with unsaved edits applied, falling back to its declared
     * default. Swagger has no seeded default, so without the declared one a fresh
     * deployment would read as off while the app treats it as on.
     */
    const readSwitch = (key: string, includeDraft: boolean) =>
        asBoolean(
            readFieldValue(fieldsByKey.get(key) ?? READ_ONLY_REF(key), settings, includeDraft ? draft : {}),
        );

    /** A link from a setting to the section its effect shows up in. */
    const renderRelatedSection = (field: AdminField) => {
        const related = field.related_section;
        if (!related || !data) {
            return null;
        }
        const shownHere =
            !related.classic_only && sections.some((section) => section.sectionId === related.section_id);
        return (
            <div className={clsx('pb-2', field.type === 'switch' && 'ml-14')}>
                <RelatedSectionLink
                    label={related.label}
                    location={findNavLocation(data.admin_nav, related.section_id)}
                    onNavigate={shownHere ? () => goToSection(related.section_id) : undefined}
                />
            </div>
        );
    };

    /**
     * Move the page to a section, from a cross-reference elsewhere on it.
     *
     * The target has to be on screen to scroll to, so a filter that hides it is changed: a
     * search that leaves it out is cleared, and a different category switches to the
     * target's own. Filters that already show it are left alone, so a jump within the
     * current category keeps the administrator where they were. The scroll is deferred to
     * an effect, because the element only exists once that filter change has rendered.
     */
    const goToSection = useCallback((sectionId: string) => {
        const shown = visibleSections.some((section) => section.sectionId === sectionId);
        if (!shown) {
            const target = sections.find((section) => section.sectionId === sectionId);
            const nextGroup = !target ? null : activeGroup && target.groupId !== activeGroup ? target.groupId : activeGroup;
            if (nextGroup !== activeGroup && delegationDirty) {
                // Changing category would unmount the delegation manager and its edits.
                toast.error('Save or cancel Call agent changes before changing settings categories.');
                return;
            }
            setQuery('');
            setActiveGroup(nextGroup);
        }
        setPendingScroll(sectionId);
    }, [visibleSections, sections, activeGroup, delegationDirty]);

    useEffect(() => {
        if (!pendingScroll) {
            return;
        }
        // Cards carry their section id as their own id; the heading takes focus so a
        // keyboard or screen reader user lands where the page now shows.
        const target = document.getElementById(pendingScroll);
        if (target) {
            const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
            target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
            document.getElementById(`${pendingScroll}-title`)?.focus({ preventScroll: true });
        }
        setPendingScroll(null);
    }, [pendingScroll]);

    /**
     * Go from the Model Catalog to AI Connections, opening one connection when named.
     *
     * The connection list opens the editor itself once it holds the row; this only leaves
     * the request and brings the section into view.
     */
    const openConnection = useCallback(
        (target?: CatalogConnectionTarget) => {
            if (target) {
                requestConnectionFocus(target);
            }
            goToSection('multi-endpoint-configuration');
        },
        [goToSection],
    );

    /** Render one declared field, dispatching the types the page owns. */
    const renderField = (field: AdminField) => {
        if (!isFieldVisible(field, settings, draft, fieldsByKey, runtimeFlags)) {
            return null;
        }

        const key = field.key ?? field.component ?? field.status_source ?? field.label;
        const value =
            field.type === 'status'
                ? data?.status_readouts?.[field.status_source ?? '']
                : readFieldValue(field, settings, draft);
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

        if (field.type === 'entry_list') {
            return (
                <EntryListEditor
                    key={key}
                    field={field}
                    value={value}
                    error={error}
                    disabled={saving}
                    onChange={(next) => field.key && setValue(field.key, next)}
                />
            );
        }

        if (field.type === 'secret') {
            return (
                <SecretField
                    key={key}
                    field={field}
                    value={value}
                    // The saved value, not the draft: only that says whether a credential
                    // exists, which is what tells an empty box apart from a pending delete.
                    // Read from where the field is stored, which for the Web Search client
                    // secret is inside `web_search_agent` rather than under its own key.
                    storedValue={readStoredFieldValue(field, settings)}
                    error={error}
                    warning={warning}
                    disabled={saving}
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
                case 'content-screening-policy':
                    return (
                        <div key={key} data-testid="screening-admin-settings" className="min-w-0 space-y-3">
                            <GlassButton type="button" variant="subtle" size="sm"
                                onClick={() => goToSection('enhanced-citations-section')}>
                                Configure Enhanced Citations
                            </GlassButton>
                            <ScreeningPolicyEditor scope={{ scope_type: 'global', scope_id: 'global' }}
                                configurationVersion={screeningConfigurationVersion} disabled={saving} />
                            <ScreeningWorkspaceControls scope={{ scope_type: 'global', scope_id: 'global' }} />
                            <a href="/admin/safety_violations#unchecked-chat-content"
                                className="inline-block text-sm text-accent hover:underline">
                                Review unchecked chat content
                            </a>
                        </div>
                    );
                case 'custom-pages-table':
                    return <CustomPagesTable key={key} help={field.help} />;
                case 'connection-test':
                    return (
                        <ConnectionTest
                            key={key}
                            field={field}
                            settings={settings}
                            draft={draft}
                            fieldsByKey={fieldsByKey}
                            disabled={saving}
                        />
                    );
                case 'agent-orchestration':
                    return <OrchestrationCard key={key} help={field.help} />;
                case 'inbound-mcp-disabled-notice':
                    return <InboundMcpNotice key={key} />;
                case 'model-connections-manager':
                    // The section card is already the "AI Connections" region.
                    return <ModelConnectionsManager key={key} help={field.help} landmark={false} />;
                case 'model-catalog-manager':
                    return (
                        <ModelCatalogManager
                            key={key}
                            help={field.help}
                            onOpenConnection={openConnection}
                        />
                    );
                case 'model-picker':
                    return (
                        <ModelPicker
                            key={key}
                            field={field}
                            value={value}
                            error={error}
                            warning={warning}
                            disabled={saving}
                            models={data?.model_catalog ?? []}
                            onChange={(next) => field.key && setValue(field.key, next)}
                        />
                    );
                case 'orchestration-planner-model':
                    // One control for the four planner keys, which only make sense together.
                    return (
                        <OrchestrationPlannerModelPicker
                            key={key}
                            field={field}
                            connectionsEnabled={asBoolean(settings['enable_multi_model_endpoints'])}
                            read={(settingKey) => readFieldValue(READ_ONLY_REF(settingKey), settings, draft)}
                            error={Object.values(PLANNER_MODEL_KEYS)
                                .map((plannerKey) => fieldErrors[plannerKey])
                                .find(Boolean)}
                            disabled={saving}
                            onChange={(updates) => {
                                for (const [plannerKey, next] of Object.entries(updates)) {
                                    setValue(plannerKey, next);
                                }
                            }}
                        />
                    );
                case 'resource-id-builder':
                    return (
                        <ResourceIdBuilder
                            key={key}
                            field={field}
                            value={value}
                            error={error}
                            warning={warning}
                            disabled={saving}
                            readSibling={readSibling}
                            onChange={(next) => field.key && setValue(field.key, next)}
                        />
                    );
                case 'chat-mode-notice': {
                    // The saved value decides which route is live; the draft value only
                    // says what a pending save would change it to, so the notice is given
                    // both rather than the merged reading the other fields use.
                    const savedEnabled = asBoolean(settings['enable_multi_model_endpoints']);
                    return (
                        <ChatModeNotice
                            key={key}
                            enabled={savedEnabled}
                            pending={
                                Object.prototype.hasOwnProperty.call(
                                    draft,
                                    'enable_multi_model_endpoints',
                                )
                                    ? asBoolean(draft['enable_multi_model_endpoints'])
                                    : undefined
                            }
                            help={field.help}
                        />
                    );
                }
                case 'chat-default-model':
                    return (
                        <ChatDefaultModel
                            key={key}
                            multiEndpointEnabled={asBoolean(
                                settings['enable_multi_model_endpoints'],
                            )}
                            help={field.help}
                        />
                    );
                case 'embedding-model-selection':
                    return (
                        <ModelSelectionPicker
                            key={key}
                            kind="embedding"
                            label={field.label}
                            help={field.help}
                            unsavedConnectionEdits={hasUnsavedDiscoveryEdits(
                                'embedding',
                                Object.keys(draft),
                            )}
                        />
                    );
                case 'image-generation-model-selection':
                case 'embedding-default-model-selection':
                    return (
                        <CapabilityModelPicker
                            key={key}
                            capability={field.component === 'embedding-default-model-selection' ? 'embeddings' : 'image_generation'}
                            featureEnabled={field.component === 'embedding-default-model-selection' || asBoolean(settings['enable_image_generation'])}
                            help={field.help}
                        />
                    );
                case 'global-identities-list':
                    return <GlobalIdentitiesList key={key} help={field.help} />;
                case 'promoted-popular-agents':
                    return (
                        <PromotedAgentsEditor
                            key={key}
                            field={field}
                            value={value}
                            error={error}
                            disabled={saving}
                            onChange={(next) => field.key && setValue(field.key, next)}
                        />
                    );
                case 'app-role-requirements-roster':
                    return (
                        <AppRoleRoster
                            key={key}
                            entries={appRoleEntries}
                            values={appRoleValues}
                            help={field.help}
                            disabled={saving}
                            onChange={setValue}
                            onNavigate={goToSection}
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
                case 'enhanced-citations-storage-test':
                    return (
                        <EnhancedCitationsStorageTest
                            key={key}
                            help={field.help}
                            authenticationType={readSibling(
                                'office_docs_authentication_type',
                                'key',
                            )}
                            connectionString={readSibling('office_docs_storage_account_url')}
                            blobEndpoint={readSibling(
                                'office_docs_storage_account_blob_endpoint',
                            )}
                        />
                    );
                case 'key-vault-secret-reminders':
                    return (
                        <KeyVaultReminders key={key} label={field.label} help={field.help} />
                    );
                case 'enhanced-extraction-engine': {
                    // Read twice: once as the page stands, and once as saved, so the
                    // notice can say when what it describes is not in force yet.
                    const supported = Boolean(runtimeFlags[CONTENT_UNDERSTANDING_SUPPORTED_FLAG]);
                    const reading = resolveEnhancedExtractionEngine(
                        (settingKey) => readFieldValue(READ_ONLY_REF(settingKey), settings, draft),
                        supported,
                    );
                    const saved = resolveEnhancedExtractionEngine(
                        (settingKey) => readFieldValue(READ_ONLY_REF(settingKey), settings, {}),
                        supported,
                    );
                    const pending =
                        !asBoolean(settings['enable_enhanced_extraction']) ||
                        saved.engine !== reading.engine ||
                        saved.reason !== reading.reason;
                    return (
                        <EnhancedExtractionEngine
                            key={key}
                            label={field.label}
                            help={field.help}
                            reading={reading}
                            pending={pending}
                        />
                    );
                }
                case 'front-door-redirect-preview':
                    return (
                        <FrontDoorRedirectPreview
                            key={key}
                            origin={readSibling('front_door_url')}
                            label={field.label}
                            help={field.help}
                        />
                    );
                case 'control-center-refresh-schedule':
                    return (
                        <RefreshScheduleStatus
                            key={key}
                            label={field.label}
                            help={field.help}
                            settings={settings}
                            draft={draft}
                        />
                    );
                case 'control-center-access-matrix': {
                    const accessKeys = Object.values(CONTROL_CENTER_ACCESS_KEYS);
                    return (
                        <ControlCenterAccessMatrix
                            key={key}
                            label={field.label}
                            help={field.help}
                            requireAdminRole={readSwitch(CONTROL_CENTER_ACCESS_KEYS.requireAdminRole, true)}
                            allowDashboardReader={readSwitch(
                                CONTROL_CENTER_ACCESS_KEYS.allowDashboardReader,
                                true,
                            )}
                            unsaved={accessKeys.some(
                                (accessKey) => readSwitch(accessKey, true) !== readSwitch(accessKey, false),
                            )}
                        />
                    );
                }
                case 'restart-status':
                    // Compared against how the running process started, which no save changes.
                    return field.watches && field.runtime_flag ? (
                        <RestartStatus
                            key={key}
                            label={field.label}
                            help={field.help}
                            saved={readSwitch(field.watches, false)}
                            draft={readSwitch(field.watches, true)}
                            running={Boolean(runtimeFlags[field.runtime_flag])}
                            available={
                                field.runtime_requires ? Boolean(runtimeFlags[field.runtime_requires]) : true
                            }
                        />
                    ) : null;
                case 'logging-timer-status':
                    return field.timer_keys ? (
                        <LoggingTimerStatus
                            key={key}
                            label={field.label}
                            help={field.help}
                            keys={field.timer_keys}
                            settings={settings}
                            draft={draft}
                        />
                    ) : null;
                case 'file-processing-log-cleanup':
                    return (
                        <FileProcessingLogCleanup
                            key={key}
                            label={field.label}
                            help={field.help}
                            disabled={saving}
                        />
                    );
                case 'endpoint-links':
                    return (
                        <EndpointLinks
                            key={key}
                            label={field.label}
                            help={field.help}
                            endpoints={field.endpoints ?? []}
                            isSavedOn={(gateKey) => readSwitch(gateKey, false)}
                            isDraftOn={(gateKey) => readSwitch(gateKey, true)}
                            runtimeFlags={runtimeFlags}
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
                disabled={saving || (
                    field.key === 'enable_content_screening_workspace_uploads'
                    && !asBoolean(value) && !isRequirementSatisfied(field, settings, draft)
                )}
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
                    {/* A row of its own, so on a wide card the preview sits under the editor in
                        the control column instead of spanning the label column as well. */}
                    <div className="admin-field pb-3" data-field-width="full">
                        <div className="admin-field-heading text-xs font-medium text-text-3">
                            Preview
                        </div>
                        <div className="admin-field-control min-w-0 rounded-lg border border-edge bg-surface-1 p-3">
                            <AdminMarkdown content={asString(value)} align={align} />
                        </div>
                    </div>
                </div>
            );
        }

        return (
            <div key={key}>
                {control}
                {renderRelatedSection(field)}
            </div>
        );
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
    const showDelegationManager = !loading && Boolean(data) && !error &&
        (activeGroup === 'agents-actions' ||
            (activeGroup === null && /call agent|delegation/i.test(query)));

    // The index needs at least two sections to be worth the width it takes.
    const showIndex = !loading && !error && indexEntries.length > 1;

    const categories: { id: string | null; label: string; Icon: LucideIcon }[] = [
        { id: null, label: 'All settings', Icon: ALL_SETTINGS_ICON },
        ...(data?.admin_nav ?? []).map((group) => ({
            id: group.id,
            label: group.label,
            Icon: resolveAdminNavIcon(group.icon),
        })),
    ];

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

            <div
                role="status"
                aria-label="Application version"
                className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-edge px-6 py-3 text-sm"
            >
                <span className="font-medium text-text-1">
                    Version: {data?.version || bootstrapVersion || 'Unavailable'}
                </span>
                {checkingForUpdates ? (
                    <span className="text-text-3">Checking for updates...</span>
                ) : updateStatus ? (
                    <>
                        {updateStatus.update_available && (
                            <span className="text-warn">
                                {updateStatus.status === 'checked' ? 'New version available' : 'Last known newer release'}
                                : v{updateStatus.latest_version}.{' '}
                                <a
                                    href="https://github.com/microsoft/simplechat/releases"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-accent underline"
                                >
                                    View releases
                                </a>
                            </span>
                        )}
                        {updateStatus.status !== 'checked' ? (
                            <span className="text-warn">
                                {updateStatus.error || 'Unable to check for application updates.'}
                                {updateStatus.latest_version && (
                                    <> Last known release: v{updateStatus.latest_version}; this result may be stale.</>
                                )}
                            </span>
                        ) : !updateStatus.update_available && (
                            <span className="text-text-3">No newer release found.</span>
                        )}
                    </>
                ) : (
                    <span className="text-warn">Unable to check for application updates.</span>
                )}
            </div>

            <div className="flex min-h-0 flex-1">
                <aside
                    aria-label="Settings categories"
                    className={clsx(
                        'hidden shrink-0 overflow-y-auto border-r border-edge transition-[width] motion-reduce:transition-none lg:block',
                        railCollapsed ? 'w-16 px-2 py-3' : 'w-56 p-3',
                    )}
                >
                    <button
                        type="button"
                        onClick={() => updateUserSettings({ v2AdminRailCollapsed: !railCollapsed })}
                        aria-label={railCollapsed ? 'Expand settings categories' : 'Collapse settings categories'}
                        aria-expanded={!railCollapsed}
                        aria-controls="admin-settings-category-list"
                        title={railCollapsed ? 'Expand settings categories' : 'Collapse settings categories'}
                        className={clsx(
                            'mb-2 flex w-full items-center gap-2 rounded-lg py-1.5 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
                            railCollapsed ? 'justify-center px-2' : 'px-3',
                        )}
                    >
                        {railCollapsed ? <PanelLeftOpen size={15} aria-hidden="true" /> : (
                            <><PanelLeftClose size={15} aria-hidden="true" /><span>Collapse</span></>
                        )}
                    </button>
                    <div id="admin-settings-category-list" className="space-y-0.5">
                        {categories.map((category) => {
                            const active = activeGroup === category.id;
                            return (
                                <button
                                    key={category.id ?? '__all'}
                                    type="button"
                                    disabled={delegationDirty}
                                    aria-pressed={active}
                                    title={railCollapsed ? category.label : undefined}
                                    onClick={() => setActiveGroup(category.id)}
                                    className={clsx(
                                        'flex w-full items-center gap-2.5 rounded-lg py-2.5 text-left text-sm transition-colors',
                                        railCollapsed ? 'justify-center px-2' : 'px-3',
                                        'disabled:cursor-not-allowed disabled:opacity-60',
                                        active
                                            ? 'bg-accent-soft font-semibold text-accent'
                                            : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                                    )}
                                >
                                    <category.Icon
                                        size={16}
                                        aria-hidden="true"
                                        className={clsx('shrink-0', active ? 'text-accent' : 'text-text-3')}
                                    />
                                    {/* Collapsed, the label stays as the button's accessible name. */}
                                    <span className={railCollapsed ? 'sr-only' : 'min-w-0 flex-1'}>{category.label}</span>
                                </button>
                            );
                        })}
                    </div>
                </aside>

                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="shrink-0 border-b border-edge px-4 py-3 lg:px-6">
                        <div className="mx-auto w-full max-w-[112rem]">
                            <div className="mb-3 max-w-md lg:hidden">
                                <label htmlFor="admin-settings-category" className="mb-1 block text-xs text-text-2">Settings category</label>
                                <select id="admin-settings-category" value={activeGroup ?? ''} disabled={delegationDirty}
                                    onChange={(event) => setActiveGroup(event.target.value || null)}
                                    className="w-full rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1">
                                    <option value="">All settings</option>
                                    {(data?.admin_nav ?? []).map((group) => (
                                        <option key={group.id} value={group.id}>{group.label}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="relative max-w-2xl">
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
                                    disabled={delegationDirty}
                                    className={clsx(
                                        'w-full rounded-xl border border-edge bg-surface-1 py-2.5 pr-3 pl-9',
                                        'text-sm text-text-1 placeholder:text-text-3',
                                        'focus:border-accent focus:outline-none',
                                    )}
                                />
                            </div>
                        </div>
                    </div>

                    <div
                        ref={scrollRef}
                        data-testid="admin-settings-scroll"
                        className="@container min-h-0 flex-1 overflow-y-auto px-4 py-4 lg:px-6"
                    >
                        <div className="mx-auto grid w-full max-w-[112rem] items-start gap-6 @min-[76rem]:grid-cols-[minmax(0,1fr)_15rem]">
                            <div data-testid="admin-settings-content" className="min-w-0 space-y-4">
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

                                {showDelegationManager ? (
                                    <GlassPanel
                                        edge
                                        role="region"
                                        aria-labelledby="global-agent-delegation-title"
                                        className="admin-settings-distinct border-edge-strong"
                                    >
                                        <div className="flex items-start gap-3 rounded-t-2xl border-b border-edge-strong bg-surface-2 p-4 sm:px-5">
                                            <span
                                                aria-hidden="true"
                                                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-edge-strong bg-surface-solid text-text-2"
                                            >
                                                <Network size={20} />
                                            </span>
                                            <div className="min-w-0">
                                                <h2 id="global-agent-delegation-title" className="text-lg leading-snug font-semibold text-text-1">
                                                    Global agent delegation
                                                </h2>
                                                <p className="mt-1 text-xs text-text-3">Agents &amp; Actions · Call agent</p>
                                            </div>
                                        </div>
                                        <div className="space-y-3 p-4 sm:p-5">
                                            <AgentDelegationManager scope={GLOBAL_DELEGATION_SCOPE}
                                                allowManage={isAdmin} onDirtyChange={setDelegationDirty} />
                                            {delegationDirty ? <p className="text-xs text-warn">Save or cancel Call agent changes before changing settings categories.</p> : null}
                                            <p className="text-xs text-text-3">These resources save separately from settings. Full global agent and other connector management remains on the <a href="/admin/settings" className="text-accent underline">classic admin page</a>.</p>
                                        </div>
                                    </GlassPanel>
                                ) : null}

                                {!loading && !showDelegationManager && visibleSections.length === 0 && (
                                    <p className="py-12 text-center text-sm text-text-3">
                                        No settings match “{query}”.
                                    </p>
                                )}

                                {visibleSections.map((section) => {
                                    const guide = guideFor(section.sectionId);
                                    return (
                                    <SettingsSection
                                        key={section.sectionId}
                                        sectionId={section.sectionId}
                                        label={section.label}
                                        groupLabel={section.groupLabel}
                                        tabLabel={section.tabLabel}
                                        icon={resolveAdminNavIcon(section.icon)}
                                        fields={section.fields}
                                        hierarchyFields={section.allFields}
                                        fieldsByKey={fieldsByKey}
                                        settings={settings}
                                        draft={draft}
                                        // Sections that describe a status rule use it;
                                        // the rest have their status derived from which
                                        // of their required fields are filled.
                                        statusRule={sectionStatus[section.sectionId]}
                                        status={statusBySection.get(section.sectionId)}
                                        renderField={renderField}
                                        renderCapability={renderField}
                                        appearance={agentSectionAppearances[section.sectionId]}
                                        guide={
                                            guide
                                                ? { label: guide.label, onOpen: () => setOpenGuide(guide) }
                                                : undefined
                                        }
                                        runtimeFlags={runtimeFlags}
                                        // While a search is filtering, a match inside a
                                        // collapsed group has to be shown or the card would
                                        // appear empty.
                                        forceExpanded={Boolean(query.trim())}
                                    >
                                        {section.capabilities.length ? (
                                            <div className="admin-switch-grid" data-testid="admin-switch-grid">
                                                {section.capabilities.map((row) => (
                                                    <div key={row.key} className="py-1">
                                                        <Toggle
                                                            label={row.label}
                                                            description={row.key}
                                                            labelClassName="font-semibold"
                                                            descriptionClassName="font-mono text-xs"
                                                            checked={asBoolean(
                                                                Object.prototype.hasOwnProperty.call(
                                                                    draft,
                                                                    row.key,
                                                                )
                                                                    ? draft[row.key]
                                                                    : settings[row.key],
                                                            )}
                                                            disabled={saving}
                                                            onChange={(next) =>
                                                                setValue(row.key, next)
                                                            }
                                                        />
                                                    </div>
                                                ))}
                                            </div>
                                        ) : null}
                                    </SettingsSection>
                                    );
                                })}

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

                            {showIndex ? (
                                <SettingsIndex
                                    className="hidden @min-[76rem]:block"
                                    entries={indexEntries}
                                    grouped={activeGroup === null || Boolean(query.trim())}
                                    scrollRoot={scrollRef}
                                    onJump={setPendingScroll}
                                />
                            ) : null}
                        </div>
                    </div>
                </div>
            </div>

            {openGuide ? (
                <SectionGuide
                    guide={openGuide}
                    // Saved settings, not the draft: a guide describes what is live.
                    context={{ settings, runtimeFlags }}
                    onClose={() => setOpenGuide(null)}
                />
            ) : null}

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
