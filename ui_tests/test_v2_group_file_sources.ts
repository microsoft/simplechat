// test_v2_group_file_sources.ts
//
// Runtime pin for the scope seam in fileSourceWorkbench.ts.
// Version: 0.261.310
// Implemented in: 0.261.147
// Tag suggestions read by explicit group: 0.261.171
//
// The browser suite proves the group editor, gating, conflict and delete behaviour against a
// mocked backend. This probe proves that the personal list/sync/history keep their existing URLs,
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
    assert.equal(adapter.manageable, true, 'Personal scope offers native creation.');

    stub({ sources: [{ id: 's1', config_revision: 'r1' }] });
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

    // Full native personal configuration is exercised by file_source_configuration_probe.ts.
}

async function testGroupTransportNeverTouchesPersonal(): Promise<void> {
    const adapter = createGroupFileSourceWorkbench(
        { kind: 'group', id: 'group-a', name: 'A' },
        { schema_version: 1, operations: ['create', 'edit', 'delete', 'sync', 'test'] },
    );

    stub({ file_sources: [{ id: 's1', config_revision: 'r1', source_actions: [] }], file_source_management: { schema_version: 1, operations: [] } });
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

    // The fixed-tag suggestions come from the explicit-group tag read the Documents and Tags sections
    // use, named by group id, never from the active group or a personal tag read, and most used first.
    stub({ tags: [{ name: 'legal', count: 2 }, { name: 'quarterly', count: 7 }, { name: 'finance', count: 7 }] });
    assert.deepEqual(await adapter.tags(), ['finance', 'quarterly', 'legal'],
        'Tag suggestions are ordered most used first, then by name.');
    assert.deepEqual(calls, [{ method: 'GET', path: '/api/group_documents/tags?group_id=group-a' }],
        'The group tag suggestions must name the group explicitly.');
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
