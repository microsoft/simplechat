// ScreeningFields.tsx

import { useId, type ReactNode } from 'react';

export const screeningInputClass =
    'w-full min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1 focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';

export function ScreeningField({
    label,
    children,
    help,
}: {
    label: string;
    children: (id: string) => ReactNode;
    help?: string;
}) {
    const id = useId();
    return (
        <div className="min-w-0 space-y-1">
            <label htmlFor={id} className="block text-xs font-medium text-text-2">{label}</label>
            {children(id)}
            {help ? <p className="text-xs leading-relaxed text-text-3">{help}</p> : null}
        </div>
    );
}

export function ScreeningNumberField({
    label,
    value,
    onChange,
    disabled,
    min = 0,
    step = 1,
    help,
}: {
    label: string;
    value: number;
    onChange: (value: number) => void;
    disabled?: boolean;
    min?: number;
    step?: number | 'any';
    help?: string;
}) {
    return (
        <ScreeningField label={label} help={help}>
            {(id) => (
                <input id={id} type="number" className={screeningInputClass} value={value}
                    min={min} step={step} disabled={disabled}
                    onChange={(event) => onChange(Number(event.target.value))} />
            )}
        </ScreeningField>
    );
}
