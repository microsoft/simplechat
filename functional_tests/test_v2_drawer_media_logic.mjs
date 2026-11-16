// test_v2_drawer_media_logic.mjs
// Version: 0.261.255
// Implemented in: 0.261.255
// Executes the real V2 helper that fills the Media section of the conversation drawer: images
// from image messages and reply markdown, recordings and clips linked in replies (including
// signed links from remote services), each file once, and nothing the thread itself hides --
// masked text, a fully masked message, a message a workflow reply replaced, code samples, or
// anything a person typed as plain text.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';

const hadWindow = 'window' in globalThis;
const previousWindow = globalThis.window;
globalThis.window = { location: { href: 'https://chat.example.gov/chat' } };

try {
    const { collectConversationMedia, messageMedia } = await import(
        '../application/v2_ui/src/lib/conversationMedia.ts'
    );

    const signedImage = 'https://media.example.com/captures/cap-1.jpg?exp=1&sig=abc';
    const signedClip = 'https://media.example.com/clips/clip-7.mp4?exp=1&sig=def';
    const recording = 'https://media.example.com/audio/rec-1.wav';

    function reply(id, content, metadata) {
        return { id, role: 'assistant', content, ...(metadata ? { metadata } : {}) };
    }

    // Images and recordings in a reply, in order, with titles taken from the markdown.
    const answer = reply('a-1', [
        'Two captures came back.',
        `![Plate capture at the bridge](${signedImage})`,
        `[Open video: Bridge camera clip](${signedClip}) and [Open audio: Call audio REC-1](${recording}).`,
        '[A web page](https://example.com/report) is not media.',
        '```markdown',
        '![In a code sample](https://media.example.com/sample.png)',
        '```',
        'Inline `![code](https://media.example.com/inline.png)` too.',
        '![Bad](javascript:alert(1))',
    ].join('\n'));
    const items = messageMedia(answer);
    assert.deepEqual(items.map((item) => [item.kind, item.title]), [
        ['image', 'Plate capture at the bridge'],
        ['video', 'Bridge camera clip'],
        ['audio', 'Call audio REC-1'],
    ]);
    assert.equal(items[0].src, signedImage, 'a signed remote image keeps its query string');
    assert.equal(items[1].src, signedClip);
    assert.ok(items.every((item) => item.messageId === 'a-1'));

    // Image messages: generated, uploaded and served by the app.
    const generated = { id: 'i-1', role: 'image', content: '/api/image/i-1', metadata: { prompt: 'Map of the harbor' } };
    const uploaded = { id: 'i-2', role: 'image', content: 'data:image/png;base64,AAAA', metadata: { is_user_upload: true } };
    const unknown = { id: 'i-3', role: 'image', content: 'not an image' };
    assert.deepEqual(messageMedia(generated).map((item) => [item.src, item.title]), [['/api/image/i-1', 'Map of the harbor']]);
    assert.equal(messageMedia(uploaded)[0].title, 'Uploaded image');
    assert.deepEqual(messageMedia(unknown), []);

    // What the thread hides stays hidden.
    const maskedStart = answer.content.indexOf(signedImage);
    const partlyMasked = reply('a-2', answer.content, {
        masked_ranges: [{ start: maskedStart, end: maskedStart + signedImage.length }],
    });
    assert.deepEqual(messageMedia(partlyMasked).map((item) => item.kind), ['video', 'audio'],
        'a masked URL is never listed');
    assert.deepEqual(messageMedia(reply('a-3', answer.content, { masked: true })), []);
    assert.deepEqual(messageMedia({ ...generated, metadata: { masked: true } }), []);
    assert.deepEqual(messageMedia(reply('a-4', answer.content, { superseded_by_workflow_reply: true })), []);

    // People type plain text; an agent posting on their behalf writes markdown.
    const typed = { id: 'u-1', role: 'user', content: `look ![x](${signedImage})` };
    const posted = {
        id: 'u-2', role: 'user', content: `![Briefing map](${signedImage})`,
        metadata: { posted_via: 'agent_action', content_format: 'markdown' },
    };
    assert.deepEqual(messageMedia(typed), []);
    assert.equal(messageMedia(posted).length, 1);

    // Each file once, in conversation order.
    const all = collectConversationMedia([generated, answer, posted, reply('a-5', `again ![dup](${signedImage})`)]);
    assert.deepEqual(all.map((item) => item.key), [
        'image:/api/image/i-1',
        `image:${signedImage}`,
        `video:${signedClip}`,
        `audio:${recording}`,
    ]);

    console.log('Drawer media checks passed');
} finally {
    if (hadWindow) {
        globalThis.window = previousWindow;
    } else {
        delete globalThis.window;
    }
}
