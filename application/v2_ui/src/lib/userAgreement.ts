// userAgreement.ts
// The User Agreement an administrator can require before files are uploaded.
//
// Classic enforces it in the browser (static/js/user-agreement.js): before an upload it asks
// GET /api/user_agreement/check, shows the agreement when the answer is yes, records the answer with
// POST /api/user_agreement/accept, and only then sends the files. No upload route checks it, so the
// browser is the whole control. V2 had only the administrator's preview of the dialog, which meant a
// V2 user could upload without ever being shown the agreement.
//
// This is the V2 client for the same two routes, sending the same parameters. That matters beyond
// tidiness: "accept once per day" is answered from the activity-log records those routes write, keyed
// by workspace type and workspace id, so an acceptance made in either interface counts in the other
// only if both name the workspace the same way. Chat and personal uploads therefore send `default`
// as the workspace id, exactly as classic does.
//
// Where V2 deliberately differs from classic: classic fails open. A check that errors lets the upload
// carry on, and so does an acceptance the server could not record. For a compliance control that is the
// wrong default, so here neither does (see `agreementFailureMessage` and useUserAgreementGate). A request
// that never answers counts as a failed one after a fixed time (USER_AGREEMENT_REQUEST_TIMEOUT_MS), so it
// cannot hold an upload or the dialog for good.

import { ApiError, request } from './apiClient';
import type { Json } from './types';

/** The workspace types the routes accept (`valid_types` in route_backend_user_agreement.py). */
export type UserAgreementWorkspaceType = 'chat' | 'personal' | 'group' | 'public';

export interface UserAgreementScope {
    type: UserAgreementWorkspaceType;
    /** The group or public workspace. Chat and personal uploads have none of their own. */
    id?: string;
}

export const USER_AGREEMENT_CHECK_PATH = '/api/user_agreement/check';
export const USER_AGREEMENT_ACCEPT_PATH = '/api/user_agreement/accept';

/**
 * What both routes default to and classic always sends. The check route also reads `chat` here as a
 * second way for the chat setting to apply, which classic never uses, so V2 does not either.
 */
export const USER_AGREEMENT_ACTION_CONTEXT = 'file_upload';

/** What classic sends as the workspace id where a scope has no id of its own. */
export const USER_AGREEMENT_DEFAULT_WORKSPACE_ID = 'default';

export const CHAT_AGREEMENT_SCOPE: Readonly<UserAgreementScope> = Object.freeze({ type: 'chat' });

/** The workspace documents explorer's scope, which already names its kind and id. */
export function workspaceAgreementScope(
    scope: { kind: 'personal' | 'group' | 'public'; id?: string },
): UserAgreementScope {
    return scope.kind === 'personal' ? { type: 'personal' } : { type: scope.kind, id: scope.id };
}

/**
 * The workspace id the routes are told about.
 *
 * Classic skips the check altogether when a group or public page has no active workspace, which
 * would let a missing id bypass the agreement. A group or public upload without an id is a bug in
 * the caller, so it is refused here instead.
 */
export function agreementWorkspaceId(scope: UserAgreementScope): string {
    if (scope.type === 'group' || scope.type === 'public') {
        const id = typeof scope.id === 'string' ? scope.id.trim() : '';
        if (!id) {
            throw new Error(`A ${scope.type} workspace id is required to check the user agreement.`);
        }
        return id;
    }
    return USER_AGREEMENT_DEFAULT_WORKSPACE_ID;
}

export function userAgreementCheckPath(scope: UserAgreementScope): string {
    const query = new URLSearchParams({
        workspace_type: scope.type,
        workspace_id: agreementWorkspaceId(scope),
        action_context: USER_AGREEMENT_ACTION_CONTEXT,
    });
    return `${USER_AGREEMENT_CHECK_PATH}?${query.toString()}`;
}

export function userAgreementAcceptBody(scope: UserAgreementScope): Record<string, string> {
    return {
        workspace_type: scope.type,
        workspace_id: agreementWorkspaceId(scope),
        action_context: USER_AGREEMENT_ACTION_CONTEXT,
    };
}

/**
 * Whether the administrator's switch could be on, as the bootstrap payload carries it.
 *
 * Classic only loads its agreement script when `enable_user_agreement` is on, so a deployment that
 * does not use the feature never pays for a check. V2 does the same. The server reads a missing
 * switch as off, so a missing value is off here too; anything else that is not an explicit off is
 * treated as possibly on, which sends an unexpected stored value to the server to decide rather than
 * skipping the control on a guess.
 */
export function userAgreementSwitchedOn(settings: Json | null | undefined): boolean {
    const value = settings?.enable_user_agreement;
    return value !== undefined && value !== null && value !== false;
}

/**
 * What to do before an upload of `fileCount` files starts.
 *
 * - `nothing`: no files, so there is nothing to upload and nothing to ask (classic returns here too).
 * - `proceed`: the feature is off, so the upload goes ahead without a request.
 * - `check`: ask the server, which knows the scopes the agreement applies to and today's acceptances.
 */
export type AgreementGateDecision = 'nothing' | 'proceed' | 'check';

export function agreementGateDecision(settings: Json | null | undefined, fileCount: number): AgreementGateDecision {
    if (!(fileCount > 0)) {
        return 'nothing';
    }
    return userAgreementSwitchedOn(settings) ? 'check' : 'proceed';
}

/** The server's answer to a check. */
export interface UserAgreementCheck {
    needsAgreement: boolean;
    agreementText: string;
    enableDailyAcceptance: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Read a check response, refusing anything that does not clearly say whether an agreement applies.
 *
 * A reply that cannot be read is a failed check, never "no agreement": an HTML error page or a
 * proxy's JSON must not let an upload through.
 */
export function parseUserAgreementCheck(payload: unknown): UserAgreementCheck {
    if (!isRecord(payload) || typeof payload.needsAgreement !== 'boolean') {
        throw new Error('The user agreement check returned an unexpected answer.');
    }
    return {
        needsAgreement: payload.needsAgreement,
        agreementText: typeof payload.agreementText === 'string' ? payload.agreementText : '',
        enableDailyAcceptance: payload.enableDailyAcceptance === true,
    };
}

/**
 * How long a check or an acceptance may take before it counts as failed.
 *
 * `request()` has no time limit of its own, so a request that never answered would hold the upload for
 * good: a check holds Send, and an acceptance holds the dialog, whose Cancel is ignored while one is in
 * flight. Twenty seconds is far longer than either takes, and short enough that no one is left looking at
 * nothing. A request that runs out of time takes the path of any other failure: the dialog says so, and
 * offers Try again and Cancel.
 */
export const USER_AGREEMENT_REQUEST_TIMEOUT_MS = 20_000;

/** A check or an acceptance that did not answer within USER_AGREEMENT_REQUEST_TIMEOUT_MS. */
export class UserAgreementTimeoutError extends Error {
    constructor() {
        super(`The user agreement request did not answer within ${USER_AGREEMENT_REQUEST_TIMEOUT_MS / 1000} seconds.`);
        this.name = 'UserAgreementTimeoutError';
    }
}

/**
 * Send a request that is abandoned once USER_AGREEMENT_REQUEST_TIMEOUT_MS has passed.
 *
 * The request gets a controller of its own. It follows the caller's signal, which the gate aborts when its
 * owner goes away, and it is also aborted when the time runs out. A timeout rejects with
 * UserAgreementTimeoutError; an abort by the caller rejects as the request does, so the two stay apart.
 */
async function withTimeLimit<T>(
    callerSignal: AbortSignal | undefined,
    send: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
    const controller = new AbortController();
    const followCaller = () => controller.abort();
    if (callerSignal?.aborted) {
        controller.abort();
    } else {
        callerSignal?.addEventListener('abort', followCaller, { once: true });
    }
    let timedOut = false;
    const timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, USER_AGREEMENT_REQUEST_TIMEOUT_MS);
    try {
        return await send(controller.signal);
    } catch (error) {
        throw timedOut && !callerSignal?.aborted ? new UserAgreementTimeoutError() : error;
    } finally {
        clearTimeout(timer);
        callerSignal?.removeEventListener('abort', followCaller);
    }
}

export async function checkUserAgreement(scope: UserAgreementScope, signal?: AbortSignal): Promise<UserAgreementCheck> {
    // Built first, so a scope that cannot be asked about never starts a request or a timer.
    const path = userAgreementCheckPath(scope);
    // `no-store`: the answer depends on acceptances recorded moments ago, so a cached read must never
    // stand in for it.
    const payload = await withTimeLimit(signal, (limited) => request<unknown>(
        path, { method: 'GET', signal: limited, cache: 'no-store' },
    ));
    return parseUserAgreementCheck(payload);
}

/** Record the acceptance. Resolves only when the server says it was recorded. */
export async function acceptUserAgreement(scope: UserAgreementScope, signal?: AbortSignal): Promise<void> {
    const body = userAgreementAcceptBody(scope);
    // An acceptance that times out is a failed one, however the server went on to treat the request:
    // nothing is reported as accepted that the server did not say it recorded.
    const payload = await withTimeLimit(signal, (limited) => request<unknown>(
        USER_AGREEMENT_ACCEPT_PATH, { method: 'POST', body, signal: limited },
    ));
    if (!isRecord(payload) || payload.success !== true) {
        throw new Error('The server did not confirm that your acceptance was recorded.');
    }
}

export const CHECK_FAILED_MESSAGE = 'We could not confirm whether a user agreement applies, so nothing was uploaded.';
export const ACCEPT_FAILED_MESSAGE = 'Your acceptance could not be recorded, so nothing was uploaded.';

/**
 * Said, as text and not only as a held Send control, while a file waits on the agreement before it is
 * attached. The file has no chip yet, so this is the only place the wait is explained.
 */
export const AGREEMENT_PENDING_MESSAGE = 'Checking the user agreement before attaching your file…';

/** The sentence shown when a check or an acceptance fails. The server's own text is never echoed. */
export function agreementFailureMessage(phase: 'check' | 'accept', error: unknown): string {
    const sentence = phase === 'check' ? CHECK_FAILED_MESSAGE : ACCEPT_FAILED_MESSAGE;
    if (error instanceof UserAgreementTimeoutError) {
        return `${sentence} (no answer within ${USER_AGREEMENT_REQUEST_TIMEOUT_MS / 1000} seconds)`;
    }
    return error instanceof ApiError && error.status > 0 ? `${sentence} (status ${error.status})` : sentence;
}
