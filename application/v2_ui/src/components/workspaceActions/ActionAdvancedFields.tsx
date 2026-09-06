// ActionAdvancedFields.tsx

import { useId } from 'react';
import { Toggle } from '../ui/primitives';
import { ActionField, ActionJsonInput, ACTION_INPUT_CLASS } from './ActionFields';
import { ActionSchemaFields } from './ActionSchemaFields';
import { isRecord, type ActionTypeDefinition } from '../../lib/workspaceAuthoring';
import { actionFieldError, actionHasStoredArraySecrets, actionText, actionValueAt, changeActionField } from '../../lib/workspaceActionLogic';
import type { ActionEditorHints } from '../../lib/workspaceActionServices';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';

const reminderPath = '/metadata/key_vault_secret_reminders/__all__';

export function ActionAdvancedFields(props: ActionConnectorProps & {
    definition: ActionTypeDefinition;
    hints: ActionEditorHints | null;
    hintsError: string | null;
}) {
    const { draft, onChange, readOnly, definition, hints, hintsError } = props;
    const id = useId();
    const rawReminder = actionValueAt(draft, reminderPath);
    const reminder = isRecord(rawReminder) ? rawReminder : {};
    const enabled = reminder.enabled === true;
    const updateReminder = (key: string, value: unknown) => onChange((current) => changeActionField(current, `${reminderPath}/${key}`, value));
    const sync = draft.metadata.key_vault_secret_reminder_sync;
    const syncStates = isRecord(sync) ? Object.entries(sync) : [];
    return (
        <div className="min-w-0 space-y-6">
            <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                <ActionField id={`${id}-machine-name`} label="Machine name" required
                    help="Letters, numbers, underscores, and dashes only. Renaming does not change the action ID."
                    error={actionFieldError(props.errors, '/name')}>
                    <input id={`${id}-machine-name`} className={ACTION_INPUT_CLASS} value={draft.name} required
                        pattern="[A-Za-z0-9_\-]+" disabled={readOnly}
                        onChange={(event) => onChange((current) => ({ ...current, name: event.target.value }))} />
                </ActionField>
                <div className="min-w-0 space-y-1.5 text-xs text-text-3">
                    <p className="text-sm font-medium text-text-1">Action ID</p>
                    <p className="break-all">{draft.id || 'Assigned when the action is saved.'}</p>
                    <p>The ID, not the display name, identifies this action in agent assignments.</p>
                </div>
            </div>
            <ActionSchemaFields props={props} schema={definition.metadata_schema} path="/metadata"
                coveredPaths={['/metadata/key_vault_secret_reminders', '/metadata/key_vault_secret_reminder_sync',
                    ...(draft.type === 'log_analytics' ? ['/metadata/name'] : [])]}
                allowCustom={false} />
            {draft.type !== 'agent' ? (
                <fieldset className="min-w-0 space-y-4 rounded-xl border border-edge p-4">
                    <legend className="px-1 text-sm font-medium text-text-1">Secret expiration and reminders</legend>
                    <p className="text-xs leading-relaxed text-text-3">
                        Track expiration and send a rotation reminder for this action’s stored secrets. Tracking does not rotate credentials automatically.
                    </p>
                    {hints ? <p className="text-xs text-text-3">
                        Key Vault storage is {hints.storageEnabled ? 'enabled' : 'disabled'}; reminder delivery is {hints.remindersEnabled ? 'enabled' : 'disabled'}.
                        {hints.requireExpiration ? ' Your administrator requires expiration dates for tracked secrets.' : ''}
                    </p> : <p className="text-xs text-text-3">{hintsError || 'Loading reminder defaults…'} Existing reminder settings are preserved.</p>}
                    {!hints?.storageEnabled && hints ? <p className="rounded-lg bg-warn-soft p-2 text-xs text-warn">
                        This configuration is retained, but reminders for Key Vault secrets require enabled Key Vault storage and reminder delivery.
                    </p> : null}
                    <Toggle checked={enabled} disabled={readOnly} label="Track secret expiration"
                        description="Apply these defaults to all secret fields on this action. Existing field-specific settings are kept."
                        onChange={(value) => onChange((current) => {
                            const existing = actionValueAt(current, reminderPath);
                            const previous = isRecord(existing) ? existing : {};
                            return changeActionField(current, reminderPath, {
                                ...previous, enabled: value,
                                ...(value ? {
                                    lead_days: previous.lead_days ?? hints?.reminderLeadDays ?? 30,
                                    contact_email: previous.contact_email ?? previous.reminder_email ?? hints?.reminderEmail ?? '',
                                    expires_on: previous.expires_on ?? previous.expiration_date ?? '',
                                } : {}),
                            });
                        })} />
                    {enabled ? <div className="grid min-w-0 gap-4 sm:grid-cols-2">
                        <ActionField id={`${id}-expiration`} label="Secret expiration date" required
                            error={actionFieldError(props.errors, `${reminderPath}/expires_on`)}>
                            <input id={`${id}-expiration`} type="date" className={ACTION_INPUT_CLASS} required disabled={readOnly}
                                value={actionText(reminder.expires_on ?? reminder.expiration_date).slice(0, 10)}
                                onChange={(event) => updateReminder('expires_on', event.target.value)} />
                        </ActionField>
                        <ActionField id={`${id}-reminder-email`} label="Reminder email" required
                            error={actionFieldError(props.errors, `${reminderPath}/contact_email`)}>
                            <input id={`${id}-reminder-email`} type="email" className={ACTION_INPUT_CLASS} required disabled={readOnly}
                                value={actionText(reminder.contact_email ?? reminder.reminder_email)}
                                onChange={(event) => updateReminder('contact_email', event.target.value)} />
                        </ActionField>
                        <ActionField id={`${id}-reminder-days`} label="Reminder lead days" required
                            error={actionFieldError(props.errors, `${reminderPath}/lead_days`)}>
                            <input id={`${id}-reminder-days`} type="number" min={1} max={3650} step={1} className={ACTION_INPUT_CLASS} required disabled={readOnly}
                                value={typeof reminder.lead_days === 'number' ? reminder.lead_days : ''}
                                onChange={(event) => updateReminder('lead_days', event.target.value === '' ? undefined : event.target.valueAsNumber)} />
                        </ActionField>
                        <ActionField id={`${id}-reminder-label`} label="Reminder label">
                            <input id={`${id}-reminder-label`} className={ACTION_INPUT_CLASS} disabled={readOnly}
                                value={actionText(reminder.label ?? reminder.friendly_label)} onChange={(event) => updateReminder('label', event.target.value)} />
                        </ActionField>
                        <div className="sm:col-span-2">
                            <ActionField id={`${id}-reminder-notes`} label="Rotation notes">
                                <textarea id={`${id}-reminder-notes`} rows={3} className={ACTION_INPUT_CLASS} disabled={readOnly}
                                    value={actionText(reminder.notes ?? reminder.rotation_notes)} onChange={(event) => updateReminder('notes', event.target.value)} />
                            </ActionField>
                        </div>
                    </div> : null}
                    {syncStates.length ? <div className="space-y-1 text-xs text-text-3">
                        <p className="font-medium text-text-2">Last reminder synchronization</p>
                        {syncStates.map(([path, state]) => <p key={path} className="break-words">
                            {path}: {isRecord(state) ? actionText(state.status) || (state.success === true ? 'Synced' : 'Review required') : String(state)}
                        </p>)}
                    </div> : null}
                </fieldset>
            ) : null}
            <div className="min-w-0 space-y-4">
                <p className="text-xs leading-relaxed text-text-3">
                    JSON and structured fields edit the same draft. Unrecognized properties are retained.
                    Stored secrets appear only as masks; leave a mask unchanged to keep it, or explicitly clear/replace the corresponding field.
                </p>
                {draft.type !== 'agent' ? <ActionJsonInput id={`${id}-additional-json`} label="Additional fields JSON"
                    value={draft.additionalFields} readOnly={readOnly} onValidityChange={props.onValidityChange}
                    protectArraySecrets={actionHasStoredArraySecrets(draft, props.original, '/additionalFields')}
                    onChange={(value) => { if (isRecord(value)) onChange((current) => ({ ...current, additionalFields: value })); }} /> : null}
                <ActionJsonInput id={`${id}-metadata-json`} label="Metadata JSON" value={draft.metadata} readOnly={readOnly}
                    onValidityChange={props.onValidityChange}
                    protectArraySecrets={actionHasStoredArraySecrets(draft, props.original, '/metadata')}
                    onChange={(value) => { if (isRecord(value)) onChange((current) => ({ ...current, metadata: value })); }} />
            </div>
        </div>
    );
}
