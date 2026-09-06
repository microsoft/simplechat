// AgentInstructionsFields.tsx

import { useEffect, useId, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { Sparkles } from 'lucide-react';
import type { ActionConfiguration, AgentConfiguration } from '../../lib/workspaceAuthoring';
import { AGENT_INPUT_CLASS, agentText, clearAgentDraftFields } from '../../lib/workspaceAgentAuthoring';
import { readAgentKnowledge, type AgentKnowledgeCatalog } from '../../lib/workspaceAgentKnowledge';
import { agentMentions, agentMentionTrigger, filterAgentMentions, type AgentMention } from '../../lib/workspaceAgentReferences';
import { draftAgentInstructions, withAgentInstructionProposal } from '../../lib/workspaceAgentCommands';
import { GlassButton } from '../ui/primitives';
import { AgentField, AgentNotice } from './AgentFields';

export function AgentInstructionsFields({
    draft, setDraft, actions, catalog, contextError, readOnly,
}: {
    draft: AgentConfiguration;
    setDraft: Dispatch<SetStateAction<AgentConfiguration>>;
    actions: ActionConfiguration[];
    catalog: AgentKnowledgeCatalog | null;
    contextError: string | null;
    readOnly: boolean;
}) {
    const textarea = useRef<HTMLTextAreaElement>(null);
    const request = useRef<AbortController | null>(null);
    const [drafting, setDrafting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [cursor, setCursor] = useState(0);
    const [focused, setFocused] = useState(false);
    const [dismissed, setDismissed] = useState(false);
    const [activeIndex, setActiveIndex] = useState(0);
    const [confirmReplace, setConfirmReplace] = useState(false);
    const menuId = useId();
    const mentions = useMemo(() => agentMentions(draft, actions, catalog), [draft, actions, catalog]);
    const trigger = focused && !dismissed ? agentMentionTrigger(draft.instructions, cursor) : null;
    const suggestions = trigger ? filterAgentMentions(mentions, trigger.query) : [];
    const selectedIndex = Math.min(activeIndex, Math.max(0, suggestions.length - 1));
    const brief = agentText(draft._editor_instruction_brief);
    const proposal = agentText(draft._editor_instruction_proposal);
    const baseline = agentText(draft._editor_instruction_baseline);
    const needsKnowledge = readAgentKnowledge(draft).enabled && !catalog;
    useEffect(() => () => request.current?.abort(), []);

    const insertMention = (mention: AgentMention) => {
        if (!trigger || !textarea.current) return;
        const nextText = `${draft.instructions.slice(0, trigger.start)}${mention.token} ${draft.instructions.slice(cursor)}`;
        const nextCursor = trigger.start + mention.token.length + 1;
        setDraft((current) => ({ ...current, instructions: nextText }));
        setDismissed(true);
        setCursor(nextCursor);
        requestAnimationFrame(() => {
            textarea.current?.focus();
            textarea.current?.setSelectionRange(nextCursor, nextCursor);
        });
    };

    const generate = async () => {
        if (draft.agent_type !== 'local' || readOnly) return;
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        setDrafting(true);
        setError(null);
        const snapshot = draft.instructions;
        try {
            const instructions = await draftAgentInstructions(draft, actions, catalog, controller.signal);
            if (!controller.signal.aborted) {
                setDraft((current) => withAgentInstructionProposal(current, instructions, snapshot));
                setConfirmReplace(false);
            }
        } catch (cause) {
            if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Unable to draft instructions.');
        } finally {
            if (!controller.signal.aborted) setDrafting(false);
        }
    };
    const applyProposal = () => {
        if (draft.instructions !== baseline && !confirmReplace) {
            setConfirmReplace(true);
            return;
        }
        setDraft((current) => clearAgentDraftFields({ ...current, instructions: proposal }, '_editor_instruction_proposal', '_editor_instruction_baseline'));
        setConfirmReplace(false);
        textarea.current?.focus();
    };

    if (draft.agent_type !== 'local') {
        return (
            <div className="space-y-3">
                <AgentNotice>Instructions are managed in Foundry. Any stored local prompt is retained, but cannot be edited or drafted for this type.</AgentNotice>
                {draft.instructions ? <pre className="whitespace-pre-wrap break-words rounded-xl border border-edge p-3 text-xs text-text-3">{draft.instructions}</pre> : null}
            </div>
        );
    }
    return (
        <div className="space-y-4">
            <AgentField id="agent-instructions" label="Instructions" help={'Type # to reference selected actions, enabled capabilities, or assigned knowledge. Values with spaces or colons are quoted, for example #knowledge:doc:"Employee Handbook.pdf".'}>
                <textarea id="agent-instructions" ref={textarea} value={draft.instructions} rows={18} required spellCheck
                    className={`${AGENT_INPUT_CLASS} resize-y leading-relaxed`}
                    aria-autocomplete="list" aria-controls={suggestions.length ? menuId : undefined}
                    aria-activedescendant={suggestions.length ? `${menuId}-${selectedIndex}` : undefined}
                    onChange={(event) => {
                        setDraft((current) => ({ ...current, instructions: event.target.value }));
                        setCursor(event.target.selectionStart);
                        setDismissed(false);
                        setActiveIndex(0);
                        setConfirmReplace(false);
                    }}
                    onSelect={(event) => setCursor(event.currentTarget.selectionStart)}
                    onFocus={() => setFocused(true)}
                    onBlur={() => setFocused(false)}
                    onKeyDown={(event) => {
                        if (!suggestions.length) return;
                        if (event.key === 'Escape') { event.preventDefault(); setDismissed(true); }
                        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                            event.preventDefault();
                            setActiveIndex((index) => (index + (event.key === 'ArrowDown' ? 1 : suggestions.length - 1)) % suggestions.length);
                        }
                        if (event.key === 'Enter' || event.key === 'Tab') { event.preventDefault(); insertMention(suggestions[selectedIndex]); }
                    }} />
            </AgentField>
            {suggestions.length && !readOnly ? (
                <ul id={menuId} role="listbox" aria-label="Instruction references" className="rounded-xl border border-edge bg-surface-1 p-1">
                    {suggestions.map((mention, index) => (
                        <li key={`${mention.token}:${index}`} id={`${menuId}-${index}`} role="option" aria-selected={index === selectedIndex}
                            onMouseDown={(event) => event.preventDefault()} onMouseMove={() => setActiveIndex(index)}
                            className={index === selectedIndex ? 'rounded-lg bg-accent-soft' : 'rounded-lg'}>
                            <button type="button" tabIndex={-1} className="w-full break-words px-3 py-2 text-left text-xs text-text-2" onClick={() => insertMention(mention)}>
                                <span className="block font-medium">{mention.label}</span>
                                <code className="block break-all text-[11px] text-text-3">{mention.token}</code>
                                <span className="text-[11px] text-text-3">{mention.description}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            ) : null}
            {!readOnly ? (
                <div className="space-y-3 rounded-xl border border-edge p-3">
                    <AgentField id="agent-instruction-brief" label="Instruction brief" help="Describe the task, audience, guardrails, and desired output. Drafting runs only when requested and includes the selected action and knowledge context.">
                        <textarea id="agent-instruction-brief" rows={3} value={brief} className={AGENT_INPUT_CLASS}
                            onChange={(event) => setDraft((current) => ({ ...current, _editor_instruction_brief: event.target.value }))} />
                    </AgentField>
                    <GlassButton type="button" size="sm" disabled={drafting || needsKnowledge || Boolean(contextError) ||
                        ![brief, draft.display_name, draft.description, draft.instructions].some((value) => value.trim())}
                        onClick={() => void generate()}><Sparkles size={14} />{drafting ? 'Drafting instructions…' : 'Draft instructions'}</GlassButton>
                    {needsKnowledge || contextError ? <AgentNotice>Load the selected action and knowledge context before drafting. {contextError}</AgentNotice> : null}
                    {error ? <AgentNotice error>{error}</AgentNotice> : null}
                    {proposal ? (
                        <div className="space-y-3">
                            <AgentField id="agent-generated-instructions" label="Generated instructions — not yet applied">
                                <textarea id="agent-generated-instructions" rows={12} value={proposal} readOnly className={AGENT_INPUT_CLASS} />
                            </AgentField>
                            {draft.instructions !== baseline ? <AgentNotice>Your instructions changed while this draft was generated. They have not been overwritten.</AgentNotice> : null}
                            {confirmReplace ? <AgentNotice>Replace your newer instructions with the generated proposal? This still does not save the agent.</AgentNotice> : null}
                            <div className="flex flex-wrap gap-2">
                                <GlassButton type="button" size="sm" variant={confirmReplace ? 'danger' : 'primary'} onClick={applyProposal}>
                                    {confirmReplace ? 'Replace edited instructions' : 'Use generated instructions'}
                                </GlassButton>
                                <GlassButton type="button" size="sm" onClick={() => {
                                    setDraft((current) => clearAgentDraftFields(current, '_editor_instruction_proposal', '_editor_instruction_baseline'));
                                    setConfirmReplace(false);
                                }}>Discard generated draft</GlassButton>
                            </div>
                        </div>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}
