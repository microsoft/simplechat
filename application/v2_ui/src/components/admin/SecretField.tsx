// SecretField.tsx
// A stored credential: masked, replaceable, and clearable, but never displayed.
//
// The server never sends the real value. It sends `SECRET_PLACEHOLDER` when one is stored,
// and treats that same string coming back as "leave it alone", so an untouched field
// round-trips without the credential reaching the browser.
//
// That leaves three states an administrator can be in, and the whole point of this
// component is to keep them distinguishable. An empty input could otherwise mean "nothing
// is configured", "something is configured and hidden", or "the configured value is about
// to be deleted" -- and deleting a working connection string by backspacing, with no
// visible difference from the untouched state, is the one outcome that must not happen
// quietly. The stored value is passed in alongside the draft value so the component can
// tell the difference and say which state it is in.

import { clsx } from 'clsx';
import { useState } from 'react';
import { Eye, EyeOff, TriangleAlert } from 'lucide-react';
import { asString, SECRET_PLACEHOLDER, type AdminField } from '../../lib/adminFields';
import { FieldShell, inputClass } from './fields';

export function SecretField({
    field,
    value,
    storedValue,
    error,
    warning,
    disabled,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    /** The value the server sent: the mask when a credential is stored, else empty. */
    storedValue: unknown;
    error?: string;
    warning?: string;
    disabled?: boolean;
    onChange: (next: unknown) => void;
}) {
    const id = `admin-field-${field.key}`;
    const [revealed, setRevealed] = useState(false);

    const current = asString(value);
    const isConfigured = asString(storedValue) === SECRET_PLACEHOLDER;
    const isUntouched = current === SECRET_PLACEHOLDER;
    // Configured, and the pending value is empty: saving now removes the credential.
    // Reached by pressing Clear and also by simply erasing what was typed.
    const willBeRemoved = isConfigured && !isUntouched && current === '';

    // The mask is never put in the input. A keystroke would append to it and save
    // `***REDACTED***newvalue` as the credential.
    const inputValue = isUntouched ? '' : current;

    const placeholder = isUntouched
        ? 'Saved — type to replace'
        : (field.placeholder ?? 'Not configured');

    return (
        <FieldShell
            field={field}
            error={error}
            warning={warning}
            htmlFor={id}
            trailing={
                isUntouched ? (
                    <button
                        type="button"
                        className="text-xs text-text-3 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-60"
                        disabled={disabled}
                        onClick={() => onChange('')}
                    >
                        Clear
                    </button>
                ) : willBeRemoved ? (
                    <button
                        type="button"
                        className="text-xs text-text-3 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-60"
                        disabled={disabled}
                        // Restoring the mask is what marks the field untouched again, so
                        // the save leaves the stored credential alone.
                        onClick={() => onChange(SECRET_PLACEHOLDER)}
                    >
                        Undo
                    </button>
                ) : null
            }
        >
            <div className="flex items-center gap-2">
                <input
                    id={id}
                    type={revealed ? 'text' : 'password'}
                    className={clsx(inputClass, 'font-mono')}
                    value={inputValue}
                    placeholder={placeholder}
                    disabled={disabled}
                    spellCheck={false}
                    autoComplete="off"
                    onChange={(event) => onChange(event.target.value)}
                />
                <button
                    type="button"
                    className="shrink-0 rounded-lg border border-edge p-2 text-text-3 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-60"
                    aria-label={revealed ? `Hide ${field.label}` : `Show ${field.label}`}
                    aria-pressed={revealed}
                    // Nothing to reveal until something has been typed: the stored value
                    // is not here to show.
                    disabled={disabled || !inputValue}
                    onClick={() => setRevealed((previous) => !previous)}
                >
                    {revealed ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
            </div>

            {isUntouched ? (
                <p className="mt-1.5 text-xs text-text-3">
                    A value is saved and hidden. Type a new one to replace it, or Clear to
                    remove it.
                </p>
            ) : null}

            {willBeRemoved ? (
                <p
                    role="alert"
                    className="mt-1.5 flex items-start gap-1.5 text-xs text-warn"
                >
                    <TriangleAlert size={13} className="mt-0.5 shrink-0" />
                    The saved value will be removed when you save.
                </p>
            ) : null}
        </FieldShell>
    );
}
