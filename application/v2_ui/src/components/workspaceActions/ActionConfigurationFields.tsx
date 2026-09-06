// ActionConfigurationFields.tsx

import { useId, useState } from 'react';
import { FlaskConical } from 'lucide-react';
import { GlassButton, Toggle } from '../ui/primitives';
import { ConfirmDialog } from '../ui/ConfirmDialog';
import { ActionField, ActionJsonInput, ActionLinesInput, ActionSecretInput, ACTION_INPUT_CLASS } from './ActionFields';
import { ActionSchemaFields } from './ActionSchemaFields';
import { CallAgentActionConfiguration } from './CallAgentActionConfiguration';
import { ConnectorFeedbackPanel, useConnectorRequest } from './OpenApiActionConfiguration';
import {
    actionFieldError, actionHasStoredArraySecrets, actionText, actionValueAt, changeActionField,
    changeSqlConnectionMethod, deriveBlobEndpoint, displayedActionValue,
} from '../../lib/workspaceActionLogic';
import { nativeActionDefinition, sqlConnectionMethod, usesDirectBlobConnectionString } from '../../lib/workspaceActionRegistry';
import { EDITOR_SECRET_MASK, isRecord, type ActionTypeDefinition } from '../../lib/workspaceAuthoring';
import { testWorkspaceAction } from '../../lib/workspaceActionServices';
import type { ActionConnectorProps, ActionFieldDescriptor } from '../../lib/workspaceActionTypes';

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
            <div className="space-y-1">
                <Toggle checked={typeof value === 'boolean' ? value : defaults === true} onChange={change}
                    disabled={disabled} label={descriptor.label} description={descriptor.help} />
                {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
            </div>
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
    return (
        <ActionField id={id} label={descriptor.label} help={descriptor.help} error={error} required={descriptor.required}>
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

export function ActionConfigurationFields(props: ActionConnectorProps & { definition: ActionTypeDefinition }) {
    const { draft, onChange, readOnly, definition } = props;
    const id = useId();
    const [confirmParameters, setConfirmParameters] = useState(false);
    const native = nativeActionDefinition(draft.type);
    const request = useConnectorRequest(props);
    if (draft.type === 'agent') return <CallAgentActionConfiguration {...props} />;
    const sql = ['sql_query', 'sql_schema'].includes(draft.type);
    const capabilities = native.capabilities;
    const rawCapabilities = capabilities ? actionValueAt(draft, capabilities.path) : undefined;
    const capabilityValues = isRecord(rawCapabilities) ? rawCapabilities : {};
    const derivedEndpoint = draft.type === 'blob_storage' ? deriveBlobEndpoint(actionText(draft.auth.key)) : '';
    const coveredPaths = [
        ...native.fields.map(({ path }) => path),
        '/additionalFields/identity_auth_type',
        ...(sql ? ['/additionalFields/auth_type', '/additionalFields/username', '/additionalFields/password', '/additionalFields/identity_uses_connection_string'] : []),
        ...(['databricks', 'databricks_table', 'snowflake', 'tableau', 'yamcs'].includes(draft.type) ? ['/additionalFields/auth_method'] : []),
        ...(['databricks', 'databricks_table'].includes(draft.type) ? ['/additionalFields/workspace_url'] : []),
        ...(['tableau', 'yamcs'].includes(draft.type) ? ['/additionalFields/server_url'] : []),
        ...(draft.type === 'tableau' ? ['/additionalFields/pat_name'] : []),
        ...(draft.type === 'snowflake' ? ['/additionalFields/private_key_passphrase'] : []),
        ...(draft.type === 'rocksdb' ? ['/additionalFields/auth_scheme', '/additionalFields/api_key_header', '/additionalFields/base_url'] : []),
        ...(capabilities ? [capabilities.path] : []),
    ];

    return (
        <div className="min-w-0 space-y-5" data-testid="action-configuration" data-action-type={draft.type}>
            {native.help ? <p className="text-sm leading-relaxed text-text-2">{native.help}</p> : null}
            {sql ? <ActionField id={`${id}-connection-method`} label="Connection mode"
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
            <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                {native.fields.map((descriptor) => <div key={descriptor.path}
                    className={['textarea', 'lines', 'secret', 'json'].includes(descriptor.kind ?? '') ? 'min-w-0 sm:col-span-2' : 'min-w-0'}>
                    <ActionDescriptorField props={props} descriptor={descriptor} />
                </div>)}
            </div>
            {usesDirectBlobConnectionString(draft) ? (
                <div className="space-y-2 text-xs text-text-3">
                    <p>The blob service endpoint is derived automatically when saving or testing. A stored connection string keeps the saved endpoint.</p>
                    <p className="break-all" data-testid="blob-derived-endpoint">
                        Blob service endpoint: {derivedEndpoint || draft.endpoint || 'Enter the connection string in Authentication.'}
                    </p>
                </div>
            ) : null}
            {capabilities ? <fieldset className="min-w-0 space-y-2">
                <legend className="mb-2 text-sm font-medium text-text-1">Allowed capabilities</legend>
                {capabilities.options.map((capability) => {
                    const legacyUpload = draft.type === 'simplechat' &&
                        ['upload_word_document', 'upload_powerpoint_document'].includes(capability.key) &&
                        typeof capabilityValues.upload_markdown_document === 'boolean'
                        ? capabilityValues.upload_markdown_document : capability.defaultEnabled !== false;
                    return <Toggle key={capability.key} label={capability.label} description={capability.description}
                        checked={typeof capabilityValues[capability.key] === 'boolean' ? capabilityValues[capability.key] === true : legacyUpload}
                        disabled={readOnly}
                        onChange={(value) => onChange((current) => changeActionField(current, `${capabilities.path}/${capability.key}`, value))} />;
                })}
                {actionFieldError(props.errors, capabilities.path) ? <p role="alert" className="text-sm text-danger">{actionFieldError(props.errors, capabilities.path)}</p> : null}
            </fieldset> : null}
            <ActionSchemaFields props={props} schema={definition.additional_fields_schema} coveredPaths={coveredPaths}
                allowCustom={definition.additional_fields_schema.additionalProperties !== false} />
            {native.testPath ? <div className="space-y-3 border-t border-edge pt-4">
                <p className="text-xs leading-relaxed text-text-3">
                    Test connection makes a small request using this draft. An edited action uses its owned stored credentials when their masked values are unchanged.
                    Saving does not run this test.
                </p>
                <GlassButton type="button" size="sm" disabled={readOnly || Boolean(request.busy)}
                    onClick={() => void request.run('Testing connection…', (signal) => testWorkspaceAction(draft, props.original, definition, signal))}>
                    <FlaskConical size={15} />{request.busy || 'Test connection'}
                </GlassButton>
                <ConnectorFeedbackPanel feedback={request.feedback} stale={request.stale} />
            </div> : null}
            {confirmParameters ? <ConfirmDialog title="Use individual connection parameters?" tone="primary"
                description="The saved connection string will be explicitly cleared when you save. Server, database, and authentication fields are kept for you to review."
                confirmLabel="Use parameters" onClose={() => setConfirmParameters(false)}
                onConfirm={() => { onChange((current) => changeSqlConnectionMethod(current, 'parameters')); setConfirmParameters(false); }}>
                <p className="text-sm text-text-2">This changes which connection source the SQL action uses.</p>
            </ConfirmDialog> : null}
        </div>
    );
}
