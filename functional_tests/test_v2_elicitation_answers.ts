// test_v2_elicitation_answers.ts
// Version: 0.261.096
// Implemented in: 0.261.096
// Validates primitive answers and answer-local context without a browser or Azure services.

import assert from 'node:assert/strict';
import { documentContextItem, PERSONAL_SCOPE, tagContextItem } from '../application/v2_ui/src/lib/chatContext';
import {
    buildElicitationAnswer,
    createElicitationDraft,
    elicitationFieldKind,
    elicitationPages,
} from '../application/v2_ui/src/lib/elicitationAnswers';
import type { ComposerReference } from '../application/v2_ui/src/lib/composerDraft';
import type { Elicitation, ElicitationFieldSchema } from '../application/v2_ui/src/lib/orchestration';

const original: ComposerReference = {
    kind: 'document', id: 'original-document', label: 'Suggested report',
    scope: { kind: 'personal', id: null, name: 'My workspace' },
};
const replacement: ComposerReference = {
    kind: 'document', id: 'replacement-document', label: 'Correct report',
    scope: { kind: 'group', id: 'group-1', name: 'Research' },
};
const chatAttachment: ComposerReference = {
    kind: 'chat_attachment', id: 'conversation-file-message', label: 'Attached image',
    scope: { kind: 'chat', id: 'conversation-1', name: 'This conversation' },
};

function question(properties: Record<string, ElicitationFieldSchema>, required = Object.keys(properties)): Elicitation {
    return {
        elicitation_id: 'question-1',
        run_id: '',
        turn_id: 'turn-1',
        contract_version: 2,
        revision: 0,
        message: 'A little more information',
        requested_schema: { type: 'object', properties, required },
        ui_hints: { pages: [Object.keys(properties)], order: Object.keys(properties) },
    };
}

function fileQuestion(multiple = true): Elicitation {
    const result = question({
        files: multiple
            ? { type: 'array', items: { type: 'string' }, title: 'Files' }
            : { type: 'string', title: 'File' },
    });
    result.ui_hints.fields = { files: { input: 'files', candidates: [original, replacement] } };
    return result;
}

{
    const spec = question({
        notes: { type: 'string' },
        count: { type: 'integer', default: 0 },
        enabled: { type: 'boolean', default: false },
    });
    const draft = createElicitationDraft(spec);
    let built = buildElicitationAnswer(spec, draft, {});
    assert.equal(built.response.content.count, 0);
    assert.equal(built.response.content.enabled, false);
    assert.equal(built.errors.notes, 'An answer is required.');
    draft.editors.notes.text = 'Use the updated version';
    built = buildElicitationAnswer(spec, draft, {});
    assert.deepEqual(built.errors, {});
    assert.equal(built.response.content.notes, 'Use the updated version');
    assert.notEqual(draft.editors.notes, draft.editors.count);
    assert.notEqual(draft.editors.notes.contextItems, draft.editors.count.contextItems);
    draft.values.count = '1.5';
    assert.match(buildElicitationAnswer(spec, draft, {}).errors.count, /integer/);
}

{
    const spec = question({
        tone: { type: 'string', enum: ['formal', 'casual'] },
        audiences: { type: 'array', items: { type: 'string', enum: ['staff', 'customers'] } },
    });
    const draft = createElicitationDraft(spec);
    draft.values.tone = 'formal';
    draft.values.audiences = ['staff', 'customers', 'staff'];
    draft.editors.tone.text = 'Keep it short';
    draft.editors.tone.contextItems = [documentContextItem(
        { id: 'original-document', title: 'Suggested report' }, PERSONAL_SCOPE,
    )];
    let built = buildElicitationAnswer(spec, draft, {});
    assert.deepEqual(built.errors, {});
    assert.equal(built.response.content.tone, 'formal');
    assert.deepEqual(built.response.content.audiences, ['staff', 'customers']);
    assert.equal(built.context.tone.text, 'Keep it short');
    assert.equal(built.context.tone.references?.[0].id, 'original-document');
    draft.values.tone = 'made up';
    draft.values.audiences = [];
    built = buildElicitationAnswer(spec, draft, {});
    assert.match(built.errors.tone, /offered/);
    assert.match(built.errors.audiences, /required/);
    assert.equal(built.response.content.tone, undefined);
}

{
    const spec = fileQuestion();
    const draft = createElicitationDraft(spec);
    assert.equal(elicitationFieldKind(spec, 'files'), 'files');
    assert.match(buildElicitationAnswer(spec, draft, {}).errors.files, /upload a file/);
    draft.editors.files.uploads = [{
        id: 'upload-1', fileName: 'correct.pdf', state: 'ready', reference: replacement,
    }];
    let built = buildElicitationAnswer(spec, draft, {});
    assert.deepEqual(built.errors, {});
    assert.deepEqual(built.response.content.files, ['replacement-document']);
    assert.deepEqual(built.context.files.references, [replacement]);
    assert.equal(draft.values.files, undefined, 'No suggestion had to be selected');
    draft.values.files = ['original-document', 'replacement-document'];
    built = buildElicitationAnswer(spec, draft, {});
    assert.deepEqual(built.response.content.files, ['original-document', 'replacement-document']);
    assert.equal(built.context.files.references?.length, 2, 'Candidate/upload references must be deduplicated');
}

{
    const spec = fileQuestion(false);
    const draft = createElicitationDraft(spec);
    draft.values.files = 'original-document';
    assert.equal(buildElicitationAnswer(spec, draft, {}).response.content.files, original.id);
    draft.editors.files.uploads = [{
        id: 'upload-1', fileName: 'photo.png', state: 'ready', reference: chatAttachment,
    }];
    assert.match(buildElicitationAnswer(spec, draft, {}).errors.files, /one file/);
    draft.values.files = undefined;
    const built = buildElicitationAnswer(spec, draft, {});
    assert.deepEqual(built.errors, {});
    assert.equal(built.response.content.files, chatAttachment.id);
    assert.equal(built.context.files.references?.[0].scope.kind, 'chat');
}

{
    const spec = fileQuestion();
    const draft = createElicitationDraft(spec);
    draft.editors.files.contextItems = [tagContextItem('Quarterly', PERSONAL_SCOPE)];
    draft.editors.files.text = 'A file called report.pdf';
    let built = buildElicitationAnswer(spec, draft, {});
    assert.match(built.errors.files, /file/);
    assert.equal(built.response.content.files, undefined, 'A filename or tag is not an actual selected file');
    draft.editors.files.uploads = [{ id: 'u', fileName: 'report.pdf', state: 'processing', progress: 50 }];
    built = buildElicitationAnswer(spec, draft, {});
    assert.equal(built.pendingUploads, true);
    assert.match(built.errors.files, /processing/);
    draft.editors.files.uploads[0].state = 'failed';
    built = buildElicitationAnswer(spec, draft, {});
    assert.equal(built.pendingUploads, false);
    assert.match(built.errors.files, /Retry or remove/);
}

{
    const spec = question({ subject: { type: 'string' } });
    const draft = createElicitationDraft(spec);
    draft.editors.subject.text = 'these findings';
    draft.editors.subject.attachedPrompt = {
        id: 'prompt-1', name: 'Explain', originalContent: 'Explain {{composer}} for {{audience}}.',
        editedContent: null,
    };
    draft.editors.subject.promptValues = { audience: 'researchers' };
    const built = buildElicitationAnswer(spec, draft, { composerText: 'UNRELATED MAIN DRAFT' });
    assert.equal(built.response.content.subject, 'Explain these findings for researchers.');
    assert.equal(built.context.subject.prompt_info?.id, 'prompt-1');
    assert.equal(built.context.subject.prompt_info?.user_text, '');
    assert.equal(draft.editors.subject.text, 'these findings');
    assert.equal(draft.editors.subject.attachedPrompt.originalContent, 'Explain {{composer}} for {{audience}}.');
}

{
    const spec = question({
        names: { type: 'array', items: { type: 'string' }, default: ['one', 'two'] },
        numbers: { type: 'array', items: { type: 'integer' } },
        flags: { type: 'array', items: { type: 'boolean' } },
    });
    const draft = createElicitationDraft(spec);
    draft.values.numbers = '0\n2';
    draft.values.flags = 'false\ntrue';
    let built = buildElicitationAnswer(spec, draft, {});
    assert.deepEqual(built.errors, {});
    assert.deepEqual(built.response.content, { names: ['one', 'two'], numbers: [0, 2], flags: [false, true] });
    draft.values.numbers = '1.5';
    draft.values.flags = 'maybe';
    built = buildElicitationAnswer(spec, draft, {});
    assert.match(built.errors.numbers, /integer/);
    assert.match(built.errors.flags, /boolean/);
}

{
    const spec = question({ answer: { type: 'string' } });
    const draft = createElicitationDraft(spec);
    draft.editors.answer.uploads = [{
        id: 'u', fileName: 'notes.pdf', state: 'ready', reference: replacement,
    }];
    const built = buildElicitationAnswer(spec, draft, {});
    assert.deepEqual(built.errors, {});
    assert.equal(built.response.content.answer, 'Correct report');
    assert.equal(draft.editors.answer.text, '', 'File-only submission must not rewrite the visible draft');
}

{
    const spec = question({ first: { type: 'string' }, second: { type: 'string' }, third: { type: 'number' } }, []);
    spec.ui_hints = { order: ['second', 'first', 'third'], pages: [['first'], ['first', 'unknown'], ['second']] };
    assert.deepEqual(elicitationPages(spec), [['first'], ['second'], ['third']]);
    spec.ui_hints.pages = [];
    assert.deepEqual(elicitationPages(spec), [['second', 'first', 'third']]);
}

console.log('Elicitation answer contracts passed.');
