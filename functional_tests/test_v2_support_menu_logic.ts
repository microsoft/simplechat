// test_v2_support_menu_logic.ts
//
// Runtime test for the V2 Support menu: the rail group, the Latest Features page and the Send
// Feedback page.
// Version: 0.261.294
// Implemented in: 0.261.294
//
// The judgement calls here do not show in a screenshot: which destinations the rail offers
// once a user has hidden Latest Features, where each catalogue shortcut lands in V2, that a
// shortcut can never become a script URL or an absolute router target, and that the pages draw
// the states they promise. Each is executed here, with static renders of the new components.
//
// Run by test_v2_support_menu.py, which bundles this with the esbuild Vite already brings in
// and executes it under node. When SUPPORT_MENU_CATALOGUE_HREFS names a JSON file, every
// shortcut in the real user catalogue is also checked to be followable from V2.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { SupportMenuView } from '../application/v2_ui/src/components/layout/SupportMenu';
import {
    AnnouncementShortcuts,
    PASSIVE_NOTE,
    SupportAnnouncementList,
    initiallyOpenGroups,
} from '../application/v2_ui/src/components/support/SupportAnnouncements';
import { SupportFeedbackForm } from '../application/v2_ui/src/components/support/SupportFeedbackForm';
import { SupportLatestFeaturesPage } from '../application/v2_ui/src/pages/SupportLatestFeaturesPage';
import { SupportSendFeedbackPage } from '../application/v2_ui/src/pages/SupportSendFeedbackPage';
import {
    DEFAULT_SUPPORT_MENU_NAME,
    SUPPORT_LATEST_FEATURES_PATH,
    SUPPORT_SEND_FEEDBACK_PATH,
    isSendFeedbackAvailable,
    resolveSupportMenu,
    type SupportMenuState,
} from '../application/v2_ui/src/lib/supportMenu';
import {
    resolveLatestFeatureShortcut,
    safeShortcutRouteHref,
} from '../application/v2_ui/src/lib/latestFeatureShortcuts';
import { USER_LATEST_FEATURES_ENDPOINT, type LatestFeature, type LatestFeatureGroup } from '../application/v2_ui/src/lib/latestFeatures';
import { SUPPORT_FEEDBACK_ENDPOINT } from '../application/v2_ui/src/lib/supportFeedback';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

function routed(element: ReactElement, path = '/chat'): string {
    return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: [path] }, element));
}

function feature(id: string, overrides: Partial<LatestFeature> = {}): LatestFeature {
    return {
        id,
        title: `Title ${id}`,
        icon: 'bi-robot',
        summary: `Summary ${id}`,
        details: `Details ${id}`,
        why: 'This matters because it helps.',
        guidance: ['Step one'],
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

function action(href: string, label = 'Open', description = '') {
    return { label, description, icon: 'bi-chat-dots', kind: 'page' as const, href, requires_settings: [] };
}

const BOTH = {
    latest_features: { available: true, hidden_by_development: false, menu_name: 'Help Desk' },
    send_feedback: { available: true, menu_name: 'Help Desk' },
};

/* ------------------------------------ rail ------------------------------------ */

check('both destinations show under the administrator-chosen heading', () => {
    const menu = resolveSupportMenu(BOTH, null, '1.0');
    assert.deepEqual(menu, {
        menuName: 'Help Desk',
        showLatestFeatures: true,
        showSendFeedback: true,
        visible: true,
    });
});

check('hiding Latest Features for this version leaves Send Feedback in the menu', () => {
    const menu = resolveSupportMenu(BOTH, ' 1.0 ', '1.0');
    assert.equal(menu.showLatestFeatures, false);
    assert.equal(menu.showSendFeedback, true);
    assert.equal(menu.visible, true);
});

check('a hide saved for an older version lapses', () => {
    assert.equal(resolveSupportMenu(BOTH, '0.9', '1.0').showLatestFeatures, true);
});

check('the menu disappears when it has nothing to offer', () => {
    const hiddenOnly = { latest_features: BOTH.latest_features, send_feedback: { available: false } };
    assert.equal(resolveSupportMenu(hiddenOnly, '1.0', '1.0').visible, false);
    assert.equal(resolveSupportMenu(null, null, '1.0').visible, false);
    assert.equal(resolveSupportMenu({}, null, '1.0').visible, false);
});

check('development mode hides Latest Features but not Send Feedback', () => {
    const development = {
        ...BOTH,
        latest_features: { ...BOTH.latest_features, hidden_by_development: true },
    };
    const menu = resolveSupportMenu(development, null, '1.0');
    assert.equal(menu.showLatestFeatures, false);
    assert.equal(menu.showSendFeedback, true);
});

check('the heading falls back to Send Feedback, then to Support', () => {
    assert.equal(
        resolveSupportMenu({ send_feedback: { available: true, menu_name: 'Service Desk' } }, null, '1').menuName,
        'Service Desk',
    );
    assert.equal(
        resolveSupportMenu({ send_feedback: { available: true, menu_name: '   ' } }, null, '1').menuName,
        DEFAULT_SUPPORT_MENU_NAME,
    );
});

check('Send Feedback is only available when the server says so', () => {
    assert.equal(isSendFeedbackAvailable(BOTH), true);
    assert.equal(isSendFeedbackAvailable({ send_feedback: { available: false } }), false);
    assert.equal(isSendFeedbackAvailable({}), false);
    assert.equal(isSendFeedbackAvailable(undefined), false);
});

const OPEN_MENU: SupportMenuState = {
    menuName: 'Help Desk',
    showLatestFeatures: true,
    showSendFeedback: true,
    visible: true,
};

function renderMenu(menu: SupportMenuState, collapsed: boolean, expanded = true, path = '/chat') {
    return routed(
        createElement(SupportMenuView, {
            menu,
            collapsed,
            expanded,
            onToggle: () => undefined,
            onHideLatestFeatures: () => undefined,
        }),
        path,
    );
}

check('the rail menu links to the V2 pages, never the classic ones', () => {
    const html = renderMenu(OPEN_MENU, false);
    assert.match(html, />Help Desk</);
    assert.match(html, /href="\/support\/latest-features"/);
    assert.match(html, /href="\/support\/send-feedback"/);
    assert.match(html, />New</);
    assert.match(html, /aria-label="Hide Latest Features until the next release"/);
    assert.match(html, /aria-expanded="true"/);
    assert.match(html, /data-tour="latest-features"/);
});

check('the current page is marked in the menu', () => {
    const html = renderMenu(OPEN_MENU, false, true, SUPPORT_SEND_FEEDBACK_PATH);
    assert.match(html, /aria-current="page"[^>]*href="\/support\/send-feedback"|href="\/support\/send-feedback"[^>]*aria-current="page"/);
});

check('a closed menu keeps its heading and drops its links', () => {
    const html = renderMenu(OPEN_MENU, false, false);
    assert.match(html, /aria-expanded="false"/);
    assert.doesNotMatch(html, /href="\/support\//);
});

check('the collapsed rail names its icon-only links', () => {
    const html = renderMenu(OPEN_MENU, true);
    assert.match(html, /aria-label="Latest Features"/);
    assert.match(html, /aria-label="Send Feedback"/);
    assert.doesNotMatch(html, />Help Desk</, 'The collapsed strip has no room for a heading');
});

check('only the offered destinations are drawn', () => {
    const feedbackOnly = renderMenu({ ...OPEN_MENU, showLatestFeatures: false }, false);
    assert.doesNotMatch(feedbackOnly, /latest-features/);
    assert.match(feedbackOnly, /send-feedback/);
    assert.equal(renderMenu({ ...OPEN_MENU, showLatestFeatures: false, showSendFeedback: false, visible: false }, false), '');
});

/* ---------------------------------- shortcuts ---------------------------------- */

const ROUTES: [string, string, Record<string, unknown>?][] = [
    ['/chats#chatbox', '/chat', { freshChat: true }],
    ['/chats?feature_action=conversation_export', '/chat', { freshChat: true }],
    ['/chats#chat-tutorial-launch', '/chat', { freshChat: true, tour: 'chat' }],
    ['/chats#model-select-container', '/chat'],
    ['/conversations', '/chat'],
    ['/workspace', '/workspace'],
    ['/workspace#documents-tab', '/workspace/documents'],
    ['/workspace#upload-area', '/workspace/documents'],
    ['/workspace#agents-tab', '/workspace/agents'],
    ['/workspace#plugins-tab', '/workspace/actions'],
    ['/workspace#workflows-tab', '/workspace/workflows'],
    ['/workspace#identities-tab', '/workspace/identities'],
    ['/workspace#prompts-tab', '/workspace/prompts'],
    ['/workspace#endpoints-tab', '/workspace/endpoints'],
    ['/workspace#sync-tab', '/workspace/sync'],
    ['/workspace?feature_action=document_tag_system', '/workspace/tags'],
    ['/workspace?feature_action=workspace_folder_view', '/workspace/documents'],
    ['/workspace?feature_action=file_sync', '/workspace/sync'],
    ['/workspace#workspace-tutorial-launch', '/workspace', { tour: 'workspace' }],
    ['/profile', '/settings'],
    ['/profile#fact-memory-settings', '/settings'],
    ['/profile?tab=settings#profile-settings-pane', '/settings'],
    ['/profile?tab=stats#profile-stats-pane', '/settings?tab=stats'],
    ['/profile?tab=violations', '/settings?tab=violations'],
    ['/profile?feature_action=retention_policy#retention-policy-settings', '/settings'],
    ['/group_workspaces', '/groups'],
    ['/public_workspaces', '/public'],
    ['/public_directory', '/public/directory'],
    ['/approvals', '/approvals'],
    ['/support/latest-features', SUPPORT_LATEST_FEATURES_PATH],
    ['/support/send-feedback', SUPPORT_SEND_FEEDBACK_PATH],
];

check('classic shortcuts land on the matching V2 page', () => {
    for (const [href, path, extra] of ROUTES) {
        const target = resolveLatestFeatureShortcut(href);
        assert.ok(target && target.kind === 'route', `${href} should open a V2 page`);
        assert.equal(target.path, path, href);
        assert.equal(target.tour, extra?.tour, `${href} tour`);
        if (extra?.freshChat !== undefined) {
            assert.equal(target.freshChat, extra.freshChat, `${href} fresh chat`);
        }
        assert.equal(safeShortcutRouteHref(target.path), target.path, `${href} must be allowlisted`);
    }
});

check('pages V2 has not rebuilt open as written', () => {
    for (const href of ['/agents', '/workflow-activity', '/groups/abc', '/admin/safety_violations']) {
        assert.deepEqual(resolveLatestFeatureShortcut(href), { kind: 'page', href });
    }
});

check('documentation links leave the site', () => {
    const href = 'https://microsoft.github.io/simplechat/latest-release/retention-policy/';
    assert.deepEqual(resolveLatestFeatureShortcut(href), { kind: 'external', href });
});

check('unsafe shortcuts are dropped', () => {
    for (const href of [
        'javascript:alert(1)',
        'JAVASCRIPT:alert(1)',
        'data:text/html,hi',
        '//evil.example/path',
        '/\\evil.example',
        '/a/../admin',
        '/a/%2e%2e/admin',
        '#chatbox',
        'chats',
        '',
        null,
        undefined,
        42,
    ]) {
        assert.equal(resolveLatestFeatureShortcut(href), null, String(href));
    }
});

check('a router target can only ever be an allowlisted V2 path', () => {
    for (const value of ['/evil', 'https://evil.example', '//evil.example', 'javascript:alert(1)', '']) {
        assert.equal(safeShortcutRouteHref(value), SUPPORT_LATEST_FEATURES_PATH, value);
    }
});

check('every shortcut in the real user catalogue can be followed from V2', () => {
    const file = process.env.SUPPORT_MENU_CATALOGUE_HREFS;
    if (!file) {
        console.log('       (catalogue cross-check skipped: no catalogue file supplied)');
        return;
    }
    const hrefs = JSON.parse(readFileSync(file, 'utf8')) as string[];
    assert.ok(hrefs.length > 20, `Only ${hrefs.length} catalogue shortcuts were supplied`);
    const kinds = new Set<string>();
    for (const href of hrefs) {
        const target = resolveLatestFeatureShortcut(href);
        assert.ok(target, `Catalogue shortcut ${href} would be dropped in V2`);
        kinds.add(target.kind);
        if (target.kind === 'route') {
            assert.equal(safeShortcutRouteHref(target.path), target.path, href);
        }
    }
    assert.ok(kinds.has('route'), 'No catalogue shortcut was translated to a V2 page');
});

/* -------------------------------- announcements -------------------------------- */

check('announcement shortcuts render by kind', () => {
    const html = routed(
        createElement(AnnouncementShortcuts, {
            feature: feature('mixed', {
                actions: [
                    action('/chats#chatbox', 'Open Chat', 'Ask a question from Chat.'),
                    action('/agents', 'Open Agents'),
                    action('https://microsoft.github.io/simplechat/', 'Read the guide'),
                    action('javascript:alert(1)', 'Bad'),
                ],
            }),
        }),
    );
    assert.match(html, /href="\/chat"[^>]*>.*Open Chat/);
    assert.match(html, /Ask a question from Chat\./);
    assert.match(html, /href="\/agents"/);
    assert.match(html, /opens in the classic interface/);
    assert.match(html, /href="https:\/\/microsoft\.github\.io\/simplechat\/"[^>]*target="_blank"[^>]*rel="noopener noreferrer"|target="_blank"[^>]*rel="noopener noreferrer"[^>]*href="https:\/\/microsoft\.github\.io\/simplechat\/"/);
    assert.match(html, /opens in a new tab/);
    assert.doesNotMatch(html, /javascript:/i);
    assert.doesNotMatch(html, />Bad</);
});

check('an announcement with nowhere to go says so', () => {
    const html = routed(createElement(AnnouncementShortcuts, { feature: feature('quiet') }));
    assert.ok(html.includes(PASSIVE_NOTE.slice(0, 40)), html);
    const unsafeOnly = routed(
        createElement(AnnouncementShortcuts, {
            feature: feature('unsafe', { actions: [action('javascript:alert(1)')] }),
        }),
    );
    assert.ok(unsafeOnly.includes(PASSIVE_NOTE.slice(0, 40)), 'A dropped shortcut leaves the note');
});

check('the current release starts open and older ones start closed', () => {
    const groups = [
        group('current_release', [feature('alpha')], true),
        group('previous_release', [feature('beta')], false),
    ];
    const html = routed(createElement(SupportAnnouncementList, { groups, query: '' }));
    assert.match(html, />Title alpha</);
    assert.doesNotMatch(html, />Title beta</);
    assert.match(html, /Group previous_release/);
    assert.match(html, /1 announcement</);
    assert.match(html, /id="latest-features-alpha-card"/);
});

check('the first release opens when none is marked', () => {
    assert.deepEqual([...initiallyOpenGroups([group('a', [], false), group('b', [], false)])], ['a']);
    assert.deepEqual([...initiallyOpenGroups([group('a', [], false), group('b', [], true)])], ['b']);
    assert.deepEqual([...initiallyOpenGroups([])], []);
});

check('a search opens every release and keeps only matches', () => {
    const groups = [
        group('current_release', [feature('alpha'), feature('gamma', { title: 'Chart creation' })], true),
        group('previous_release', [feature('beta', { summary: 'Charts in older releases' })], false),
    ];
    const html = routed(createElement(SupportAnnouncementList, { groups, query: 'chart' }));
    assert.match(html, />Chart creation</);
    assert.match(html, />Title beta</, 'A match in a closed release must be shown');
    assert.doesNotMatch(html, />Title alpha</);
    const none = routed(createElement(SupportAnnouncementList, { groups, query: 'zebra' }));
    assert.match(none, /No announcements match/);
});

/* ------------------------------------ pages ------------------------------------ */

check('the Latest Features page reads the user endpoint and starts loading', () => {
    assert.equal(USER_LATEST_FEATURES_ENDPOINT, '/api/v2/support/latest-features');
    const html = routed(createElement(SupportLatestFeaturesPage), SUPPORT_LATEST_FEATURES_PATH);
    assert.match(html, /<h1[^>]*>Latest Features<\/h1>/);
    assert.match(html, /role="status"/);
});

check('the Send Feedback page explains when it is not offered', () => {
    // No bootstrap payload is loaded here, so nothing has offered the page.
    const html = routed(createElement(SupportSendFeedbackPage), SUPPORT_SEND_FEEDBACK_PATH);
    assert.match(html, /<h1[^>]*>Send Feedback<\/h1>/);
    assert.match(html, /Send Feedback is not available/);
    assert.doesNotMatch(html, /<form/);
});

check('the feedback form posts to the support endpoint, not the admin one', () => {
    assert.equal(SUPPORT_FEEDBACK_ENDPOINT, '/api/support/send_feedback_email');
});

check('the feedback form is labelled and prefilled', () => {
    const html = renderToStaticMarkup(
        createElement(SupportFeedbackForm, {
            defaultName: 'Ada Lovelace',
            defaultEmail: 'ada@contoso.example',
            appVersion: '0.261.294',
        }),
    );
    for (const id of ['name', 'email', 'organization', 'details']) {
        assert.match(html, new RegExp(`<label[^>]*for="support-feedback-${id}"`), id);
        assert.match(html, new RegExp(`id="support-feedback-${id}"`), id);
    }
    assert.match(html, /value="Ada Lovelace"/);
    assert.match(html, /value="ada@contoso\.example"/);
    assert.match(html, /<legend[^>]*>What are you sending\?<\/legend>/);
    assert.match(html, /type="radio"[^>]*value="bug_report"[^>]*checked|checked[^>]*value="bug_report"/);
    assert.match(html, />Bug Report</);
    assert.match(html, />Feature Request</);
    assert.match(html, />Bug Details</);
    assert.match(html, /Open Bug Report Draft/);
    assert.match(html, /noValidate|novalidate/i);
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
