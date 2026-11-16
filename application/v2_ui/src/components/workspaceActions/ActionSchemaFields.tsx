// ActionSchemaFields.tsx

import { useId } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { ActionField, ActionJsonInput, ActionSecretInput, ACTION_INPUT_CLASS } from './ActionFields';
import { EditorPanelFieldset, EditorRow } from '../workspace/EditorLayout';
import { EDITOR_SECRET_MASK, isRecord, pointerPart, type EditorSchema } from '../../lib/workspaceAuthoring';
import {
    actionArrayRemovalError, actionFieldError, actionHasStoredArraySecrets, actionSchemaDefaults,
    actionText, actionValueAt, resolveActionSchema, withActionValue,
} from '../../lib/workspaceActionLogic';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';

const humanLabel = (key: string) => key.replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
const knownSecret = (key: string) => key.endsWith('__Secret') ||
    /^(password|key|secret|token|api_key|connection_string|client_secret|private_key|private_key_passphrase)$/i.test(key);

function schemaType(schema: EditorSchema, value: unknown): string {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (value !== undefined && value !== null) {
        const actual = Array.isArray(value) ? 'array' : isRecord(value) ? 'object' : typeof value;
        if (types.includes(actual)) return actual;
    }
    return types.find((type) => type && type !== 'null') ||
        (schema.properties ? 'object' : Array.isArray(value) ? 'array' : isRecord(value) ? 'object' : typeof value === 'boolean' ? 'boolean' : typeof value === 'number' ? 'number' : 'string');
}

export function ActionSchemaValue({
    props, schema, path, label, required = false, root = schema, depth = 0,
}: {
    props: ActionConnectorProps;
    schema: EditorSchema;
    path: string;
    label: string;
    required?: boolean;
    root?: EditorSchema;
    depth?: number;
}) {
    const id = useId();
    const value = actionValueAt(props.draft, path);
    const resolved = resolveActionSchema(schema, root);
    const fieldType = schemaType(resolved, value);
    const error = actionFieldError(props.errors, path);
    const key = path.split('/').at(-1)?.replace(/~1/g, '/').replace(/~0/g, '~') || '';
    const change = (next: unknown) => props.onChange((draft) => withActionValue(draft, path, next));
    const secret = props.original?.secret_paths.includes(path) || value === EDITOR_SECRET_MASK ||
        (fieldType === 'string' && knownSecret(key));

    if (secret) return <ActionSecretInput id={id} label={label} value={value}
        storedValue={actionValueAt(props.original?.record, path)} onChange={(next) => change(next)}
        disabled={props.readOnly} error={error} help={resolved.description} />;
    if (depth >= 12 && ['object', 'array'].includes(fieldType)) return (
        <ActionJsonInput id={id} label={label} value={value} onChange={change} objectOnly={fieldType === 'object'}
            readOnly={props.readOnly} error={error} onValidityChange={props.onValidityChange}
            protectArraySecrets={actionHasStoredArraySecrets(props.draft, props.original, path)}
            help="Deeply nested configuration can be edited here without replacing sibling properties." />
    );
    if (fieldType === 'object' && value === undefined && !required) return (
        <EditorRow heading={<>{label} <span className="text-xs font-normal text-text-3">(optional)</span></>} help={resolved.description}>
            {props.readOnly ? <p className="text-xs text-text-3">Not configured.</p> :
                <div><GlassButton type="button" size="sm" variant="subtle" onClick={() => change(actionSchemaDefaults(resolved, root) ?? {})}>
                    <Plus size={13} /> Configure {label.toLowerCase()}
                </GlassButton></div>}
        </EditorRow>
    );
    if (depth < 12 && fieldType === 'object') return (
        <EditorPanelFieldset legend={label} description={resolved.description}>
            <ActionSchemaFields props={props} schema={resolved} path={path} root={root} depth={depth + 1}
                allowCustom={resolved.additionalProperties !== false} />
            {!required && !props.readOnly ? <div><GlassButton type="button" size="sm" variant="ghost" onClick={() => change(undefined)}>Remove {label.toLowerCase()} configuration</GlassButton></div> : null}
            {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
        </EditorPanelFieldset>
    );
    if (depth < 12 && fieldType === 'array') {
        const items = Array.isArray(value) ? value : [];
        const itemSchema = resolved.items ?? {};
        return (
            <EditorPanelFieldset legend={label} description={resolved.description}>
                {items.map((_, index) => {
                    const removalError = actionArrayRemovalError(props.draft, props.original, path, index);
                    return <div key={index} className="min-w-0 space-y-2 rounded-lg border border-edge bg-surface-1 p-3">
                        <ActionSchemaValue props={props} path={`${path}/${index}`} schema={itemSchema} root={root}
                            label={`${label} ${index + 1}`} depth={depth + 1} />
                        {!props.readOnly ? <GlassButton type="button" size="sm" disabled={Boolean(removalError)}
                            aria-describedby={removalError ? `${id}-remove-${index}` : undefined}
                            onClick={() => change(items.filter((_, itemIndex) => itemIndex !== index))}>
                            <Trash2 size={13} /> Remove entry {index + 1}
                        </GlassButton> : null}
                        {!props.readOnly && removalError ? <p id={`${id}-remove-${index}`} role="status" className="text-xs text-warn">{removalError}</p> : null}
                    </div>;
                })}
                {!items.length ? <p className="text-xs text-text-3">No entries configured.</p> : null}
                {!props.readOnly ? <GlassButton type="button" size="sm" disabled={resolved.maxItems !== undefined && items.length >= resolved.maxItems}
                    onClick={() => {
                        const initial = actionSchemaDefaults(itemSchema, root);
                        const itemType = schemaType(itemSchema, undefined);
                        change([...items, initial ?? (itemType === 'object' ? {} : itemType === 'array' ? [] : itemType === 'boolean' ? false : itemType === 'number' || itemType === 'integer' ? 0 : '')]);
                    }}><Plus size={13} /> Add {label.toLowerCase()} entry</GlassButton> : null}
                {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
            </EditorPanelFieldset>
        );
    }
    if (fieldType === 'boolean') return (
        <ActionField id={id} label={label} help={resolved.description} error={error} width="standard">
            <select id={id} value={value === undefined ? '' : String(value)} disabled={props.readOnly}
                className={ACTION_INPUT_CLASS} aria-invalid={Boolean(error)}
                onChange={(event) => change(event.target.value === '' ? undefined : event.target.value === 'true')}>
                <option value="">Use runtime default{resolved.default !== undefined ? ` (${String(resolved.default)})` : ''}</option>
                <option value="true">Enabled</option><option value="false">Disabled</option>
            </select>
        </ActionField>
    );
    const values = resolved.enum ?? (Object.hasOwn(resolved, 'const') ? [resolved.const] : undefined);
    if (values) {
        const selected = values.findIndex((item) => JSON.stringify(item) === JSON.stringify(value));
        return (
            <ActionField id={id} label={label} help={resolved.description} error={error} required={required} width="standard">
                <select id={id} value={selected < 0 ? (value === undefined ? '' : 'unavailable') : String(selected)}
                    required={required} disabled={props.readOnly || Object.hasOwn(resolved, 'const')} className={ACTION_INPUT_CLASS}
                    onChange={(event) => change(event.target.value === '' ? undefined : values[Number(event.target.value)])}>
                    <option value="">Select a value</option>
                    {value !== undefined && selected < 0 ? <option value="unavailable" disabled>Current value: {String(value)}</option> : null}
                    {values.map((item, index) => <option key={index} value={String(index)}>{String(item)}</option>)}
                </select>
            </ActionField>
        );
    }
    const numeric = fieldType === 'number' || fieldType === 'integer';
    const shared = {
        id, className: ACTION_INPUT_CLASS, required, disabled: props.readOnly,
        'aria-invalid': Boolean(error), 'aria-describedby': `${id}-help ${id}-error`,
    };
    return (
        <ActionField id={id} label={label} help={resolved.description} error={error} required={required} width={numeric ? 'compact' : 'wide'}>
            {numeric ? <input {...shared} type="number" step={fieldType === 'integer' ? 1 : 'any'}
                min={resolved.minimum} max={resolved.maximum} value={typeof value === 'number' ? value : ''}
                onChange={(event) => change(event.target.value === '' ? undefined : event.target.valueAsNumber)} />
                : <textarea {...shared} rows={typeof value === 'string' && (value.includes('\n') || value.length > 100) ? 4 : 2}
                    value={actionText(value)} maxLength={resolved.maxLength}
                    onChange={(event) => change(event.target.value)} />}
        </ActionField>
    );
}

export function ActionSchemaFields({
    props, schema, path = '/additionalFields', coveredPaths = [], root = schema, depth = 0, allowCustom = true,
}: {
    props: ActionConnectorProps;
    schema: EditorSchema;
    path?: string;
    coveredPaths?: string[];
    root?: EditorSchema;
    depth?: number;
    allowCustom?: boolean;
}) {
    const resolved = resolveActionSchema(schema, root);
    const value = actionValueAt(props.draft, path);
    const record = isRecord(value) ? value : {};
    const covered = (pointer: string) => coveredPaths.some((known) =>
        pointer === known || pointer.startsWith(`${known}/`) || known.startsWith(`${pointer}/`));
    const properties = Object.entries(resolved.properties ?? {}).filter(([key]) => !covered(`${path}/${pointerPart(key)}`));
    void record;
    void allowCustom;
    return (
        <div className="min-w-0 space-y-4">
            {properties.map(([key, definition]) => (
                <ActionSchemaValue key={key} props={props} path={`${path}/${pointerPart(key)}`} schema={definition} root={root}
                    label={definition.title || humanLabel(key)} required={resolved.required?.includes(key)} depth={depth} />
            ))}
        </div>
    );
}
