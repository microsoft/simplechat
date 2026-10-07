// ActionConfigurationFields.tsx

import { useId, useState } from 'react';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { EditorFieldset, EditorSwitch, type EditorFieldWidth } from '../workspace/EditorLayout';
import { ActionField, ActionJsonInput, ActionLinesInput, ActionSecretInput, ACTION_INPUT_CLASS } from './ActionFields';
import { ActionSchemaFields } from './ActionSchemaFields';
import { CallAgentActionConfiguration } from './CallAgentActionConfiguration';
import { DocumentSearchActionConfiguration } from './DocumentSearchActionConfiguration';
import {
    actionFieldError, actionHasStoredArraySecrets, actionText, actionValueAt, changeActionField,
    changeSqlConnectionMethod, deriveBlobEndpoint, displayedActionValue,
} from '../../lib/workspaceActionLogic';
import { nativeActionDefinition, sqlConnectionMethod, usesDirectBlobConnectionString } from '../../lib/workspaceActionRegistry';
import { EDITOR_SECRET_MASK, isRecord, pointerPart, type ActionTypeDefinition } from '../../lib/workspaceAuthoring';
import type { ActionCapability, ActionConnectorProps, ActionFieldDescriptor } from '../../lib/workspaceActionTypes';

export function ActionDescriptorField({ props, descriptor }: { props: ActionConnectorProps; descriptor: ActionFieldDescriptor }) {
    const id = useId();
    if (descriptor.visible && !descriptor.visible(props.draft)) return null;
    const value = displayedActionValue(props.draft, descriptor.path);
    const storedValue = actionValueAt(props.original?.record, descriptor.path);
    const error = actionFieldError(props.errors, descriptor.path);
    const disabled = props.readOnly || descriptor.readOnly;
    const change = (next: unknown) => props.onChange((draft) => changeActionField(draft, descriptor.path, next));
    if (descriptor.kind === 'secret' || value === EDITOR_SECRET_MASK || props.original?.secret_paths.includes(descriptor.path)) return <ActionSecretInput id={id} label={descriptor.label} value={value}
        storedValue={storedValue} onChange={change} disabled={disabled} help={descriptor.help} error={error} />;
    if (descriptor.kind === 'boolean') {
        const defaults = actionValueAt(nativeActionDefinition(props.draft.type).defaults, descriptor.path);
        return (
            <EditorSwitch checked={typeof value === 'boolean' ? value : defaults === true} onChange={change}
                disabled={disabled} label={descriptor.label} description={descriptor.help} error={error} />
        );
    }
    if (descriptor.kind === 'json') return <ActionJsonInput id={id} label={descriptor.label} value={value}
        protectArraySecrets={actionHasStoredArraySecrets(props.draft, props.original, descriptor.path)}
        onChange={change} readOnly={disabled} onValidityChange={props.onValidityChange} help={descriptor.help} error={error} />;
    if (descriptor.kind === 'lines') return <ActionLinesInput id={id} label={descriptor.label} value={value}
        onChange={change} disabled={disabled} help={descriptor.help} error={error} />;
    const attributes = {
        id, className: ACTION_INPUT_CLASS, disabled, required: descriptor.required,
        'aria-invalid': Boolean(error), 'aria-describedby': `${id}-help ${id}-error`,
    };
    const width: EditorFieldWidth = descriptor.kind === 'number' ? 'compact' : descriptor.kind === 'select' ? 'standard' : 'wide';
    return (
        <ActionField id={id} label={descriptor.label} help={descriptor.help} error={error} required={descriptor.required} width={width}>
            {descriptor.kind === 'select' ? <select {...attributes} value={actionText(value)} onChange={(event) => change(event.target.value || undefined)}>
                <option value="">Select a value</option>
                {value !== undefined && value !== '' && !descriptor.options?.some((option) => option.value === value)
                    ? <option value={String(value)} disabled>Current value: {String(value)}</option> : null}
                {descriptor.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select> : descriptor.kind === 'number' ? <input {...attributes} type="number" min={descriptor.min} max={descriptor.max}
                step={descriptor.step ?? 'any'} value={typeof value === 'number' ? value : ''}
                onChange={(event) => change(event.target.value === '' ? undefined : event.target.valueAsNumber)} />
                : descriptor.kind === 'textarea'
                    ? <textarea {...attributes} rows={3} placeholder={descriptor.placeholder}
                        value={actionText(value)} onChange={(event) => change(event.target.value)} />
                    : <input {...attributes} type="text" placeholder={descriptor.placeholder} value={actionText(value)}
                        onChange={(event) => change(event.target.value)} />}
        </ActionField>
    );
}

function capabilityDefinition(definition: ActionTypeDefinition, native = nativeActionDefinition(definition.type)) {
    if (native.capabilities) return native.capabilities;
    if (!definition.capabilities?.length) return undefined;
    const defaults = isRecord(definition.defaults) ? definition.defaults : {};
    const savedDefaults = isRecord(defaults.m365_capabilities) ? defaults.m365_capabilities : {};
    const options: ActionCapability[] = definition.capabilities.map((capability) => ({
        key: capability.key,
        label: capability.label,
        description: capability.description,
        defaultEnabled: typeof savedDefaults[capability.key] === 'boolean' ? savedDefaults[capability.key] === true : capability.default !== false,
    }));
    return { path: '/additionalFields/m365_capabilities', options };
}

function configurationCoveredPaths(definition: ActionTypeDefinition) {
    const native = nativeActionDefinition(definition.type);
    const sql = ['sql_query', 'sql_schema'].includes(definition.type);
    const capabilities = capabilityDefinition(definition, native);
    return [
        ...native.fields.map(({ path }) => path),
        '/additionalFields/identity_auth_type',
        ...(sql ? ['/additionalFields/auth_type', '/additionalFields/username', '/additionalFields/password', '/additionalFields/identity_uses_connection_string'] : []),
        ...(['databricks', 'databricks_table', 'snowflake', 'tableau', 'yamcs'].includes(definition.type) ? ['/additionalFields/auth_method'] : []),
        ...(['databricks', 'databricks_table'].includes(definition.type) ? ['/additionalFields/workspace_url'] : []),
        ...(['tableau', 'yamcs'].includes(definition.type) ? ['/additionalFields/server_url'] : []),
        ...(definition.type === 'tableau' ? ['/additionalFields/pat_name'] : []),
        ...(definition.type === 'snowflake' ? ['/additionalFields/private_key_passphrase'] : []),
        ...(definition.type === 'rocksdb' ? ['/additionalFields/auth_scheme', '/additionalFields/api_key_header', '/additionalFields/base_url'] : []),
        ...(definition.type === 'log_analytics' ? ['/additionalFields/query_history'] : []),
        ...(definition.type === 'yamcs' ? [
            '/additionalFields/enable_basic_auth', '/additionalFields/basic_auth_username',
            '/additionalFields/basic_auth_password', '/additionalFields/basic_auth_identity_id',
        ] : []),
        ...(capabilities ? [capabilities.path] : []),
    ];
}

function schemaHasVisibleProperties(definition: ActionTypeDefinition) {
    const coveredPaths = configurationCoveredPaths(definition);
    const properties = definition.additional_fields_schema.properties ?? {};
    return Object.keys(properties).some((key) => {
        const pointer = `/additionalFields/${pointerPart(key)}`;
        return !coveredPaths.some((known) =>
            pointer === known || pointer.startsWith(`${known}/`) || known.startsWith(`${pointer}/`));
    });
}

export function hasActionConfigurationFields(definition: ActionTypeDefinition) {
    if (definition.type === 'agent' || definition.type === 'document_search' || definition.type === 'search' ||
        definition.type === 'openapi' || definition.type === 'mcp') return true;
    const native = nativeActionDefinition(definition.type);
    return native.fields.length > 0 || Boolean(capabilityDefinition(definition, native)) || schemaHasVisibleProperties(definition);
}

export function ActionConfigurationFields(props: ActionConnectorProps & { definition: ActionTypeDefinition }) {
    const { draft, onChange, readOnly, definition } = props;
    const id = useId();
    const [confirmParameters, setConfirmParameters] = useState(false);
    const native = nativeActionDefinition(draft.type);
    if (draft.type === 'agent') return <CallAgentActionConfiguration {...props} />;
    if (draft.type === 'document_search' || draft.type === 'search') return <DocumentSearchActionConfiguration {...props} />;
    const sql = ['sql_query', 'sql_schema'].includes(draft.type);
    const capabilities = capabilityDefinition(definition, native);
    const rawCapabilities = capabilities ? actionValueAt(draft, capabilities.path) : undefined;
    const capabilityValues = isRecord(rawCapabilities) ? rawCapabilities : {};
    const derivedEndpoint = draft.type === 'blob_storage' ? deriveBlobEndpoint(actionText(draft.auth.key)) : '';
    const coveredPaths = configurationCoveredPaths(definition);

    return (
        <div className="min-w-0 space-y-5" data-testid="action-configuration" data-action-type={draft.type}>
            {native.help ? <p className="text-[0.8125rem] leading-relaxed text-text-2">{native.help}</p> : null}
            {sql ? <ActionField id={`${id}-connection-method`} label="Connection mode" width="standard"
                help="A connection string takes precedence over individual parameters. Switching to parameters explicitly clears that stored connection string. Other settings are retained.">
                <select id={`${id}-connection-method`} className={ACTION_INPUT_CLASS} value={sqlConnectionMethod(draft)}
                    disabled={readOnly || draft.additionalFields.identity_uses_connection_string === true}
                    onChange={(event) => {
                        const method = event.target.value === 'connection_string' ? 'connection_string' : 'parameters';
                        if (method === 'parameters' && draft.additionalFields.connection_string) setConfirmParameters(true);
                        else onChange((current) => changeSqlConnectionMethod(current, method));
                    }}>
                    <option value="parameters">Individual parameters</option><option value="connection_string">Connection string</option>
                </select>
            </ActionField> : null}
            {native.fields.map((descriptor) => <ActionDescriptorField key={descriptor.path} props={props} descriptor={descriptor} />)}
            {draft.type.startsWith('m365_') && definition.graph_endpoint ? <ActionField id={`${id}-graph-endpoint`} label="Microsoft Graph endpoint"
                help="Derived from this deployment’s Azure cloud. Agents cannot change it.">
                <input id={`${id}-graph-endpoint`} className={ACTION_INPUT_CLASS} value={definition.graph_endpoint} readOnly />
            </ActionField> : null}
            {usesDirectBlobConnectionString(draft) ? (
                <div className="space-y-2 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-xs text-text-3">
                    <p>The blob service endpoint is derived automatically when saving or testing. A stored connection string keeps the saved endpoint.</p>
                    <p className="break-all" data-testid="blob-derived-endpoint">
                        Blob service endpoint: {derivedEndpoint || draft.endpoint || 'Enter the connection string in Authentication.'}
                    </p>
                </div>
            ) : null}
            {capabilities ? <EditorFieldset legend="Allowed capabilities"
                help="Choose what an agent can do through this action.">
                {capabilities.options.map((capability) => {
                    const legacyUpload = draft.type === 'simplechat' &&
                        ['upload_word_document', 'upload_powerpoint_document'].includes(capability.key) &&
                        typeof capabilityValues.upload_markdown_document === 'boolean'
                        ? capabilityValues.upload_markdown_document : capability.defaultEnabled !== false;
                    return <EditorSwitch key={capability.key} label={capability.label} description={capability.description}
                        checked={typeof capabilityValues[capability.key] === 'boolean' ? capabilityValues[capability.key] === true : legacyUpload}
                        disabled={readOnly}
                        onChange={(value) => onChange((current) => changeActionField(current, `${capabilities.path}/${capability.key}`, value))} />;
                })}
                {actionFieldError(props.errors, capabilities.path) ? <p role="alert" className="text-sm text-danger">{actionFieldError(props.errors, capabilities.path)}</p> : null}
            </EditorFieldset> : null}
            <ActionSchemaFields props={props} schema={definition.additional_fields_schema} coveredPaths={coveredPaths}
                allowCustom={definition.additional_fields_schema.additionalProperties !== false} />
            {confirmParameters ? <ConfirmDialog title="Use individual connection parameters?" tone="primary"
                description="The saved connection string will be explicitly cleared when you save. Server, database, and authentication fields are kept for you to review."
                confirmLabel="Use parameters" onClose={() => setConfirmParameters(false)}
                onConfirm={() => { onChange((current) => changeSqlConnectionMethod(current, 'parameters')); setConfirmParameters(false); }}>
                <p className="text-sm text-text-2">This changes which connection source the SQL action uses.</p>
            </ConfirmDialog> : null}
        </div>
    );
}
