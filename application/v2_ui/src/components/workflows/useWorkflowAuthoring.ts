// useWorkflowAuthoring.ts

import { useCallback, useRef, useState } from 'react';
import {
    applyWorkflowEdit, workflowDraftStructure, type WorkflowEditCommand, type WorkflowEditImpact, type WorkflowEditResult,
} from '../../lib/workflowAuthoring';
import { workflowErrorMessage, type WorkflowDefinition, type WorkflowEditorOptions } from '../../lib/workflowEditor';
import type { WorkflowAuthoringFocus } from './WorkflowFlowAuthoring';

interface PendingEdit {
    command: WorkflowEditCommand;
    source: WorkflowDefinition;
    message: string;
    impact: WorkflowEditImpact[];
}

export function useWorkflowAuthoring({
    draft, options, readOnly, saving, onChange, onError, getDraft, onRejected,
}: {
    draft: WorkflowDefinition;
    options: WorkflowEditorOptions;
    readOnly: boolean;
    saving: boolean;
    onChange: (workflow: WorkflowDefinition, command: WorkflowEditCommand, selectedId: string) => boolean | void;
    onError: (message: string) => void;
    getDraft?: () => WorkflowDefinition;
    onRejected?: () => void;
}) {
    const latest = useRef({ draft, options, readOnly, saving, onChange, onError, getDraft, onRejected });
    latest.current = { draft, options, readOnly, saving, onChange, onError, getDraft, onRejected };
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [positions, setPositions] = useState(() => new Map<string, { x: number; y: number }>());
    const [collapsed, setCollapsed] = useState(() => new Set<string>());
    const [focusRequest, setFocusRequest] = useState<WorkflowAuthoringFocus | null>(null);
    const [pending, setPending] = useState<PendingEdit | null>(null);
    const [announcement, setAnnouncement] = useState('');
    const sequence = useRef(0);

    const requestFocus = useCallback((id: string, fields = false) => {
        setFocusRequest({ id, sequence: ++sequence.current, fields });
    }, []);

    const evaluate = useCallback((command: WorkflowEditCommand, confirmed: boolean): WorkflowEditResult => {
        const current = latest.current;
        if (current.readOnly || current.saving) {
            return { status: 'rejected', message: 'Editing is unavailable while this workflow is read-only or being saved.' };
        }
        try {
            return applyWorkflowEdit(current.getDraft?.() ?? current.draft, command, current.options, confirmed);
        } catch (cause: unknown) {
            return { status: 'rejected', message: workflowErrorMessage(cause, 'The draft edit could not be applied. No changes were saved.') };
        }
    }, []);

    const execute = useCallback((command: WorkflowEditCommand, confirmed = false) => {
        const current = { ...latest.current, draft: latest.current.getDraft?.() ?? latest.current.draft };
        const result = evaluate(command, confirmed);
        if (result.status === 'rejected') {
            current.onRejected?.();
            current.onError(result.message);
            return result.status;
        }
        current.onError('');
        if (result.status === 'confirmation_required') {
            current.onRejected?.();
            setPending({ command, source: current.draft, message: result.message, impact: result.impact });
            return result.status;
        }
        if (current.onChange(result.workflow, command, result.selectedId) === false) return 'rejected';
        const structural = command.type === 'add' || command.type === 'move' || command.type === 'remove';
        if (structural) {
            const before = new Map(workflowDraftStructure(current.draft).nodes.map((node) => [node.id, node.parent_id]));
            const after = new Map(workflowDraftStructure(result.workflow).nodes.map((node) => [node.id, node.parent_id]));
            setPositions((positions) => new Map([...positions].filter(([id]) =>
                after.has(id) && before.get(id) === after.get(id))));
            setCollapsed((collapsed) => new Set([...collapsed].filter((id) => after.has(id))));
            setSelectedId(result.selectedId);
            requestFocus(result.selectedId, command.type === 'add');
            setAnnouncement(command.type === 'add' ? 'Block added to the unsaved draft.'
                : command.type === 'move' ? 'Block moved in execution order. The draft has not been saved.'
                    : 'Block removed from the unsaved draft. Existing references were not retargeted.');
        } else setSelectedId((selected) => selected ?? result.selectedId);
        latest.current = { ...current, draft: result.workflow };
        return result.status;
    }, [evaluate, requestFocus]);

    const confirm = useCallback(() => {
        if (!pending) return;
        const currentDraft = latest.current.getDraft?.() ?? latest.current.draft;
        if (pending.source !== currentDraft) {
            const result = evaluate(pending.command, false);
            if (result.status === 'rejected') {
                latest.current.onError(result.message);
                setPending(null);
            } else {
                setPending({ ...pending, source: currentDraft, impact: result.impact,
                    message: 'The draft changed while confirmation was open. Review the current impact and confirm again; no edit has been applied.' });
            }
            return;
        }
        setPending(null);
        execute(pending.command, true);
    }, [pending, evaluate, execute]);

    const cancel = useCallback(() => {
        setPending(null);
        if (pending && (pending.command.type === 'move' || pending.command.type === 'remove')) {
            requestFocus(pending.command.nodeId);
        }
    }, [pending, requestFocus]);

    const recover = useCallback((before: WorkflowDefinition, after: WorkflowDefinition, targetId?: string, focus = true) => {
        const previous = workflowDraftStructure(before);
        const next = workflowDraftStructure(after);
        const targets = new Map(next.nodes.map((node) => [node.id, node]));
        const old = previous.nodes.find((node) => node.id === (targetId ?? selectedId));
        const siblings = old ? next.nodes.filter((node) => node.parent_id === old.parent_id) : [];
        const id = targetId && targets.has(targetId) ? targetId
            : old ? siblings.find((node) => node.order >= old.order)?.id ?? siblings.at(-1)?.id ??
                (old.parent_id && targets.has(old.parent_id) ? old.parent_id : next.root_region_id)
                : selectedId && targets.has(selectedId) ? selectedId : next.root_region_id;
        const parents = new Map(previous.nodes.map((node) => [node.id, node.parent_id]));
        setPositions((current) => new Map([...current].filter(([key]) =>
            targets.has(key) && targets.get(key)?.parent_id === parents.get(key))));
        setCollapsed((current) => new Set([...current].filter((key) => targets.has(key))));
        setSelectedId(id);
        if (focus) requestFocus(id);
        else setFocusRequest(null);
        setAnnouncement('');
        latest.current = { ...latest.current, draft: after };
    }, [selectedId, requestFocus]);

    const reset = useCallback(() => {
        setPending(null);
        setSelectedId(null);
        setPositions(new Map());
        setCollapsed(new Set());
        setFocusRequest(null);
        setAnnouncement('');
    }, []);

    return {
        selectedId, setSelectedId, positions, setPositions, collapsed, setCollapsed,
        focusRequest, requestFocus, pending, cancel, confirm, execute, announcement, recover, reset,
    };
}
