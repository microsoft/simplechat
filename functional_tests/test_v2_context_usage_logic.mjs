// test_v2_context_usage_logic.mjs
// Version: 0.261.489
// Implemented in: 0.261.489
// Executes the real V2 helpers behind the composer's context ring and the drawer's Context tab.
// The provider's count is the total when one request produced it; the server's estimate supplies
// the split, and the difference between the two is shown as its own row or scaled away, never
// hidden. A reply made by several requests falls back to the estimate, and a model with no
// configured limits shows a size and no percentage.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const {
    contextLevel,
    describeContextUsage,
    describeStepContextFill,
    formatContextSize,
    normalizeStepContextFill,
    readContextTurns,
    readContextUsage,
} = await import('../application/v2_ui/src/lib/contextUsage.ts');

const estimate = (overrides = {}) => ({
    version: 1,
    estimator: 'o200k_base',
    model: 'gpt-4o',
    estimated_total: 8000,
    categories: { messages: 3000, files: 4000, search: 400, web: 200, instructions: 400 },
    items: [
        { category: 'files', label: 'Q3-forecast.xlsx', size: 3000 },
        { category: 'files', label: 'notes.txt', size: 1000 },
        { category: 'files', label: '', size: 5 },
        { category: 'other', label: 'ignored', size: 5 },
    ],
    limits: { window: 128000, input_limit: 128000, reply_reserve: 4096, input_ceiling: 20000 },
    ...overrides,
});

const reply = (id, { usage, contextUsage, history = {}, active } = {}) => ({
    id,
    conversation_id: 'c1',
    role: 'assistant',
    content: 'answer',
    model_deployment_name: 'deployed-name',
    metadata: {
        ...(usage ? { token_usage: usage } : {}),
        history_context: { history_limit: 6, recent_message_count: 6, ...history, ...(contextUsage ? { context_usage: contextUsage } : {}) },
        ...(active === undefined ? {} : { thread_info: { active_thread: active } }),
    },
});
const question = (id, content) => ({ id, conversation_id: 'c1', role: 'user', content });

// Nothing recorded yet: no ring, no tab content.
assert.equal(readContextUsage([]), null);
assert.equal(readContextUsage([question('u1', 'hi')]), null);
assert.equal(readContextUsage([reply('a0', {})]), null);

// One request: the provider's count is the total and the gap becomes "Agent, tools and overhead".
const measured = readContextUsage([
    question('u1', 'Compare the forecast'),
    reply('a1', { usage: { prompt_tokens: 10000, completion_tokens: 200, request_count: 1 }, contextUsage: estimate() }),
]);
assert.equal(measured.messageId, 'a1');
assert.equal(measured.used, 10000);
assert.equal(measured.measured, true);
assert.equal(measured.limit, 20000);
assert.equal(measured.percent, 50);
assert.equal(measured.free, 10000);
assert.equal(measured.replyReserve, 4096);
assert.equal(measured.window, 128000);
assert.equal(measured.model, 'gpt-4o');
assert.equal(measured.level, 'ok');
assert.deepEqual(measured.categories.map((row) => [row.id, row.size]), [
    ['messages', 3000], ['files', 4000], ['search', 400], ['web', 200], ['instructions', 400], ['other', 2000],
]);
assert.equal(measured.categories.reduce((sum, row) => sum + row.size, 0), measured.used);
assert.equal(measured.categories[1].label, 'Attached files');
assert.equal(measured.categories[1].share, 0.4);
assert.equal(measured.categories[3].label, 'Web results');
assert.deepEqual(measured.files, [
    { label: 'Q3-forecast.xlsx', size: 3000 },
    { label: 'notes.txt', size: 1000 },
]);
assert.deepEqual(measured.history, { limit: 6, recentCount: 6, olderCount: 0, summaryUsed: false });
assert.equal(describeContextUsage(measured), 'Context: 50% used, 10K tokens of 20K');

// The estimate ran high: rows are scaled down to the provider's count and no gap row is added.
const scaled = readContextUsage([
    reply('a1', { usage: { prompt_tokens: 4000 }, contextUsage: estimate() }),
]);
assert.equal(scaled.used, 4000);
assert.deepEqual(scaled.categories.map((row) => [row.id, row.size]), [
    ['messages', 1500], ['files', 2000], ['search', 200], ['web', 100], ['instructions', 200],
]);

// Several requests (an agent calling tools): the summed count is spend, so the estimate is used.
const agent = readContextUsage([
    reply('a1', { usage: { prompt_tokens: 60000, request_count: 4 }, contextUsage: estimate() }),
]);
assert.equal(agent.used, 8000);
assert.equal(agent.measured, false);
assert.equal(agent.percent, 40);
assert.equal(agent.categories.some((row) => row.id === 'other'), false);

// A reply saved before the breakdown existed still gives a total, with no split and no limit.
const older = readContextUsage([
    reply('a1', { usage: { prompt_tokens: 5200 }, history: { older_message_count: 4, summary_used: true } }),
]);
assert.equal(older.used, 5200);
assert.equal(older.limit, null);
assert.equal(older.percent, null);
assert.equal(older.free, null);
assert.equal(older.level, 'ok');
assert.deepEqual(older.categories, []);
assert.equal(older.model, 'deployed-name');
assert.deepEqual(older.history, { limit: 6, recentCount: 6, olderCount: 4, summaryUsed: true });
assert.equal(describeContextUsage(older), 'Context: 5.2K tokens in the last request');

// The latest active reply wins; a replaced attempt and a reply with nothing recorded are skipped.
const latest = readContextUsage([
    reply('a1', { usage: { prompt_tokens: 1000 }, contextUsage: estimate() }),
    reply('a2', { usage: { prompt_tokens: 19000 }, contextUsage: estimate() }),
    reply('a3', { usage: { prompt_tokens: 99999 }, contextUsage: estimate(), active: false }),
    reply('a4', {}),
]);
assert.equal(latest.messageId, 'a2');
assert.equal(latest.percent, 95);
assert.equal(latest.level, 'full');

// A request larger than the ceiling reads 100%, never more, with nothing free.
const over = readContextUsage([reply('a1', { usage: { prompt_tokens: 30000 }, contextUsage: estimate() })]);
assert.equal(over.percent, 100);
assert.equal(over.free, 0);

assert.equal(contextLevel(null), 'ok');
assert.equal(contextLevel(74), 'ok');
assert.equal(contextLevel(75), 'warn');
assert.equal(contextLevel(89), 'warn');
assert.equal(contextLevel(90), 'full');

// By turn: each reply's request size, labelled with the question it answered.
const turns = readContextTurns([
    question('u1', 'First question'),
    reply('a1', { usage: { prompt_tokens: 2000 } }),
    question('u2', 'Second question'),
    reply('a2-old', { usage: { prompt_tokens: 9000 }, active: false }),
    reply('a2', { usage: { prompt_tokens: 8000, request_count: 3 }, contextUsage: estimate({ estimated_total: 4000 }) }),
    question('u3', 'Third question'),
    reply('a3', {}),
]);
assert.deepEqual(turns, [
    { messageId: 'a1', index: 1, question: 'First question', used: 2000, measured: true, plan: false, models: [], share: 0.5 },
    { messageId: 'a2', index: 2, question: 'Second question', used: 4000, measured: false, plan: false, models: [], share: 1 },
]);

// An orchestration plan's reply carries counts added up over planning and every step, with no
// request count. That is spend: it must never become the context total, and the ring keeps
// showing the last ordinary reply. By turn lists it as spend, with no bar.
const planReply = (id, usage) => {
    const message = reply(id, { usage });
    message.metadata.orchestration = { run_id: 'r1', status: 'completed' };
    return message;
};
const afterPlan = [
    question('u1', 'Ordinary question'),
    reply('a1', { usage: { prompt_tokens: 6000 }, contextUsage: estimate() }),
    question('u2', 'Build me a report'),
    planReply('p1', { prompt_tokens: 240000, completion_tokens: 9000, total_tokens: 249000 }),
];
const ringAfterPlan = readContextUsage(afterPlan);
assert.equal(ringAfterPlan.messageId, 'a1');
assert.equal(ringAfterPlan.used, 6000);
assert.equal(readContextUsage([question('u1', 'Plan only'), planReply('p1', { prompt_tokens: 240000 })]), null);
assert.deepEqual(readContextTurns(afterPlan), [
    { messageId: 'a1', index: 1, question: 'Ordinary question', used: 6000, measured: true, plan: false, models: [], share: 1 },
    { messageId: 'p1', index: 2, question: 'Build me a report', used: 249000, measured: true, plan: true, models: [], share: 0 },
]);

// Steps can run on different models. The plan's row lists what each model spent.
const routed = planReply('p2', { prompt_tokens: 240000, completion_tokens: 9000, total_tokens: 249000 });
routed.metadata.usage_by_model = [
    { model: 'gpt-5', label: 'GPT-5', prompt_tokens: 170000, completion_tokens: 5000, total_tokens: 175000, step_count: 2, roles: ['steps'] },
    { model: 'gpt-4o', label: 'GPT-4o', prompt_tokens: 70000, completion_tokens: 4000, total_tokens: 74000, step_count: 1, roles: ['steps', 'planning_and_answer'] },
    { model: 'empty', label: 'Empty', total_tokens: 0, step_count: 1, roles: ['steps'] },
    { total_tokens: 500 },
    'not a row',
];
assert.deepEqual(readContextTurns([question('u1', 'Routed plan'), routed])[0].models, [
    { label: 'GPT-5', total: 175000, stepCount: 2, answered: false },
    { label: 'GPT-4o', total: 74000, stepCount: 1, answered: true },
]);
assert.deepEqual(readContextTurns([planReply('p0', {})]), []);
assert.deepEqual(readContextTurns([]), []);

assert.equal(formatContextSize(0), '0');
assert.equal(formatContextSize(-5), '0');
assert.equal(formatContextSize(950), '950');
assert.equal(formatContextSize(1000), '1K');
assert.equal(formatContextSize(8240), '8.2K');
assert.equal(formatContextSize(82600), '82.6K');
assert.equal(formatContextSize(128000), '128K');
assert.equal(formatContextSize(999960), '1M');
assert.equal(formatContextSize(1200000), '1.2M');

// Switching models re-bases the ring at once: the size is still the last reply's, but the limit
// is the selected model's, because that is where the next message goes.
const lastReply = [reply('a1', { usage: { prompt_tokens: 10000 }, contextUsage: estimate() })];
assert.equal(readContextUsage(lastReply).rebased, false);
const switched = readContextUsage(lastReply, {
    model: 'gpt-4o-mini', label: 'GPT-4o mini', limits: { window: 16000, reply_reserve: 3500, input_ceiling: 12500 },
});
assert.equal(switched.used, 10000);
assert.equal(switched.limit, 12500);
assert.equal(switched.percent, 80);
assert.equal(switched.level, 'warn');
assert.equal(switched.free, 2500);
assert.equal(switched.replyReserve, 3500);
assert.equal(switched.window, 16000);
assert.equal(switched.model, 'GPT-4o mini');
assert.equal(switched.rebased, true);
// The same model selected again is not a re-base, but its current limits still apply.
const same = readContextUsage(lastReply, { model: 'gpt-4o', label: 'GPT-4o', limits: { input_ceiling: 40000 } });
assert.equal(same.rebased, false);
assert.equal(same.percent, 25);
// A selected model with no known limits leaves the last reply's limit in place.
for (const limits of [undefined, null, {}, { input_ceiling: 0 }, 'text']) {
    const kept = readContextUsage(lastReply, { model: 'custom', label: 'Custom', limits });
    assert.equal(kept.limit, 20000);
    assert.equal(kept.model, 'gpt-4o');
    assert.equal(kept.rebased, false);
}
assert.equal(readContextUsage(lastReply, null).limit, 20000);
// A reply with no limits of its own gains a percentage from the selected model.
const gained = readContextUsage(
    [reply('a1', { usage: { prompt_tokens: 5200 } })],
    { model: 'gpt-4o', label: 'GPT-4o', limits: { input_ceiling: 52000 } },
);
assert.equal(gained.percent, 10);

// A plan step's fullest single request against the limit of the model it ran on.
assert.deepEqual(normalizeStepContextFill({ model: 'GPT-4o', peak_request: 92000, limit: 112000, percent: 82 }), {
    model: 'GPT-4o', peakRequest: 92000, limit: 112000, percent: 82, level: 'warn',
});
assert.equal(
    describeStepContextFill(normalizeStepContextFill({ model: 'GPT-4o', peak_request: 92000, limit: 112000 })),
    "Largest request: 82% of GPT-4o's window (92K of 112K tokens)",
);
const unknownLimit = normalizeStepContextFill({ model: 'custom-deployment', peak_request: 5200 });
assert.deepEqual(unknownLimit, { model: 'custom-deployment', peakRequest: 5200, limit: null, percent: null, level: 'ok' });
assert.equal(describeStepContextFill(unknownLimit), 'Largest request: 5.2K tokens on custom-deployment');
assert.equal(describeStepContextFill(normalizeStepContextFill({ peak_request: 800 })), 'Largest request: 800 tokens');
assert.equal(
    describeStepContextFill(normalizeStepContextFill({ peak_request: 99000, limit: 100000 })),
    "Largest request: 99% of the model's window (99K of 100K tokens)",
);
assert.equal(normalizeStepContextFill({ peak_request: 99000, limit: 100000 }).level, 'full');
assert.equal(normalizeStepContextFill({ peak_request: 500000, limit: 100000 }).percent, 100);
for (const nothing of [undefined, null, {}, { peak_request: 0 }, { peak_request: '9' }, 'text', []]) {
    assert.equal(normalizeStepContextFill(nothing), undefined);
}

console.log('V2 context usage logic tests passed.');
