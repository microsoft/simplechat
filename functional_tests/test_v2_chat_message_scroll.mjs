// test_v2_chat_message_scroll.mjs
// Version: 0.261.318
// Implemented in: 0.261.318
// Verify production arrival identity, message-start geometry, and the live-follow threshold.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';
import {
    isMessageNearBottom,
    messageMatchesScrollId,
    messageStartScrollTop,
    newestMessageArrival,
} from '../application/v2_ui/src/lib/messageScroll.ts';

const message = (id, extra = {}) => ({ id, role: 'assistant', content: id, conversation_id: 'chat', ...extra });
const first = message('first');
const second = message('second');

assert.equal(newestMessageArrival([first], [first, second]), second);
assert.equal(newestMessageArrival([], [first]), first);
assert.equal(newestMessageArrival([first], [{ ...first, content: 'Edited' }]), null);
assert.equal(newestMessageArrival([first, second], [first]), null);
assert.equal(newestMessageArrival([first], [second]), null);
assert.equal(newestMessageArrival([first], [second, first]), null);
assert.equal(newestMessageArrival([first, second], [first, { ...second, metadata: { masked: true } }]), null);

const pending = message('pending-user-1', { role: 'user', content: 'Question' });
assert.equal(newestMessageArrival([first, pending], [first, { ...pending, id: 'saved-user' }]), null);
const mirrored = message('shared-answer', { metadata: { source_message_id: first.id } });
assert.equal(newestMessageArrival([first], [mirrored]), null);
assert.equal(newestMessageArrival([mirrored], [first]), null);
assert.equal(messageMatchesScrollId(mirrored, first.id), true);
assert.equal(messageMatchesScrollId(mirrored, 'not-the-answer'), false);

const attempt = message('attempt-one', { metadata: { thread_info: { thread_id: 'turn-1', thread_attempt: 1 } } });
const retry = message('attempt-two', { metadata: { thread_info: { thread_id: 'turn-1', thread_attempt: 2 } } });
assert.equal(newestMessageArrival([first, attempt], [first, retry]), null);
assert.equal(newestMessageArrival([first, attempt], [first, attempt, retry]), retry);
assert.equal(newestMessageArrival([first], [first, message('malformed', { metadata: { thread_info: [] } })]).id, 'malformed');

assert.equal(messageStartScrollTop(1000, 200, 700), 1476);
assert.equal(messageStartScrollTop(0, 200, 210), 0);
assert.equal(isMessageNearBottom(921, 1500, 500), true);
assert.equal(isMessageNearBottom(920, 1500, 500), false);
assert.equal(isMessageNearBottom(0, 100, 500), true);
