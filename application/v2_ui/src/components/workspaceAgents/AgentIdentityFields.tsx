// AgentIdentityFields.tsx

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { Bot } from 'lucide-react';
import { api } from '../../lib/apiClient';
import type { AgentConfiguration, AgentEditorOptions, WorkspaceAgentType } from '../../lib/workspaceAuthoring';
import {
    AGENT_INPUT_CLASS, AGENT_TYPE_LABELS, changeAgentType, clearAgentDraftFields, isAgentIconImage, renameAgentDraft,
} from '../../lib/workspaceAgentAuthoring';
import { GlassButton } from '../ui/primitives';
import { AgentField, AgentNotice, AgentTextField } from './AgentFields';

const ICON_FALLBACKS = [
    'bi-robot', 'bi-stars', 'bi-lightbulb', 'bi-search', 'bi-graph-up', 'bi-shield-check',
    'bi-code-square', 'bi-database', 'bi-envelope', 'bi-calendar-check', 'bi-file-earmark-text',
    'bi-bar-chart', 'bi-diagram-3', 'bi-globe', 'bi-gear', 'bi-person-workspace',
];

export function AgentIcon({ icon }: { icon: AgentConfiguration['icon'] }) {
    if (icon?.kind === 'image' && isAgentIconImage(icon.value)) return <img src={icon.value} alt="" className="h-10 w-10 shrink-0 rounded-xl object-contain" />;
    if (icon?.kind === 'bootstrap' && /^bi-[a-z0-9][a-z0-9-]{0,80}$/.test(icon.value)) {
        return <i aria-hidden="true" className={`bi ${icon.value} flex h-10 w-10 shrink-0 items-center justify-center text-xl text-accent`} />;
    }
    return <Bot aria-hidden="true" size={28} className="shrink-0 text-accent" />;
}

async function resizeAgentIcon(file: File): Promise<string> {
    if (!['image/png', 'image/jpeg'].includes(file.type)) throw new Error('Choose a PNG or JPEG image.');
    const url = URL.createObjectURL(file);
    try {
        const image = new Image();
        image.src = url;
        await image.decode();
        const scale = Math.min(1, 128 / Math.max(image.width, image.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        const context = canvas.getContext('2d');
        if (!context) throw new Error('This browser cannot resize the icon.');
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        const data = canvas.toDataURL('image/png');
        if (!isAgentIconImage(data)) throw new Error('The resized icon exceeds the 350000-character limit.');
        return data;
    } finally {
        URL.revokeObjectURL(url);
    }
}

export function AgentIdentityFields({
    draft, setDraft, options, isNew, onIconBusyChange,
}: {
    draft: AgentConfiguration; setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    options: AgentEditorOptions; isNew: boolean; onIconBusyChange?: (busy: boolean) => void;
}) {
    const [icons, setIcons] = useState(ICON_FALLBACKS);
    const [iconSearch, setIconSearch] = useState('');
    const [iconError, setIconError] = useState<string | null>(null);
    const [imageBusy, setImageBusy] = useState(false);
    const uploadSequence = useRef(0);
    useEffect(() => () => { uploadSequence.current += 1; }, []);

    const loadIcons = async () => {
        setIconError(null);
        try {
            const css = await api.get<string>('/static/css/bootstrap-icons.css');
            const available = [...new Set([...css.matchAll(/\.bi-([a-z0-9][a-z0-9-]*)::before/g)].map((match) => `bi-${match[1]}`))].sort();
            if (!available.length) throw new Error('The local icon catalogue could not be read.');
            setIcons(available);
        } catch (error) {
            setIconError(error instanceof Error ? error.message : 'Could not load the local icon catalogue.');
        }
    };

    const uploadIcon = async (file: File) => {
        const sequence = ++uploadSequence.current;
        setImageBusy(true);
        onIconBusyChange?.(true);
        setIconError(null);
        try {
            const value = await resizeAgentIcon(file);
            if (sequence === uploadSequence.current) setDraft((current) => ({ ...current, icon: { kind: 'image', value, mime_type: 'image/png' } }));
        } catch (error) {
            if (sequence === uploadSequence.current) setIconError(error instanceof Error ? error.message : 'Could not load the image.');
        } finally {
            if (sequence === uploadSequence.current) {
                setImageBusy(false);
                onIconBusyChange?.(false);
            }
        }
    };
    const currentIcon = draft.icon?.kind === 'bootstrap' ? draft.icon.value : '';
    const visibleIcons = icons.filter((icon) => icon.includes(iconSearch.toLowerCase()));

    return (
        <div className="space-y-4">
            <link rel="stylesheet" href="/static/css/bootstrap-icons.css" />
            <AgentTextField id="agent-display-name" label="Display name" value={draft.display_name} required
                onChange={(value) => setDraft((current) => renameAgentDraft(current, value, isNew))} />
            <AgentField id="agent-description" label="Description" help="Explain what this agent does and when someone should choose it.">
                <textarea id="agent-description" rows={3} value={draft.description} required className={AGENT_INPUT_CLASS}
                    onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />
            </AgentField>
            <AgentTextField label="Tags" value={typeof draft._editor_tags_text === 'string' ? draft._editor_tags_text : (draft.tags ?? []).join(', ')}
                help="Comma-separated. Up to 20 tags, each at most 40 characters."
                onChange={(value) => setDraft((current) => ({
                    ...current, tags: [...new Set(value.split(',').map((tag) => tag.trim()).filter(Boolean))], _editor_tags_text: value,
                }))} onBlur={() => setDraft((current) => clearAgentDraftFields(current, '_editor_tags_text'))} />
            <fieldset className="space-y-2">
                <legend className="mb-2 text-sm font-medium text-text-2">Agent type</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                    {(Object.keys(AGENT_TYPE_LABELS) as WorkspaceAgentType[]).map((type) => {
                        const option = options.agent_types.find((item) => item.value === type);
                        return (
                            <label key={type} className={`flex items-start gap-2 rounded-xl border p-3 ${draft.agent_type === type ? 'border-accent bg-accent-soft' : 'border-edge'} ${!option?.enabled ? 'opacity-60' : ''}`}>
                                <input type="radio" name="workspace-agent-type" value={type} checked={draft.agent_type === type}
                                    disabled={!option?.enabled} className="mt-1 accent-accent"
                                    onChange={() => setDraft((current) => changeAgentType(current, type))} />
                                <span className="min-w-0 text-sm text-text-1">{option?.label || AGENT_TYPE_LABELS[type]}
                                    {!option?.enabled ? <span className="mt-1 block text-xs text-text-3">{option?.reason || 'Not available for your workspace.'}</span> : null}
                                </span>
                            </label>
                        );
                    })}
                </div>
                <p className="text-xs text-text-3">Changing type preserves existing settings. Foundry owns prompts and tools; any local action removal must be confirmed before saving.</p>
            </fieldset>
            <fieldset className="space-y-3">
                <legend className="mb-2 text-sm font-medium text-text-2">Agent icon</legend>
                <div className="flex flex-wrap items-center gap-3">
                    <AgentIcon icon={draft.icon} />
                    <GlassButton type="button" size="sm" onClick={() => {
                        uploadSequence.current += 1;
                        setImageBusy(false);
                        onIconBusyChange?.(false);
                        setDraft((current) => ({ ...current, icon: { kind: 'bootstrap', value: 'bi-robot' } }));
                    }}>Use default icon</GlassButton>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2">
                        <AgentTextField label="Search Bootstrap icons" type="search" value={iconSearch} onChange={setIconSearch} />
                        <AgentField id="agent-bootstrap-icon" label="Bootstrap icon">
                            <select id="agent-bootstrap-icon" className={AGENT_INPUT_CLASS} value={currentIcon}
                                onChange={(event) => {
                                    uploadSequence.current += 1;
                                    setImageBusy(false);
                                    onIconBusyChange?.(false);
                                    setDraft((current) => ({ ...current, icon: { kind: 'bootstrap', value: event.target.value } }));
                                }}>
                                {!currentIcon ? <option value="">Choose an icon</option> : null}
                                {currentIcon && !visibleIcons.includes(currentIcon) ? <option value={currentIcon}>{currentIcon}</option> : null}
                                {visibleIcons.map((icon) => <option key={icon} value={icon}>{icon}</option>)}
                            </select>
                        </AgentField>
                        <GlassButton type="button" size="sm" onClick={() => void loadIcons()}>Load all local icons</GlassButton>
                    </div>
                    <AgentField id="agent-icon-upload" label="Upload icon" help="PNG or JPEG, resized to at most 128 × 128 pixels. The stored PNG must fit the existing 350000-character limit.">
                        <input id="agent-icon-upload" type="file" accept="image/png,image/jpeg" disabled={imageBusy}
                            className={`${AGENT_INPUT_CLASS} file:mr-3 file:rounded-lg file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-text-1`}
                            onChange={(event) => {
                                const file = event.target.files?.[0];
                                if (file) void uploadIcon(file);
                                event.target.value = '';
                            }} />
                        {imageBusy ? <p role="status" className="mt-2 text-xs text-text-3">Resizing icon…</p> : null}
                    </AgentField>
                </div>
                {iconError ? <AgentNotice error>{iconError}</AgentNotice> : null}
            </fieldset>
            <details className="rounded-xl border border-edge p-3">
                <summary className="cursor-pointer text-sm font-medium text-text-2">Internal identity</summary>
                <div className="mt-3 space-y-3">
                    <AgentTextField label="Internal name" value={draft.name} pattern="[A-Za-z0-9_\-]+" required
                        help="Derived from the display name only for a new agent. Changing a saved display name does not rename this value or change its stable ID."
                        onChange={(value) => setDraft((current) => ({ ...current, name: value }))} />
                    <p className="break-all text-xs text-text-3">Stable ID: {draft.id || 'Allocated when this agent is first saved.'}</p>
                </div>
            </details>
        </div>
    );
}
