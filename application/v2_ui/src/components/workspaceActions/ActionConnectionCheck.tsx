// ActionConnectionCheck.tsx

import { useEffect, useRef, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { EditorPanel } from '../workspace/EditorLayout';
import { nativeActionDefinition } from '../../lib/workspaceActionRegistry';
import { testWorkspaceAction } from '../../lib/workspaceActionServices';
import { connectorFeedback, testApiConnector, validateApiConnector, type ConnectorFeedback } from '../../lib/workspaceActionConnectors';
import { isRecord, type ActionConfiguration, type ActionTypeDefinition } from '../../lib/workspaceAuthoring';
import { connectorTestScope, type ActionConnectorProps } from '../../lib/workspaceActionTypes';

export function useConnectorRequest(props: ActionConnectorProps) {
    const latest = useRef(props);
    latest.current = props;
    const activeRequest = useRef<{
        controller: AbortController;
        draft: ActionConfiguration;
        original: ActionConnectorProps['original'];
    } | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [feedback, setFeedback] = useState<{ value: ConnectorFeedback; draft: ActionConfiguration } | null>(null);

    useEffect(() => {
        const active = activeRequest.current;
        if (active && (active.draft !== props.draft || active.original !== props.original || props.readOnly || props.original?.read_only)) {
            active.controller.abort();
            activeRequest.current = null;
            setBusy(null);
        }
    }, [props.draft, props.original, props.readOnly]);
    useEffect(() => () => {
        activeRequest.current?.controller.abort();
        activeRequest.current = null;
    }, []);

    async function run<T>(
        label: string,
        operation: (signal: AbortSignal) => Promise<T>,
        apply?: (draft: ActionConfiguration, result: T) => ActionConfiguration,
        describe?: (result: T) => ConnectorFeedback,
    ): Promise<T | undefined> {
        const snapshot = latest.current;
        if (snapshot.readOnly || snapshot.original?.read_only) return undefined;
        activeRequest.current?.controller.abort();
        const request = new AbortController();
        activeRequest.current = { controller: request, draft: snapshot.draft, original: snapshot.original };
        setBusy(label);
        try {
            const response = await operation(request.signal);
            if (request.signal.aborted || latest.current.draft !== snapshot.draft ||
                latest.current.original !== snapshot.original || latest.current.readOnly) return undefined;
            const value = describe ? describe(response) : connectorFeedback(response);
            let resultDraft = snapshot.draft;
            if (value.success && apply) {
                resultDraft = apply(snapshot.draft, response);
                snapshot.onChange((current) => current === snapshot.draft ? resultDraft : current);
            }
            setFeedback({ value, draft: resultDraft });
            return value.success ? response : undefined;
        } catch (error) {
            if (!request.signal.aborted && latest.current.draft === snapshot.draft &&
                latest.current.original === snapshot.original) {
                setFeedback({ value: connectorFeedback(error), draft: snapshot.draft });
            }
            return undefined;
        } finally {
            if (activeRequest.current?.controller === request) {
                activeRequest.current = null;
                setBusy(null);
            }
        }
    }
    return { busy, feedback: feedback?.value ?? null, stale: Boolean(feedback && feedback.draft !== props.draft), run };
}

export function ConnectorFeedbackPanel({ feedback, stale }: { feedback: ConnectorFeedback | null; stale?: boolean }) {
    if (!feedback) return null;
    const checks = Array.isArray(feedback.details.checks) ? feedback.details.checks.flatMap((item) => {
        if (!isRecord(item)) return [];
        const status = item.status === 'pass' || item.status === 'warn' || item.status === 'fail' ? item.status : 'warn';
        const name = typeof item.name === 'string' ? item.name : 'Check';
        const message = typeof item.message === 'string' ? item.message : '';
        return [{ status, name, message }];
    }) : [];
    const details = Object.entries(feedback.details).filter(([name, value]) =>
        name !== 'checks' && ['string', 'number', 'boolean'].includes(typeof value));
    return (
        <div role={feedback.success ? 'status' : 'alert'} aria-live="polite"
            className={`alert rounded-xl border p-3 text-sm ${feedback.success
                ? 'alert-success border-edge bg-surface-2 text-text-1'
                : 'alert-danger border-danger/30 bg-danger-soft text-danger'}`}>
            <p className="break-words">{feedback.message}</p>
            {stale ? <p className="mt-1 text-xs text-text-3">This result describes an earlier draft. Run the command again to check your current configuration.</p> : null}
            {feedback.errors.length ? <ul className="mt-2 list-disc space-y-1 pl-5">
                {feedback.errors.map((message, index) => <li key={index} className="break-words">{message}</li>)}
            </ul> : null}
            {feedback.warnings.length ? <div className="alert alert-warning mt-2 rounded-lg bg-warn-soft p-2 text-warn">
                <p className="font-medium">Warnings</p>
                <ul className="list-disc space-y-1 pl-5">
                    {feedback.warnings.map((message, index) => <li key={index} className="break-words">{message}</li>)}
                </ul>
            </div> : null}
            {checks.length ? <ul className="mt-2 space-y-1 text-xs">
                {checks.map((check, index) => <li key={`${check.name}-${index}`} className="flex items-start gap-2 rounded-lg bg-surface-1 px-2 py-1.5">
                    <span className={`mt-0.5 rounded-full px-1.5 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-wide ${
                        check.status === 'pass' ? 'bg-accent-soft text-accent' :
                            check.status === 'fail' ? 'bg-danger-soft text-danger' : 'bg-warn-soft text-warn'
                    }`}>
                        {check.status}
                    </span>
                    <span className="min-w-0 break-words text-text-2">
                        <span className="font-medium text-text-1">{check.name}</span>{check.message ? ` — ${check.message}` : ''}
                    </span>
                </li>)}
            </ul> : null}
            {details.length ? <dl className="mt-2 grid gap-1 text-xs text-text-2">
                {details.map(([name, value]) => <div key={name} className="flex flex-wrap gap-x-2">
                    <dt className="font-medium">{name.replaceAll('_', ' ')}:</dt><dd className="break-all">{String(value)}</dd>
                </div>)}
            </dl> : null}
        </div>
    );
}

export function ActionConnectionCheck({
    props, definition, kind = 'native', disabled = false, configurationError = false,
}: {
    props: ActionConnectorProps;
    definition?: ActionTypeDefinition;
    kind?: 'native' | 'openapi' | 'mcp';
    disabled?: boolean;
    configurationError?: boolean;
}) {
    const { draft, original } = props;
    const readOnly = props.readOnly || Boolean(original?.read_only);
    const request = useConnectorRequest(props);
    if (kind === 'native') {
        const native = nativeActionDefinition(draft.type);
        if (!native.testPath || !definition) return null;
        return (
            <EditorPanel title="Connection check"
                description="Test connection makes a small request using this draft. An edited action uses its owned stored credentials when their masked values are unchanged. Saving does not run this test.">
                <div>
                    <GlassButton type="button" size="sm" variant="subtle" disabled={readOnly || Boolean(request.busy)}
                        onClick={() => void request.run('Testing connection…', (signal) => testWorkspaceAction(draft, original, definition, signal, connectorTestScope(props)))}>
                        <FlaskConical size={15} />{request.busy || 'Test connection'}
                    </GlassButton>
                </div>
                <ConnectorFeedbackPanel feedback={request.feedback} stale={request.stale} />
            </EditorPanel>
        );
    }
    const label = kind === 'mcp' ? 'MCP' : 'OpenAPI';
    return (
        <EditorPanel title="Validate and test"
            description={kind === 'mcp'
                ? 'The connection test initializes a server session and lists its tools. It does not invoke tools or save discovered metadata.'
                : 'Validation checks the manifest without running it. Connection testing parses the specification and probes the authenticated base URL; it does not invoke an individual API operation.'}>
            <div className="flex flex-wrap items-center gap-2">
                <GlassButton type="button" variant="subtle" disabled={readOnly || Boolean(request.busy) || disabled || configurationError}
                    onClick={() => void request.run(`Validating ${label} configuration…`, (signal) => validateApiConnector(draft, original, kind, signal, connectorTestScope(props)))}>
                    Validate {label} configuration
                </GlassButton>
                <GlassButton type="button" variant="subtle" disabled={readOnly || Boolean(request.busy) || disabled || configurationError}
                    onClick={() => void request.run(`Testing ${label} connection…`, (signal) => testApiConnector(draft, original, kind, signal, connectorTestScope(props)))}>
                    Test {label} connection
                </GlassButton>
                {request.busy ? <p role="status" className="text-sm text-text-3">{request.busy}</p> : null}
            </div>
            {readOnly ? <p className="text-xs text-text-3">Provided actions are read-only. Validation and connection testing are disabled.</p> : null}
            {!readOnly && configurationError ? <p className="text-xs text-text-3">Resolve the highlighted configuration errors before validating or connecting.</p> : null}
            <ConnectorFeedbackPanel feedback={request.feedback} stale={request.stale} />
        </EditorPanel>
    );
}
