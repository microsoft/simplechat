# test_chat_optional_feature_initializers.py
"""
Functional test for optional chat feature initializers.
Version: 0.241.152
Implemented in: 0.241.145

This test ensures that optional chat agent and speech-input modules exit quietly
when their feature controls are intentionally absent from the chat page.
"""

import os
import sys
import traceback


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT_AGENTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-agents.js',
)
CHAT_SPEECH_INPUT_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-speech-input.js',
)


def read_file(path):
    """Read a repository file as UTF-8 text."""
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_agent_initializer_skips_missing_controls():
    """Verify agent initialization treats missing controls as a disabled feature."""
    print('Testing optional agent initializer guard...')

    try:
        content = read_file(CHAT_AGENTS_FILE)
        required_snippets = [
            'function hasAgentInteractionControls() {',
            'return Boolean(enableAgentsBtn && agentSelectContainer && agentSelect);',
            'if (!hasAgentInteractionControls()) {\n        return;\n    }\n\n    initializeAgentSelector();',
            'export async function populateAgentDropdown() {\n    if (!hasAgentInteractionControls()) {',
        ]
        forbidden_snippets = [
            'Agent Init Error: enable-agents-btn not found.',
            'Agent Init Error: agent-select-container not found.',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        present = [snippet for snippet in forbidden_snippets if snippet in content]
        assert not missing, f'Missing agent initializer guard snippets: {missing}'
        assert not present, f'Agent initializer still emits disabled-feature errors: {present}'

        print('Agent initializer guard passed')
        return True
    except Exception as exc:
        print(f'Test failed: {exc}')
        traceback.print_exc()
        return False


def test_speech_initializer_skips_disabled_setting():
    """Verify speech initialization exits quietly when speech input is disabled."""
    print('Testing optional speech initializer guard...')

    try:
        content = read_file(CHAT_SPEECH_INPUT_FILE)
        required_snippets = [
            'if (!window.appSettings?.enable_speech_to_text_input) {\n        return;\n    }',
            "const speechBtn = document.getElementById('speech-input-btn');",
            'if (!speechBtn) {\n        return;\n    }',
        ]
        forbidden_snippets = [
            'Speech input button not found in DOM',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        present = [snippet for snippet in forbidden_snippets if snippet in content]
        assert not missing, f'Missing speech initializer guard snippets: {missing}'
        assert not present, f'Speech initializer still warns for disabled-feature markup: {present}'

        print('Speech initializer guard passed')
        return True
    except Exception as exc:
        print(f'Test failed: {exc}')
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_agent_initializer_skips_missing_controls,
        test_speech_initializer_skips_disabled_setting,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
