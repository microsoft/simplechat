// ActionRecoveryNotice.tsx

import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import {
    chooseActionRecovery, clearActionRecovery, getActionRecovery, reportUnavailableAction,
    restoreActionRecovery, safeRecoveryEditUrl, setActionRecoveryConversation, subscribeActionRecovery,
} from '../../lib/actionRecovery';
import { resumeActionRecoveryChat, useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';

export function ActionRecoveryNotice({ conversationId, hasAgent, agentSelection }: {
    conversationId: string | null; hasAgent: boolean; agentSelection?: string;
}) {
    const actorId = useBootstrapStore((state) => state.data?.user?.id);
    const notice = useSyncExternalStore(subscribeActionRecovery, getActionRecovery);
    const streaming = useChatStore((state) => state.streaming);
    const [reports, setReports] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    useLayoutEffect(() => () => clearActionRecovery(), [agentSelection, actorId]);
    useLayoutEffect(() => {
        setActionRecoveryConversation(conversationId);
    }, [conversationId]);
    useEffect(() => {
        if (!conversationId) return;
        const controller = new AbortController();
        void restoreActionRecovery(conversationId, controller.signal).catch((failure: unknown) => {
            if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Recovery is unavailable.');
        });
        return () => controller.abort();
    }, [conversationId, actorId]);
    useEffect(() => { setReports({}); setError(null); }, [notice?.recovery.id, conversationId]);

    if (!notice || notice.recovery.conversation_id !== conversationId || notice.actorId !== actorId) {
        return hasAgent ? (
            <p className="px-1 py-2 text-xs text-text-3" role="status">
                {error ?? 'Actions are checked before sending. Service sign-in and approvals may still be required.'}
            </p>
        ) : null;
    }
    const { recovery, body, waiting, checking } = notice;
    const report = async (key: string) => {
        setReports((current) => ({ ...current, [key]: 'Sending report...' }));
        try {
            await reportUnavailableAction(recovery.id, key);
            if (getActionRecovery()?.recovery.id === recovery.id) {
                setReports((current) => ({ ...current, [key]: 'Reported' }));
            }
        } catch {
            if (getActionRecovery()?.recovery.id === recovery.id) {
                setReports((current) => ({ ...current, [key]: 'Delivery uncertain. Retry safely.' }));
            }
        }
    };
    const content = (
        <div className="space-y-3 text-sm text-text-2 [overflow-wrap:anywhere]">
            <p><strong>{recovery.agent_name}</strong>: {!recovery.id
                ? 'Your message has not been sent. Recheck before sending.'
                : recovery.ready ? 'Actions are available again. Your message has not been sent.'
                    : 'The actions below could not load. No model or action has run.'}</p>
            {recovery.all_actions_unavailable && (
                <p className="font-medium text-text-1">All assigned actions are unavailable. Continuing cannot use any of them.</p>
            )}
            <ul className="divide-y divide-edge">
                {recovery.actions.map((action) => (
                    <li key={action.key} className="space-y-1 py-3">
                        <p className="font-medium text-text-1">{action.name}</p>
                        <p className="text-xs text-text-3">{action.scope} action</p>
                        <p>{action.reason}</p>
                        <p className="text-xs text-text-3">Unavailable: {action.capabilities.join(', ')}</p>
                        {!action.edit_url && <p>Contact the action's owner or administrator to review its configuration.</p>}
                        <div className="flex flex-wrap items-center gap-3">
                            {safeRecoveryEditUrl(action.edit_url) && (
                                <a className="text-accent underline" href={safeRecoveryEditUrl(action.edit_url)}
                                    target="_blank" rel="noopener noreferrer">Open action in a new tab</a>
                            )}
                            {action.can_report && (
                                <GlassButton size="sm" disabled={reports[action.key] === 'Reported' || reports[action.key] === 'Sending report...'}
                                    onClick={() => { void report(action.key); }}>
                                    {reports[action.key] === 'Reported' ? 'Reported' : 'Notify owner/admin'}
                                </GlassButton>
                            )}
                            <span role="status" className="text-xs text-text-3">{reports[action.key]}</span>
                        </div>
                    </li>
                ))}
            </ul>
            <details>
                <summary className="cursor-pointer text-text-1">Preserved unsent message</summary>
                <p className="mt-2 whitespace-pre-wrap">{body.message}</p>
            </details>
            <p className="text-xs text-text-3">Existing sign-in, credential and approval prompts still apply when an available action is used. This choice never retries a calendar or email operation.</p>
            {(error || notice.error) && <p role="alert" className="text-danger">{error || notice.error}</p>}
        </div>
    );
    if (!waiting) {
        return (
            <section className="my-2 rounded-xl border border-edge bg-surface-2 p-3" aria-label="Unavailable actions">
                <h2 className="mb-2 text-sm font-semibold text-text-1">{!recovery.id
                    ? 'Action availability could not be confirmed'
                    : recovery.ready ? 'Your unsent request is ready to recheck' : 'This agent has unavailable actions'}</h2>
                {content}
                <GlassButton className="mt-3" disabled={streaming} onClick={() => {
                    void resumeActionRecoveryChat(body).catch((failure: unknown) => {
                        setError(failure instanceof Error ? failure.message : 'The preserved message could not be continued.');
                    });
                }}>Recheck and send preserved request</GlassButton>
            </section>
        );
    }
    return (
        <Modal title="This agent has unavailable actions" onClose={() => chooseActionRecovery('cancel')}
            description="Choose whether to continue with fewer capabilities. Your message is preserved."
            footer={(
                <div className="flex flex-wrap justify-end gap-2">
                    <GlassButton onClick={() => chooseActionRecovery('cancel')}>Cancel / choose another agent</GlassButton>
                    <GlassButton disabled={checking} onClick={() => chooseActionRecovery('recheck')}>
                        {checking ? 'Checking...' : 'Recheck'}
                    </GlassButton>
                    <GlassButton variant="primary" disabled={checking} onClick={() => chooseActionRecovery('continue')}>
                        Continue without these actions
                    </GlassButton>
                </div>
            )}>{content}</Modal>
    );
}
