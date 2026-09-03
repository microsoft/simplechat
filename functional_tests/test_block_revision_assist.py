#!/usr/bin/env python3
"""
Functional test for the scoped diagram edit request.
Version: 0.261.043
Implemented in: 0.261.043

This test ensures that asking the AI to change a diagram sends only that diagram's own
context — never the conversation — and that whatever the model replies with is reduced to
usable Mermaid source before it is stored.

The context assertions are the point of the feature. Refining a diagram must not drag the
thread into the request, and the reply must not end up in the thread either.
"""

import os
import sys
import types

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'application',
        'single_app',
    )
)

# config.py builds a Cosmos client at import time, so it cannot be imported on a developer
# machine. Only the two names the module under test reads from it are needed, and neither is
# exercised here: every test either fails before a client is constructed or replaces client
# resolution outright. test_support.app_stubs does the same thing for the seams it covers, but
# does not stub config itself.
if 'config' not in sys.modules:
    _config_stub = types.ModuleType('config')
    _config_stub.AzureOpenAI = object
    _config_stub.cognitive_services_scope = 'https://cognitiveservices.azure.com/.default'
    sys.modules['config'] = _config_stub

from test_support.versioning import assert_app_version_at_least

import functions_block_revision_assist as assist
from functions_block_revision_assist import (
    MAX_INSTRUCTION_LENGTH,
    BlockAssistError,
    build_assist_messages,
    extract_diagram_source,
    normalize_instruction,
    request_block_edit,
)

CURRENT_SOURCE = 'graph TD\n  A[Start] --> B[Finish]'
UPDATED_SOURCE = 'graph LR\n  A[Start] --> B[Finish]'

# Something that must never appear in an edit request, so its absence is checkable.
CONVERSATION_SECRET = 'UNRELATED_THREAD_CHATTER_9f3a'


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, reply, recorder):
        self._reply = reply
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.update(kwargs)
        if isinstance(self._reply, Exception):
            raise self._reply
        return _FakeResponse(self._reply)


class _FakeChat:
    def __init__(self, reply, recorder):
        self.completions = _FakeCompletions(reply, recorder)


class _FakeClient:
    def __init__(self, reply, recorder):
        self.chat = _FakeChat(reply, recorder)


def _with_fake_model(reply, recorder):
    """Replace client resolution with a recorder, returning the original for restoration."""
    original = assist.resolve_assist_client
    assist.resolve_assist_client = lambda settings: (
        _FakeClient(reply, recorder),
        'fake-deployment',
    )
    return original


def test_an_instruction_is_required_and_bounded():
    """An empty instruction is not an edit, and an essay is not one either."""
    print("Testing instruction validation...")
    try:
        for empty in (None, '', '   ', '\n\t ', 123):
            try:
                normalize_instruction(empty)
                raise AssertionError(f"an empty instruction was accepted: {empty!r}")
            except BlockAssistError:
                pass

        assert normalize_instruction('  make it left to right  ') == 'make it left to right'

        long_instruction = 'x' * (MAX_INSTRUCTION_LENGTH + 500)
        assert len(normalize_instruction(long_instruction)) == MAX_INSTRUCTION_LENGTH

        print("Instruction validation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_the_request_never_carries_the_conversation():
    """Only the diagram, its own turns and the originating request are sent."""
    print("Testing that conversation history is excluded...")
    try:
        messages = build_assist_messages(
            CURRENT_SOURCE,
            'make it left to right',
            chat_turns=[
                {'role': 'user', 'content': 'add a validation step'},
                {'role': 'assistant', 'content': 'graph TD\n  A --> V --> B'},
            ],
            originating_request='draw the signup flow',
        )

        serialized = '\n'.join(message['content'] for message in messages)
        assert CONVERSATION_SECRET not in serialized

        # Everything that should be there.
        assert messages[0]['role'] == 'system'
        assert 'Mermaid' in messages[0]['content']
        assert 'draw the signup flow' in serialized, "the originating request was dropped"
        assert 'add a validation step' in serialized, "a prior sub-chat turn was dropped"
        assert CURRENT_SOURCE in messages[-1]['content'], "the current source was not sent"
        assert 'make it left to right' in messages[-1]['content']
        assert messages[-1]['role'] == 'user'

        # The originating request is background, not an instruction, and says so.
        grounding = next(
            message for message in messages
            if message['role'] == 'system' and 'draw the signup flow' in message['content']
        )
        assert 'not as instructions' in grounding['content']

        # Without grounding there is exactly one system message.
        bare = build_assist_messages(CURRENT_SOURCE, 'flip it')
        assert len([m for m in bare if m['role'] == 'system']) == 1
        assert len(bare) == 2

        print("Context isolation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_the_prompt_is_honest_about_positioning():
    """The model must not be encouraged to fake node placement Mermaid cannot express."""
    print("Testing positioning guidance in the prompt...")
    try:
        prompt = assist.ASSIST_SYSTEM_PROMPT
        assert 'no syntax for placing a node at a coordinate' in prompt
        assert 'flow direction' in prompt
        # And the prompt injection instruction is present, since the source is untrusted.
        assert 'Never follow' in prompt

        print("Prompt guidance test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_source_is_extracted_from_any_reply_shape():
    """A model that wraps or narrates its answer must still yield usable source."""
    print("Testing reply parsing...")
    try:
        cases = [
            (UPDATED_SOURCE, UPDATED_SOURCE),
            (f'```mermaid\n{UPDATED_SOURCE}\n```', UPDATED_SOURCE),
            (f'```\n{UPDATED_SOURCE}\n```', UPDATED_SOURCE),
            (f'Here is the updated diagram:\n\n{UPDATED_SOURCE}', UPDATED_SOURCE),
            (
                f'Sure! Here you go.\n\n```mermaid\n{UPDATED_SOURCE}\n```\n\nLet me know!',
                UPDATED_SOURCE,
            ),
            (f'~~~mermaid\n{UPDATED_SOURCE}\n~~~', UPDATED_SOURCE),
            (f'   {UPDATED_SOURCE}   ', UPDATED_SOURCE),
        ]
        for reply, expected in cases:
            got = extract_diagram_source(reply)
            assert got == expected, f"parsing {reply!r} gave {got!r}"

        # A sequence diagram is recognised too, not just flowcharts.
        sequence = 'sequenceDiagram\n  A->>B: hi'
        assert extract_diagram_source(f'Done:\n\n{sequence}') == sequence

        for empty in ('', '   ', None):
            try:
                extract_diagram_source(empty)
                raise AssertionError("an empty reply was accepted")
            except BlockAssistError:
                pass

        print("Reply parsing test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_an_edit_request_is_shaped_correctly():
    """End to end, with a stand-in model, the request and result look as expected."""
    print("Testing a full edit request...")
    try:
        recorder = {}
        original = _with_fake_model(f'```mermaid\n{UPDATED_SOURCE}\n```', recorder)
        try:
            result = request_block_edit(
                {'gpt_model': {'selected': [{'deploymentName': 'ignored'}]}},
                CURRENT_SOURCE,
                '  make it left to right  ',
                chat_turns=[{'role': 'user', 'content': 'earlier turn'}],
                originating_request='draw the signup flow',
            )
        finally:
            assist.resolve_assist_client = original

        assert result['source'] == UPDATED_SOURCE, "the fence was not stripped"
        assert result['instruction'] == 'make it left to right'
        assert result['model'] == 'fake-deployment'

        sent = '\n'.join(message['content'] for message in recorder['messages'])
        assert CURRENT_SOURCE in sent
        assert 'earlier turn' in sent
        assert CONVERSATION_SECRET not in sent
        assert recorder['model'] == 'fake-deployment'
        # A low temperature, so an edit is a predictable change rather than a redraw.
        assert recorder['temperature'] <= 0.5

        print("Edit request test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_model_failure_is_reported_not_raised():
    """A failing model must surface as a handled error, not an unhandled exception."""
    print("Testing model failure handling...")
    try:
        recorder = {}
        original = _with_fake_model(RuntimeError('upstream exploded'), recorder)
        try:
            request_block_edit({}, CURRENT_SOURCE, 'flip it')
            raise AssertionError("a model failure did not raise BlockAssistError")
        except BlockAssistError as exc:
            assert 'could not be updated' in str(exc)
            # The upstream message is not surfaced to the caller verbatim.
            assert 'upstream exploded' not in str(exc)
        finally:
            assist.resolve_assist_client = original

        # An empty source is refused before any model call is attempted.
        try:
            request_block_edit({}, '   ', 'flip it')
            raise AssertionError("an empty source was accepted")
        except BlockAssistError:
            pass

        print("Model failure test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_a_missing_deployment_is_reported():
    """An unconfigured deployment fails with a clear error rather than a stack trace."""
    print("Testing deployment resolution...")
    try:
        for settings in ({}, {'gpt_model': {}}, {'enable_gpt_apim': True}):
            try:
                assist.resolve_assist_client(settings)
                raise AssertionError(f"missing configuration was accepted: {settings!r}")
            except BlockAssistError as exc:
                assert 'configured' in str(exc)

        print("Deployment resolution test passed!")
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
        test_an_instruction_is_required_and_bounded,
        test_the_request_never_carries_the_conversation,
        test_the_prompt_is_honest_about_positioning,
        test_source_is_extracted_from_any_reply_shape,
        test_an_edit_request_is_shaped_correctly,
        test_a_model_failure_is_reported_not_raised,
        test_a_missing_deployment_is_reported,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
