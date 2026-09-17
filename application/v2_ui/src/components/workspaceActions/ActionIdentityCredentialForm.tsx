// ActionIdentityCredentialForm.tsx

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { GlassButton } from '../ui/primitives';
import { ActionField, ACTION_INPUT_CLASS } from './ActionFields';
import type { ActionCredentialValues, ActionIdentityAuthType } from '../../lib/actionAuth';

/** Values stay in this mounted form, not drafts, stores, navigation, or browser storage. */
export function ActionIdentityCredentialForm({
    authType, initialUsername = '', keepStoredSecret = false, collectCredentials = true,
    busy = false, disabled = false, error, submitLabel = 'Save identity',
    onSubmit, onCancel, children, afterFields,
}: {
    authType: ActionIdentityAuthType;
    initialUsername?: string;
    keepStoredSecret?: boolean;
    collectCredentials?: boolean;
    busy?: boolean;
    disabled?: boolean;
    error?: string | null;
    submitLabel?: string;
    onSubmit: (credentials: ActionCredentialValues | undefined) => Promise<void>;
    onCancel: () => void;
    children?: ReactNode;
    afterFields?: ReactNode;
}) {
    const id = useId();
    const formRef = useRef<HTMLFormElement>(null);
    const submitting = useRef(false);
    const mounted = useRef(true);
    const [pending, setPending] = useState(false);
    const [username, setUsername] = useState(initialUsername);
    const [password, setPassword] = useState('');
    const [secret, setSecret] = useState('');
    const [localError, setLocalError] = useState<string | null>(null);
    const locked = busy || pending;
    const secretLabel = authType === 'api_key' ? 'API key' : 'Bearer token';

    useEffect(() => {
        mounted.current = true;
        formRef.current?.querySelector<HTMLElement>('input:not([type="checkbox"]):not([disabled])')?.focus();
        return () => { mounted.current = false; };
    }, []);
    useEffect(() => {
        setPassword('');
        setSecret('');
        setUsername(initialUsername);
        setLocalError(null);
    }, [authType, collectCredentials, initialUsername]);

    return (
        <form ref={formRef} className="space-y-4" aria-busy={locked} autoComplete="off"
            onKeyDown={(event) => {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    event.stopPropagation();
                    onCancel();
                }
            }}
            onSubmit={(event) => {
                event.preventDefault();
                if (submitting.current || locked || disabled) return;
                if (collectCredentials && (authType === 'username_password'
                    ? !username.trim() || !keepStoredSecret && !password
                    : !keepStoredSecret && !secret)) {
                    setLocalError('Complete the required credential fields.');
                    return;
                }
                submitting.current = true;
                setPending(true);
                setLocalError(null);
                const credentials = !collectCredentials ? undefined : authType === 'username_password'
                    ? { username: username.trim(), password } : { secret };
                // A rejected attempt requires fresh secret entry, never a reflected API value.
                setPassword('');
                setSecret('');
                void onSubmit(credentials).catch(() => {
                    if (mounted.current) setLocalError('The credential could not be saved. Please try again.');
                }).finally(() => {
                    submitting.current = false;
                    if (mounted.current) setPending(false);
                });
            }}>
            {children}
            {collectCredentials ? <fieldset disabled={locked} className="space-y-4">
                <legend className="sr-only">Private action credentials</legend>
                {authType === 'username_password' ? <>
                    <ActionField id={`${id}-username`} label="Username" required>
                        <input id={`${id}-username`} name="action-username" value={username} required maxLength={255}
                            autoComplete="username" autoCapitalize="none" spellCheck={false} className={ACTION_INPUT_CLASS}
                            onChange={(event) => setUsername(event.target.value)} />
                    </ActionField>
                    <ActionField id={`${id}-password`} label="Password" required={!keepStoredSecret}
                        help={keepStoredSecret ? 'A password is stored. Leave this blank to keep it; enter a replacement to change it.' : undefined}>
                        <input id={`${id}-password`} name="action-password" type="password" value={password}
                            required={!keepStoredSecret} maxLength={8192} autoComplete="new-password"
                            placeholder={keepStoredSecret ? 'Stored password — unchanged' : ''}
                            aria-describedby={keepStoredSecret ? `${id}-password-help` : undefined}
                            className={ACTION_INPUT_CLASS} onChange={(event) => setPassword(event.target.value)} />
                    </ActionField>
                </> : (
                    <ActionField id={`${id}-secret`} label={secretLabel} required={!keepStoredSecret}
                        help={keepStoredSecret ? 'A credential is stored. Leave this blank to keep it; enter a replacement to change it.' : undefined}>
                        <input id={`${id}-secret`} name="action-secret" type="password" value={secret} autoComplete="new-password"
                            required={!keepStoredSecret} maxLength={8192} spellCheck={false}
                            placeholder={keepStoredSecret ? 'Stored credential — unchanged' : ''}
                            aria-describedby={keepStoredSecret ? `${id}-secret-help` : undefined}
                            className={ACTION_INPUT_CLASS} onChange={(event) => setSecret(event.target.value)} />
                    </ActionField>
                )}
            </fieldset> : <p className="text-xs text-text-3">The saved credential stays on the server. No secret is loaded into this form.</p>}
            {afterFields}
            {error || localError ? <p role="alert" className="rounded-xl border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
                {error || localError}
            </p> : null}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <GlassButton type="button" size="sm" onClick={onCancel}>Cancel</GlassButton>
                <GlassButton type="submit" size="sm" variant="primary" disabled={locked || disabled}>
                    {locked ? 'Saving…' : submitLabel}
                </GlassButton>
            </div>
        </form>
    );
}
