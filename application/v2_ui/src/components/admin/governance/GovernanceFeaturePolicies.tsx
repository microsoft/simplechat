// GovernanceFeaturePolicies.tsx
// Who passes each governance switch, edited in place.
//
// The classic page showed only the policies whose switch was on, as a table of hidden
// comma-separated inputs saved together by one button. Here every feature is listed, so a
// policy can be prepared before its switch is turned on, and each row says plainly whether
// it is being enforced right now: on, off, or waiting for the feature it governs. A row opens
// in place to edit, and saves on its own through the governance API rather than through the
// page's Save bar, because policies live in their own store.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, AlertTriangle, ArrowRight, Pencil, RotateCw } from 'lucide-react';
import {
    GOVERNANCE_FEATURES,
    GOVERNANCE_SCOPE_LABELS,
    allowsNobody,
    describeFeatureEnforcement,
    fetchFeaturePolicies,
    governanceErrorMessage,
    normalizePolicyState,
    principalsForSave,
    saveFeaturePolicy,
    summarizeAllowed,
    summarizeBlocked,
    EMPTY_PRINCIPALS,
    type FeatureEnforcement,
    type FeatureEnforcementState,
    type GovernanceFeature,
    type GovernanceFeaturePolicy,
    type GovernancePrincipals,
    type GovernanceScope,
} from '../../../lib/governance';
import type { Json } from '../../../lib/types';
import { toast } from '../../../stores/toastStore';
import { GlassButton, Skeleton, Toggle } from '../../ui/primitives';
import { PrincipalListEditor } from './PrincipalListEditor';

const TOGGLES_SECTION_ID = 'governance-feature-toggles-section';

const STATE_PRESENTATION: Record<FeatureEnforcementState, { label: string; className: string }> = {
    enforced: { label: 'Enforced', className: 'border-ok/40 bg-ok/5 text-ok' },
    off: { label: 'Not enforced', className: 'border-edge-strong text-text-3' },
    waiting: { label: 'Waiting for its feature', className: 'border-warn/40 bg-warn/5 text-warn' },
};

function samePrincipals(left: GovernancePrincipals, right: GovernancePrincipals): boolean {
    const a = principalsForSave(left);
    const b = principalsForSave(right);
    return a.allow_all === b.allow_all
        && a.allowed_users.join('\n') === b.allowed_users.join('\n')
        && a.allowed_groups.join('\n') === b.allowed_groups.join('\n')
        && a.denied_users.join('\n') === b.denied_users.join('\n')
        && a.denied_groups.join('\n') === b.denied_groups.join('\n');
}

function EnforcementBadge({
    feature,
    enforcement,
    onNavigate,
}: {
    feature: GovernanceFeature;
    enforcement: FeatureEnforcement;
    onNavigate: (sectionId: string) => void;
}) {
    const live = STATE_PRESENTATION[enforcement.state];
    const pending = enforcement.pending ? STATE_PRESENTATION[enforcement.pending] : null;
    const waitingOn = feature.primary?.label;

    // Where the administrator goes to change what the badge reports.
    const target = enforcement.state === 'waiting' && feature.primary
        ? feature.primary.section
        : enforcement.state === 'off'
            ? TOGGLES_SECTION_ID
            : null;

    return (
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className={clsx('inline-flex items-center rounded-full border px-2 py-0.5 text-xs', live.className)}>
                {enforcement.state === 'waiting' && waitingOn ? `Waiting for ${waitingOn}` : live.label}
            </span>
            {pending ? (
                <span className="inline-flex items-center gap-1 text-xs text-accent">
                    <ArrowRight size={12} aria-hidden="true" />
                    {pending.label === 'Waiting for its feature' && waitingOn ? `Waiting for ${waitingOn}` : pending.label} after you save
                </span>
            ) : null}
            {target && !feature.alwaysEnforced ? (
                <button
                    type="button"
                    onClick={() => onNavigate(target)}
                    className="text-xs text-accent hover:underline"
                >
                    Go to setting
                </button>
            ) : null}
        </div>
    );
}

function FeaturePolicyEditor({
    feature,
    saved,
    onCancel,
    onSaved,
    onDirtyChange,
}: {
    feature: GovernanceFeature;
    saved: GovernancePrincipals;
    onCancel: () => void;
    onSaved: (policy: GovernanceFeaturePolicy | null) => void;
    /** Must be stable; called with false when the editor closes. */
    onDirtyChange: (dirty: boolean) => void;
}) {
    const [draft, setDraft] = useState<GovernancePrincipals>(() => ({ ...saved }));
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const dirty = !samePrincipals(draft, saved);
    const prefix = `governance-feature-${feature.key}`;

    useEffect(() => {
        onDirtyChange(dirty);
    }, [dirty, onDirtyChange]);
    useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

    useEffect(() => {
        if (!dirty) {
            return;
        }
        const beforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty]);

    const update = (changes: Partial<GovernancePrincipals>) => setDraft((current) => ({ ...current, ...changes }));

    const save = async () => {
        setSaving(true);
        setError(null);
        try {
            const policy = await saveFeaturePolicy(feature.key, draft);
            toast.success(`${feature.label} policy saved.`);
            onSaved(policy);
        } catch (saveError) {
            setError(governanceErrorMessage(saveError, 'The policy could not be saved.'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="mt-3 space-y-4 border-t border-edge pt-3" aria-label={`Edit the ${feature.label} policy`} role="group">
            <Toggle
                label="Allow everyone"
                description="Everyone passes unless they are blocked below. Turn this off to allow only the people and groups you list."
                checked={draft.allow_all}
                disabled={saving}
                onChange={(next) => update({ allow_all: next })}
            />

            {!draft.allow_all ? (
                <div className="grid gap-4 @min-[50rem]:grid-cols-2">
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
                    Nobody passes this policy as it stands. Add people or groups, or allow everyone.
                </p>
            ) : null}

            <div className="grid gap-4 @min-[50rem]:grid-cols-2">
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
                A blocked person, or a member of a blocked group, is refused even when Allow everyone or an
                allowed group would let them through.
            </p>

            {error ? (
                <p role="alert" className="flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {error}
                </p>
            ) : null}

            <div className="flex flex-wrap items-center justify-end gap-2">
                <div className="mr-auto min-w-0 text-xs">
                    <p className="text-text-3">Saves now, separately from the Save bar.</p>
                    {dirty ? (
                        <p className="text-warn">
                            Settings categories and search are locked until you save or discard this policy.
                        </p>
                    ) : null}
                </div>
                <GlassButton type="button" size="sm" variant="ghost" disabled={saving} onClick={onCancel}>
                    {dirty ? 'Discard changes' : 'Close'}
                </GlassButton>
                <GlassButton type="button" size="sm" variant="primary" disabled={saving || !dirty} onClick={() => void save()}>
                    {saving ? 'Saving…' : 'Save policy'}
                </GlassButton>
            </div>
        </div>
    );
}

export function GovernanceFeaturePolicies({
    help,
    settings,
    draft,
    onNavigate,
    onDirtyChange,
}: {
    help?: string;
    settings: Json;
    draft: Json;
    onNavigate: (sectionId: string) => void;
    /**
     * Whether a policy has unsaved edits. Leaving the category or searching would unmount
     * this section and discard them, so the page locks both until the edit is settled.
     */
    onDirtyChange?: (dirty: boolean) => void;
}) {
    const [policies, setPolicies] = useState<Record<string, GovernanceFeaturePolicy> | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [editing, setEditing] = useState<string | null>(null);
    const [editorDirty, setEditorDirty] = useState(false);
    const [reload, setReload] = useState(0);

    useEffect(() => {
        onDirtyChange?.(editorDirty);
    }, [editorDirty, onDirtyChange]);
    // Released however the section goes away, so the page can never stay locked.
    useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

    const load = useCallback(async (signal: AbortSignal) => {
        try {
            const loaded = await fetchFeaturePolicies(signal);
            if (!signal.aborted) {
                setPolicies(Object.fromEntries(loaded.map((policy) => [policy.feature_key, policy])));
                setError(null);
            }
        } catch (loadError) {
            if (!signal.aborted) {
                setError(governanceErrorMessage(loadError, 'Feature policies could not be loaded.'));
            }
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void load(controller.signal);
        return () => controller.abort();
    }, [load, reload]);

    const grouped = useMemo(() => {
        const scopes: GovernanceScope[] = ['personal', 'group', 'global'];
        return scopes.map((scope) => ({
            scope,
            features: GOVERNANCE_FEATURES.filter((feature) => feature.scope === scope),
        }));
    }, []);

    return (
        <div className="py-3">
            {help ? <p className="mb-3 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{help}</p> : null}

            {error ? (
                <div role="alert" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-text-2">
                    <AlertCircle size={13} className="shrink-0 text-danger" aria-hidden="true" />
                    <span className="min-w-0 flex-1">{error}</span>
                    <GlassButton type="button" size="sm" variant="ghost" onClick={() => setReload((value) => value + 1)}>
                        <RotateCw size={13} aria-hidden="true" />
                        Try again
                    </GlassButton>
                </div>
            ) : null}

            <div className="space-y-5">
                {grouped.map(({ scope, features }) => (
                    <section key={scope} aria-labelledby={`governance-feature-scope-${scope}`}>
                        <h3 id={`governance-feature-scope-${scope}`} className="mb-2 text-sm font-semibold text-text-2">
                            {GOVERNANCE_SCOPE_LABELS[scope]}
                        </h3>
                        <ul className="divide-y divide-edge rounded-xl border border-edge-strong bg-surface-solid">
                            {features.map((feature) => {
                                const policy = policies?.[feature.key];
                                const principals = policy ?? EMPTY_PRINCIPALS;
                                const blocked = summarizeBlocked(principals);
                                const enforcement = describeFeatureEnforcement(feature, settings, draft);
                                const isEditing = editing === feature.key;
                                // The Edit button collapses an open editor, which would discard unsaved edits.
                                const holdingEdits = isEditing && editorDirty;
                                return (
                                    <li key={feature.key} className="px-3 py-3 sm:px-4" data-feature-policy={feature.key}>
                                        <div className="grid items-start gap-x-4 gap-y-2 @min-[44rem]:grid-cols-[minmax(10rem,1.3fr)_minmax(9rem,1fr)_minmax(8rem,1fr)_auto]">
                                            <div className="min-w-0">
                                                <p className="text-sm font-semibold text-text-1">{feature.label}</p>
                                                <p className="mt-0.5 text-xs leading-relaxed text-text-3">{feature.summary}</p>
                                            </div>
                                            <EnforcementBadge feature={feature} enforcement={enforcement} onNavigate={onNavigate} />
                                            <div className="min-w-0 text-xs">
                                                {policies === null && !error ? (
                                                    <Skeleton className="h-4 w-32" />
                                                ) : (
                                                    <>
                                                        <p className={clsx(allowsNobody(principals) ? 'text-warn' : 'text-text-2')}>
                                                            <span className="text-text-3">Allows </span>
                                                            {summarizeAllowed(principals)}
                                                        </p>
                                                        {blocked ? (
                                                            <p className="mt-0.5 text-text-2">
                                                                <span className="text-text-3">Blocks </span>
                                                                {blocked}
                                                            </p>
                                                        ) : null}
                                                    </>
                                                )}
                                            </div>
                                            <div className="flex justify-start @min-[44rem]:justify-end">
                                                <GlassButton
                                                    type="button"
                                                    size="sm"
                                                    variant="subtle"
                                                    disabled={policies === null || (editing !== null && !isEditing) || holdingEdits}
                                                    aria-expanded={isEditing}
                                                    aria-label={`Edit the ${feature.label} policy`}
                                                    title={
                                                        holdingEdits
                                                            ? 'Save or discard your changes first.'
                                                            : editing !== null && !isEditing
                                                                ? 'Finish the policy you are editing first.'
                                                                : undefined
                                                    }
                                                    onClick={() => setEditing(isEditing ? null : feature.key)}
                                                >
                                                    <Pencil size={13} aria-hidden="true" />
                                                    Edit
                                                </GlassButton>
                                            </div>
                                        </div>

                                        {isEditing ? (
                                            <FeaturePolicyEditor
                                                feature={feature}
                                                saved={normalizePolicyState({ ...principals })}
                                                onCancel={() => setEditing(null)}
                                                onDirtyChange={setEditorDirty}
                                                onSaved={(saved) => {
                                                    if (saved) {
                                                        setPolicies((current) => ({ ...(current ?? {}), [saved.feature_key]: saved }));
                                                    } else {
                                                        setReload((value) => value + 1);
                                                    }
                                                    setEditing(null);
                                                }}
                                            />
                                        ) : null}
                                    </li>
                                );
                            })}
                        </ul>
                    </section>
                ))}
            </div>
        </div>
    );
}
