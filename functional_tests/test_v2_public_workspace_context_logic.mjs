// test_v2_public_workspace_context_logic.mjs
// Version: 0.261.177
// Implemented in: 0.261.177
// Executes the real public workspace context validator (isPublicWorkspaceContext in
// lib/workspaceContext.ts) for the M10A additions: the optional top-level membership_management
// hint, and the `members` manage section validated in the `manage` group exactly as the group
// validator validates its own manage sections. Sits beside test_v2_group_workspace_context_logic.mjs.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    PUBLIC_WORKSPACE_SECTION_IDS, PUBLIC_MANAGE_SECTION_IDS, isPublicWorkspaceContext,
} = await import('../application/v2_ui/src/lib/workspaceContext.ts');

let checks = 0;

function sectionGroup(id) {
    if (id === 'identities') return 'connections';
    return 'knowledge';
}

function context(id, viewer = 'viewer') {
    return {
        schema_version: 1, enabled: true, viewer_id: viewer, scope: { kind: 'public', id },
        workspace: {
            name: `Name ${id}`, description: `Description ${id}`,
            owner: { display_name: 'Owner', email: 'owner@example.test' },
            hero_color: '#0078d4', logo_url: null,
        },
        role: 'Owner', status: 'active', can_manage_workspace: true,
        sections: Object.fromEntries(PUBLIC_WORKSPACE_SECTION_IDS.map((sectionId) => [
            sectionId, { enabled: true, can_manage: true, reason: null, group: sectionGroup(sectionId) },
        ])),
        document_permissions: {
            can_view: true, can_chat: true, can_upload: true, can_edit: true,
            can_delete: true, can_download: true,
        },
        document_queries: { sort_fields: ['_ts', 'file_name', 'title'], facets: false, places: false },
        membership_management: { schema_version: 1, operations: ['add_member', 'review_requests'] },
    };
}

function run(name, check) {
    check();
    checks += 1;
    console.log(`ok ${name}`);
}

try {
    run('a valid public context, with or without the membership hint, passes', () => {
        assert.equal(PUBLIC_MANAGE_SECTION_IDS.length, 1);
        assert.equal(PUBLIC_MANAGE_SECTION_IDS[0], 'members');
        const valid = context('ws-a');
        assert.equal(isPublicWorkspaceContext(valid, 'viewer', 'ws-a'), true);
        const withoutHint = structuredClone(valid);
        delete withoutHint.membership_management;
        assert.equal(isPublicWorkspaceContext(withoutHint, 'viewer', 'ws-a'), true,
            'The membership hint is optional at the validator, like the other management hints.');
        const foreignViewer = context('ws-a', 'someone-else');
        assert.equal(isPublicWorkspaceContext(foreignViewer, 'viewer', 'ws-a'), false);
    });

    run('a reported Members section must be a valid manage section; an absent one stays unavailable', () => {
        const valid = context('ws-a');
        assert.equal(isPublicWorkspaceContext(valid, 'viewer', 'ws-a'), true,
            'A context without a members section is still valid.');
        const withMembers = structuredClone(valid);
        withMembers.sections.members = { enabled: true, can_manage: true, reason: null, group: 'manage' };
        assert.equal(isPublicWorkspaceContext(withMembers, 'viewer', 'ws-a'), true);
        for (const members of [
            { enabled: true, can_manage: true, reason: 'x', group: 'manage' },
            { enabled: false, can_manage: true, reason: 'locked', group: 'manage' },
            { enabled: true, can_manage: 'yes', reason: null, group: 'manage' },
            { enabled: true, can_manage: true, reason: null, group: 'knowledge' },
            { enabled: true, can_manage: true, reason: null },
        ]) {
            const changed = structuredClone(valid);
            changed.sections.members = members;
            assert.equal(isPublicWorkspaceContext(changed, 'viewer', 'ws-a'), false);
        }
        const misfiled = structuredClone(withMembers);
        misfiled.sections.documents = { ...misfiled.sections.documents, group: 'manage' };
        assert.equal(isPublicWorkspaceContext(misfiled, 'viewer', 'ws-a'), false,
            'A content section never claims the manage group.');
    });

    console.log(`${checks} public workspace context validator checks passed.`);
} catch (error) {
    console.error(error);
    process.exit(1);
}
