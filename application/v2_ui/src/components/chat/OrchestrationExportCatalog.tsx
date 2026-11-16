// OrchestrationExportCatalog.tsx

import { useEffect, useRef, useState } from 'react';
import type { OrchestrationExportFormat } from '../../lib/orchestrationExports';
import { fetchOrchestrationExportCatalog } from '../../lib/orchestration';
import { legacyPlanErrorMessage } from '../../lib/orchestrationErrors';
import { useOrchestrationStore } from '../../stores/orchestrationStore';
import { GlassButton } from '../ui/primitives';

/** Loading the authorized reference neither admits a capability nor changes a plan. */
export function OrchestrationExportCatalog({
    catalog, conversationId, runId,
}: { catalog?: readonly OrchestrationExportFormat[]; conversationId?: string; runId?: string }) {
    const controller = useRef<AbortController | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        setLoading(false);
        setError(null);
        return () => { controller.current?.abort(); controller.current = null; };
    }, [conversationId, runId]);
    const load = async () => {
        if (!conversationId || !runId || loading) return;
        const request = new AbortController();
        controller.current = request;
        setLoading(true);
        setError(null);
        try {
            const formats = await fetchOrchestrationExportCatalog(conversationId, runId, request.signal);
            if (!request.signal.aborted) {
                useOrchestrationStore.getState().updateRunRecovery(runId, { export_catalog: formats });
            }
        } catch (requestError) {
            if (!request.signal.aborted) {
                setError(legacyPlanErrorMessage(requestError)
                    || 'The server file format reference could not be loaded. No file options were changed.');
            }
        } finally {
            if (!request.signal.aborted) setLoading(false);
        }
    };
    if (catalog === undefined && conversationId && runId) return (
        <div className="space-y-2">
            <GlassButton size="sm" variant="ghost" disabled={loading} onClick={() => void load()}>
                {loading ? 'Loading file format reference...' : 'Load server file format reference'}
            </GlassButton>
            {error ? <p role="alert" className="alert text-xs text-warn">{error}</p> : null}
        </div>
    );
    if (!catalog) return null;
    if (!catalog.length) return (
        <p role="status" className="text-xs text-text-3">The server did not advertise file formats for this plan.</p>
    );
    return (
        <details className="rounded-xl border border-edge bg-surface-sunken p-3 text-xs">
            <summary className="cursor-pointer font-medium text-text-2">Server file format reference</summary>
            <p className="mt-2 text-text-3">
                Ask the planner for a validated revision to change a file task. Format support alone does not authorize a task.
            </p>
            <ul className="mt-2 space-y-3 break-words">
                {catalog.map((format) => (
                    <li key={format.format_id}>
                        <h4 className="font-medium text-text-1">{format.format_id} (.{format.file_extension})</h4>
                        <p className="text-text-3">{format.media_type}</p>
                        <ul className="mt-1 space-y-2 text-text-2">
                            {format.profiles.map((profile) => (
                                <li key={profile.profile}>
                                    <p><strong>Profile:</strong> {profile.profile}</p>
                                    <p><strong>Sources:</strong> {profile.source_kinds.join(', ')}</p>
                                    {profile.requires_complete ? <p>Complete results required.</p> : null}
                                    {profile.required_options.length ? (
                                        <p><strong>Required options:</strong> {profile.required_options.join(', ')}</p>
                                    ) : null}
                                    {profile.supported_options.length ? (
                                        <p><strong>Supported options:</strong> {profile.supported_options.join(', ')}</p>
                                    ) : null}
                                    <details className="mt-1">
                                        <summary className="cursor-pointer">Option rules for {profile.profile}</summary>
                                        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all">
                                            {JSON.stringify(profile.options_schema, null, 2)}
                                        </pre>
                                    </details>
                                </li>
                            ))}
                        </ul>
                        <details className="mt-1 text-text-3">
                            <summary className="cursor-pointer">Default renderer limits for {format.format_id}</summary>
                            <dl className="mt-1 space-y-1">
                                {Object.entries({ ...format.default_limits, ...format.office_default_limits })
                                    .map(([name, value]) => (
                                        <div key={name}><dt>{name}</dt><dd>{value}</dd></div>
                                    ))}
                            </dl>
                        </details>
                    </li>
                ))}
            </ul>
        </details>
    );
}
