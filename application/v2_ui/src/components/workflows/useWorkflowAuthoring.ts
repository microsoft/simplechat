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
    draft, options, readOnly, saving, onChange, onError,
}: {
    draft: WorkflowDefinition;
    options: WorkflowEditorOptions;
    readOnly: boolean;
    saving: boolean;
    onChange: (workflow: WorkflowDefinition) => void;
    onError: (message: string) => void;
}) {
    const latest = useRef({ draft, options, readOnly, saving, onChange, onError });
    latest.current = { draft, options, readOnly, saving, onChange, onError };
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
            return applyWorkflowEdit(current.draft, command, current.options, confirmed);
        } catch (cause: unknown) {
            return { status: 'rejected', message: workflowErrorMessage(cause, 'The draft edit could not be applied. No changes were saved.') };
        }
    }, []);

    const execute = useCallback((command: WorkflowEditCommand, confirmed = false) => {
        const current = latest.current;
        const result = evaluate(command, confirmed);
        if (result.status === 'rejected') {
            current.onError(result.message);
            return result.status;
        }
        current.onError('');
        if (result.status === 'confirmation_required') {
            setPending({ command, source: current.draft, message: result.message, impact: result.impact });
            return result.status;
        }
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
        current.onChange(result.workflow);
        return result.status;
    }, [evaluate, requestFocus]);

    const confirm = useCallback(() => {
        if (!pending) return;
        if (pending.source !== latest.current.draft) {
            const result = evaluate(pending.command, false);
            if (result.status === 'rejected') {
                latest.current.onError(result.message);
                setPending(null);
            } else {
                setPending({ ...pending, source: latest.current.draft, impact: result.impact,
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

    return {
        selectedId, setSelectedId, positions, setPositions, collapsed, setCollapsed,
        focusRequest, requestFocus, pending, cancel, confirm, execute, announcement,
    };
}
