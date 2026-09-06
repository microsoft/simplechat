// AgentFields.tsx

import { useId, useState, type InputHTMLAttributes, type ReactNode } from 'react';
import { EDITOR_SECRET_MASK } from '../../lib/workspaceAuthoring';
import { AGENT_INPUT_CLASS, agentText, secretIntent } from '../../lib/workspaceAgentAuthoring';

export function AgentField({
    label, help, children, id,
}: { label: string; help?: string; children: ReactNode; id: string }) {
    return (
        <div className="min-w-0">
            <label htmlFor={id} className="mb-1 block break-words text-sm font-medium text-text-2">{label}</label>
            {children}
            {help ? <p id={`${id}-help`} className="mt-1 text-xs leading-relaxed text-text-3">{help}</p> : null}
        </div>
    );
}

export function AgentTextField({
    label, value, onChange, help, ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'value'> & {
    label: string; value: unknown; onChange: (value: string) => void; help?: string;
}) {
    const generatedId = useId();
    const id = props.id || generatedId;
    return (
        <AgentField id={id} label={label} help={help}>
            <input {...props} id={id} value={agentText(value)} onChange={(event) => onChange(event.target.value)}
                aria-describedby={help ? `${id}-help` : undefined} className={AGENT_INPUT_CLASS} />
        </AgentField>
    );
}

export function AgentSecretField({
    label, value, original, onChange,
}: { label: string; value: unknown; original: unknown; onChange: (value: string) => void }) {
    const id = useId();
    const stored = original === EDITOR_SECRET_MASK;
    const [replacing, setReplacing] = useState(() => stored && secretIntent(value, original) === 'replace');
    const intent = replacing ? 'replace' : secretIntent(value, original);
    return (
        <div className="min-w-0 space-y-2">
            {stored ? (
                <AgentField id={`${id}-intent`} label={label} help="The stored value is never sent to this page. Keep it, replace it, or explicitly clear it on save.">
                    <select id={`${id}-intent`} value={intent} className={AGENT_INPUT_CLASS}
                        onChange={(event) => {
                            const mode = event.target.value;
                            setReplacing(mode === 'replace');
                            if (mode === 'keep') onChange(EDITOR_SECRET_MASK);
                            if (mode === 'clear') onChange('');
                            if (mode === 'replace' && !value) onChange(EDITOR_SECRET_MASK);
                        }}>
                        <option value="keep">Keep saved value</option>
                        <option value="replace">Replace saved value</option>
                        <option value="clear">Clear saved value</option>
                    </select>
                </AgentField>
            ) : null}
            {!stored || intent === 'replace' ? (
                <AgentTextField label={stored ? `Replacement ${label.toLowerCase()}` : label} type="password"
                    value={value === EDITOR_SECRET_MASK ? '' : value} autoComplete="new-password"
                    onChange={(next) => onChange(stored && !next ? EDITOR_SECRET_MASK : next)}
                    help={stored ? 'Enter a replacement. An empty replacement keeps the saved value; use Clear saved value to delete it.' : 'Optional. Never included in template submissions.'} />
            ) : null}
            {stored && intent === 'clear' ? <p role="status" className="text-xs text-warn">The saved value will be cleared when you save.</p> : null}
        </div>
    );
}

export function AgentNotice({ children, error = false }: { children: ReactNode; error?: boolean }) {
    return (
        <div role={error ? 'alert' : 'status'}
            className={`rounded-xl border p-3 text-sm ${error ? 'border-danger/30 bg-danger-soft text-danger' : 'border-edge bg-surface-2 text-text-2'}`}>
            {children}
        </div>
    );
}
