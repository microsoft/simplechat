// ScreeningPolicyEditor.tsx

import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from '../../lib/apiClient';
import {
    fetchScreeningPolicy,
    isStaleScreeningError,
    saveScreeningPolicy,
    screeningErrorMessage,
    testScreeningPolicy,
    type ScreeningPolicyResponse,
    type ScreeningSampleResult,
    type ScreeningScope,
} from '../../lib/contentScreeningApi';
import {
    approvedScreeningChoices,
    editableScreeningPolicy,
    isScreeningPolicyInitialization,
    screeningCatalogChoices,
    screeningPolicyTemplates,
    screeningPolicySummary,
    validateScreeningPolicy,
    type ScreeningPolicy,
} from '../../lib/contentScreeningPolicy';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { GlassButton, Skeleton } from '../ui/primitives';
import { ScreeningBaselineSummary } from './ScreeningBaselineSummary';
import { ScreeningField, screeningInputClass } from './ScreeningFields';
import { ScreeningPolicyFields } from './ScreeningPolicyFields';


function PolicyEditor({
    scope,
    onSaved,
    configurationVersion = 0,
    disabled: externallyDisabled = false,
}: {
    scope: ScreeningScope;
    onSaved?: (response: ScreeningPolicyResponse) => void;
    configurationVersion?: number;
    disabled?: boolean;
}) {
    const catalog = useBootstrapStore((state) => state.data?.catalogs.models);
    const [response, setResponse] = useState<ScreeningPolicyResponse | null>(null);
    const [policy, setPolicy] = useState<ScreeningPolicy | null>(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [stale, setStale] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [validation, setValidation] = useState<string[]>([]);
    const [saved, setSaved] = useState(false);
    const [sample, setSample] = useState('');
    const [sampleResult, setSampleResult] = useState<ScreeningSampleResult | null>(null);
    const [refresh, setRefresh] = useState(0);
    const active = useRef(true);
    const inFlight = useRef(false);
    const dirty = useRef(false);
    const previousConfigurationVersion = useRef(configurationVersion);
    const global = scope.scope_type === 'global';
    const configuredModels = useMemo(() => screeningCatalogChoices(catalog ?? []), [catalog]);
    const models = useMemo(
        () => global ? configuredModels : approvedScreeningChoices(configuredModels, response?.allowed_models ?? []),
        [configuredModels, global, response?.allowed_models],
    );
    const templates = useMemo(
        () => response ? screeningPolicyTemplates(response.templates) : null,
        [response],
    );

    useEffect(() => {
        active.current = true;
        return () => { active.current = false; };
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        const preserveDraft = previousConfigurationVersion.current !== configurationVersion;
        previousConfigurationVersion.current = configurationVersion;
        setLoading(true);
        setError(null);
        setSaved(false);
        setValidation([]);
        setSampleResult(null);
        void fetchScreeningPolicy(scope, controller.signal).then((next) => {
            if (controller.signal.aborted) return;
            if (preserveDraft && dirty.current && policy && response) {
                const initialized = response.etag === null && isScreeningPolicyInitialization(response.policy, next.policy);
                if (next.etag !== response.etag && !initialized) {
                    setError('The saved policy changed while screening settings were saved. Your policy draft has been retained.');
                    setStale(true);
                    return;
                }
                setResponse(next);
                if (initialized && policy.enabled === response.policy.enabled) {
                    setPolicy({ ...policy, enabled: next.policy.enabled });
                }
                setStale(false);
                return;
            }
            setResponse(next);
            setPolicy(editableScreeningPolicy(next.policy, global));
            dirty.current = false;
            setStale(false);
        }).catch((failure) => {
            if (controller.signal.aborted) return;
            if (preserveDraft && !(failure instanceof ApiError && failure.isAuthError)) {
                setError('Screening settings were saved, but the policy could not be refreshed. Your policy draft has been retained.');
                setStale(true);
                return;
            }
            setResponse(null);
            setPolicy(null);
            setError(screeningErrorMessage(failure));
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [scope.scope_type, scope.scope_id, global, refresh, configurationVersion]);

    async function submit(kind: 'save' | 'test') {
        if (!policy || !response || inFlight.current || loading || stale || externallyDisabled) return;
        const errors = validateScreeningPolicy(policy, models);
        if (kind === 'test' && !sample.trim()) errors.push('Enter sample content to inspect.');
        if (kind === 'test' && !policy.rules.some((rule) => rule.enabled) && !policy.ai.enabled) {
            errors.push('Add an enabled rule or AI check before testing. An empty policy can still be saved.');
        }
        setValidation(errors);
        if (errors.length) return;
        inFlight.current = true;
        setBusy(true);
        setError(null);
        setSaved(false);
        setSampleResult(null);
        const candidate = editableScreeningPolicy(policy, global);
        try {
            if (kind === 'save') {
                const next = await saveScreeningPolicy(scope, candidate, response.etag);
                if (!active.current) return;
                setResponse(next);
                setPolicy(editableScreeningPolicy(next.policy, global));
                dirty.current = false;
                setSaved(true);
                onSaved?.(next);
            } else {
                const result = await testScreeningPolicy(scope, candidate, sample);
                if (active.current) setSampleResult(result);
            }
        } catch (failure) {
            if (!active.current) return;
            setError(screeningErrorMessage(failure));
            if (isStaleScreeningError(failure)) setStale(true);
            if (failure instanceof ApiError && failure.isAuthError) {
                setPolicy(null);
                setResponse(null);
                setSample('');
                setSampleResult(null);
            }
        } finally {
            inFlight.current = false;
            if (active.current) setBusy(false);
        }
    }

    const disabled = externallyDisabled || busy || stale || loading;
    const summary = policy && response ? screeningPolicySummary(policy, global, response.inherited_summary) : null;
    return (
        <section className="min-w-0 space-y-4 py-4" aria-label={global ? 'Global screening policy' : 'Workspace screening policy'}>
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                    <h3 className="text-base font-semibold text-text-1">{global ? 'Required screening policy' : 'Workspace policy additions'}</h3>
                    <p className="max-w-3xl text-xs leading-relaxed text-text-3">
                        {global
                            ? 'Enabling Content Screening creates an enabled empty baseline if none exists. You can save it empty and add checks later.'
                            : 'These checks add to the required administrator baseline. They cannot remove or weaken its rules.'}
                        {' '}Policy saves are independent of the Admin Settings Save button and do not release held documents.
                    </p>
                </div>
                <GlassButton type="button" size="sm" variant="subtle" disabled={loading || busy || externallyDisabled}
                    onClick={() => setRefresh((value) => value + 1)}>
                    {stale ? 'Reload current policy' : 'Reload saved policy'}
                </GlassButton>
            </div>
            {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
            {stale ? <p className="text-sm text-warn" role="alert">Reload the saved policy before saving or testing again; your draft has not overwritten it.</p> : null}
            {validation.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-danger" role="alert">
                {validation.map((message) => <li key={message}>{message}</li>)}
            </ul> : null}
            {saved ? <p className="text-sm text-ok" role="status">Screening policy saved.</p> : null}
            {loading ? <Skeleton className="h-32" /> : null}
            {!loading && policy && templates && response ? (
                <>
                    {response.inherited_summary ? <ScreeningBaselineSummary summary={response.inherited_summary} /> : null}
                    {summary ? <div className="space-y-1 rounded-lg border border-edge bg-surface-2 p-3" role="status" aria-label="Configured screening checks">
                        <p className="text-sm font-semibold text-text-1">{summary.label}</p>
                        <p className="text-xs text-text-3">{summary.detail}</p>
                        <p className="text-xs text-text-3">This summarizes the current draft. Save the policy to apply it; new scans must also be enabled separately.</p>
                        {global ? <p className="text-xs text-text-3">
                            Enabled chat checkpoints use this same baseline. An empty baseline cannot produce a passed chat check;
                            those attempts follow the failure setting and are recorded privately for administrators.
                        </p> : null}
                    </div> : null}
                    <ScreeningPolicyFields policy={policy} templates={templates} models={models}
                        baseline={global} disabled={disabled} onChange={(next) => {
                            dirty.current = true;
                            setPolicy(next);
                            setSaved(false);
                            setSampleResult(null);
                            setValidation([]);
                        }} />
                    <GlassButton type="button" variant="primary" disabled={disabled} onClick={() => void submit('save')}>
                        {busy ? 'Working...' : 'Save screening policy'}
                    </GlassButton>
                    <div className="space-y-3 border-t border-edge pt-4">
                        <ScreeningField label="Sample content" help="Test the current draft without saving it or publishing a document. Enabled model checks send this sample to the selected model.">
                            {(id) => <textarea id={id} rows={4} maxLength={20000} className={screeningInputClass}
                                value={sample} disabled={disabled} onChange={(event) => {
                                    setSample(event.target.value);
                                    setSampleResult(null);
                                }} />}
                        </ScreeningField>
                        <GlassButton type="button" variant="subtle" disabled={disabled || !sample.trim()}
                            onClick={() => void submit('test')}>Test screening policy</GlassButton>
                        {sampleResult ? <div role="status" className="space-y-2 rounded-lg border border-edge p-3 text-sm text-text-2">
                            <p>{sampleResult.complete
                                ? `Sample inspection complete: ${sampleResult.finding_count} finding(s).`
                                : 'Sample inspection did not complete. This is not a clean result.'}</p>
                            {sampleResult.error_code ? <p>{sampleResult.error_code}</p> : null}
                            {sampleResult.findings.length ? (
                                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">
                                    {JSON.stringify(sampleResult.findings, null, 2)}
                                </pre>
                            ) : null}
                            {sampleResult.findings_truncated ? <p>Only the first findings are displayed.</p> : null}
                        </div> : null}
                    </div>
                </>
            ) : null}
        </section>
    );
}

export function ScreeningPolicyEditor(props: {
    scope: ScreeningScope;
    onSaved?: (response: ScreeningPolicyResponse) => void;
    configurationVersion?: number;
    disabled?: boolean;
}) {
    return <PolicyEditor key={`${props.scope.scope_type}:${props.scope.scope_id}`} {...props} />;
}
