// DmField.tsx
// One Backup & Recovery setting, drawn with the shared Admin Settings controls.
//
// The value comes from the data-management store rather than the page's draft, because
// these settings are a separate document with their own save. Everything an administrator
// sees -- label, help, error, the secret field's stored/replace/remove states -- is the same
// control every other setting on the page uses.

import { useMemo, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { DM_DEFAULTS, type DmEditableKey } from '../../../lib/dataManagement';
import { DM_FIELDS, toAdminField, type DmFieldDef } from '../../../lib/dataManagementFields';
import { useDataManagementStore } from '../../../stores/dataManagementStore';
import { SettingField } from '../fields';
import { SecretField } from '../SecretField';

export type DmFieldEmphasis = 'primary' | 'dependent';

/** Read one editable value: the unsaved edit, else the saved value, else the default. */
export function useDmValue(key: DmEditableKey): unknown {
    return useDataManagementStore((state) => {
        if (Object.prototype.hasOwnProperty.call(state.draft, key)) return state.draft[key];
        const saved = state.settings?.[key];
        return saved === undefined || saved === null ? DM_DEFAULTS[key] : saved;
    });
}

export function DmField({
    dmKey,
    disabled,
    emphasis,
    overrides,
    after,
}: {
    dmKey: DmEditableKey;
    disabled?: boolean;
    /** `primary` frames the switch a card hangs off; `dependent` indents a setting under one. */
    emphasis?: DmFieldEmphasis;
    /** Per-use changes to the declared label, help or notice. */
    overrides?: Partial<Omit<DmFieldDef, 'dmKey'>>;
    /** Content drawn directly beneath the control, inside its emphasis frame. */
    after?: ReactNode;
}) {
    const declared = DM_FIELDS[dmKey];
    const value = useDmValue(dmKey);
    const stored = useDataManagementStore((state) => state.settings?.[dmKey]);
    const error = useDataManagementStore((state) => state.fieldErrors[dmKey]);
    const saving = useDataManagementStore((state) => state.saving);
    const setValue = useDataManagementStore((state) => state.setValue);

    const field = useMemo(
        () => (declared ? toAdminField({ ...declared, ...overrides, dmKey }) : null),
        [declared, overrides, dmKey],
    );
    if (!field) return null;

    const locked = Boolean(disabled || saving);
    const onChange = (next: unknown) => setValue(dmKey, next);
    const control =
        field.type === 'secret' ? (
            <SecretField
                field={field}
                value={value}
                storedValue={stored}
                error={error}
                disabled={locked}
                onChange={onChange}
            />
        ) : (
            <SettingField field={field} value={value} error={error} disabled={locked} onChange={onChange} />
        );

    // Each field is its own size container. The shared field layout switches to a label
    // column beside the control once its container is wide, and measured against the whole
    // card that would overflow a field placed in a grid cell; measured against itself, a
    // field sits beside its label in a full row and stacks in a narrow cell.
    return (
        <div
            data-setting-emphasis={emphasis}
            data-dm-key={dmKey}
            className={clsx(
                '@container min-w-0',
                emphasis === 'primary' && 'mb-3 rounded-xl border border-accent/40 bg-accent-soft px-3 py-1',
                emphasis === 'dependent' && 'ms-3 border-s-2 border-edge-strong ps-3',
            )}
        >
            {control}
            {after}
        </div>
    );
}
