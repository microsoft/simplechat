// AgentAdvancedFields.tsx

import type { Dispatch, SetStateAction } from 'react';
import { getModelSupportedLevels } from '../../lib/reasoning';
import type { AgentConfiguration, AgentEditorOptions, AuthoringResource } from '../../lib/workspaceAuthoring';
import {
    AGENT_INPUT_CLASS, agentModelChoices, agentStoredArrayEditError, agentText, clearAgentDraftFields, parseAgentSettings,
    secretValueAt, selectedAgentModel, setAgentSecret,
} from '../../lib/workspaceAgentAuthoring';
import { GlassButton } from '../ui/primitives';
import { AgentField, AgentNotice, AgentSecretField } from './AgentFields';

export function agentAdvancedError(
    draft: AgentConfiguration, original: AuthoringResource<AgentConfiguration> | null = null,
): string | null {
    const storedArrayError = agentText(draft._editor_array_secret_error) || agentStoredArrayEditError(draft, original);
    if (storedArrayError) return storedArrayError;
    if (typeof draft._editor_settings_text !== 'string') return null;
    try {
        const settings = parseAgentSettings(draft._editor_settings_text, draft.other_settings);
        return agentStoredArrayEditError({ ...draft, other_settings: settings }, original);
    } catch (error) {
        return error instanceof Error ? error.message : 'Invalid additional-settings JSON.';
    }
}

export function AgentAdvancedFields({
    draft, setDraft, original, options,
}: {
    draft: AgentConfiguration;
    setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    original: AuthoringResource<AgentConfiguration> | null;
    options: AgentEditorOptions;
}) {
    const selectedModel = selectedAgentModel(draft, agentModelChoices(options));
    const levels = getModelSupportedLevels(selectedModel?.modelName || draft.model_id || draft.azure_openai_gpt_deployment || draft.azure_agent_apim_gpt_deployment);
    const rawSettings = typeof draft._editor_settings_text === 'string' ? draft._editor_settings_text : JSON.stringify(draft.other_settings, null, 2);
    const error = agentAdvancedError(draft, original);
    return (
        <div className="space-y-4">
            {draft.agent_type === 'local' ? (
                <div className="grid gap-4 sm:grid-cols-2">
                    <AgentField id="agent-completion-tokens" label="Completion token limit" help="-1 uses the model default. Zero is retained as an explicit value. Maximum: 512000.">
                        <input id="agent-completion-tokens" type="number" min={-1} max={512000} step={1} required
                            value={typeof draft._editor_completion_text === 'string' ? draft._editor_completion_text : draft.max_completion_tokens}
                            onChange={(event) => setDraft((current) => {
                                const value = event.target.value;
                                const next = { ...current, max_completion_tokens: value === '' ? Number.NaN : Number(value) };
                                return value === '' ? { ...next, _editor_completion_text: value } : clearAgentDraftFields(next, '_editor_completion_text');
                            })} className={AGENT_INPUT_CLASS} />
                    </AgentField>
                    <AgentField id="agent-reasoning-effort" label="Reasoning effort" help="Only levels supported by the selected model are offered. An existing unsupported value is retained for explicit review.">
                        <select id="agent-reasoning-effort" value={draft.reasoning_effort ?? ''} className={AGENT_INPUT_CLASS}
                            onChange={(event) => setDraft((current) => {
                                const next = { ...current };
                                if (event.target.value) next.reasoning_effort = event.target.value;
                                else delete next.reasoning_effort;
                                return next;
                            })}>
                            <option value="">Use configured default</option>
                            {draft.reasoning_effort && !levels.some((level) => level === draft.reasoning_effort) ? <option value={draft.reasoning_effort}>Saved value (unsupported by selected model): {draft.reasoning_effort}</option> : null}
                            {levels.map((level) => <option key={level} value={level}>{level[0].toUpperCase() + level.slice(1)}</option>)}
                        </select>
                    </AgentField>
                </div>
            ) : <p className="text-sm text-text-3">Token and reasoning behavior are managed by the selected Foundry resource. Saved local values remain intact.</p>}
            <AgentField id="agent-additional-settings" label="Additional settings JSON"
                help="This is the same draft used by the structured controls. Managed action, knowledge and provider siblings are preserved when omitted from a pasted object. Explicit values, including false, zero and empty arrays, are retained.">
                <textarea id="agent-additional-settings" rows={16} value={rawSettings} spellCheck={false}
                    aria-invalid={Boolean(error)} className={`${AGENT_INPUT_CLASS} font-mono text-xs`}
                    onChange={(event) => {
                        const raw = event.target.value;
                        setDraft((current) => {
                            try {
                                return { ...current, other_settings: parseAgentSettings(raw, current.other_settings), _editor_settings_text: raw };
                            } catch {
                                return { ...current, _editor_settings_text: raw };
                            }
                        });
                    }}
                    onBlur={() => {
                        if (!error) setDraft((current) => clearAgentDraftFields(current, '_editor_settings_text'));
                    }} />
            </AgentField>
            {original?.secret_paths.length ? <p className="text-xs text-text-3">
                Array credentials are tied to saved positions, not entry names or IDs. Individual credential controls can replace or clear them.
                Unrelated JSON fields remain editable; changing a retained entry or array structure requires replacing or clearing the affected stored credentials first.
            </p> : null}
            {error ? (
                <AgentNotice error>
                    {error} Fix the JSON or reset its text before changing structured settings or saving.
                    <div className="mt-2"><GlassButton type="button" size="sm" onClick={() => setDraft((current) => clearAgentDraftFields(current, '_editor_settings_text', '_editor_array_secret_error'))}>Reset JSON text to current settings</GlassButton></div>
                </AgentNotice>
            ) : null}
            {original?.secret_paths.length ? (
                <details className="rounded-xl border border-edge p-3">
                    <summary className="cursor-pointer text-sm font-medium text-text-2">Stored credentials and custom secret fields</summary>
                    <fieldset disabled={Boolean(error)} className="mt-3 space-y-4">
                        <legend className="sr-only">Secret field changes</legend>
                        {original.secret_paths.map((path) => <AgentSecretField key={path} label={path}
                            value={secretValueAt(draft, path)} original={secretValueAt(original.record, path)}
                            onChange={(value) => setDraft((current) => setAgentSecret(current, path, value))} />)}
                    </fieldset>
                </details>
            ) : null}
            <p className="text-xs text-text-3">Ownership and the stable ID are not editable JSON settings. {agentText(draft.id) ? `Agent ID: ${draft.id}` : 'A stable ID is allocated on save.'}</p>
        </div>
    );
}
