// groupMembership.ts
// The native group membership adapter behind the V2 Members section.
//
// It talks to the M7B backend family and nothing else:
// - GET and POST /api/groups/<g>/membership/members, PATCH and DELETE .../members/<user_id>;
// - GET .../membership/requests, and POST .../requests/<user_id>/approve and .../reject;
// - PUT .../membership/owner;
// plus the directory people search, GET /api/userSearch?query=, which the add dialog uses.
//
// Every membership response is validated strictly. A list whose envelope, hint or any row is
// malformed is a load error rather than a partly rendered list, because every control on the
// page is gated by those hints, and a row the reader could not verify would offer the wrong
// ones. Unknown operation or action names are ignored, so a newer server can only ever offer
// less here, never more. Every write returns the server's own row or outcome and the page
// reloads the list afterwards, so nothing is kept optimistically.
//
// The CSV import reads the classic manage page's format, with its rules and messages
// (manage_group.js, handleCsvFileSelect), so a file that works there works here. Each row is
// then added one at a time through the native route.

import { api, ApiError, requestWithStatus } from './apiClient';
import { codePointLength } from './groupDirectory';
import { groupRoleLabel } from './groupWorkspaceNavigation';
import { isRecord } from './workspaceAuthoring';
import { requireWorkspaceId } from './workspaceContext';

export const GROUP_MEMBER_ROLES = ['Owner', 'Admin', 'DocumentManager', 'User'] as const;
export type GroupMemberRole = typeof GROUP_MEMBER_ROLES[number];

/** The roles a member can be given. The owner changes only by transferring ownership. */
export const ASSIGNABLE_MEMBER_ROLES = ['Admin', 'DocumentManager', 'User'] as const;
export type AssignableMemberRole = typeof ASSIGNABLE_MEMBER_ROLES[number];

export const MEMBERSHIP_OPERATIONS = [
    'add_member', 'review_requests', 'change_role', 'remove_member', 'transfer_ownership', 'leave',
] as const;
export type MembershipOperation = typeof MEMBERSHIP_OPERATIONS[number];

export const MEMBER_ACTIONS = ['change_role', 'remove', 'transfer_ownership', 'leave'] as const;
export type MemberAction = typeof MEMBER_ACTIONS[number];

// The server's list and text limits (`functions_group_membership`), mirrored so the page never
// sends a request whose 400 a Retry could only repeat.
export const MEMBERS_PAGE_SIZE = 20;
export const MEMBERS_MAX_PAGE = 10000;
export const MEMBER_SEARCH_MAX_LENGTH = 200;
export const MEMBER_TEXT_MAX_LENGTH = 256;

export interface GroupMember {
    userId: string;
    displayName: string;
    email: string;
    role: GroupMemberRole;
    /** What the caller may do to this member, from the row's `member_actions`. */
    actions: MemberAction[];
}

export interface MemberListPage {
    members: GroupMember[];
    page: number;
    pageSize: number;
    totalCount: number;
    /** What the caller may do to the group's membership, from `membership_management`. */
    operations: MembershipOperation[];
}

export interface JoinRequest {
    userId: string;
    displayName: string;
    email: string;
}

export interface JoinRequestList {
    requests: JoinRequest[];
    totalCount: number;
}

export interface DirectoryUser {
    id: string;
    displayName: string;
    email: string;
}

export interface MemberListQuery {
    search: string;
    role: GroupMemberRole | null;
    page: number;
    pageSize: number;
}

export interface NewMember {
    userId: string;
    displayName: string;
    email: string;
    role: AssignableMemberRole;
}

/** A membership answer this reader could not verify, so its outcome is unknown. */
export class MembershipResponseError extends Error {
    constructor(message: string) {
        super(message);
        this.name = 'MembershipResponseError';
    }
}

const LIST_INVALID = 'The member list could not be read. Please retry.';
const REQUESTS_INVALID = 'The requests to join could not be read. Please retry.';
const WRITE_INVALID = 'The group returned an unexpected answer, so the members were reloaded. Check the change before trying again.';
const SEARCH_INVALID = 'The directory search returned an unexpected answer. Try again.';

export function isGroupMemberRole(value: unknown): value is GroupMemberRole {
    return typeof value === 'string' && (GROUP_MEMBER_ROLES as readonly string[]).includes(value);
}

function isWholeNumber(value: unknown, minimum: number): value is number {
    return typeof value === 'number' && Number.isInteger(value) && value >= minimum;
}

/** The known names from an array of strings, in canonical order; null when it is not one. */
function readNames<T extends string>(value: unknown, known: readonly T[]): T[] | null {
    if (!Array.isArray(value) || !value.every((entry) => typeof entry === 'string')) return null;
    return known.filter((name) => value.includes(name));
}

function readMemberRow(value: unknown): GroupMember | null {
    if (!isRecord(value) || typeof value.userId !== 'string' || !value.userId
        || typeof value.displayName !== 'string' || typeof value.email !== 'string'
        || !isGroupMemberRole(value.role)) {
        return null;
    }
    const actions = readNames(value.member_actions, MEMBER_ACTIONS);
    if (!actions) return null;
    return { userId: value.userId, displayName: value.displayName, email: value.email, role: value.role, actions };
}

/** A member row returned by a write. */
export function readGroupMember(value: unknown): GroupMember {
    const member = readMemberRow(value);
    if (!member) throw new MembershipResponseError(WRITE_INVALID);
    return member;
}

export function readMemberListPage(response: unknown): MemberListPage {
    if (!isRecord(response) || !Array.isArray(response.members)
        || !isWholeNumber(response.page, 1) || !isWholeNumber(response.page_size, 1)
        || !isWholeNumber(response.total_count, 0)
        || !isRecord(response.membership_management)
        || response.membership_management.schema_version !== 1) {
        throw new MembershipResponseError(LIST_INVALID);
    }
    const operations = readNames(response.membership_management.operations, MEMBERSHIP_OPERATIONS);
    const members = response.members.map(readMemberRow);
    if (!operations || members.some((member) => member === null)) {
        throw new MembershipResponseError(LIST_INVALID);
    }
    const rows = members as GroupMember[];
    // A person listed twice would let one row's controls act on the other's state.
    if (new Set(rows.map((member) => member.userId)).size !== rows.length) {
        throw new MembershipResponseError(LIST_INVALID);
    }
    return {
        members: rows,
        page: response.page,
        pageSize: response.page_size,
        totalCount: response.total_count,
        operations,
    };
}

export function readJoinRequests(response: unknown): JoinRequestList {
    if (!isRecord(response) || !Array.isArray(response.requests) || !isWholeNumber(response.total_count, 0)) {
        throw new MembershipResponseError(REQUESTS_INVALID);
    }
    const requests: JoinRequest[] = [];
    for (const entry of response.requests) {
        if (!isRecord(entry) || typeof entry.userId !== 'string' || !entry.userId
            || typeof entry.displayName !== 'string' || typeof entry.email !== 'string'
            || requests.some((request) => request.userId === entry.userId)) {
            throw new MembershipResponseError(REQUESTS_INVALID);
        }
        requests.push({ userId: entry.userId, displayName: entry.displayName, email: entry.email });
    }
    return { requests, totalCount: response.total_count };
}

/** The machine-readable `error_code` on a membership refusal, when the server sent one. */
export function membershipErrorCode(error: unknown): string | null {
    if (error instanceof ApiError && isRecord(error.payload) && typeof error.payload.error_code === 'string') {
        return error.payload.error_code;
    }
    return null;
}

/**
 * The text to show for a failed membership request: the server's own reviewed, data-free
 * `error`, or the caller's fallback for a transport failure or a non-JSON answer.
 */
export function membershipErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof MembershipResponseError) return error.message;
    if (error instanceof ApiError && isRecord(error.payload)
        && typeof error.payload.error === 'string' && error.payload.error.trim()) {
        return error.payload.error;
    }
    return fallback;
}

/**
 * A refusal after which the next request of the same kind can only be refused too, so a bulk
 * run or a CSV import stops rather than repeating it: the caller lost their standing, the group
 * is gone or can't take members now, or the session ended.
 */
export function isTerminalMembershipError(error: unknown): boolean {
    const code = membershipErrorCode(error);
    if (code && ['membership_permission', 'not_a_member', 'group_not_found', 'group_status_unavailable', 'owner_only'].includes(code)) {
        return true;
    }
    return error instanceof ApiError && error.status === 401;
}

/** A refusal that means the caller's own standing changed, so the workspace context is stale. */
export function isAccessChangedError(error: unknown): boolean {
    const code = membershipErrorCode(error);
    return code === 'membership_permission' || code === 'not_a_member' || code === 'owner_only'
        || code === 'group_not_found';
}

export function memberDisplayName(member: { displayName: string; email: string; userId: string }): string {
    return member.displayName.trim() || member.email.trim() || member.userId;
}

export const ASSIGNABLE_ROLE_OPTIONS: { value: AssignableMemberRole; label: string }[] = [
    { value: 'User', label: groupRoleLabel('User') },
    { value: 'DocumentManager', label: groupRoleLabel('DocumentManager') },
    { value: 'Admin', label: groupRoleLabel('Admin') },
];

export function isAssignableMemberRole(value: unknown): value is AssignableMemberRole {
    return typeof value === 'string' && (ASSIGNABLE_MEMBER_ROLES as readonly string[]).includes(value);
}

const MEMBER_TEXT_CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/;

/**
 * A directory value to send as the add's fallback details. The server resolves the person by
 * id and uses these only when the directory can't answer, so a value it would refuse is sent
 * empty rather than earning a 400 for the whole add.
 */
export function fallbackMemberText(value: string): string {
    const trimmed = value.trim();
    return codePointLength(trimmed) > MEMBER_TEXT_MAX_LENGTH || MEMBER_TEXT_CONTROL_CHARACTERS.test(trimmed) ? '' : trimmed;
}

function pathSegment(id: string): string {
    return encodeURIComponent(requireWorkspaceId(id));
}

export function memberListParams(query: MemberListQuery): string {
    const params = new URLSearchParams();
    const search = query.search.trim();
    if (search) params.set('search', search);
    if (query.role) params.set('role', query.role);
    params.set('page', String(query.page));
    params.set('page_size', String(query.pageSize));
    return params.toString();
}

export interface GroupMembershipClient {
    list: (query: MemberListQuery, signal?: AbortSignal) => Promise<MemberListPage>;
    requests: (signal?: AbortSignal) => Promise<JoinRequestList>;
    add: (member: NewMember) => Promise<GroupMember>;
    changeRole: (userId: string, role: AssignableMemberRole) => Promise<{ member: GroupMember; changed: boolean }>;
    remove: (userId: string) => Promise<{ userId: string; left: boolean }>;
    approve: (userId: string) => Promise<{ member: GroupMember; alreadyMember: boolean }>;
    reject: (userId: string) => Promise<{ userId: string }>;
    transfer: (userId: string) => Promise<{ owner: GroupMember; changed: boolean }>;
}

export function createGroupMembershipClient(groupId: string): GroupMembershipClient {
    const base = `/api/groups/${pathSegment(groupId)}/membership`;
    const memberPath = (userId: string) => `${base}/members/${pathSegment(userId)}`;
    const requestPath = (userId: string, decision: 'approve' | 'reject') => `${base}/requests/${pathSegment(userId)}/${decision}`;
    return {
        list: async (query, signal) => readMemberListPage(
            await api.get<unknown>(`${base}/members?${memberListParams(query)}`, signal),
        ),
        requests: async (signal) => readJoinRequests(await api.get<unknown>(`${base}/requests`, signal)),
        add: async (member) => {
            const { data } = await requestWithStatus<unknown>(`${base}/members`, {
                method: 'POST',
                body: { userId: member.userId, displayName: member.displayName, email: member.email, role: member.role },
            });
            if (!isRecord(data)) throw new MembershipResponseError(WRITE_INVALID);
            return readGroupMember(data.member);
        },
        changeRole: async (userId, role) => {
            const { data } = await requestWithStatus<unknown>(memberPath(userId), { method: 'PATCH', body: { role } });
            if (!isRecord(data) || typeof data.changed !== 'boolean') throw new MembershipResponseError(WRITE_INVALID);
            const member = readGroupMember(data.member);
            if (member.userId !== userId) throw new MembershipResponseError(WRITE_INVALID);
            return { member, changed: data.changed };
        },
        remove: async (userId) => {
            const { data } = await requestWithStatus<unknown>(memberPath(userId), { method: 'DELETE' });
            if (!isRecord(data) || data.userId !== userId || typeof data.left !== 'boolean') {
                throw new MembershipResponseError(WRITE_INVALID);
            }
            return { userId, left: data.left };
        },
        approve: async (userId) => {
            const { data } = await requestWithStatus<unknown>(requestPath(userId, 'approve'), { method: 'POST' });
            if (!isRecord(data) || typeof data.already_member !== 'boolean') throw new MembershipResponseError(WRITE_INVALID);
            const member = readGroupMember(data.member);
            if (member.userId !== userId) throw new MembershipResponseError(WRITE_INVALID);
            return { member, alreadyMember: data.already_member };
        },
        reject: async (userId) => {
            const { data } = await requestWithStatus<unknown>(requestPath(userId, 'reject'), { method: 'POST' });
            if (!isRecord(data) || data.userId !== userId) throw new MembershipResponseError(WRITE_INVALID);
            return { userId };
        },
        transfer: async (userId) => {
            const { data } = await requestWithStatus<unknown>(`${base}/owner`, { method: 'PUT', body: { userId } });
            if (!isRecord(data) || typeof data.changed !== 'boolean') throw new MembershipResponseError(WRITE_INVALID);
            const owner = readGroupMember(data.owner);
            if (owner.userId !== userId || owner.role !== 'Owner') throw new MembershipResponseError(WRITE_INVALID);
            return { owner, changed: data.changed };
        },
    };
}

/**
 * Search the directory for people to add, through the caller's own delegated access.
 *
 * The answer is a bare array of `{id, displayName, email}`. It is not a membership envelope, so
 * an entry without an id is skipped rather than failing the whole search; anything that is not
 * an array is refused.
 */
export async function searchDirectoryUsers(query: string, signal?: AbortSignal): Promise<DirectoryUser[]> {
    const term = query.trim();
    if (!term) return [];
    const response = await api.get<unknown>(`/api/userSearch?query=${encodeURIComponent(term)}`, signal);
    if (!Array.isArray(response)) throw new MembershipResponseError(SEARCH_INVALID);
    const users: DirectoryUser[] = [];
    for (const entry of response) {
        if (!isRecord(entry) || typeof entry.id !== 'string' || !entry.id.trim()
            || users.some((user) => user.id === entry.id)) {
            continue;
        }
        users.push({
            id: entry.id,
            displayName: typeof entry.displayName === 'string' ? entry.displayName : '',
            email: typeof entry.email === 'string' ? entry.email : '',
        });
    }
    return users;
}

// ---------------------------------------------------------------------------------------------
// CSV import, in the classic manage page's format.
// ---------------------------------------------------------------------------------------------

export const MEMBER_CSV_MAX_ROWS = 1000;
export const MEMBER_CSV_HEADER = 'userId,displayName,email,role';

const CSV_GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CSV_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CSV_ROLES = new Map<string, AssignableMemberRole>([
    ['user', 'User'],
    ['admin', 'Admin'],
    ['document_manager', 'DocumentManager'],
]);

export interface MemberCsvRow {
    /** The row number the classic page reports: blank lines are skipped, the header is row 1. */
    row: number;
    userId: string;
    displayName: string;
    email: string;
    role: AssignableMemberRole;
}

export interface MemberCsvParse {
    rows: MemberCsvRow[];
    /** Any error refuses the whole file, as the classic page does. */
    errors: string[];
}

export function parseMemberCsv(text: string): MemberCsvParse {
    const lines = text.split(/\r?\n/).filter((line) => line.trim());
    if (lines.length < 2) {
        return { rows: [], errors: ['CSV must contain at least a header row and one data row'] };
    }
    if (lines[0].toLowerCase().trim() !== MEMBER_CSV_HEADER.toLowerCase()) {
        return { rows: [], errors: [`Invalid header. Expected: ${MEMBER_CSV_HEADER}`] };
    }
    const dataRows = lines.slice(1);
    if (dataRows.length > MEMBER_CSV_MAX_ROWS) {
        return { rows: [], errors: [`Too many rows. Maximum 1,000 members allowed (found ${dataRows.length})`] };
    }
    const rows: MemberCsvRow[] = [];
    const errors: string[] = [];
    dataRows.forEach((line, index) => {
        const rowNumber = index + 2;
        const cells = line.split(',');
        if (cells.length !== 4) {
            errors.push(`Row ${rowNumber}: Expected 4 columns, found ${cells.length}`);
            return;
        }
        const userId = cells[0].trim();
        const displayName = cells[1].trim();
        const email = cells[2].trim();
        const roleName = cells[3].trim().toLowerCase();
        if (!userId || !displayName || !email || !roleName) {
            errors.push(`Row ${rowNumber}: All fields are required`);
            return;
        }
        if (!CSV_GUID.test(userId)) {
            errors.push(`Row ${rowNumber}: Invalid GUID format for userId`);
            return;
        }
        if (!CSV_EMAIL.test(email)) {
            errors.push(`Row ${rowNumber}: Invalid email format`);
            return;
        }
        const role = CSV_ROLES.get(roleName);
        if (!role) {
            errors.push(`Row ${rowNumber}: Invalid role '${roleName}'. Must be: user, admin, or document_manager`);
            return;
        }
        rows.push({ row: rowNumber, userId, displayName, email, role });
    });
    return errors.length ? { rows: [], errors } : { rows, errors };
}
