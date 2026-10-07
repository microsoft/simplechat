// test_v2_admin_help_logic.ts
//
// Runtime test for the V2 Admin Settings Help group.
// Version: 0.261.276
// Implemented in: 0.261.276
//
// The Help group's judgement calls are invisible in a screenshot: which announcements are
// shared when the stored map is incomplete, where an admin shortcut lands, which URLs may
// reach an href or a mailto: draft, and what the publication notice tells an administrator
// in each Support state. Each is executed here, along with static renders of the new cards.
//
// Run by test_v2_admin_help_logic.py, which bundles this with the esbuild Vite already
// brings in and executes it under node, skipping when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AdminLatestFeatures } from '../application/v2_ui/src/components/admin/AdminLatestFeatures';
import { LatestFeaturesVisibility } from '../application/v2_ui/src/components/admin/LatestFeaturesVisibility';
import {
    LatestFeaturesPublication,
    describePublication,
} from '../application/v2_ui/src/components/admin/LatestFeaturesPublication';
import { ReleaseNotificationsBadge } from '../application/v2_ui/src/components/admin/ReleaseNotificationsBadge';
import { SendFeedbackForm, SendFeedbackOverview } from '../application/v2_ui/src/components/admin/SendFeedback';
import { SettingField } from '../application/v2_ui/src/components/admin/fields';
import { SectionStatusContext } from '../application/v2_ui/src/components/admin/sectionStatusContext';
import {
    FALLBACK_LATEST_FEATURE_ICON,
    resolveLatestFeatureIcon,
} from '../application/v2_ui/src/components/admin/latestFeatureIcons';
import {
    countShared,
    filterGroups,
    isActionShown,
    readVisibility,
    resolveAdminActionTarget,
    safeClassicAdminTabHref,
    safeLatestFeatureHref,
    safeLatestFeatureImageUrl,
    type LatestFeature,
    type LatestFeatureAction,
    type LatestFeatureGroup,
} from '../application/v2_ui/src/lib/latestFeatures';
import {
    feedbackDraftBody,
    isPlausibleEmail,
    registrationDraftBody,
    safeMailtoHref,
    validateFeedbackFields,
} from '../application/v2_ui/src/lib/supportFeedback';
import type { AdminField } from '../application/v2_ui/src/lib/adminFields';
import type { AdminNavGroup } from '../application/v2_ui/src/lib/types';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

function feature(id: string, overrides: Partial<LatestFeature> = {}): LatestFeature {
    return {
        id,
        title: `Title ${id}`,
        icon: 'bi-robot',
        summary: `Summary ${id}`,
        details: `Details ${id}`,
        why: 'This matters because it helps.',
        guidance: ['Step one', 'Step two'],
        images: [],
        actions: [],
        ...overrides,
    };
}

function group(id: string, features: LatestFeature[], defaultExpanded: boolean): LatestFeatureGroup {
    return {
        id,
        label: `Group ${id}`,
        description: `Description ${id}`,
        release_version: '0.261.001',
        default_expanded: defaultExpanded,
        features,
    };
}

const USER_GROUPS: LatestFeatureGroup[] = [
    group('current_release', [feature('alpha'), feature('beta', { default_visible: false })], true),
    group('previous_release', [feature('gamma', { summary: 'Agents catalog search' })], false),
];

const NAV: AdminNavGroup[] = [
    {
        id: 'help',
        label: 'Help',
        tabs: [
            { id: 'support-menu', label: 'Support Menu', sections: [{ id: 'support-menu-section', label: 'Support' }] },
            { id: 'latest-features', label: 'Admin Latest Features', sections: [], render: 'latest_features' },
        ],
    },
    {
        id: 'backup-recovery',
        label: 'Backup',
        tabs: [{ id: 'backup', label: 'Backup', sections: [{ id: 'data-management-storage-section', label: 'Storage' }] }],
    },
    {
        id: 'scale',
        label: 'Scale',
        tabs: [
            {
                id: 'cosmos',
                label: 'Cosmos',
                sections: [
                    { id: 'cosmos-maintenance-section', label: 'Maintenance' },
                    { id: 'cosmos-throughput-section', label: 'Throughput' },
                ],
            },
        ],
    },
];

function adminAction(tab: string, section: string | null = null): LatestFeatureAction {
    return {
        label: `Open ${tab}`,
        description: '',
        icon: 'bi-gear',
        kind: 'admin',
        href: `/admin/settings#${tab}`,
        admin_tab: tab,
        admin_section: section,
        requires_settings: [],
    };
}

check('stored visibility wins, and an unmentioned announcement uses its default', () => {
    const visibility = readVisibility({ alpha: 'false', retired: true }, USER_GROUPS);
    assert.deepEqual(visibility, { alpha: false, beta: false, gamma: true });
    assert.deepEqual(readVisibility(null, USER_GROUPS), { alpha: true, beta: false, gamma: true });
    assert.deepEqual(readVisibility(['alpha'], USER_GROUPS), { alpha: true, beta: false, gamma: true });
    assert.equal(countShared(visibility, USER_GROUPS.flatMap((item) => item.features)), 1);
});

check('a search narrows groups to matching announcements and drops empty groups', () => {
    assert.equal(filterGroups(USER_GROUPS, '   '), USER_GROUPS);
    const narrowed = filterGroups(USER_GROUPS, 'agents catalog');
    assert.deepEqual(narrowed.map((item) => item.id), ['previous_release']);
    assert.deepEqual(narrowed[0].features.map((item) => item.id), ['gamma']);
    assert.deepEqual(filterGroups(USER_GROUPS, 'nothing like this'), []);
});

check('a shortcut shows only while every setting it needs is on in the draft', () => {
    const action = { ...adminAction('x'), kind: 'external' as const, requires_settings: ['enable_docs', 'enable_menu'] };
    assert.equal(isActionShown(action, (key) => ({ enable_docs: true, enable_menu: 'on' })[key]), true);
    assert.equal(isActionShown(action, (key) => ({ enable_docs: true, enable_menu: false })[key]), false);
    assert.equal(isActionShown({ ...action, requires_settings: [] }, () => false), true);
});

check('admin shortcuts land on a drawn card, the catalogue card, or the classic tab', () => {
    const rendered = new Set(['support-menu-section', 'latest-features', 'cosmos-throughput-section']);
    assert.deepEqual(resolveAdminActionTarget(adminAction('cosmos', 'cosmos-throughput-section'), NAV, rendered), {
        kind: 'section',
        sectionId: 'cosmos-throughput-section',
    });
    assert.deepEqual(resolveAdminActionTarget(adminAction('cosmos', 'plugins-table'), NAV, rendered), {
        kind: 'section',
        sectionId: 'cosmos-throughput-section',
    });
    assert.deepEqual(resolveAdminActionTarget(adminAction('latest-features'), NAV, rendered), {
        kind: 'section',
        sectionId: 'latest-features',
    });
    assert.deepEqual(resolveAdminActionTarget(adminAction('backup'), NAV, rendered), { kind: 'classic', tab: 'backup' });
    assert.equal(safeClassicAdminTabHref('backup'), '/admin/settings#backup');
    assert.equal(safeClassicAdminTabHref('a b"c'), '/admin/settings#a%20b%22c');
});

check('only same-origin paths and http(s) addresses may become a shortcut href', () => {
    for (const href of ['/chats#chatbox', '/workspace#workflows-tab', 'https://microsoft.github.io/simplechat/']) {
        assert.equal(safeLatestFeatureHref(href), href);
    }
    for (const href of [
        'javascript:alert(1)',
        'JaVaScRiPt:alert(1)',
        '//evil.example/x',
        '/a/../admin',
        '/a/%2e%2e/admin',
        '\\\\evil',
        'mailto:x@y.z',
        'data:text/html,hi',
        42,
        undefined,
    ]) {
        assert.equal(safeLatestFeatureHref(href), undefined, String(href));
    }
});

check('only static files may become a screenshot source', () => {
    assert.equal(safeLatestFeatureImageUrl('/static/images/features/a.png'), '/static/images/features/a.png');
    for (const url of ['/uploads/a.png', 'https://cdn.example/a.png', '/static/../secret', '//x/static/a.png']) {
        assert.equal(safeLatestFeatureImageUrl(url), undefined, url);
    }
});

check('a mailto draft accepts one plain address and encodes everything else', () => {
    const href = safeMailtoHref('simplechat@microsoft.com', 'Bug & fix', 'Line one\nLine two?');
    assert.equal(
        href,
        'mailto:simplechat@microsoft.com?subject=Bug%20%26%20fix&body=Line%20one%0ALine%20two%3F',
    );
    for (const recipient of [
        'a@b.com,c@d.com',
        'a@b.com;c@d.com',
        'a@b.com?cc=evil@x.com',
        'Name <a@b.com>',
        'not-an-address',
        'javascript:alert(1)@x',
    ]) {
        assert.equal(safeMailtoHref(recipient, 's', 'b'), undefined, recipient);
    }
    assert.equal(isPlausibleEmail(' admin@contoso.com '), true);
    assert.equal(isPlausibleEmail('admin@'), false);
});

check('feedback and registration drafts are worded as the classic page words them', () => {
    const fields = { name: ' Ada ', email: 'ada@contoso.com', organization: 'Contoso', details: 'It broke.' };
    assert.equal(
        feedbackDraftBody('bug_report', fields, '0.261.276'),
        [
            'Feedback Type: Bug Report',
            'Name: Ada',
            'Email: ada@contoso.com',
            'Organization: Contoso',
            'App Version: 0.261.276',
            '',
            'Details:',
            'It broke.',
        ].join('\n'),
    );
    const registration = registrationDraftBody({
        name: 'Ada',
        email: 'ada@contoso.com',
        organization: 'Contoso',
        appVersion: '',
    });
    assert.match(registration, /^Registration submission to receive the latest release updates/);
    assert.match(registration, /App Version: Unknown\nRegistered At: Pending$/);
    assert.deepEqual(Object.keys(validateFeedbackFields({ name: '', email: 'bad', organization: ' ', details: '' })), [
        'name',
        'email',
        'organization',
        'details',
    ]);
    assert.deepEqual(validateFeedbackFields(fields), {});
});

check('the publication notice says what is stopping announcements reaching users', () => {
    const base = { menuName: 'Help Desk', shared: 12, total: 79 };
    const menuOff = describePublication({ ...base, menuOn: false, destinationOn: true });
    assert.equal(menuOff.tone, 'warn');
    assert.equal(menuOff.pointsToSupport, true);
    assert.match(menuOff.detail, /Support menu is off/);

    const destinationOff = describePublication({ ...base, menuOn: true, destinationOn: false });
    assert.equal(destinationOff.pointsToSupport, true);
    assert.match(destinationOff.detail, /Help Desk menu/);

    const empty = describePublication({ ...base, shared: 0, menuOn: true, destinationOn: true });
    assert.equal(empty.tone, 'warn');
    assert.equal(empty.pointsToSupport, false);

    const published = describePublication({ ...base, menuOn: true, destinationOn: true });
    assert.equal(published.tone, 'ok');
    assert.match(published.detail, /12 of 79 announcements under Help Desk › Latest Features/);

    const loading = describePublication({ menuName: ' ', shared: null, total: null, menuOn: true, destinationOn: true });
    assert.match(loading.detail, /from the Support menu/);
});

check('the publication card offers the way to the Support settings only when it helps', () => {
    const field: AdminField = { type: 'component', component: 'support-latest-features-publication', label: 'Publication' };
    const off = renderToStaticMarkup(
        createElement(LatestFeaturesPublication, {
            field,
            state: describePublication({ menuName: 'Support', shared: 3, total: 9, menuOn: false, destinationOn: true }),
            onNavigate: () => undefined,
        }),
    );
    assert.match(off, /Not published yet/);
    assert.match(off, /Open Support settings/);

    const on = renderToStaticMarkup(
        createElement(LatestFeaturesPublication, {
            field,
            state: describePublication({ menuName: 'Support', shared: 3, total: 9, menuOn: true, destinationOn: true }),
            onNavigate: () => undefined,
        }),
    );
    assert.match(on, />Published</);
    assert.doesNotMatch(on, /Open Support settings/);
});

check('an empty required text field is flagged while its section needs configuration', () => {
    const recipient: AdminField = {
        key: 'support_feedback_recipient_email',
        type: 'text',
        input_type: 'email',
        label: 'Support Recipient Email',
        required: true,
    };
    const empty = renderToStaticMarkup(createElement(SettingField, { field: recipient, value: '', onChange: () => undefined }));
    assert.match(empty, />Required</);
    assert.match(empty, /type="email"/);
    const filled = renderToStaticMarkup(
        createElement(SettingField, { field: recipient, value: 'help@contoso.com', onChange: () => undefined }),
    );
    assert.doesNotMatch(filled, />Required</);

    // Inside a card, the marker follows the section: only "Needs configuration" asks for it.
    const inSection = (status: 'off' | 'incomplete' | 'blocked') =>
        renderToStaticMarkup(
            createElement(
                SectionStatusContext.Provider,
                { value: status },
                createElement(SettingField, { field: recipient, value: '', onChange: () => undefined }),
            ),
        );
    assert.match(inSection('incomplete'), />Required</);
    assert.doesNotMatch(inSection('off'), />Required</);
    assert.doesNotMatch(inSection('blocked'), />Required</);
});

check('admin announcements open by release, and shortcuts know where they land', () => {
    const groups = [
        group('current_release', [feature('keys', { actions: [adminAction('backup'), adminAction('support-menu')] })], true),
        group('previous_release', [feature('older')], false),
    ];
    const markup = renderToStaticMarkup(
        createElement(AdminLatestFeatures, {
            groups,
            loading: false,
            error: null,
            onRetry: () => undefined,
            query: '',
            resolveAction: (action) => resolveAdminActionTarget(action, NAV, new Set(['support-menu-section'])),
            onNavigate: () => undefined,
        }),
    );
    assert.match(markup, /Title keys/);
    assert.doesNotMatch(markup, /Title older/, 'Older releases start closed.');
    assert.match(markup, /1 feature/);
    assert.match(markup, /id="latest-features-keys-card"/);

    const searched = renderToStaticMarkup(
        createElement(AdminLatestFeatures, {
            groups,
            loading: false,
            error: null,
            onRetry: () => undefined,
            query: 'older',
            resolveAction: () => ({ kind: 'classic', tab: 'backup' }),
            onNavigate: () => undefined,
        }),
    );
    assert.match(searched, /Title older/, 'A search opens the release holding the match.');
    assert.doesNotMatch(searched, /Title keys/);

    const loading = renderToStaticMarkup(
        createElement(AdminLatestFeatures, {
            groups: null,
            loading: false,
            error: 'Failed to load Latest Features.',
            onRetry: () => undefined,
            query: '',
            resolveAction: () => ({ kind: 'classic', tab: 'backup' }),
            onNavigate: () => undefined,
        }),
    );
    assert.match(loading, /role="alert"/);
    assert.match(loading, /Try again/);
});

check('the user-facing list shows what is shared and flags what is hidden', () => {
    const field: AdminField = {
        type: 'component',
        component: 'support-latest-features-visibility',
        key: 'support_latest_features_visibility',
        label: 'Announcements Shared with Users',
    };
    const markup = renderToStaticMarkup(
        createElement(LatestFeaturesVisibility, {
            field,
            groups: USER_GROUPS,
            loading: false,
            error: null,
            onRetry: () => undefined,
            value: { alpha: true },
            disabled: false,
            query: '',
            read: () => undefined,
            onChange: () => undefined,
        }),
    );
    assert.match(markup, /2 of 3 shared/);
    assert.match(markup, /1 of 2 shared/);
    assert.match(markup, /Hidden from users/);
    assert.match(markup, /Share all/);
    assert.equal((markup.match(/type="checkbox"/g) ?? []).length, 2, 'Only the open release lists its rows.');
});

check('the Send Feedback cards prefill the administrator and link to the Support settings', () => {
    const form = renderToStaticMarkup(
        createElement(SendFeedbackForm, {
            kind: 'feature_request',
            field: { type: 'component', component: 'send-feedback-feature-request', label: 'Request a Feature' },
            defaultName: 'Ada Admin',
            defaultEmail: 'ada@contoso.com',
            appVersion: '0.261.276',
        }),
    );
    assert.match(form, /value="Ada Admin"/);
    assert.match(form, /value="ada@contoso.com"/);
    assert.match(form, /Feature Request Details/);
    assert.match(form, /Open Feature Request Email/);
    assert.match(form, /autoComplete="organization"|autocomplete="organization"/);

    const overview = renderToStaticMarkup(
        createElement(SendFeedbackOverview, {
            field: { type: 'component', component: 'send-feedback-overview', label: 'Send Feedback to the SimpleChat Team' },
            onNavigate: () => undefined,
        }),
    );
    assert.match(overview, /text only/);
    assert.match(overview, /Open Support settings/);
});

check('the registration badge reads the stored registration', () => {
    const render = (registered: boolean) =>
        renderToStaticMarkup(
            createElement(ReleaseNotificationsBadge, {
                settings: { release_notifications_registered: registered },
                defaultName: 'Ada',
                defaultEmail: 'ada@contoso.com',
                appVersion: '0.261.276',
                onRegistered: () => undefined,
            }),
        );
    assert.match(render(false), />Unregistered</);
    assert.match(render(true), />Registered</);
    assert.match(render(true), /aria-haspopup="dialog"/);
});

check('catalogue icons resolve, with a neutral fallback', () => {
    assert.notEqual(resolveLatestFeatureIcon('bi-database-gear'), FALLBACK_LATEST_FEATURE_ICON);
    assert.notEqual(resolveLatestFeatureIcon('bi-robot'), FALLBACK_LATEST_FEATURE_ICON);
    assert.equal(resolveLatestFeatureIcon('bi-not-a-real-icon'), FALLBACK_LATEST_FEATURE_ICON);
    assert.equal(resolveLatestFeatureIcon(undefined), FALLBACK_LATEST_FEATURE_ICON);
});

let passed = 0;
for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.error(`  FAIL ${name}`);
        console.error(`       ${(error as Error).message}`);
    }
}

console.log(`\nResults: ${passed}/${checks.length} checks passed`);
process.exit(passed === checks.length ? 0 : 1);
