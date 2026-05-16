# test_chat_prompt_desktop_toolbar_position.py
"""
Functional test for desktop chat prompt selector placement.
Version: 0.241.030
Implemented in: 0.241.025

This test ensures the prompt selector is anchored in the larger desktop toolbar
surface to the left of the model or agent selector and modifier buttons, while
the mobile-only toolbar controls row remains reserved for the mobile tools
toggle.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHATS_TEMPLATE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'templates',
    'chats.html',
)
CHAT_CSS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'css',
    'chats.css',
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_desktop_prompt_slot_precedes_model_and_modifier_controls():
    """Verify the prompt selector is in the desktop tools surface before model controls."""
    print('Testing desktop prompt selector toolbar order...')

    content = read_file(CHATS_TEMPLATE)

    tools_start = content.index('id="chat-toolbar-tools-surface"')
    controls_start = content.index('<div class="chat-toolbar-controls">', tools_start)
    tools_markup = content[tools_start:controls_start]
    controls_end = content.index('<div id="chat-mobile-tools-panel"', controls_start)
    controls_markup = content[controls_start:controls_end]

    selectors_index = tools_markup.index('id="chat-toolbar-desktop-selectors-slot"')
    prompt_index = tools_markup.index('id="prompt-selection-container"')
    primary_index = tools_markup.index('id="chat-toolbar-desktop-primary-slot"')
    model_index = tools_markup.index('id="model-select-container"')
    agent_index = tools_markup.index('id="agent-select-container"')
    toggles_index = tools_markup.index('class="chat-toolbar-toggles"')

    assert selectors_index < primary_index < toggles_index, (
        'Expected desktop prompt slot, then model/agent slot, then modifier toggles.'
    )
    assert selectors_index < prompt_index < primary_index, 'Expected prompt selector before the model/agent slot.'
    assert primary_index < model_index < toggles_index, 'Expected model selector before modifier toggles.'
    assert primary_index < agent_index < toggles_index, 'Expected agent selector before modifier toggles.'
    assert 'id="prompt-selection-container"' not in controls_markup, (
        'Expected prompt selector outside chat-toolbar-controls.'
    )
    assert 'id="model-select-container"' not in controls_markup, (
        'Expected model selector outside chat-toolbar-controls.'
    )
    assert 'id="agent-select-container"' not in controls_markup, (
        'Expected agent selector outside chat-toolbar-controls.'
    )
    assert 'id="chat-mobile-tools-toggle"' in controls_markup, (
        'Expected chat-toolbar-controls to keep the mobile tools toggle.'
    )

    print('Desktop prompt selector toolbar order passed')


def test_desktop_toolbar_css_keeps_controls_mobile_only():
    """Verify CSS supports desktop prompt/model placement and mobile controls."""
    print('Testing desktop toolbar CSS placement rules...')

    content = read_file(CHAT_CSS_FILE)

    required_snippets = [
        '#chat-toolbar-desktop-primary-slot,',
        '.chat-toolbar-tools-surface {',
        'align-items: center;',
        '.chat-toolbar-action-rail {\n    flex: 1 1 100%;',
        '@media (min-width: 992px) {\n  .chat-toolbar-controls {\n    display: none;',
        '@media (max-width: 991.98px) {',
        '.chat-toolbar-controls {\n    display: flex;',
        '.chat-toolbar-mobile-selectors-slot .chat-toolbar-selector,',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f'Missing desktop toolbar CSS rules: {missing}'

    print('Desktop toolbar CSS placement rules passed')


def test_version_bumped_for_prompt_toolbar_position_fix():
    """Verify config version was bumped for the prompt toolbar placement fix."""
    print('Testing config version bump...')

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.241.030"' in config_content, 'Expected config.py version 0.241.030'

    print('Config version bump passed')


if __name__ == '__main__':
    tests = [
        test_desktop_prompt_slot_precedes_model_and_modifier_controls,
        test_desktop_toolbar_css_keeps_controls_mobile_only,
        test_version_bumped_for_prompt_toolbar_position_fix,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'Test failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)