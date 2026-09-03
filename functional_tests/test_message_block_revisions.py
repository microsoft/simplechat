#!/usr/bin/env python3
"""
Functional test for inline diagram revision storage.
Version: 0.261.043
Implemented in: 0.261.043

This test ensures that a diagram inside an assistant message can be edited, versioned and
restored without rewriting the message content, and that every way the stored revisions could
be applied to the wrong block instead fails safe and leaves the original in place.

The fingerprint parity check is the important one. The client computes the hashes that get
stored, so a Python port that disagrees with it by even one character would silently stop
every stored revision from resolving. The JavaScript reference is read out of
visualPalettes.ts and executed, rather than retyped here, so this compares against the shipped
implementation instead of a copy of it.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'application',
        'single_app',
    )
)

from test_support.versioning import assert_app_version_at_least

from functions_message_block_revisions import (
    MAX_REVISIONS,
    ORIGIN_ORIGINAL,
    BlockRevisionConflictError,
    BlockRevisionError,
    append_block_chat_turn,
    apply_block_revision,
    current_block_source,
    fingerprint_source,
    read_block_chat,
    read_block_entry,
    remove_block_entry,
    resolve_block_sources_in_content,
    resolve_message_content,
    scan_markdown_fences,
    set_current_revision,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VISUAL_PALETTES = os.path.join(
    REPO_ROOT, 'application', 'v2_ui', 'src', 'lib', 'visualPalettes.ts'
)

FIRST_DIAGRAM = 'graph TD\n  A --> B'
SECOND_DIAGRAM = 'graph LR\n  C --> D'

MESSAGE_CONTENT = (
    'Here is a diagram.\n'
    '\n'
    '```mermaid\n'
    f'{FIRST_DIAGRAM}\n'
    '```\n'
    '\n'
    'And some python:\n'
    '\n'
    '```python\n'
    'print("hi")\n'
    '```\n'
    '\n'
    'And a second diagram, indented:\n'
    '\n'
    '  ```mermaid\n'
    '  graph LR\n'
    '    C --> D\n'
    '  ```\n'
    '\n'
    'Done.\n'
)

# Deliberately awkward: CRLF, a byte order mark, an emoji outside the Basic Multilingual Plane
# and CJK text. The emoji is the case a naive `ord()` port gets wrong, because JavaScript hashes
# UTF-16 code units and an astral character is two of them.
FINGERPRINT_SAMPLES = [
    'graph TD\n  A[Start] --> B[End]',
    'flowchart LR\n  A --> B\n  B --> C',
    '  graph TD\n  A --> B  \n',
    'graph TD\n  A["Caf\u00e9 \u2014 na\u00efve"] --> B',
    'graph TD\n  A["\U0001F600 emoji"] --> B["\U0001F680"]',
    'graph TD\n  A["\u4e2d\u6587"] --> B',
    '',
    '\ufeffgraph TD\n  A --> B\ufeff',
    'graph TD\r\n  A --> B\r\n',
]

JS_REFERENCE_HARNESS = r'''
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');

const start = source.indexOf('export function fingerprintSource');
if (start === -1) {
    throw new Error('fingerprintSource not found in visualPalettes.ts');
}
const end = source.indexOf('\n}', start);
const declaration = source
    .slice(start, end + 2)
    .replace('export function fingerprintSource', 'function')
    .replace('(source: string): string', '(source)');

const fingerprintSource = eval(`(${declaration})`);
const samples = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
console.log(JSON.stringify(samples.map((sample) => fingerprintSource(sample))));
'''


def _new_message():
    return {'id': 'm1', 'conversation_id': 'c1', 'content': MESSAGE_CONTENT, 'metadata': {}}


def _edit(message, index, source, original, **kwargs):
    return apply_block_revision(
        message,
        'mermaid',
        index,
        source,
        fingerprint_source(original),
        original_source=original,
        **kwargs,
    )


def test_fingerprint_matches_the_client():
    """The Python fingerprint must agree with the shipped JavaScript one, character for character."""
    print("Testing fingerprint parity with visualPalettes.ts...")
    try:
        if shutil.which('node') is None:
            print("--  skipped: node is not available to run the JavaScript reference")
            return True

        workspace = tempfile.mkdtemp(prefix='block-revisions-')
        try:
            harness_path = os.path.join(workspace, 'harness.js')
            samples_path = os.path.join(workspace, 'samples.json')
            with open(harness_path, 'w', encoding='utf-8') as handle:
                handle.write(JS_REFERENCE_HARNESS)
            with open(samples_path, 'w', encoding='utf-8') as handle:
                json.dump(FINGERPRINT_SAMPLES, handle)

            completed = subprocess.run(
                ['node', harness_path, VISUAL_PALETTES, samples_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

        assert completed.returncode == 0, f"JavaScript reference failed: {completed.stderr}"
        expected = json.loads(completed.stdout)
        actual = [fingerprint_source(sample) for sample in FINGERPRINT_SAMPLES]

        assert len(expected) == len(FINGERPRINT_SAMPLES)
        for sample, want, got in zip(FINGERPRINT_SAMPLES, expected, actual):
            assert want == got, (
                f"fingerprint mismatch for {sample.encode('unicode_escape')!r}: "
                f"JavaScript said {want}, Python said {got}"
            )

        # The BOM and CRLF samples must land on the same hash as the plain one, which is what
        # proves the trim and newline normalisation agree rather than merely both running.
        assert actual[2] == actual[7] == actual[8], (
            "trim and CRLF normalisation disagree between the samples"
        )

        print(f"Fingerprint parity test passed across {len(actual)} samples!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fences_are_scanned_and_numbered():
    """Fences are found and numbered per language, so a diagram is addressed by its own position."""
    print("Testing markdown fence scanning...")
    try:
        fences = scan_markdown_fences(MESSAGE_CONTENT)
        mermaid = [fence for fence in fences if fence['language'] == 'mermaid']
        python_fences = [fence for fence in fences if fence['language'] == 'python']

        assert len(mermaid) == 2, f"expected two diagrams, found {len(mermaid)}"
        assert len(python_fences) == 1, "the python fence should be scanned too"

        # Numbering is per language: the python fence must not push the second diagram to two.
        assert mermaid[0]['index'] == 0
        assert mermaid[1]['index'] == 1

        assert mermaid[0]['body'] == FIRST_DIAGRAM
        # The indented fence's body is dedented, matching what the markdown parser hands the
        # client, so the two agree about what the source is before it is hashed.
        assert mermaid[1]['body'] == SECOND_DIAGRAM
        assert mermaid[1]['indent'] == '  '

        print("Fence scanning test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_an_edit_is_stored_without_rewriting_the_message():
    """An edit changes what is read back while leaving the stored content exactly as written."""
    print("Testing that an edit leaves message content untouched...")
    try:
        message = _new_message()
        _edit(message, 0, 'graph LR\n  A --> B\n  B --> E', FIRST_DIAGRAM, note='flip direction')

        assert message['content'] == MESSAGE_CONTENT, (
            "the stored content was rewritten; masked range offsets would now be wrong"
        )

        resolved = resolve_message_content(message)
        assert 'graph LR\n  A --> B\n  B --> E' in resolved, "the edit was not applied"
        assert FIRST_DIAGRAM not in resolved, "the original diagram is still present"
        assert 'print("hi")' in resolved, "an unrelated fence was disturbed"
        assert '  graph LR\n    C --> D' in resolved, "the second diagram was disturbed"

        print("Overlay storage test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_an_indented_fence_keeps_its_indentation():
    """A substituted source is re-indented, so an indented fence stays a fence."""
    print("Testing indentation is preserved on substitution...")
    try:
        message = _new_message()
        _edit(message, 1, 'graph TD\n  C --> D\n  D --> F', SECOND_DIAGRAM)

        resolved = resolve_message_content(message)
        assert '  graph TD\n    C --> D\n    D --> F' in resolved, (
            "the indented fence lost its indentation and would no longer parse as a fence"
        )
        # The fence must still be closed by its own marker line.
        assert resolved.count('  ```') >= 2

        print("Indentation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_restoring_a_revision_moves_a_pointer():
    """Restoring an old version does not discard the newer ones, so history stays complete."""
    print("Testing restore and history retention...")
    try:
        message = _new_message()
        entry = _edit(message, 0, 'graph LR\n  A --> B', FIRST_DIAGRAM)
        entry = _edit(message, 0, 'graph BT\n  A --> B', FIRST_DIAGRAM)
        assert len(entry['revisions']) == 3, "original plus two edits expected"
        assert entry['revisions'][0]['origin'] == ORIGIN_ORIGINAL

        original_id = entry['revisions'][0]['id']
        restored = set_current_revision(
            message, 'mermaid', 0, original_id, fingerprint_source(FIRST_DIAGRAM)
        )
        assert restored['current'] == 0
        assert len(restored['revisions']) == 3, "restoring must not truncate the history"
        assert FIRST_DIAGRAM in resolve_message_content(message), "restore did not take effect"

        # Editing after a restore appends rather than branching, so the list stays a readable log.
        after = _edit(message, 0, 'graph RL\n  A --> B', FIRST_DIAGRAM)
        assert len(after['revisions']) == 4
        assert after['current'] == 3
        assert 'graph RL' in resolve_message_content(message)

        print("Restore test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_history_is_capped_but_keeps_the_original():
    """Pruning bounds the stored document without losing the version the model produced."""
    print("Testing revision pruning...")
    try:
        message = _new_message()
        for step in range(MAX_REVISIONS + 5):
            _edit(message, 0, f'graph TD\n  A --> B{step}', FIRST_DIAGRAM)

        entry = read_block_entry(message, 'mermaid', 0, fingerprint_source(FIRST_DIAGRAM))
        assert len(entry['revisions']) == MAX_REVISIONS, "the cap was not applied"
        assert entry['revisions'][0]['origin'] == ORIGIN_ORIGINAL, (
            "the original was pruned; restoring it would be impossible"
        )
        assert entry['revisions'][0]['source'] == FIRST_DIAGRAM
        assert entry['current'] == MAX_REVISIONS - 1, "current must follow the newest revision"

        original_id = entry['revisions'][0]['id']
        set_current_revision(
            message, 'mermaid', 0, original_id, fingerprint_source(FIRST_DIAGRAM)
        )
        assert FIRST_DIAGRAM in resolve_message_content(message)

        print("Pruning test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_stale_entry_is_ignored():
    """An entry whose fingerprint no longer matches never gets applied to another diagram."""
    print("Testing stale entries fail safe...")
    try:
        stale = {
            'content': MESSAGE_CONTENT,
            'metadata': {
                'block_revisions': {
                    'mermaid': {
                        '0': {
                            'source_hash': 'deadbeef',
                            'current': 1,
                            'revisions': [
                                {'id': 'a', 'source': 'graph TD\n  X --> Y'},
                                {'id': 'b', 'source': 'graph LR\n  WRONG --> DIAGRAM'},
                            ],
                            'chat': [],
                        }
                    }
                }
            },
        }
        resolved = resolve_message_content(stale)
        assert 'WRONG' not in resolved, "a stale entry was applied to a different diagram"
        assert resolved == MESSAGE_CONTENT, "content changed despite the fingerprint mismatch"

        assert read_block_entry(stale, 'mermaid', 0, fingerprint_source(FIRST_DIAGRAM)) is None

        print("Stale entry test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_moved_block_is_found_by_fingerprint():
    """When positions shift, the fingerprint still identifies the right diagram."""
    print("Testing recovery when block positions shift...")
    try:
        message = _new_message()
        _edit(message, 1, 'graph TD\n  C --> D\n  D --> F', SECOND_DIAGRAM)

        # The first diagram is removed, so the second one is now at position zero while its
        # stored entry is still filed under one. Position alone would find nothing.
        shortened = dict(message)
        shortened['content'] = MESSAGE_CONTENT.replace(
            f'```mermaid\n{FIRST_DIAGRAM}\n```\n\n', ''
        )

        resolved = resolve_message_content(shortened)
        assert 'D --> F' in resolved, (
            "the fingerprint fallback did not find the diagram after positions shifted"
        )

        print("Position-shift recovery test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ambiguous_duplicates_are_left_alone():
    """Two identical diagrams cannot be told apart, so neither is silently rewritten."""
    print("Testing ambiguous duplicate blocks...")
    try:
        duplicated = (
            f'```mermaid\n{FIRST_DIAGRAM}\n```\n\n'
            f'```mermaid\n{FIRST_DIAGRAM}\n```\n'
        )
        message = {'content': duplicated, 'metadata': {}}
        _edit(message, 0, 'graph LR\n  A --> B', FIRST_DIAGRAM)

        resolved = resolve_message_content(message)
        # Position zero matches its own fingerprint, so exactly one block is replaced and the
        # duplicate is left as it was.
        assert resolved.count('graph LR\n  A --> B') == 1
        assert resolved.count(FIRST_DIAGRAM) == 1

        print("Duplicate block test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_source_cannot_escape_its_fence():
    """A source containing a fence would inject markdown into the message, so it is refused."""
    print("Testing fence breakout is refused...")
    try:
        message = _new_message()
        for hostile in (
            'graph TD\n```\n\n# Injected heading',
            'graph TD\n~~~\n\nInjected',
            'graph TD\n   ````\n\nInjected',
        ):
            try:
                _edit(message, 0, hostile, FIRST_DIAGRAM)
                raise AssertionError(f"a fence breakout was accepted: {hostile!r}")
            except BlockRevisionError as exc:
                assert 'fence' in str(exc).lower()

        assert message['content'] == MESSAGE_CONTENT
        assert not message['metadata'].get('block_revisions')

        print("Fence breakout test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_mismatched_original_is_refused():
    """Seeding the history with content that is not the original would break restoring it."""
    print("Testing the seeded original is verified...")
    try:
        message = _new_message()
        try:
            apply_block_revision(
                message,
                'mermaid',
                0,
                'graph LR\n  A --> B',
                fingerprint_source(FIRST_DIAGRAM),
                original_source='graph TD\n  SOMETHING --> ELSE',
            )
            raise AssertionError("a mismatched original was accepted")
        except BlockRevisionError as exc:
            assert 'fingerprint' in str(exc).lower()

        try:
            apply_block_revision(
                message, 'mermaid', 0, 'graph LR\n  A --> B', fingerprint_source(FIRST_DIAGRAM)
            )
            raise AssertionError("an edit with no original was accepted")
        except BlockRevisionError:
            pass

        print("Original verification test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_concurrent_edit_is_reported():
    """Two people editing one diagram must not silently overwrite each other."""
    print("Testing the concurrency guard...")
    try:
        message = _new_message()
        _edit(message, 0, 'graph LR\n  A --> B', FIRST_DIAGRAM)

        try:
            _edit(
                message,
                0,
                'graph BT\n  A --> B',
                FIRST_DIAGRAM,
                expected_revision_count=1,
            )
            raise AssertionError("a stale write was accepted")
        except BlockRevisionConflictError:
            pass

        # Writing against what is actually stored succeeds.
        entry = _edit(
            message, 0, 'graph BT\n  A --> B', FIRST_DIAGRAM, expected_revision_count=2
        )
        assert len(entry['revisions']) == 3

        print("Concurrency guard test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_masks_are_applied_before_revisions_resolve():
    """Masking is by character offset into the stored content, so it has to run first."""
    print("Testing mask and revision ordering...")
    try:
        message = _new_message()
        _edit(message, 0, 'graph LR\n  A --> B\n  B --> E', FIRST_DIAGRAM)

        # A mask that removed some earlier prose leaves the diagram's own body untouched, so it
        # still resolves even though its position may have moved.
        masked_content = MESSAGE_CONTENT.replace('Here is a diagram.', '')
        resolved = resolve_block_sources_in_content(message, masked_content)
        assert 'B --> E' in resolved, "an edited diagram stopped resolving after unrelated masking"

        # A mask that cut into the diagram itself changes its fingerprint, so the revision is not
        # applied to content the reader deliberately removed.
        cut_content = MESSAGE_CONTENT.replace('  A --> B\n', '  A --> REDACTED\n', 1)
        cut_resolved = resolve_block_sources_in_content(message, cut_content)
        assert 'B --> E' not in cut_resolved, (
            "a revision was applied over a diagram whose body had been masked"
        )
        assert 'REDACTED' in cut_resolved

        print("Mask ordering test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_the_scoped_chat_is_stored_and_capped():
    """The sub-conversation lives with the block, which is what keeps it out of the thread."""
    print("Testing the scoped sub-conversation...")
    try:
        message = _new_message()
        _edit(message, 0, 'graph LR\n  A --> B', FIRST_DIAGRAM)
        source_hash = fingerprint_source(FIRST_DIAGRAM)

        append_block_chat_turn(message, 'mermaid', 0, 'user', 'make it left to right', source_hash)
        append_block_chat_turn(message, 'mermaid', 0, 'assistant', 'done', source_hash)

        entry = read_block_entry(message, 'mermaid', 0, source_hash)
        turns = read_block_chat(entry)
        assert [turn['role'] for turn in turns] == ['user', 'assistant']
        assert turns[0]['content'] == 'make it left to right'

        for index in range(40):
            append_block_chat_turn(message, 'mermaid', 0, 'user', f'turn {index}', source_hash)
        entry = read_block_entry(message, 'mermaid', 0, source_hash)
        assert len(entry['chat']) <= 20, "the transcript grew without bound"
        assert entry['chat'][-1]['content'] == 'turn 39', "the newest turn was dropped"

        # The transcript must never leak into the message content.
        assert 'make it left to right' not in resolve_message_content(message)

        print("Scoped chat test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_removing_an_entry_clears_the_metadata():
    """Clearing a block's history leaves no empty scaffolding behind on the document."""
    print("Testing entry removal...")
    try:
        message = _new_message()
        _edit(message, 0, 'graph LR\n  A --> B', FIRST_DIAGRAM)
        assert message['metadata'].get('block_revisions')

        remove_block_entry(message, 'mermaid', 0)
        assert 'block_revisions' not in message['metadata'], "an empty map was left behind"
        assert resolve_message_content(message) == MESSAGE_CONTENT

        print("Entry removal test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_current_source_falls_back_to_the_original():
    """Reading the current source works before any edit and after restoring the original."""
    print("Testing current source resolution...")
    try:
        message = _new_message()
        entry = _edit(message, 0, 'graph LR\n  A --> B', FIRST_DIAGRAM)
        assert current_block_source(entry) == 'graph LR\n  A --> B'

        set_current_revision(
            message, 'mermaid', 0, entry['revisions'][0]['id'], fingerprint_source(FIRST_DIAGRAM)
        )
        entry = read_block_entry(message, 'mermaid', 0, fingerprint_source(FIRST_DIAGRAM))
        assert current_block_source(entry) == FIRST_DIAGRAM
        assert current_block_source(None, fallback='fallback') == 'fallback'

        print("Current source test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_invalid_requests_are_refused():
    """Bad addressing is refused rather than stored against whatever it happens to hit."""
    print("Testing request validation...")
    try:
        message = _new_message()
        cases = [
            ('simplechart', 0, 'unsupported kind'),
            ('mermaid', -1, 'negative index'),
            ('mermaid', 10_000, 'index out of range'),
            ('mermaid', True, 'boolean index'),
        ]
        for kind, index, label in cases:
            try:
                apply_block_revision(
                    message,
                    kind,
                    index,
                    'graph LR\n  A --> B',
                    fingerprint_source(FIRST_DIAGRAM),
                    original_source=FIRST_DIAGRAM,
                )
                raise AssertionError(f"{label} was accepted")
            except BlockRevisionError:
                pass

        # An empty source is not an edit, and a missing hash cannot address a block.
        for bad_source in ('', '   \n  '):
            try:
                _edit(message, 0, bad_source, FIRST_DIAGRAM)
                raise AssertionError("an empty source was accepted")
            except BlockRevisionError:
                pass

        try:
            apply_block_revision(
                message, 'mermaid', 0, 'graph LR\n  A --> B', '', original_source=FIRST_DIAGRAM
            )
            raise AssertionError("a missing source hash was accepted")
        except BlockRevisionError:
            pass

        assert not message['metadata'].get('block_revisions')

        print("Validation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_version_is_at_least_implementation_version():
    """The feature must not appear in a build older than the one that introduced it."""
    print("Testing application version...")
    try:
        assert_app_version_at_least("0.261.043")
        print("Application version test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_fingerprint_matches_the_client,
        test_fences_are_scanned_and_numbered,
        test_an_edit_is_stored_without_rewriting_the_message,
        test_an_indented_fence_keeps_its_indentation,
        test_restoring_a_revision_moves_a_pointer,
        test_history_is_capped_but_keeps_the_original,
        test_a_stale_entry_is_ignored,
        test_a_moved_block_is_found_by_fingerprint,
        test_ambiguous_duplicates_are_left_alone,
        test_a_source_cannot_escape_its_fence,
        test_a_mismatched_original_is_refused,
        test_a_concurrent_edit_is_reported,
        test_masks_are_applied_before_revisions_resolve,
        test_the_scoped_chat_is_stored_and_capped,
        test_removing_an_entry_clears_the_metadata,
        test_current_source_falls_back_to_the_original,
        test_invalid_requests_are_refused,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
