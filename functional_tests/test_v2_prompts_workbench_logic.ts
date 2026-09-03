// test_v2_prompts_workbench_logic.ts
//
// Runtime test for the V2 prompts workbench rules.
// Version: 0.261.050
// Implemented in: 0.261.050
//
// The companion test, test_v2_prompts_workbench.py, asserts that the pieces are wired
// together: routes carry their decorators, the shared validator is used by all three prompt
// blueprints, the section is registered as full-bleed. Those are source assertions and prove
// connection, not behaviour.
//
// This file executes the behaviour, because these failure modes are all quiet ones:
//
//   - A `{{ ... }}` inside a fenced code block parsed as a variable would turn a prompt that
//     documents Handlebars or Jinja into a form, and substitution would then rewrite the very
//     example the prompt exists to explain.
//   - A permissive variable name pattern turns `{{ this is prose, honestly }}` into a field the
//     user has to dismiss before the prompt can be used.
//   - `{{today}}` formatted through `toISOString` reports yesterday for anyone west of UTC in
//     the evening, and through `toLocaleDateString` cannot be asserted at all.
//   - A remembered value keyed on the bare variable name pre-fills one prompt's "name" into
//     another's, which is the specific case where an auto-filled value is worse than a blank
//     one: it is plausible enough to be sent without being read.
//   - A value that looks like an API key, persisted, is a liability that outlives the session.
//   - A slash query that keeps matching after the caret has left the token leaves the menu
//     hovering over the composer, and one that triggers mid-word fires on `https://` and
//     `and/or`.
//   - Insertion that replaces the whole composer is what the picker used to do, and is the
//     reason reaching for a prompt lost whatever had already been written.
//
// Run by test_v2_prompts_workbench.py, which bundles this with the esbuild Vite already brings
// in and executes it under node, skipping it when the front-end toolchain is absent.

import assert from 'node:assert/strict';
import {
    BUILT_IN_PROMPT_VARIABLES,
    applyPromptVariables,
    countPromptVariables,
    describeUnfilledVariables,
    literalCodeRegions,
    parsePromptVariables,
    promptNeedsFilling,
    promptVariableKey,
    resolveBuiltInPromptVariables,
} from '../application/v2_ui/src/lib/promptVariables';
import {
    MAX_REMEMBERED_PROMPTS,
    MAX_REMEMBERED_VALUES,
    MAX_REMEMBERED_VARIABLES,
    looksLikeSecret,
    pruneMemory,
} from '../application/v2_ui/src/lib/promptVariableMemory';
import {
    MAX_SLASH_QUERY_LENGTH,
    filterPromptsForSlash,
    insertPromptText,
    readSlashQuery,
    suggestPromptName,
} from '../application/v2_ui/src/lib/promptSlash';
import {
    duplicatePromptName,
    promptMatchesQuery,
    promptPreview,
    readPromptParam,
    sortPrompts,
    visiblePrompts,
} from '../application/v2_ui/src/lib/promptLibrary';
import {
    chatHrefForPrompt,
    syncedConversationParams,
} from '../application/v2_ui/src/lib/conversationUrl';

const checks: [string, () => void][] = [];
function check(name: string, fn: () => void) {
    checks.push([name, fn]);
}

/* ------------------------------ variable parsing ------------------------------ */

check('a simple placeholder is found', () => {
    const found = parsePromptVariables('Summarise this for {{audience}}.');
    assert.deepEqual(
        found.map((item) => item.name),
        ['audience'],
    );
    assert.equal(found[0].key, 'audience');
    assert.equal(found[0].builtIn, false);
});

check('repeated placeholders collapse to one field', () => {
    const found = parsePromptVariables('Dear {{customer}}, thank you {{customer}}.');
    assert.equal(found.length, 1);
    assert.equal(countPromptVariables('Dear {{customer}}, thank you {{customer}}.'), 1);
});

check('a later default is adopted when the first occurrence has none', () => {
    const found = parsePromptVariables('{{tone}} ... write it {{tone|formal}}');
    assert.equal(found.length, 1);
    assert.equal(found[0].defaultValue, 'formal');
});

check('spaces and hyphens fold to one key', () => {
    assert.equal(promptVariableKey('Customer Name'), 'customer_name');
    assert.equal(promptVariableKey('customer-name'), 'customer_name');
    const found = parsePromptVariables('{{customer name}} and {{customer-name}}');
    assert.equal(found.length, 1, 'they are the same variable, not two fields asking the same thing');
});

check('a placeholder inside a fenced block is left alone', () => {
    const content = [
        'Explain this template:',
        '',
        '```handlebars',
        'Hello {{ user.name }}, you have {{count}} messages.',
        '```',
        '',
        'Then adapt it for {{audience}}.',
    ].join('\n');

    const found = parsePromptVariables(content);
    assert.deepEqual(
        found.map((item) => item.name),
        ['audience'],
        'only the placeholder outside the fence is a variable',
    );
});

check('a fenced block is not rewritten by substitution', () => {
    const content = '```\n{{count}}\n```\nUse {{count}} here.';
    const applied = applyPromptVariables(content, { count: '7' });
    assert.ok(applied.includes('```\n{{count}}\n```'), 'the example must survive verbatim');
    assert.ok(applied.includes('Use 7 here.'));
});

check('an inline code span is left alone', () => {
    const found = parsePromptVariables('The syntax is `{{name}}`, so write {{greeting}}.');
    assert.deepEqual(
        found.map((item) => item.name),
        ['greeting'],
    );
});

check('an unterminated fence suppresses rather than invents variables', () => {
    const found = parsePromptVariables('text\n```\n{{a}}\n{{b}}');
    assert.equal(found.length, 0);
});

check('literal code regions are reported for the whole fence', () => {
    const regions = literalCodeRegions('a\n```\nb\n```\nc');
    assert.equal(regions.length, 1);
    assert.ok(regions[0].start < regions[0].end);
});

check('prose between braces is not a variable', () => {
    assert.equal(parsePromptVariables('{{ this is prose, honestly }}').length, 0);
    assert.equal(parsePromptVariables('{{}}').length, 0);
    assert.equal(parsePromptVariables('{{ 3 + 4 }}').length, 0);
    assert.equal(parsePromptVariables('{{-}}').length, 0);
});

check('an over-long name is not a variable', () => {
    const long = 'a'.repeat(60);
    assert.equal(parsePromptVariables(`{{${long}}}`).length, 0);
});

check('an escaped placeholder is neither parsed nor substituted', () => {
    assert.equal(parsePromptVariables('literally \\{{name}}').length, 0);
    assert.equal(
        applyPromptVariables('literally \\{{name}}', { name: 'x' }),
        'literally {{name}}',
        'the escape is stripped, so the reader gets the braces they asked for',
    );
});

check('built-ins are recognised as built-in', () => {
    for (const name of BUILT_IN_PROMPT_VARIABLES) {
        const found = parsePromptVariables(`{{${name}}}`);
        assert.equal(found.length, 1, `${name} should parse`);
        assert.equal(found[0].builtIn, true, `${name} should be built in`);
    }
});

check('promptNeedsFilling only fires when there is something to fill', () => {
    assert.equal(promptNeedsFilling('no variables here'), false);
    assert.equal(promptNeedsFilling('one {{here}}'), true);
    assert.equal(promptNeedsFilling('```\n{{fenced}}\n```'), false);
});

/* --------------------------------- substitution -------------------------------- */

check('a supplied value replaces every occurrence', () => {
    assert.equal(
        applyPromptVariables('{{a}} and {{a}} and {{b}}', { a: 'X', b: 'Y' }),
        'X and X and Y',
    );
});

check('a default is used when nothing is supplied', () => {
    assert.equal(applyPromptVariables('Write it {{tone|formally}}.', {}), 'Write it formally.');
});

check('a supplied value beats the default', () => {
    assert.equal(
        applyPromptVariables('Write it {{tone|formally}}.', { tone: 'plainly' }),
        'Write it plainly.',
    );
});

check('an unfilled variable stays visible rather than blanking', () => {
    assert.equal(
        applyPromptVariables('Dear {{customer}},', {}),
        'Dear {{customer}},',
        'a blank would hide the omission mid-paragraph; the braces are what make it noticed',
    );
});

check('unfilled variables are reported for the status line', () => {
    const variables = parsePromptVariables('{{a}} {{b|default}} {{c}}');
    const unfilled = describeUnfilledVariables(variables, { a: 'set' });
    assert.deepEqual(
        unfilled.map((item) => item.key),
        ['c'],
        'a variable with a default is not outstanding',
    );
});

/* ------------------------------ built-in resolution ---------------------------- */

check('today and now are formatted from local components', () => {
    // A fixed instant, so this is not time-dependent. Local components are used on both sides
    // for the same reason the implementation uses them: toISOString would report the previous
    // day for anyone west of UTC at this hour.
    const now = new Date(2026, 8, 3, 16, 5, 0);
    const resolved = resolveBuiltInPromptVariables({ now });
    assert.equal(resolved.today, '2026-09-03');
    assert.equal(resolved.now, '2026-09-03 16:05');
});

check('a built-in with nothing behind it is left out rather than blanked', () => {
    const resolved = resolveBuiltInPromptVariables({ now: new Date(2026, 0, 1) });
    assert.equal(resolved.conversation_title, undefined);
    assert.equal(resolved.last_response, undefined);
    assert.equal(
        resolved.selected_documents,
        undefined,
        'an empty document list must not resolve to an empty string, or the dialog stops asking',
    );
});

check('selected documents are joined into one value', () => {
    const resolved = resolveBuiltInPromptVariables({
        now: new Date(2026, 0, 1),
        selectedDocuments: ['a.pdf', '', 'b.docx'],
    });
    assert.equal(resolved.selected_documents, 'a.pdf, b.docx');
});

check('whitespace-only context does not resolve', () => {
    const resolved = resolveBuiltInPromptVariables({
        now: new Date(2026, 0, 1),
        userName: '   ',
    });
    assert.equal(resolved.me, undefined);
});

/* ---------------------------------- memory ------------------------------------- */

check('secret-shaped values are recognised', () => {
    assert.ok(looksLikeSecret('sk-abcdefghijklmnopqrstuvwx'));
    assert.ok(looksLikeSecret('Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6'));
    assert.ok(looksLikeSecret('-----BEGIN RSA PRIVATE KEY-----'));
    assert.ok(looksLikeSecret('ghp_abcdefghijklmnopqrstuvwxyz01'));
    assert.ok(looksLikeSecret('api_key: something'));
    assert.ok(looksLikeSecret('eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc'));
});

check('ordinary values are not mistaken for secrets', () => {
    assert.equal(looksLikeSecret('Contoso Ltd'), false);
    assert.equal(looksLikeSecret('a formal, concise tone'), false);
    assert.equal(looksLikeSecret(''), false);
    assert.equal(looksLikeSecret('the Q3 board pack'), false);
});

check('memory is capped per variable', () => {
    const values = Array.from({ length: 12 }, (_, index) => `value ${index}`);
    const pruned = pruneMemory({ prompt: { customer: values } });
    assert.equal(pruned.prompt.customer.length, MAX_REMEMBERED_VALUES);
    assert.equal(pruned.prompt.customer[0], 'value 0', 'most recent first is preserved');
});

check('memory is capped per prompt and per variable count', () => {
    const variables: Record<string, string[]> = {};
    for (let index = 0; index < MAX_REMEMBERED_VARIABLES + 20; index += 1) {
        variables[`var${index}`] = ['x'];
    }
    const pruned = pruneMemory({ prompt: variables });
    assert.equal(Object.keys(pruned.prompt).length, MAX_REMEMBERED_VARIABLES);

    const prompts: Record<string, Record<string, string[]>> = {};
    for (let index = 0; index < MAX_REMEMBERED_PROMPTS + 10; index += 1) {
        prompts[`p${index}`] = { a: ['x'] };
    }
    assert.equal(Object.keys(pruneMemory(prompts)).length, MAX_REMEMBERED_PROMPTS);
});

check('pruning drops empty entries entirely', () => {
    const pruned = pruneMemory({ prompt: { a: [], b: [''] }, other: {} });
    assert.deepEqual(Object.keys(pruned), [], 'a prompt with nothing left should not be stored');
});

/* -------------------------------- slash search --------------------------------- */

check('a slash opening a word starts a query', () => {
    assert.deepEqual(readSlashQuery('/week', 5)?.query, 'week');
    assert.deepEqual(readSlashQuery('hello /week', 11)?.query, 'week');
    assert.equal(readSlashQuery('/week', 5)?.start, 0);
});

check('a slash mid-word does not', () => {
    assert.equal(readSlashQuery('and/or', 6), null, 'and/or must not open the menu');
    assert.equal(
        readSlashQuery('https://example.com', 19),
        null,
        'a URL must not open the menu',
    );
});

check('the query ends at a newline', () => {
    assert.equal(readSlashQuery('/week\nmore', 10), null);
});

check('an over-long query is prose rather than a search', () => {
    const long = `/${'a'.repeat(MAX_SLASH_QUERY_LENGTH + 1)}`;
    assert.equal(readSlashQuery(long, long.length), null);
});

check('a query may contain spaces', () => {
    assert.equal(readSlashQuery('/weekly status', 14)?.query, 'weekly status');
});

const catalog = [
    { id: '1', name: 'Weekly status summary', description: 'For the Monday note' },
    { id: '2', name: 'Bug triage', is_favorite: true },
    { id: '3', name: 'Apology email', description: 'Customer facing', scope_name: 'Support' },
    { id: '', name: 'Broken' },
];

check('slash results put favourites first, then alphabetical', () => {
    const results = filterPromptsForSlash(catalog, '');
    assert.deepEqual(
        results.map((item) => item.name),
        ['Bug triage', 'Apology email', 'Weekly status summary'],
    );
});

check('a prompt without an id is never offered', () => {
    assert.equal(
        filterPromptsForSlash(catalog, 'broken').length,
        0,
        'it could not be inserted, so offering it is a dead row',
    );
});

check('slash search covers description and scope, not only the name', () => {
    assert.deepEqual(
        filterPromptsForSlash(catalog, 'monday').map((item) => item.id),
        ['1'],
    );
    assert.deepEqual(
        filterPromptsForSlash(catalog, 'support').map((item) => item.id),
        ['3'],
    );
});

check('a query matching nothing returns nothing, which is what closes the menu', () => {
    assert.equal(filterPromptsForSlash(catalog, 'nothing like this').length, 0);
});

check('a slash followed by a space is prose, not a command', () => {
    // `/ ` used to yield a query of " ", which trims to "" and matched every prompt -- so the
    // menu stayed open over an ordinary sentence and swallowed the Enter meant to send it.
    assert.equal(readSlashQuery('/ ', 2), null);
    assert.equal(readSlashQuery('Hello / ', 8), null);
    assert.equal(readSlashQuery('a /  ', 5), null);
});

check('a whitespace-only query offers nothing, while an empty one offers everything', () => {
    assert.ok(filterPromptsForSlash(catalog, '').length > 0, 'nothing typed yet offers all');
    assert.equal(filterPromptsForSlash(catalog, ' ').length, 0);
    assert.equal(filterPromptsForSlash(catalog, '   ').length, 0);
});

/* -------------------------------- insertion ------------------------------------ */

check('insertion into an empty composer adds no separator', () => {
    const result = insertPromptText('', 0, 0, 'Summarise this.');
    assert.equal(result.text, 'Summarise this.');
    assert.equal(result.caret, 'Summarise this.'.length);
});

check('insertion preserves what was already written', () => {
    const result = insertPromptText('Some notes', 10, 10, 'Summarise this.');
    assert.equal(
        result.text,
        'Some notes Summarise this.',
        'replacing the whole value is what made picking a prompt destroy the draft',
    );
});

check('a multi-line prompt is separated by a blank line', () => {
    const result = insertPromptText('Notes', 5, 5, 'One\nTwo');
    assert.equal(result.text, 'Notes\n\nOne\nTwo');
});

check('existing whitespace is not doubled', () => {
    assert.equal(insertPromptText('Notes ', 6, 6, 'more').text, 'Notes more');
    assert.equal(insertPromptText('Notes\n\n', 7, 7, 'a\nb').text, 'Notes\n\na\nb');
});

check('a selection is replaced', () => {
    const result = insertPromptText('keep THIS end', 5, 9, 'that');
    assert.equal(result.text, 'keep that end');
});

check('the caret lands after the insertion, not after a trailing separator', () => {
    const result = insertPromptText('before after', 7, 7, 'X');
    assert.equal(result.text, 'before X after');
    assert.equal(result.text.slice(0, result.caret), 'before X');
});

check('a slash token is replaced rather than left in the message', () => {
    const text = 'Hi there /weekly';
    const slash = readSlashQuery(text, text.length);
    assert.ok(slash);
    const result = insertPromptText(text, slash!.start, slash!.end, 'Give me a status update.');
    assert.equal(result.text, 'Hi there Give me a status update.');
});

/* ----------------------------- names and the library ---------------------------- */

check('a suggested name is the first meaningful line, unadorned', () => {
    assert.equal(suggestPromptName('## Weekly status\n\nBody here'), 'Weekly status');
    assert.equal(suggestPromptName('\n\n- First bullet\nmore'), 'First bullet');
    assert.equal(suggestPromptName('1. Numbered start'), 'Numbered start');
    assert.equal(suggestPromptName('**Bold title**'), 'Bold title');
});

check('an empty message suggests nothing, leaving the fallback to the caller', () => {
    assert.equal(suggestPromptName('   \n  '), '');
});

check('a long first line is cut on a word boundary', () => {
    const name = suggestPromptName('The quick brown fox jumps over the lazy dog again', 20);
    assert.ok(name.length <= 21, `expected a short name, got ${name}`);
    assert.ok(name.endsWith('…'));
    assert.ok(!name.includes('  '));
});

check('duplicate names count up rather than stacking "(copy)"', () => {
    assert.equal(duplicatePromptName('Report', []), 'Report (copy)');
    assert.equal(duplicatePromptName('Report', ['Report (copy)']), 'Report (copy 2)');
    assert.equal(
        duplicatePromptName('Report', ['Report (copy)', 'Report (copy 2)']),
        'Report (copy 3)',
    );
});

check('duplicate detection ignores case, as the list does', () => {
    assert.equal(duplicatePromptName('Report', ['report (COPY)']), 'Report (copy 2)');
});

check('search covers the body, not only the name', () => {
    const prompt = { id: '1', name: 'Weekly note', content: 'mention the Contoso migration' };
    assert.ok(promptMatchesQuery(prompt, 'contoso'), 'finding a prompt by what it says is the point');
    assert.ok(promptMatchesQuery(prompt, ''));
    assert.equal(promptMatchesQuery(prompt, 'nothing'), false);
});

check('favourites float to the top of both orders', () => {
    const prompts = [
        { id: 'a', name: 'Alpha', updated_at: '2026-01-03T00:00:00Z' },
        { id: 'b', name: 'Bravo', updated_at: '2026-01-01T00:00:00Z', is_favorite: true },
        { id: 'c', name: 'Charlie', updated_at: '2026-01-02T00:00:00Z' },
    ];
    assert.deepEqual(
        sortPrompts(prompts, 'recent').map((item) => item.id),
        ['b', 'a', 'c'],
    );
    assert.deepEqual(
        sortPrompts(prompts, 'name').map((item) => item.id),
        ['b', 'a', 'c'],
    );
});

check('a prompt with no date sorts last rather than throwing', () => {
    const prompts = [
        { id: 'a', name: 'Alpha' },
        { id: 'b', name: 'Bravo', updated_at: '2026-01-01T00:00:00Z' },
    ];
    assert.deepEqual(
        sortPrompts(prompts, 'recent').map((item) => item.id),
        ['b', 'a'],
    );
});

check('an unparseable date does not break sorting', () => {
    const prompts = [
        { id: 'a', name: 'Alpha', updated_at: 'not a date' },
        { id: 'b', name: 'Bravo', updated_at: '2026-01-01T00:00:00Z' },
    ];
    assert.deepEqual(
        sortPrompts(prompts, 'recent').map((item) => item.id),
        ['b', 'a'],
    );
});

check('visible prompts filter and sort together', () => {
    const prompts = [
        { id: 'a', name: 'Alpha', content: 'shared word' },
        { id: 'b', name: 'Bravo', content: 'shared word', is_favorite: true },
        { id: 'c', name: 'Charlie', content: 'different' },
    ];
    assert.deepEqual(
        visiblePrompts(prompts, 'shared', 'name').map((item) => item.id),
        ['b', 'a'],
    );
});

check('the preview strips fenced code and markdown noise', () => {
    const preview = promptPreview({
        id: '1',
        content: '## Heading\n\n```\ncode here\n```\n\nSome **body** text',
    });
    assert.ok(!preview.includes('code here'));
    assert.ok(!preview.includes('#'));
    assert.ok(!preview.includes('*'));
    assert.ok(preview.includes('Some body text'));
});

check('a long preview is ellipsised', () => {
    const preview = promptPreview({ id: '1', content: 'word '.repeat(100) }, 40);
    assert.ok(preview.length <= 41);
    assert.ok(preview.endsWith('…'));
});

/* -------------------------------- the handoff ---------------------------------- */

check('the prompt parameter is read and trimmed', () => {
    assert.equal(readPromptParam(new URLSearchParams('prompt=abc')), 'abc');
    assert.equal(readPromptParam(new URLSearchParams('prompt=%20%20')), null);
    assert.equal(readPromptParam(new URLSearchParams('conversationId=1')), null);
});

check('the conversation URL sync strips the prompt parameter', () => {
    // The composer must not remove it itself: `setSearchParams` replaces the whole query from
    // the caller's render snapshot, so a parameter the composer deleted would be restored by
    // ChatPage's own effect moments later -- and the URL would re-insert the prompt on reload.
    const next = syncedConversationParams(new URLSearchParams('prompt=p1'), null);
    assert.ok(next, 'a prompt parameter must count as a difference worth writing');
    assert.equal(next!.get('prompt'), null);
});

check('stripping the prompt parameter keeps the conversation', () => {
    const next = syncedConversationParams(new URLSearchParams('prompt=p1'), 'conv-1');
    assert.ok(next);
    assert.equal(next!.get('prompt'), null);
    assert.equal(next!.get('conversationId'), 'conv-1');
});

check('a URL already in its final shape still writes nothing', () => {
    assert.equal(
        syncedConversationParams(new URLSearchParams('conversationId=conv-1'), 'conv-1'),
        null,
        'the null return is what stops the write effect re-entering itself',
    );
    assert.equal(syncedConversationParams(new URLSearchParams(''), null), null);
});

check('a prompt link built for chat round-trips', () => {
    const href = chatHrefForPrompt('p 1/2');
    const query = new URLSearchParams(href.slice(href.indexOf('?') + 1));
    assert.equal(readPromptParam(query), 'p 1/2');
});

/* ----------------------------------- runner ------------------------------------ */

let passed = 0;
let failed = 0;

for (const [name, fn] of checks) {
    try {
        fn();
        console.log(`  ok  ${name}`);
        passed += 1;
    } catch (error) {
        console.log(`FAIL  ${name}`);
        console.log(`      ${(error as Error).message}`);
        failed += 1;
    }
}

console.log(
    failed === 0
        ? `\nAll ${passed} checks passed.`
        : `\n${failed} of ${passed + failed} check(s) failed.`,
);
process.exit(failed > 0 ? 1 : 0);
