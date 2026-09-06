// AgentTemplatesPanel.tsx

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { api } from '../../lib/apiClient';
import type { ActionConfiguration, AgentConfiguration, AgentEditorOptions } from '../../lib/workspaceAuthoring';
import {
    agentDraftFromTemplate, agentTemplateSubmission, fetchAgentTemplates, safeAgentTemplateSettings, type AgentTemplate,
} from '../../lib/workspaceAgentTemplates';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { SectionSearch } from '../workspace/primitives';
import { AgentNotice } from './AgentFields';

function templateSettingsPreview(template: AgentTemplate): string {
    try {
        const parsed: unknown = typeof template.additional_settings === 'string' ? JSON.parse(template.additional_settings) : template.additional_settings;
        return JSON.stringify(safeAgentTemplateSettings(parsed), null, 2);
    } catch {
        return 'The template contains invalid additional-settings JSON and cannot be applied.';
    }
}

export function AgentTemplatesPanel({
    draft, setDraft, actions, options, isNew, dirty, readOnly,
}: {
    draft: AgentConfiguration; setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    actions: ActionConfiguration[]; options: AgentEditorOptions; isNew: boolean; dirty: boolean; readOnly: boolean;
}) {
    const enabled = options.settings.enable_agent_template_gallery === true;
    const submissionsAllowed = enabled && options.settings.agent_templates_allow_user_submission !== false && !readOnly;
    const [templates, setTemplates] = useState<AgentTemplate[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [query, setQuery] = useState('');
    const [revision, setRevision] = useState(0);
    const [pending, setPending] = useState<AgentTemplate | null>(null);
    const [submitting, setSubmitting] = useState(false);
    const [notice, setNotice] = useState<string | null>(null);
    const submitRequest = useRef<AbortController | null>(null);
    useEffect(() => {
        if (!enabled) return;
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        void fetchAgentTemplates(controller.signal).then((items) => {
            if (!controller.signal.aborted) setTemplates(items);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load templates.');
        }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [enabled, revision]);
    useEffect(() => () => submitRequest.current?.abort(), []);

    const apply = (template: AgentTemplate) => {
        try {
            const next = agentDraftFromTemplate(template, actions);
            setDraft(next);
            setPending(null);
            setError(null);
            setNotice('Template applied to a new, unsaved agent. Review the model and any unresolved action references.');
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : 'Could not apply this template.');
        }
    };
    const submit = async () => {
        if (!submissionsAllowed) return;
        if (!draft.display_name.trim() || !draft.description.trim() || !draft.instructions.trim()) {
            setError('A template needs a display name, description, and instructions.');
            return;
        }
        submitRequest.current?.abort();
        const controller = new AbortController();
        submitRequest.current = controller;
        setSubmitting(true);
        setError(null);
        setNotice(null);
        try {
            const payload = await api.post<{ template: AgentTemplate }>('/api/agent-templates', agentTemplateSubmission(draft), controller.signal);
            if (!payload.template) throw new Error('The template service returned an invalid response.');
            if (!controller.signal.aborted) setNotice(payload.template.status === 'approved' ? 'Template published to the approved gallery.' : 'Personal template submitted for review.');
        } catch (cause) {
            if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not submit this template.');
        } finally {
            if (!controller.signal.aborted) setSubmitting(false);
        }
    };
    if (!enabled) return <AgentNotice>The example and approved-template gallery is disabled for this workspace.</AgentNotice>;

    const visible = templates.filter((template) =>
        `${template.title} ${template.display_name} ${template.description} ${(template.tags ?? []).join(' ')}`.toLowerCase().includes(query.toLowerCase()));
    return (
        <div className="space-y-4">
            <p className="text-sm text-text-3">Start a new agent from an approved example or template. Instructions, tags, and recommended actions are copied into a draft, never saved automatically. Connection credentials are excluded.</p>
            <div className="flex flex-wrap gap-2">
                <GlassButton type="button" size="sm" disabled={loading} onClick={() => setRevision((value) => value + 1)}>Refresh templates</GlassButton>
                {submissionsAllowed ? <GlassButton type="button" size="sm" disabled={submitting} onClick={() => void submit()}>
                    {submitting ? 'Submitting template…' : 'Submit personal template'}
                </GlassButton> : null}
            </div>
            {error ? <AgentNotice error>{error}</AgentNotice> : null}
            {notice ? <AgentNotice>{notice}</AgentNotice> : null}
            {loading ? <p role="status" className="text-sm text-text-3">Loading approved templates…</p> : null}
            <SectionSearch value={query} onChange={setQuery} placeholder="Search examples and templates" />
            {pending ? (
                <AgentNotice>
                    Replace the current new-agent draft with “{pending.title || pending.display_name}”? Nothing will be saved automatically.
                    <div className="mt-3 flex flex-wrap gap-2">
                        <GlassButton type="button" size="sm" onClick={() => setPending(null)}>Keep current draft</GlassButton>
                        <GlassButton type="button" size="sm" variant="primary" onClick={() => apply(pending)}>Replace draft with template</GlassButton>
                    </div>
                </AgentNotice>
            ) : null}
            <div className="space-y-3">
                {visible.map((template) => (
                    <GlassPanel key={template.id} elevation="flat" className="space-y-3 border border-edge p-4">
                        <h4 className="text-sm font-semibold text-text-1">{template.title || template.display_name}</h4>
                        <p className="text-sm text-text-3">{template.description || template.helper_text}</p>
                        {template.tags?.length ? <p className="text-xs text-text-3">{template.tags.join(' · ')}</p> : null}
                        <details>
                            <summary className="cursor-pointer text-xs font-medium text-accent">Preview template</summary>
                            <pre className="mt-3 whitespace-pre-wrap break-words text-xs leading-relaxed text-text-2">{template.instructions}</pre>
                            {template.actions_to_load?.length ? <p className="mt-3 break-words text-xs text-text-3">Recommended actions: {template.actions_to_load.join(', ')}</p> : null}
                            {template.additional_settings ? <pre className="mt-3 whitespace-pre-wrap break-words rounded-lg border border-edge p-3 text-xs text-text-3">{templateSettingsPreview(template)}</pre> : null}
                        </details>
                        {isNew && !readOnly ? <GlassButton type="button" size="sm" onClick={() => dirty ? setPending(template) : apply(template)}>Use template</GlassButton> : null}
                    </GlassPanel>
                ))}
            </div>
            {!visible.length && !loading && !error ? <p role="status" className="text-sm text-text-3">No approved templates match.</p> : null}
            {!isNew ? <p className="text-xs text-text-3">Templates start new agents; applying one will not overwrite this saved agent.</p> : null}
            {submissionsAllowed ? <p className="text-xs text-text-3">Submission publishes a reusable recipe under the current gallery approval policy, not your connection credentials. {Object.keys(safeAgentTemplateSettings(draft.other_settings)).length ? 'Non-secret additional settings are included.' : ''}</p> : null}
        </div>
    );
}
