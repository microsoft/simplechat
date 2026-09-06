// McpActionConfiguration.tsx

import { useEffect, useRef, useState } from 'react';
import { GlassButton, GlassPanel, Toggle } from '../ui/primitives';
import { ACTION_INPUT_CLASS, ActionField, ActionJsonInput, ActionSecretInput } from './ActionFields';
import { ActionSchemaValue } from './ActionSchemaFields';
import {
    ConnectorFeedbackPanel, ConnectorIdentitySelect, useConnectorRequest, useConnectorValidity,
} from './OpenApiActionConfiguration';
import { EDITOR_SECRET_MASK, pointerPart } from '../../lib/workspaceAuthoring';
import { actionHasStoredArraySecrets } from '../../lib/workspaceActionLogic';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';
import {
    allowedMcpAuthMethods, allowedMcpTransports, applyMcpPreconfiguration, applyMcpPreset,
    changeConnectorAuthMethod, connectorAuthMethod, connectorFeedback, connectorLines, connectorObject,
    connectorStrings, connectorText, discoverMcpAction, fetchMcpPreconfigurations, fetchMcpPresets,
    MCP_AUTH_OPTIONS, MCP_GENERIC_PRESET, MCP_NUMBER_FIELDS, mcpHeaderNameError,
    mcpImplementationFields, mcpToolChoices, mergeMcpTools, parseMcpTools, setMcpToolSelection,
    testApiConnector, updateConnectorFields, validateApiConnector, validateConnectorAuthentication,
    validateConnectorConfiguration, type McpCatalogEntry, type McpDiscoveryResult,
} from '../../lib/workspaceActionConnectors';

function useMcpCatalogues(props: ActionConnectorProps, includePreconfigurations: boolean) {
    const [presets, setPresets] = useState<McpCatalogEntry[]>([MCP_GENERIC_PRESET]);
    const [preconfigurations, setPreconfigurations] = useState<McpCatalogEntry[]>([]);
    const [presetsError, setPresetsError] = useState<string | null>(null);
    const [preconfigurationsError, setPreconfigurationsError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [retry, setRetry] = useState(0);
    const recordId = props.original?.record.id;
    const type = props.draft.type;
    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        const loadPresets = fetchMcpPresets(controller.signal).then((result) => {
            if (controller.signal.aborted) return;
            setPresets(result.some(({ id }) => id === 'generic') ? result : [MCP_GENERIC_PRESET, ...result]);
            setPresetsError(null);
        }).catch((error: unknown) => {
            if (!controller.signal.aborted) setPresetsError(error instanceof Error ? error.message : 'Could not load MCP presets.');
        });
        const loadPreconfigurations = includePreconfigurations
            ? fetchMcpPreconfigurations(controller.signal).then((result) => {
                if (controller.signal.aborted) return;
                setPreconfigurations(result);
                setPreconfigurationsError(null);
            }).catch((error: unknown) => {
                if (!controller.signal.aborted) setPreconfigurationsError(error instanceof Error ? error.message : 'Could not load MCP preconfigurations.');
            })
            : Promise.resolve();
        void Promise.all([loadPresets, loadPreconfigurations]).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [recordId, type, retry, includePreconfigurations]);
    return { presets, preconfigurations, presetsError, preconfigurationsError, loading, retry: () => setRetry((value) => value + 1) };
}

function McpLinesField({
    id, label, value, onChange, readOnly, help, error, rows = 4,
}: {
    id: string; label: string; value: unknown; onChange: (value: string[]) => void;
    readOnly?: boolean; help?: string; error?: string; rows?: number;
}) {
    const serialized = connectorStrings(value).join('\n');
    const [text, setText] = useState(serialized);
    const lastApplied = useRef(serialized);
    useEffect(() => {
        if (lastApplied.current !== serialized) {
            lastApplied.current = serialized;
            setText(serialized);
        }
    }, [serialized]);
    return <ActionField id={id} label={label} help={help} error={error}>
        <textarea id={id} rows={rows} readOnly={readOnly} spellCheck={false}
            value={text} className={`${ACTION_INPUT_CLASS} font-mono text-xs`}
            aria-describedby={`${id}-help ${id}-error`} aria-invalid={Boolean(error)}
            onChange={(event) => {
                const next = event.target.value;
                const lines = connectorLines(next);
                setText(next);
                lastApplied.current = lines.join('\n');
                onChange(lines);
            }} />
    </ActionField>;
}

function McpCatalogueDetails({ entry }: { entry: McpCatalogEntry | undefined }) {
    if (!entry) return null;
    return <div className="space-y-2 text-xs leading-relaxed text-text-3">
        <p className="break-words">{connectorText(entry.ui.helpText) || entry.description}</p>
        {entry.riskLabel || entry.catalogTier || entry.authRequirement ? <p>
            {entry.catalogTier ? `Catalogue: ${entry.catalogTier}. ` : ''}
            {entry.riskLabel ? `Risk: ${entry.riskLabel}. ` : ''}
            {entry.authRequirement ? `Authentication: ${entry.authRequirement}.` : ''}
        </p> : null}
        {entry.requiredGovernanceGates?.length ? <p className="break-words">Required governance: {entry.requiredGovernanceGates.join(', ')}.</p> : null}
        {entry.operatorNotes?.length ? <ul className="list-disc space-y-1 pl-5">
            {entry.operatorNotes.map((note, index) => <li key={index} className="break-words">{note}</li>)}
        </ul> : null}
        {entry.warnings.length ? <ul className="alert alert-warning list-disc space-y-1 rounded-lg bg-warn-soft py-2 pr-3 pl-7 text-warn">
            {entry.warnings.map((warning, index) => <li key={index} className="break-words">{warning}</li>)}
        </ul> : null}
        {entry.documentationUrl ? <p className="break-all">Documentation: {entry.documentationUrl}</p> : null}
    </div>;
}

function McpImplementationConfiguration(props: ActionConnectorProps) {
    const { draft, original, onChange, errors } = props;
    const readOnly = props.readOnly || Boolean(original?.read_only);
    const implementation = connectorObject(draft.additionalFields.implementation);
    const implementationId = connectorText(implementation.id);
    const fields = mcpImplementationFields(implementationId);
    const settings = connectorObject(draft.additionalFields.additionalSettings);
    const localErrors = validateConnectorConfiguration(draft, 'mcp');
    const knownKeys = new Set(fields.map(({ key }) => key));
    const extraSettings = Object.entries(settings).filter(([key]) => !knownKeys.has(key));
    const originalSettings = connectorObject(original?.record.additionalFields.additionalSettings);
    if (!implementationId && !Object.keys(settings).length) return null;
    const updateSetting = (key: string, value: unknown) => onChange((current) => updateConnectorFields(current, {
        additionalSettings: { ...connectorObject(current.additionalFields.additionalSettings), [key]: value },
    }));
    return <GlassPanel elevation="flat" className="space-y-4 p-4">
        <div>
            <h3 className="text-sm font-semibold text-text-1">Implementation settings</h3>
            <p className="mt-1 break-words text-xs text-text-3">
                {implementationId || 'Custom implementation'}{implementation.schemaVersion ? ` · schema ${connectorText(implementation.schemaVersion)}` : ''}
            </p>
            <p className="mt-1 text-xs text-text-3">These settings come from the applied server catalogue entry. Fixed safety requirements are not editable; provider-specific selections remain explicit.</p>
        </div>
        {fields.map((field) => {
            const id = `mcp-implementation-${field.key}`;
            const value = settings[field.key];
            const errorKey = `additionalFields.additionalSettings.${field.key}`;
            const error = errors[errorKey] || localErrors[errorKey];
            if (field.kind === 'fixed') return <ActionField key={field.key} id={id} label={field.label} help={field.help} error={error}>
                <input id={id} readOnly className={ACTION_INPUT_CLASS}
                    value={value === undefined ? 'Not configured' : typeof value === 'boolean' ? value ? 'Yes' : 'No' : connectorText(value)} />
                {!readOnly && value !== field.expected ? <GlassButton type="button" size="sm" variant="subtle"
                    onClick={() => updateSetting(field.key, field.expected)}>
                    Use {field.optional ? 'recommended' : 'required'} value: {String(field.expected)}
                </GlassButton> : null}
            </ActionField>;
            if (field.kind === 'select') return <ActionField key={field.key} id={id} label={field.label} help={field.help} error={error}>
                <select id={id} className={ACTION_INPUT_CLASS} value={connectorText(value)} disabled={readOnly}
                    onChange={(event) => updateSetting(field.key, event.target.value)}>
                    {!field.options?.some((option) => option.value === value) ? <option value={connectorText(value)} disabled>{value ? `Unavailable — ${connectorText(value)}` : 'Choose a value'}</option> : null}
                    {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
            </ActionField>;
            if (field.kind === 'lines') return <McpLinesField key={field.key} id={id} label={field.label} value={value}
                help={field.help} error={error} readOnly={readOnly} onChange={(next) => updateSetting(field.key, next)} />;
            const selected = connectorStrings(value);
            const unavailable = selected.filter((item) => !field.options?.some((option) => option.value === item));
            return <fieldset key={field.key} className="space-y-2" disabled={readOnly}>
                <legend className="text-sm font-medium text-text-1">{field.label}</legend>
                {[...(field.options ?? []), ...unavailable.map((item) => ({ value: item, label: `${item} (unavailable — retained)` }))].map((option) =>
                    <label key={option.value} className="flex items-start gap-2 text-sm text-text-2">
                        <input type="checkbox" className="mt-1 accent-accent" checked={selected.includes(option.value)}
                            onChange={(event) => updateSetting(field.key, event.target.checked
                                ? [...new Set([...selected, option.value])] : selected.filter((item) => item !== option.value))} />
                        <span className="break-words">{option.label}</span>
                    </label>)}
                {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
            </fieldset>;
        })}
        {extraSettings.length ? <div className="space-y-4 border-t border-edge pt-4">
            <p className="text-xs text-text-3">Additional implementation properties are retained. The server remains authoritative for custom implementation validation.</p>
            {extraSettings.map(([key, value]) => {
                const id = `mcp-implementation-extra-${key}`;
                if (value === EDITOR_SECRET_MASK || originalSettings[key] === EDITOR_SECRET_MASK) return <ActionSecretInput key={key}
                    id={id} label={key} value={value} storedValue={originalSettings[key]} disabled={readOnly}
                    onChange={(next) => updateSetting(key, next)} />;
                if (typeof value === 'boolean') return <Toggle key={key} label={key} checked={value} disabled={readOnly}
                    onChange={(next) => updateSetting(key, next)} />;
                if (typeof value === 'string' || typeof value === 'number') return <ActionField key={key} id={id} label={key}>
                    <input id={id} className={ACTION_INPUT_CLASS} type={typeof value === 'number' ? 'number' : 'text'}
                        value={value} disabled={readOnly} onChange={(event) => updateSetting(key,
                            typeof value === 'number' && event.target.value !== '' ? Number(event.target.value) : event.target.value)} />
                </ActionField>;
                return <ActionSchemaValue key={key} props={props} schema={{}}
                    path={`/additionalFields/additionalSettings/${pointerPart(key)}`} label={key} />;
            })}
        </div> : null}
    </GlassPanel>;
}

export function McpActionConfiguration(props: ActionConnectorProps) {
    const { draft, original, onChange, errors } = props;
    const readOnly = props.readOnly || Boolean(original?.read_only);
    const fields = draft.additionalFields;
    const catalogue = useMcpCatalogues(props, true);
    const profile = connectorText(fields.server_profile) || 'generic';
    const preconfigurationId = connectorText(fields.preconfiguration_id);
    const transport = connectorText(fields.transport) || 'streamable_http';
    const preset = catalogue.presets.find(({ id }) => id === profile);
    const [presetChoice, setPresetChoice] = useState(profile);
    const [preconfigurationChoice, setPreconfigurationChoice] = useState(preconfigurationId);
    const [applyError, setApplyError] = useState<string | null>(null);
    const [toolSearch, setToolSearch] = useState('');
    const [toolLimit, setToolLimit] = useState(30);
    const [discovery, setDiscovery] = useState<{ result: McpDiscoveryResult; endpoint: string; transport: string } | null>(null);
    const { busy, feedback, stale, run } = useConnectorRequest(props);
    useEffect(() => setPresetChoice(profile), [profile]);
    useEffect(() => setPreconfigurationChoice(preconfigurationId), [preconfigurationId]);
    const chosenPreset = catalogue.presets.find(({ id }) => id === presetChoice);
    const chosenPreconfiguration = catalogue.preconfigurations.find(({ id }) => id === preconfigurationChoice);
    const localErrors = validateConnectorConfiguration(draft, 'mcp', preset);
    useConnectorValidity(props, 'mcp-configuration', Object.values(localErrors).join(' ') || null);
    const fieldError = (key: string) => errors[`additionalFields.${key}`] || localErrors[`additionalFields.${key}`];
    const updateField = (key: string, value: unknown) => onChange((current) => updateConnectorFields(current, { [key]: value }));
    const availableTransports = allowedMcpTransports(preset);
    const selectedTools = connectorStrings(fields.allowed_tool_names);
    const lastDiscoveryMatches = discovery?.endpoint === draft.endpoint && discovery?.transport === transport;
    const choices = mcpToolChoices(fields.mcp_tools, selectedTools,
        lastDiscoveryMatches ? parseMcpTools(discovery?.result.tools).map(({ original_name }) => original_name) : undefined);
    const filteredTools = choices.filter(({ name, tool }) =>
        `${name} ${tool?.function_name || ''} ${tool?.description || ''}`.toLowerCase().includes(toolSearch.toLowerCase()));
    const blockedExecution = readOnly || Boolean(busy) || Object.keys(localErrors).length > 0;
    const doDiscovery = async () => {
        const result = await run('Discovering MCP tools…', (signal) => discoverMcpAction(draft, original, signal),
            (current, response) => updateConnectorFields(current, {
                mcp_tools: mergeMcpTools(current.additionalFields.mcp_tools, response.tools, connectorStrings(current.additionalFields.allowed_tool_names)),
            }),
            (response) => ({
                ...connectorFeedback(response),
                message: response.success === true ? `Discovered ${parseMcpTools(response.tools).length} tools. Your existing allowlist has not been changed.` : response.error || 'Tool discovery failed.',
                details: {
                    transport: response.transport ?? transport,
                    ...(response.mcp_operation_id ? { operation_id: response.mcp_operation_id } : {}),
                },
            }));
        if (result) setDiscovery({ result, endpoint: draft.endpoint, transport });
    };

    return (
        <div className="min-w-0 space-y-6" data-testid="mcp-configuration">
            <p className="text-sm leading-relaxed text-text-2">Connect to a Model Context Protocol server and expose its tools or prompts to agents. Server discovery and connection testing are explicit commands; selecting a template or saving an action never runs either.</p>
            <GlassPanel elevation="flat" className="space-y-4 p-4">
                <h3 className="text-sm font-semibold text-text-1">Server starting points</h3>
                <p className="text-xs text-text-3">Choose a preconfiguration or compatibility preset, review it, then apply its defaults. Existing custom fields, secret state, identity references, and selected tools are retained.</p>
                {catalogue.loading ? <p role="status" className="text-xs text-text-3">Loading MCP catalogues…</p> : null}
                {catalogue.presetsError || catalogue.preconfigurationsError ? <div role="alert" className="alert alert-warning space-y-2 rounded-xl bg-warn-soft p-3 text-sm text-warn">
                    {catalogue.presetsError ? <p>{catalogue.presetsError} The built-in generic preset remains available.</p> : null}
                    {catalogue.preconfigurationsError ? <p>{catalogue.preconfigurationsError} This is not an empty catalogue; your saved selection is retained.</p> : null}
                    <GlassButton type="button" size="sm" disabled={catalogue.loading} onClick={catalogue.retry}>Retry catalogues</GlassButton>
                </div> : null}
                <ActionField id="mcp-preconfiguration" label="Preconfigured server">
                    <select id="mcp-preconfiguration" className={ACTION_INPUT_CLASS} value={preconfigurationChoice} disabled={readOnly || catalogue.loading}
                        onChange={(event) => setPreconfigurationChoice(event.target.value)}>
                        <option value="">Custom configuration</option>
                        {preconfigurationChoice && !chosenPreconfiguration ? <option value={preconfigurationChoice} disabled>Unavailable — {preconfigurationChoice}</option> : null}
                        {catalogue.preconfigurations.map((entry) => <option key={entry.id} value={entry.id}>{entry.displayName}</option>)}
                    </select>
                </ActionField>
                <McpCatalogueDetails entry={chosenPreconfiguration} />
                {chosenPreconfiguration ? <p className="break-all text-xs text-text-3">Endpoint to apply: {chosenPreconfiguration.endpoint || 'No endpoint default'}</p> : null}
                {preconfigurationId && !catalogue.preconfigurations.some(({ id }) => id === preconfigurationId) ? <p className="text-xs text-warn">Saved preconfiguration {preconfigurationId} is unavailable. Its implementation settings remain intact.</p> : null}
                <GlassButton type="button" variant="subtle"
                    disabled={readOnly || Boolean(busy) || catalogue.loading || Boolean(preconfigurationChoice && !chosenPreconfiguration)}
                    onClick={() => {
                        if (!chosenPreconfiguration) {
                            updateField('preconfiguration_id', '');
                            setApplyError(null);
                            return;
                        }
                        const basePreset = catalogue.presets.find(({ id }) => id === (chosenPreconfiguration.presetId || 'generic'));
                        if (!basePreset) { setApplyError('Load the preconfiguration’s compatibility preset before applying it.'); return; }
                        try {
                            applyMcpPreconfiguration(draft, chosenPreconfiguration, basePreset);
                            onChange((current) => applyMcpPreconfiguration(current, chosenPreconfiguration, basePreset));
                            setApplyError(null);
                        } catch (error) {
                            setApplyError(error instanceof Error ? error.message : 'Could not apply the preconfiguration.');
                        }
                    }}>
                    {preconfigurationChoice ? 'Apply server preconfiguration' : 'Use custom configuration'}
                </GlassButton>
                <div className="space-y-3 border-t border-edge pt-4">
                    <ActionField id="mcp-preset" label="Compatibility preset">
                        <select id="mcp-preset" className={ACTION_INPUT_CLASS} value={presetChoice} disabled={readOnly || catalogue.loading}
                            onChange={(event) => setPresetChoice(event.target.value)}>
                            {!chosenPreset ? <option value={presetChoice} disabled>Unavailable — {presetChoice}</option> : null}
                            {catalogue.presets.map((entry) => <option key={entry.id} value={entry.id}>{entry.displayName}</option>)}
                        </select>
                    </ActionField>
                    <McpCatalogueDetails entry={chosenPreset} />
                    {!preset ? <p className="text-xs text-warn">Saved preset {profile} is unavailable. It has not been replaced.</p> : null}
                    <GlassButton type="button" variant="subtle" disabled={readOnly || Boolean(busy) || !chosenPreset || catalogue.loading}
                        onClick={() => {
                            if (!chosenPreset) return;
                            try {
                                applyMcpPreset(draft, chosenPreset);
                                onChange((current) => applyMcpPreset(current, chosenPreset));
                                setApplyError(null);
                            } catch (error) {
                                setApplyError(error instanceof Error ? error.message : 'Could not apply the preset.');
                            }
                        }}>Apply preset defaults</GlassButton>
                </div>
                {applyError ? <p role="alert" className="text-sm text-danger">{applyError}</p> : null}
            </GlassPanel>
            <div className="grid gap-4 sm:grid-cols-2">
                <ActionField id="mcp-transport" label="Transport" required error={fieldError('transport')}
                    help="Personal actions support remote transports only. Local commands and stdio are reserved for admin-managed global actions.">
                    <select id="mcp-transport" className={ACTION_INPUT_CLASS} value={transport} disabled={readOnly}
                        onChange={(event) => {
                            const value = event.target.value;
                            if (availableTransports.some((option) => option.value === value)) updateField('transport', value);
                        }}>
                        {!availableTransports.some(({ value }) => value === transport) ? <option value={transport} disabled>
                            {transport === 'stdio' ? 'Stdio — admin-managed legacy configuration' : `Unavailable transport — ${transport}`}
                        </option> : null}
                        {availableTransports.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                </ActionField>
                <ActionField id="mcp-endpoint" label="MCP server endpoint" required error={errors.endpoint || localErrors.endpoint}
                    help="The server applies destination governance when connecting. Enter a server you are authorized to use.">
                    <input id="mcp-endpoint" className={ACTION_INPUT_CLASS} type="url" value={draft.endpoint}
                        disabled={readOnly || transport === 'stdio'}
                        placeholder={connectorText(preset?.ui[transport === 'websocket' ? 'websocketEndpointPlaceholder' : 'endpointPlaceholder']) ||
                            (transport === 'websocket' ? 'wss://example.com/mcp' : 'https://example.com/mcp')}
                        onChange={(event) => {
                            const endpoint = event.target.value;
                            onChange((current) => ({ ...current, endpoint }));
                        }} />
                </ActionField>
            </div>
            {transport === 'stdio' ? <div className="alert alert-warning space-y-2 rounded-xl bg-warn-soft p-3 text-sm text-warn">
                <p>This legacy configuration is preserved for review. Personal workspaces cannot edit or execute a local MCP command. Select a permitted remote transport to reconfigure an owned action.</p>
                <dl className="space-y-1 text-xs">
                    <div><dt className="font-medium">Command</dt><dd className="break-all">{connectorText(fields.command) || 'Not specified'}</dd></div>
                    <div><dt className="font-medium">Arguments</dt><dd className="break-all">{connectorStrings(fields.args).join(' ') || 'None'}</dd></div>
                    <div><dt className="font-medium">Environment variable names</dt><dd className="break-all">{Object.keys(connectorObject(fields.env)).join(', ') || 'None'}. Values remain hidden.</dd></div>
                </dl>
            </div> : null}
            {transport === 'websocket' ? <p className="alert alert-warning rounded-xl bg-warn-soft p-3 text-sm text-warn">The current WebSocket connector supports neither authentication headers nor custom headers. Existing credentials and headers are retained until you explicitly change them.</p> : null}
            <McpImplementationConfiguration {...props} />
            <div className="space-y-3">
                <h3 className="text-sm font-semibold text-text-1">Tools and prompts</h3>
                <Toggle label="Load tools" description="Expose tools from this MCP server to agents using this action."
                    checked={(fields.load_tools ?? true) === true} disabled={readOnly} onChange={(value) => updateField('load_tools', value)} />
                <Toggle label="Load prompts" description="Load MCP server prompts in addition to any enabled tools."
                    checked={(fields.load_prompts ?? false) === true} disabled={readOnly} onChange={(value) => updateField('load_prompts', value)} />
                <Toggle label="Validate tool arguments" description="Check arguments against cached tool input schemas before invocation. Discover tools to populate the schema cache."
                    checked={(fields.validate_tool_arguments ?? false) === true} disabled={readOnly} onChange={(value) => updateField('validate_tool_arguments', value)} />
                <ActionField id="mcp-result-policy" label="Large-result policy" error={fieldError('tool_result_policy')}>
                    <select id="mcp-result-policy" className={ACTION_INPUT_CLASS} value={connectorText(fields.tool_result_policy ?? 'truncate')} disabled={readOnly}
                        onChange={(event) => updateField('tool_result_policy', event.target.value)}>
                        {!['truncate', 'error_on_limit'].includes(connectorText(fields.tool_result_policy ?? 'truncate')) ? <option value={connectorText(fields.tool_result_policy)} disabled>Unavailable — {connectorText(fields.tool_result_policy)}</option> : null}
                        <option value="truncate">Truncate results above the configured size limit</option>
                        <option value="error_on_limit">Report an error instead of truncating</option>
                    </select>
                </ActionField>
                <McpLinesField id="mcp-allowed-tools" label="Allowed tool names" value={fields.allowed_tool_names}
                    readOnly={readOnly} error={fieldError('allowed_tool_names')}
                    help="One original MCP tool name per line. An empty allowlist allows all server tools; disable Load tools if no tools should be exposed. Unavailable names remain selected until you remove them."
                    onChange={(value) => updateField('allowed_tool_names', value)} />
                {!selectedTools.length ? <p className="alert alert-warning rounded-lg bg-warn-soft p-2 text-xs text-warn">No tool allowlist is configured. All server tools may be exposed when Load tools is enabled.</p> : null}
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" variant="subtle" disabled={blockedExecution} onClick={() => void doDiscovery()}>Discover MCP tools</GlassButton>
                    <p className="text-xs text-text-3">Discovery connects and lists tools; it does not invoke them.</p>
                </div>
                {discovery ? <GlassPanel elevation="flat" className="space-y-2 p-3">
                    <h4 className="text-sm font-medium text-text-1">Last discovery capabilities</h4>
                    {!lastDiscoveryMatches ? <p className="text-xs text-warn">The endpoint or transport changed after this discovery. Run discovery again to verify the current server.</p> : null}
                    <dl className="grid gap-2 text-xs text-text-2 sm:grid-cols-2">
                        {Object.entries(connectorObject(discovery.result.capabilities)).map(([key, value]) =>
                            ['string', 'boolean', 'number'].includes(typeof value) ? <div key={key}>
                                <dt className="font-medium">{key.replaceAll('_', ' ')}</dt>
                                <dd className="break-words">{typeof value === 'boolean' ? value ? 'Yes' : 'No' : String(value)}</dd>
                            </div> : null)}
                    </dl>
                    {discovery.result.warnings?.length ? <ul className="list-disc space-y-1 pl-5 text-xs text-warn">
                        {discovery.result.warnings.map((warning, index) => <li key={index} className="break-words">{warning}</li>)}
                    </ul> : null}
                </GlassPanel> : null}
                {choices.length ? <div className="space-y-3">
                    <ActionField id="mcp-tool-search" label="Find a tool">
                        <input id="mcp-tool-search" type="search" className={ACTION_INPUT_CLASS} value={toolSearch}
                            placeholder="Tool name or description" onChange={(event) => { setToolSearch(event.target.value); setToolLimit(30); }} />
                    </ActionField>
                    <p className="text-xs text-text-3">{filteredTools.length} matching tools · {selectedTools.length} explicit allowlist entries. Check a tool to add it to the allowlist.</p>
                    {filteredTools.slice(0, toolLimit).map(({ name, tool, selected, unavailable }, index) => {
                        const id = `mcp-tool-${index}`;
                        const schema = connectorObject(tool?.input_schema);
                        const required = connectorStrings(schema.required);
                        return <GlassPanel key={name} elevation="flat" className="space-y-2 p-3">
                            <label htmlFor={id} className="flex items-start gap-3">
                                <input id={id} type="checkbox" className="mt-1 accent-accent" checked={selected} disabled={readOnly}
                                    onChange={(event) => {
                                        const checked = event.target.checked;
                                        onChange((current) => setMcpToolSelection(current, name, checked));
                                    }} />
                                <span className="min-w-0">
                                    <span className="block break-all text-sm font-medium text-text-1">{name}</span>
                                    {tool?.description ? <span className="mt-1 block whitespace-pre-wrap break-words text-xs text-text-2">{tool.description}</span> : null}
                                </span>
                            </label>
                            {unavailable ? <p className="text-xs text-warn">Not available in the current tool catalogue. This selection is retained for review.</p> :
                                !discovery ? <p className="text-xs text-text-3">Cached metadata; not verified in this editor session.</p> : null}
                            {tool ? <details className="text-xs text-text-3">
                                <summary className="cursor-pointer">Tool parameters and metadata</summary>
                                <div className="mt-2 space-y-2">
                                    <p className="break-all">Function name: {tool.function_name}</p>
                                    {Object.keys(connectorObject(schema.properties)).length ? <ul className="space-y-1">
                                        {Object.entries(connectorObject(schema.properties)).map(([parameter, spec]) => <li key={parameter} className="break-words">
                                            <span className="font-mono">{parameter}</span> ({connectorText(connectorObject(spec).type) || 'value'}{required.includes(parameter) ? ', required' : ', optional'})
                                            {connectorObject(spec).description ? ` — ${connectorText(connectorObject(spec).description)}` : ''}
                                        </li>)}
                                    </ul> : <p>No named input parameters are declared.</p>}
                                    {Object.keys(connectorObject(tool.annotations)).length ? <dl className="space-y-1">
                                        {Object.entries(connectorObject(tool.annotations)).map(([key, value]) =>
                                            ['string', 'boolean', 'number'].includes(typeof value) ? <div key={key} className="break-words"><dt className="inline font-medium">{key}: </dt><dd className="inline">{String(value)}</dd></div> : null)}
                                    </dl> : null}
                                    <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-1 p-2">{JSON.stringify({
                                        input_schema: tool.input_schema, output_schema: tool.output_schema,
                                    }, null, 2)}</pre>
                                </div>
                            </details> : null}
                        </GlassPanel>;
                    })}
                    {!filteredTools.length ? <p className="text-sm text-text-3">No tools match this search.</p> : null}
                    {filteredTools.length > toolLimit ? <GlassButton type="button" variant="subtle" onClick={() => setToolLimit((value) => value + 30)}>Show more tools</GlassButton> : null}
                </div> : <p className="text-sm text-text-3">No tool metadata is cached. Discover tools when ready, or enter known tool names above.</p>}
                <details className="space-y-3">
                    <summary className="cursor-pointer text-sm text-text-2">Advanced cached tool metadata</summary>
                    <ActionJsonInput id="mcp-tool-metadata" label="Discovered tool metadata JSON" value={fields.mcp_tools ?? []}
                        objectOnly={false} readOnly={readOnly} onValidityChange={props.onValidityChange}
                        protectArraySecrets={actionHasStoredArraySecrets(draft, original, '/additionalFields/mcp_tools')}
                        error={fieldError('mcp_tools')} rows={10}
                        help="Preserve original_name and function_name. Editing cached metadata does not discover or run tools."
                        onChange={(value) => updateField('mcp_tools', value)} />
                </details>
            </div>
            <div className="space-y-3">
                <h3 className="text-sm font-semibold text-text-1">Timeouts and retry policy</h3>
                <div className="grid gap-4 sm:grid-cols-2">
                    {MCP_NUMBER_FIELDS.map((field) => <ActionField key={field.key} id={`mcp-${field.key}`} label={field.label} error={fieldError(field.key)}>
                        <input id={`mcp-${field.key}`} type="number" inputMode="numeric" step={1} min={field.min} max={field.max}
                            className={ACTION_INPUT_CLASS} disabled={readOnly}
                            value={typeof fields[field.key] === 'number' || typeof fields[field.key] === 'string' ? fields[field.key] as number | string : field.defaultValue}
                            onChange={(event) => updateField(field.key, event.target.value === '' ? '' : Number(event.target.value))} />
                    </ActionField>)}
                </div>
            </div>
            <div className="space-y-3 border-t border-edge pt-4">
                <p className="text-xs text-text-3">The connection test initializes a server session and lists its tools. It does not invoke tools or save discovered metadata. Authentication is configured in the Authentication section.</p>
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" variant="subtle" disabled={blockedExecution}
                        onClick={() => void run('Validating MCP configuration…', (signal) => validateApiConnector(draft, original, 'mcp', signal))}>Validate MCP configuration</GlassButton>
                    <GlassButton type="button" variant="subtle" disabled={blockedExecution}
                        onClick={() => void run('Testing MCP connection…', (signal) => testApiConnector(draft, original, 'mcp', signal))}>Test MCP connection</GlassButton>
                    {busy ? <p role="status" className="text-sm text-text-3">{busy}</p> : null}
                </div>
                {readOnly ? <p className="text-xs text-text-3">Provided actions are read-only. Discovery and connection testing are disabled.</p> : null}
                {!readOnly && Object.keys(localErrors).length ? <p className="text-xs text-text-3">Resolve the highlighted configuration errors before validating or connecting.</p> : null}
                <ConnectorFeedbackPanel feedback={feedback} stale={stale} />
            </div>
        </div>
    );
}

export function McpActionAuthentication(props: ActionConnectorProps) {
    const { draft, original, onChange, errors } = props;
    const readOnly = props.readOnly || Boolean(original?.read_only);
    const fields = draft.additionalFields;
    const method = connectorAuthMethod(draft, 'mcp');
    const transport = connectorText(fields.transport) || 'streamable_http';
    const catalogue = useMcpCatalogues(props, false);
    const preset = catalogue.presets.find(({ id }) => id === (fields.server_profile || 'generic'));
    const allowedMethods = allowedMcpAuthMethods(transport, preset);
    const headers = connectorObject(fields.custom_headers);
    const originalHeaders = connectorObject(original?.record.additionalFields.custom_headers);
    const [newHeaderName, setNewHeaderName] = useState('');
    const [headerError, setHeaderError] = useState<string | null>(null);
    const localErrors = {
        ...validateConnectorAuthentication(draft, 'mcp', original),
        ...Object.fromEntries(Object.entries(validateConnectorConfiguration(draft, 'mcp', preset))
            .filter(([key]) => key.includes('custom_headers') || key.endsWith('auth_method'))),
    };
    useConnectorValidity(props, 'mcp-authentication', Object.values(localErrors).join(' ') || null);
    const fieldError = (key: string) => errors[key] || localErrors[key];
    const updateAuth = (key: string, value: string) => onChange((current) => ({ ...current, auth: { ...current.auth, [key]: value } }));
    const updateHeader = (name: string, value: string) => onChange((current) => updateConnectorFields(current, {
        custom_headers: { ...connectorObject(current.additionalFields.custom_headers), [name]: value },
    }));
    const removeHeader = (name: string) => onChange((current) => updateConnectorFields(current, {
        custom_headers: Object.fromEntries(Object.entries(connectorObject(current.additionalFields.custom_headers)).filter(([key]) => key !== name)),
    }));
    const canAddHeaders = transport !== 'websocket' && preset?.constraints.customHeadersAllowed !== false;
    const apiKeyIdentity = Boolean(draft.identity_id && fields.identity_auth_type === 'api_key');
    return (
        <div className="space-y-5" data-testid="mcp-authentication">
            <ConnectorIdentitySelect {...props} identities={transport === 'websocket' ? [] : props.identities} kind="mcp" />
            {catalogue.presetsError ? <p role="alert" className="text-xs text-warn">{catalogue.presetsError} Saved authentication and header values have not been changed.</p> : null}
            <ActionField id="mcp-auth-method" label="Authentication method" error={fieldError('additionalFields.auth_method')}
                help={draft.identity_id ? 'The selected identity is resolved on the server; no credentials are copied into the action.' : 'A method change only edits this draft. Inactive credentials are retained until explicitly cleared.'}>
                <select id="mcp-auth-method" className={ACTION_INPUT_CLASS} value={method} disabled={readOnly || Boolean(draft.identity_id)}
                    onChange={(event) => {
                        const value = event.target.value;
                        onChange((current) => changeConnectorAuthMethod(current, 'mcp', value));
                    }}>
                    {!allowedMethods.some(({ value }) => value === method) ? <option value={method} disabled>
                        {method === 'identity' && draft.identity_id ? 'Reusable identity' : `Unavailable method — ${MCP_AUTH_OPTIONS.find(({ value }) => value === method)?.label || method}`}
                    </option> : null}
                    {allowedMethods.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
            </ActionField>
            {(method === 'api_key' || apiKeyIdentity) ? <ActionField id="mcp-api-key-header" label="API key header name" required error={fieldError('additionalFields.api_key_header_name')}>
                <input id="mcp-api-key-header" className={ACTION_INPUT_CLASS} disabled={readOnly}
                    value={connectorText(fields.api_key_header_name ?? 'X-API-Key')}
                    onChange={(event) => {
                        const api_key_header_name = event.target.value;
                        onChange((current) => updateConnectorFields(current, { api_key_header_name }));
                    }} />
            </ActionField> : null}
            {method === 'basic' && !draft.identity_id ? draft.auth.identity === EDITOR_SECRET_MASK || original?.record.auth.identity === EDITOR_SECRET_MASK ? (
                <ActionSecretInput id="mcp-basic-username" label="Username" value={draft.auth.identity} storedValue={original?.record.auth.identity}
                    disabled={readOnly} error={fieldError('auth.identity')} onChange={(value) => updateAuth('identity', value)} />
            ) : (
                <ActionField id="mcp-basic-username" label="Username" required error={fieldError('auth.identity')}>
                    <input id="mcp-basic-username" className={ACTION_INPUT_CLASS} disabled={readOnly} autoComplete="off"
                        value={draft.auth.identity ?? ''} onChange={(event) => updateAuth('identity', event.target.value)} />
                </ActionField>
            ) : null}
            {['bearer', 'api_key', 'basic'].includes(method) && !draft.identity_id ? <ActionSecretInput
                id="mcp-credential" label={method === 'basic' ? 'Password' : method === 'api_key' ? 'API key' : 'Bearer token'}
                value={draft.auth.key} storedValue={original?.record.auth.key} disabled={readOnly}
                error={fieldError('auth.key')} onChange={(value) => updateAuth('key', value)} /> : null}
            {method === 'identity' && !draft.identity_id ? <p role="alert" className="text-sm text-danger">Choose a compatible reusable identity above before testing or saving.</p> : null}
            <div className="space-y-4 border-t border-edge pt-4">
                <div>
                    <h3 className="text-sm font-semibold text-text-1">Custom HTTP headers</h3>
                    <p className="mt-1 text-xs leading-relaxed text-text-3">All header values are treated as secrets. Authentication headers override matching custom headers. To rename a stored header, remove it and add the new name with a replacement value.</p>
                </div>
                {!canAddHeaders ? <p className="alert alert-warning rounded-lg bg-warn-soft p-2 text-xs text-warn">This transport or preset does not support custom headers. Existing values are preserved for review; remove them explicitly before connecting, or select a compatible transport/preset.</p> : null}
                {fieldError('additionalFields.custom_headers') ? <p role="alert" className="text-sm text-danger">{fieldError('additionalFields.custom_headers')}</p> : null}
                {Object.entries(headers).map(([name, value], index) => <GlassPanel key={name} elevation="flat" className="space-y-2 p-3">
                    <ActionSecretInput id={`mcp-header-value-${index}`} label={name} value={value} storedValue={originalHeaders[name]}
                        disabled={readOnly} error={fieldError(`additionalFields.custom_headers.${name}`)}
                        onChange={(next) => updateHeader(name, next)} />
                    {!readOnly ? <GlassButton type="button" size="sm" variant="danger" onClick={() => removeHeader(name)}>Remove header {name}</GlassButton> : null}
                </GlassPanel>)}
                {!Object.keys(headers).length ? <p className="text-sm text-text-3">No custom headers configured.</p> : null}
                {!readOnly ? <div className="space-y-2">
                    <ActionField id="mcp-new-header-name" label="New header name" error={headerError ?? undefined}>
                        <input id="mcp-new-header-name" className={ACTION_INPUT_CLASS} value={newHeaderName}
                            placeholder="X-Request-Source" disabled={!canAddHeaders || Object.keys(headers).length >= 20}
                            onChange={(event) => { setNewHeaderName(event.target.value); setHeaderError(null); }} />
                    </ActionField>
                    <GlassButton type="button" variant="subtle" disabled={!canAddHeaders || Object.keys(headers).length >= 20 || !newHeaderName.trim()}
                        onClick={() => {
                            const name = newHeaderName.trim();
                            const error = mcpHeaderNameError(name, headers);
                            if (error) { setHeaderError(error); return; }
                            updateHeader(name, '');
                            setNewHeaderName('');
                            setHeaderError(null);
                        }}>Add custom header</GlassButton>
                    <p className="text-xs text-text-3">{Object.keys(headers).length}/20 headers. Values may contain up to 4096 characters and must not contain line breaks.</p>
                </div> : null}
            </div>
        </div>
    );
}
