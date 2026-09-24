// test_v2_group_file_sources.ts
//
// Runtime pin for the scope seam in fileSourceWorkbench.ts.
// Version: 0.261.145
// Implemented in: 0.261.145
//
// The browser suite proves the group editor, gating, conflict and delete behaviour against a
// mocked backend. It cannot prove the one property the contract calls the floor: that the personal
// adapter stays byte-identical in transport to the file-sync functions the section shipped with,
// and that the group adapter never reaches for a personal URL (or the reverse). That isolation
// lives entirely in the scope branch, so exercising both adapters against a stubbed api client pins
// it decisively, with a positive control beside every negative one.
//
// Run by test_v2_group_file_sources.py, bundled with the esbuild Vite already provides and executed
// under node, requiring only the existing front-end toolchain.

import assert from 'node:assert/strict';
import { api } from '../application/v2_ui/src/lib/apiClient';
import {
    PERSONAL_FILE_SOURCE_WORKBENCH,
    createGroupFileSourceWorkbench,
} from '../application/v2_ui/src/lib/fileSourceWorkbench';

interface Call { method: string; path: string; body?: unknown; }
const calls: Call[] = [];

function stub(result: unknown): void {
    calls.length = 0;
    (api as unknown as Record<string, unknown>).get = async (path: string) => {
        calls.push({ method: 'GET', path });
        return result;
    };
    (api as unknown as Record<string, unknown>).post = async (path: string, body?: unknown) => {
        calls.push({ method: 'POST', path, body });
        return result;
    };
    (api as unknown as Record<string, unknown>).delete = async (path: string, body?: unknown) => {
        calls.push({ method: 'DELETE', path, body });
        return result;
    };
}

const PERSONAL_PREFIX = '/api/file-sync/personal/';
const GROUP_PREFIX = '/api/groups/';

async function testPersonalTransportIsUnchanged(): Promise<void> {
    const adapter = PERSONAL_FILE_SOURCE_WORKBENCH;
    // The personal section can still do everything it shipped able to do: the gate never refuses.
    assert.equal(adapter.allows('create'), true, 'Personal scope never refuses an operation.');
    assert.equal(adapter.manageable, false, 'Personal scope advertises no group-style create control.');

    stub({ sources: [{ id: 's1' }] });
    await adapter.list();
    assert.deepEqual(calls, [{ method: 'GET', path: '/api/file-sync/personal/sources' }],
        'The personal list must hit the shipped personal sources URL, unchanged.');

    stub({ runs: [{ id: 'r1' }] });
    await adapter.runs('s1');
    assert.deepEqual(calls, [{ method: 'GET', path: '/api/file-sync/personal/sources/s1/runs' }],
        'The personal runs must hit the shipped personal runs URL, unchanged.');

    stub({ run: { id: 'r2' } });
    await adapter.sync('s1');
    assert.deepEqual(calls, [{ method: 'POST', path: '/api/file-sync/personal/sources/s1/sync', body: undefined }],
        'The personal sync must hit the shipped personal sync URL, unchanged.');

    stub({ message: 'ok' });
    await adapter.remove({ id: 's1' } as never, true);
    assert.deepEqual(calls, [{
        method: 'DELETE', path: '/api/file-sync/personal/sources/s1',
        body: { delete_associated_files: true },
    }], 'The personal delete must send the documents choice on the shipped personal URL, unchanged.');

    // Options and identities are group-only concepts, so the personal path answers them inertly and
    // never issues a request for them.
    stub({});
    assert.equal(await adapter.options(), null, 'Personal scope has no options endpoint.');
    assert.deepEqual(await adapter.identities(), [], 'Personal scope has no identities endpoint.');
    assert.equal(calls.length, 0, 'Personal options and identities must issue no request.');

    // The writes the section only ever offered in the classic workspace stay refused here, so the
    // group affordances can never be driven against a personal scope.
    for (const attempt of [
        () => adapter.create({ name: 'x' }),
        () => adapter.update({ id: 's1' } as never, { name: 'x' }),
        () => adapter.testConnection({ id: 's1' } as never, { name: 'x' }),
        () => adapter.browse({ id: 's1' } as never, { name: 'x' }, ''),
        () => adapter.ignorePath('s1', 'p', true),
    ]) {
        await assert.rejects(async () => attempt(), 'A personal file source write must be refused.');
    }
}

async function testGroupTransportNeverTouchesPersonal(): Promise<void> {
    const adapter = createGroupFileSourceWorkbench(
        { kind: 'group', id: 'group-a', name: 'A' },
        { schema_version: 1, operations: ['create', 'edit', 'delete', 'sync', 'test'] },
    );

    stub({ file_sources: [{ id: 's1' }], file_source_management: { schema_version: 1, operations: [] } });
    await adapter.list();
    assert.deepEqual(calls, [{ method: 'GET', path: '/api/groups/group-a/file-sources' }],
        'The group list must hit the immutable group route.');

    stub({ runs: [] });
    await adapter.runs('s1');
    assert.deepEqual(calls, [{ method: 'GET', path: '/api/groups/group-a/file-sources/s1/runs' }],
        'The group runs must hit the immutable group route.');

    stub({ run: { id: 'r1' } });
    await adapter.sync('s1');
    assert.deepEqual(calls, [{ method: 'POST', path: '/api/groups/group-a/file-sources/s1/sync', body: undefined }],
        'The group sync must hit the immutable group route.');

    // The seam is the whole guarantee: no group request may ever fall through to a personal URL.
    for (const call of calls) {
        assert.ok(!call.path.startsWith(PERSONAL_PREFIX),
            `A group operation must never reach a personal URL: ${call.path}`);
    }
    assert.ok(calls.every((call) => call.path.startsWith(GROUP_PREFIX)),
        'Every group operation stays under the group route prefix.');
}

async function main(): Promise<void> {
    await testPersonalTransportIsUnchanged();
    await testGroupTransportNeverTouchesPersonal();
    console.log('group file source scope seam checks passed');
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
