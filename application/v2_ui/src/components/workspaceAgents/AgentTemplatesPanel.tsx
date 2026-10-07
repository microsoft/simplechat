// AgentTemplatesPanel.tsx

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { api } from '../../lib/apiClient';
import type { ActionConfiguration, AgentConfiguration, AgentEditorOptions } from '../../lib/workspaceAuthoring';
import {
    agentDraftFromTemplate, agentTemplateSubmission, fetchAgentTemplates, safeAgentTemplateSettings, type AgentTemplate,
} from '../../lib/workspaceAgentTemplates';
import { GlassButton } from '../ui/primitives';
import { EditorGroup } from '../workspace/EditorLayout';
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
    draft, setDraft, actions, options, isNew, dirty, readOnly, submissionAllowed, scope = 'personal',
}: {
    draft: AgentConfiguration; setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    actions: ActionConfiguration[]; options: AgentEditorOptions; isNew: boolean; dirty: boolean; readOnly: boolean;
    submissionAllowed: boolean;
    /** Which kind of agent this is. A global agent publishes straight to the gallery. */
    scope?: 'personal' | 'group' | 'global';
}) {
    const groupScope = scope === 'group';
    const globalScope = scope === 'global';
    const enabled = options.settings.enable_agent_template_gallery === true;
    const submissionsAllowed = enabled && submissionAllowed && !readOnly;
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
            const payload = await api.post<{ template: AgentTemplate }>('/api/agent-templates', agentTemplateSubmission(draft, globalScope ? 'global' : 'personal'), controller.signal);
            if (!payload.template) throw new Error('The template service returned an invalid response.');
            if (!controller.signal.aborted) setNotice(payload.template.status === 'approved'
                ? 'Template published to the approved gallery.'
                : groupScope || globalScope ? 'Template submitted for review.' : 'Personal template submitted for review.');
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
            <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="min-w-0 flex-[1_1_20rem] text-[0.8125rem] leading-relaxed text-text-3">Start a new agent from an approved example or template. Instructions, tags, and recommended actions are copied into a draft, never saved automatically. Connection credentials are excluded.</p>
                <div className="flex flex-wrap items-center gap-2">
                    <GlassButton type="button" size="sm" variant="ghost" disabled={loading} onClick={() => setRevision((value) => value + 1)}>Refresh templates</GlassButton>
                    {submissionsAllowed ? <GlassButton type="button" size="sm" variant="subtle" disabled={submitting} onClick={() => void submit()}>
                        {submitting ? 'Submitting template…' : globalScope ? 'Publish as template' : groupScope ? 'Submit template' : 'Submit personal template'}
                    </GlassButton> : null}
                </div>
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
            <ul className="space-y-2" aria-label="Templates">
                {visible.map((template) => (
                    <li key={template.id} className="space-y-3 rounded-lg border border-edge bg-surface-1 p-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0 flex-[1_1_16rem]">
                                <h4 className="break-words text-sm font-semibold text-text-1">{template.title || template.display_name}</h4>
                                <p className="mt-0.5 break-words text-xs text-text-3">{template.description || template.helper_text}</p>
                                {template.tags?.length ? <p className="mt-1 break-words text-[11px] text-text-3">{template.tags.join(' · ')}</p> : null}
                            </div>
                            {isNew && !readOnly ? <GlassButton type="button" size="sm" variant="subtle" onClick={() => dirty ? setPending(template) : apply(template)}>Use template</GlassButton> : null}
                        </div>
                        <EditorGroup summary="Preview template">
                            <pre className="whitespace-pre-wrap break-words pt-2 text-xs leading-relaxed text-text-2">{template.instructions}</pre>
                            {template.actions_to_load?.length ? <p className="break-words text-xs text-text-3">Recommended actions: {template.actions_to_load.join(', ')}</p> : null}
                            {template.additional_settings ? <pre className="whitespace-pre-wrap break-words rounded-lg border border-edge p-3 text-xs text-text-3">{templateSettingsPreview(template)}</pre> : null}
                        </EditorGroup>
                    </li>
                ))}
            </ul>
            {!visible.length && !loading && !error ? <p role="status" className="text-sm text-text-3">No approved templates match.</p> : null}
            {!isNew ? <p className="text-xs text-text-3">Templates start new agents; applying one will not overwrite this saved agent.</p> : null}
            {submissionsAllowed ? <p className="text-xs text-text-3">{globalScope
                ? 'Publishing adds a reusable recipe to the approved gallery straight away, not your connection credentials.'
                : 'Submission publishes a reusable recipe under the current gallery approval policy, not your connection credentials.'} {Object.keys(safeAgentTemplateSettings(draft.other_settings)).length ? 'Non-secret additional settings are included.' : ''}</p> : null}
        </div>
    );
}
