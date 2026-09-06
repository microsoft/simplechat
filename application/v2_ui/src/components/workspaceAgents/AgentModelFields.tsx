// AgentModelFields.tsx

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { RefreshCw } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import type { AgentConfiguration, AgentEditorOptions, AuthoringResource } from '../../lib/workspaceAuthoring';
import {
    AGENT_INPUT_CLASS, FOUNDRY_SETTINGS_KEYS, agentModelChoices, agentText, applyFoundryDiscovery, clearAgentDraftFields,
    foundryEndpointMatches, foundrySettings, selectAgentModel, selectedAgentModel, selectFoundryEndpoint,
    updateAgentSetting, type FoundryDiscoveryRecord,
} from '../../lib/workspaceAgentAuthoring';
import { normalizeAgentKnowledgeUrl } from '../../lib/workspaceAgentKnowledge';
import { discoverAgentFoundryResources } from '../../lib/workspaceAgentCommands';
import { GlassButton, Toggle } from '../ui/primitives';
import { AgentField, AgentNotice, AgentSecretField, AgentTextField } from './AgentFields';

interface ModelFieldsProps {
    draft: AgentConfiguration;
    setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    options: AgentEditorOptions;
    original: AuthoringResource<AgentConfiguration> | null;
}

function LocalModelFields({ draft, setDraft, options, original }: ModelFieldsProps) {
    const choices = agentModelChoices(options);
    const selected = selectedAgentModel(draft, choices);
    const customAllowed = options.settings.allow_user_custom_endpoints === true;
    const [customOpen, setCustomOpen] = useState(Boolean(
        !draft.model_endpoint_id && (draft.azure_openai_gpt_endpoint || draft.azure_openai_gpt_key || draft.enable_agent_gpt_apim),
    ));
    const update = (key: keyof AgentConfiguration, value: unknown) => setDraft((current) => ({ ...current, [key]: value }));
    return (
        <div className="space-y-4">
            <AgentField id="agent-model-select" label="Model" help="Choose an enabled model on an authorized connection. An unavailable saved model is preserved until you choose a replacement.">
                <select id="agent-model-select" className={AGENT_INPUT_CLASS} value={selected?.key ?? ''}
                    onChange={(event) => {
                        const choice = choices.find((item) => item.key === event.target.value);
                        if (choice) setDraft((current) => selectAgentModel(current, choice));
                    }}>
                    <option value="">{draft.model_id || draft.azure_openai_gpt_deployment || draft.azure_agent_apim_gpt_deployment || 'Use configured default / choose a model'}</option>
                    {choices.map((choice) => <option key={choice.key} value={choice.key}>{choice.label}</option>)}
                </select>
            </AgentField>
            {!choices.length ? <AgentNotice>No enabled models are listed. You can retain the saved connection or configure a custom connection below.</AgentNotice> : null}
            <dl className="grid gap-3 rounded-xl border border-edge p-3 text-xs sm:grid-cols-3">
                <div className="min-w-0"><dt className="text-text-3">Endpoint ID</dt><dd className="break-all text-text-1">{draft.model_endpoint_id || 'Legacy / configured default'}</dd></div>
                <div className="min-w-0"><dt className="text-text-3">Model ID</dt><dd className="break-all text-text-1">{draft.model_id || draft.azure_openai_gpt_deployment || draft.azure_agent_apim_gpt_deployment || 'Configured default'}</dd></div>
                <div className="min-w-0"><dt className="text-text-3">Provider</dt><dd className="break-all text-text-1">{draft.model_provider || 'Configured default'}</dd></div>
            </dl>
            <details open={customOpen} onToggle={(event) => setCustomOpen(event.currentTarget.open)} className="rounded-xl border border-edge p-3">
                <summary className="cursor-pointer text-sm font-medium text-text-2">Custom / legacy connection and APIM</summary>
                <div className="mt-4 space-y-4">
                    <p className="text-xs text-text-3">A selected endpoint takes precedence. Custom values and stored credentials are retained when you choose a model; they are never copied from app settings.</p>
                    {!customAllowed ? <AgentNotice>Your administrator has disabled personal custom-connection changes. Existing values and credentials remain stored.</AgentNotice> : null}
                    <fieldset disabled={!customAllowed} className="space-y-4">
                    <legend className="sr-only">Custom connection settings</legend>
                    {draft.model_endpoint_id ? (
                        <GlassButton type="button" size="sm" onClick={() => setDraft((current) => ({
                            ...current, model_endpoint_id: '', model_id: '', model_provider: '',
                        }))}>Use custom connection instead of selected endpoint</GlassButton>
                    ) : null}
                    <Toggle label="Use APIM for this agent" checked={draft.enable_agent_gpt_apim === true}
                        description="Switches which custom connection fields are used. Inactive connection values remain in the draft."
                        onChange={(value) => update('enable_agent_gpt_apim', value)} />
                    <div className="grid gap-4 sm:grid-cols-2">
                        {draft.enable_agent_gpt_apim ? (
                            <>
                                <AgentTextField label="APIM endpoint" value={draft.azure_agent_apim_gpt_endpoint}
                                    onChange={(value) => update('azure_agent_apim_gpt_endpoint', value)} />
                                <AgentTextField label="APIM deployment" value={draft.azure_agent_apim_gpt_deployment}
                                    onChange={(value) => update('azure_agent_apim_gpt_deployment', value)} />
                                <AgentTextField label="APIM API version" value={draft.azure_agent_apim_gpt_api_version}
                                    onChange={(value) => update('azure_agent_apim_gpt_api_version', value)} />
                                <AgentSecretField label="APIM subscription key" value={draft.azure_agent_apim_gpt_subscription_key}
                                    original={original?.record.azure_agent_apim_gpt_subscription_key}
                                    onChange={(value) => update('azure_agent_apim_gpt_subscription_key', value)} />
                            </>
                        ) : (
                            <>
                                <AgentTextField label="Azure OpenAI endpoint" value={draft.azure_openai_gpt_endpoint}
                                    onChange={(value) => update('azure_openai_gpt_endpoint', value)} />
                                <AgentTextField label="Deployment name" value={draft.azure_openai_gpt_deployment}
                                    onChange={(value) => update('azure_openai_gpt_deployment', value)} />
                                <AgentTextField label="Azure OpenAI API version" value={draft.azure_openai_gpt_api_version}
                                    onChange={(value) => update('azure_openai_gpt_api_version', value)} />
                                <AgentSecretField label="Azure OpenAI API key" value={draft.azure_openai_gpt_key}
                                    original={original?.record.azure_openai_gpt_key}
                                    onChange={(value) => update('azure_openai_gpt_key', value)} />
                            </>
                        )}
                    </div>
                    </fieldset>
                </div>
            </details>
        </div>
    );
}

function FoundryModelFields({ draft, setDraft, options }: ModelFieldsProps) {
    const [resources, setResources] = useState<FoundryDiscoveryRecord[]>([]);
    const [responseVersion, setResponseVersion] = useState('');
    const [loading, setLoading] = useState(false);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [authUrl, setAuthUrl] = useState('');
    const request = useRef<AbortController | null>(null);
    const settings = foundrySettings(draft);
    const type = draft.agent_type;
    const endpointId = draft.model_endpoint_id || agentText(settings.endpoint_id);
    const endpoints = options.model_endpoints.filter((endpoint) => foundryEndpointMatches(type, endpoint));
    const selectedEndpoint = endpoints.find((endpoint) => endpoint.id === endpointId);
    useEffect(() => {
        setResources([]);
        setLoaded(false);
        setLoading(false);
        setError(null);
        setAuthUrl('');
        return () => request.current?.abort();
    }, [type, endpointId]);

    if (type === 'local') return null;
    const key = FOUNDRY_SETTINGS_KEYS[type];
    const update = (field: string, value: unknown) => setDraft((current) => {
        const reference = foundrySettings(current).agent_reference;
        const referenceKey = field === 'workflow_agent_id' ? 'id' : field;
        return updateAgentSetting(current, key, {
            [field]: value,
            authentication_type: 'delegated_user',
            ...(type === 'foundry_workflow' && ['workflow_agent_id', 'application_id', 'application_version'].includes(field) &&
                reference && typeof reference === 'object' && !Array.isArray(reference)
                ? { agent_reference: { ...reference, [referenceKey]: value } } : {}),
        });
    });
    const updateConnection = (field: 'endpoint' | 'project_name' | 'responses_api_version', value: string) => {
        const topLevel = field === 'endpoint' ? 'azure_openai_gpt_endpoint'
            : field === 'project_name' ? 'azure_openai_gpt_deployment' : 'azure_openai_gpt_api_version';
        setDraft((current) => updateAgentSetting({ ...current, [topLevel]: value }, key, {
            [field]: value, authentication_type: 'delegated_user',
        }));
    };
    const discover = async () => {
        if (!selectedEndpoint) return;
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        setLoading(true);
        setError(null);
        setAuthUrl('');
        try {
            const result = await discoverAgentFoundryResources(selectedEndpoint, type, controller.signal);
            if (!controller.signal.aborted) {
                setResources(result.agents);
                setResponseVersion(result.responses_api_version || '');
                setLoaded(true);
            }
        } catch (cause) {
            if (controller.signal.aborted) return;
            setError(cause instanceof Error ? cause.message : 'Unable to discover Foundry resources.');
            if (cause instanceof ApiError && cause.payload && typeof cause.payload === 'object') {
                const payload = cause.payload as Record<string, unknown>;
                if (payload.auth_required === true) setAuthUrl(normalizeAgentKnowledgeUrl(agentText(payload.auth_url || payload.consent_url)));
            }
        } finally {
            if (!controller.signal.aborted) setLoading(false);
        }
    };
    return (
        <div className="space-y-4">
            <AgentNotice>Authentication uses the signed-in user’s delegated Foundry access. Prompts and tools are managed in Foundry, not in this editor.</AgentNotice>
            <AgentField id="agent-foundry-connection" label="Saved Foundry connection" help="Optional. Choose a permitted saved connection to discover its agents, applications, or workflows.">
                <select id="agent-foundry-connection" className={AGENT_INPUT_CLASS} value={endpointId}
                    onChange={(event) => {
                        const endpoint = endpoints.find((item) => item.id === event.target.value);
                        request.current?.abort();
                        if (endpoint) setDraft((current) => selectFoundryEndpoint(current, endpoint));
                        else setDraft((current) => updateAgentSetting({ ...current, model_endpoint_id: '' }, key, { endpoint_id: '' }));
                    }}>
                    <option value="">Manual Foundry project connection</option>
                    {endpointId && !selectedEndpoint ? <option value={endpointId}>Saved connection unavailable · {endpointId}</option> : null}
                    {endpoints.map((endpoint) => <option key={endpoint.id} value={endpoint.id}>{endpoint.name || endpoint.id} · {agentText(endpoint.scope) || 'global'}</option>)}
                </select>
            </AgentField>
            <div className="flex flex-wrap items-center gap-3">
                <GlassButton type="button" size="sm" onClick={() => void discover()} disabled={!selectedEndpoint || loading}>
                    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                    {loading ? 'Discovering…' : type === 'foundry_workflow' ? 'Discover workflows' : type === 'new_foundry' ? 'Discover applications' : 'Discover agents'}
                </GlassButton>
                {loaded ? <span role="status" className="text-xs text-text-3">{resources.length} resources found.</span> : null}
            </div>
            {error ? <AgentNotice error>{error}{authUrl ? <> <a href={authUrl} target="_blank" rel="noopener noreferrer" className="underline">Sign in or grant Foundry access</a></> : null}</AgentNotice> : null}
            {resources.length ? (
                <AgentField id="agent-foundry-resource" label="Discovered resource" help="Selecting a resource updates only this draft. Review provider fields before saving.">
                    <select id="agent-foundry-resource" defaultValue="" className={AGENT_INPUT_CLASS}
                        onChange={(event) => {
                            const selected = resources[Number(event.target.value)];
                            if (selected) setDraft((current) => applyFoundryDiscovery(current, {
                                ...selected, responses_api_version: selected.responses_api_version || responseVersion || undefined,
                            }));
                        }}>
                        <option value="" disabled>Select a discovered resource</option>
                        {resources.map((resource, index) => <option key={`${resource.id || resource.name}-${index}`} value={index}>
                            {resource.display_name || resource.workflow_name || resource.application_name || resource.name || resource.id}
                            {resource.application_version ? ` · v${resource.application_version}` : ''}
                        </option>)}
                    </select>
                </AgentField>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
                <AgentTextField label="Foundry project endpoint" required value={settings.endpoint || draft.azure_openai_gpt_endpoint}
                    onChange={(value) => updateConnection('endpoint', value)} />
                <AgentTextField label="Foundry project name" value={settings.project_name || draft.azure_openai_gpt_deployment}
                    help="Needed when the endpoint does not already include /api/projects/<project>."
                    onChange={(value) => updateConnection('project_name', value)} />
                {type === 'aifoundry' ? (
                    <>
                        <AgentTextField label="Foundry agent ID" required value={settings.agent_id} onChange={(value) => update('agent_id', value)} />
                        <AgentTextField label="Foundry API version" required value={draft.azure_openai_gpt_api_version}
                            onChange={(value) => setDraft((current) => ({ ...current, azure_openai_gpt_api_version: value }))} />
                    </>
                ) : (
                    <>
                        <AgentTextField label="Responses API version" required value={settings.responses_api_version || draft.azure_openai_gpt_api_version}
                            onChange={(value) => updateConnection('responses_api_version', value)} />
                        {type === 'new_foundry' ? (
                            <>
                                <AgentTextField label="Application ID" required={!agentText(settings.application_name).trim()} value={settings.application_id}
                                    help="Provide an application ID or application name. The backend normalizes name/version references."
                                    onChange={(value) => update('application_id', value)} />
                                <AgentTextField label="Application name" value={settings.application_name} onChange={(value) => update('application_name', value)} />
                                <AgentTextField label="Application version" value={settings.application_version} onChange={(value) => update('application_version', value)} />
                                <AgentTextField label="Activity API version" value={settings.activity_api_version} onChange={(value) => update('activity_api_version', value)} />
                            </>
                        ) : (
                            <>
                                <AgentTextField label="Workflow name" required value={settings.workflow_name}
                                    onChange={(value) => setDraft((current) => {
                                        const reference = foundrySettings(current).agent_reference;
                                        return updateAgentSetting(current, key, {
                                            workflow_name: value,
                                            ...(reference && typeof reference === 'object' && !Array.isArray(reference)
                                                ? { agent_reference: { ...reference, name: value } } : {}),
                                        });
                                    })} />
                                <AgentTextField label="Workflow agent ID" value={settings.workflow_agent_id} onChange={(value) => update('workflow_agent_id', value)} />
                                <AgentTextField label="Workflow application ID" value={settings.application_id} onChange={(value) => update('application_id', value)} />
                                <AgentTextField label="Workflow application version" value={settings.application_version} onChange={(value) => update('application_version', value)} />
                                <AgentTextField label="Responses path override" value={settings.responses_path}
                                    help="Optional project Responses path; leave unset to use the runtime default."
                                    onChange={(value) => update('responses_path', value)} />
                                <AgentTextField label="Maximum context characters" type="number" min={1} step={1}
                                    value={settings.max_context_chars === undefined ? '' : String(settings.max_context_chars)}
                                    help="Optional limit for packed SimpleChat document context."
                                    onChange={(value) => {
                                        if (value) update('max_context_chars', Number(value));
                                        else setDraft((current) => {
                                            const next = { ...foundrySettings(current) };
                                            delete next.max_context_chars;
                                            return clearAgentDraftFields({ ...current, other_settings: { ...current.other_settings, [key]: next } }, '_editor_settings_text');
                                        });
                                    }} />
                            </>
                        )}
                    </>
                )}
            </div>
            {type === 'foundry_workflow' ? <Toggle label="Include SimpleChat document context"
                checked={settings.include_document_context !== false}
                description="Pack selected or uploaded document context into workflow prompts."
                onChange={(value) => update('include_document_context', value)} /> : null}
            <AgentTextField label="Foundry notes" value={settings.notes} onChange={(value) => update('notes', value)} />
            {draft.enable_agent_gpt_apim ? (
                <AgentNotice>Local APIM is incompatible with Foundry. Its fields and credentials can remain stored, but the local APIM switch must be disabled.
                    <div className="mt-2"><GlassButton type="button" size="sm" onClick={() => setDraft((current) => ({ ...current, enable_agent_gpt_apim: false }))}>Disable local APIM</GlassButton></div>
                </AgentNotice>
            ) : null}
        </div>
    );
}

export function AgentModelFields(props: ModelFieldsProps) {
    return props.draft.agent_type === 'local'
        ? <LocalModelFields {...props} />
        : <FoundryModelFields key={props.draft.agent_type} {...props} />;
}
