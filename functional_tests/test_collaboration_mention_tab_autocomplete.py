# test_collaboration_mention_tab_autocomplete.py
"""
Functional test for Tab autocomplete in the collaborative @ mention menu.
Version: 0.260.005
Implemented in: 0.260.005

This test ensures the chat composer's @ mention menu accepts the highlighted
suggestion when the user presses Tab, that Shift+Tab and the empty-results state
still fall through to normal browser focus movement, that Enter keeps its
existing behavior, and that the menu exposes proper listbox semantics so
assistive technology can announce the highlighted suggestion.

Refs: https://github.com/microsoft/simplechat/issues/1299
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_COLLABORATION_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-collaboration.js'
CHAT_MESSAGES_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-messages.js'
CHATS_TEMPLATE_FILE = REPO_ROOT / 'application' / 'single_app' / 'templates' / 'chats.html'


def read_text(path):
    return path.read_text(encoding='utf-8')


def extract_function_source(source, function_name):
    """Return the source text of a top-level function declaration."""
    marker = f'function {function_name}('
    start = source.find(marker)
    assert start != -1, f'Expected to find function {function_name} in the module source.'

    paren_depth = 0
    body_start = -1
    for index in range(start + len(marker) - 1, len(source)):
        char = source[index]
        if char == '(':
            paren_depth += 1
        elif char == ')':
            paren_depth -= 1
            if paren_depth == 0:
                body_start = source.find('{', index)
                break

    assert body_start != -1, f'Could not locate the body of {function_name}.'

    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]

    raise AssertionError(f'Unbalanced braces while extracting {function_name}.')


def test_mention_menu_accepts_tab():
    """Tab accepts the highlighted suggestion, Shift+Tab does not."""
    print('Testing Tab autocomplete in the collaborative mention menu...')
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    keydown_source = extract_function_source(collaboration_source, 'handleComposerKeydown')

    assert "event.key === 'Tab'" in keydown_source, \
        'handleComposerKeydown must handle the Tab key so users can complete a mention.'
    assert '!event.shiftKey' in keydown_source, \
        'Shift+Tab must fall through so it keeps moving focus backwards.'
    assert 'hasActiveMentionSuggestion()' in keydown_source, \
        'Tab must only be captured when there is a highlighted suggestion to accept.'
    assert 'selectActiveMentionSuggestion()' in keydown_source, \
        'Tab and Enter must share the same selection path.'

    tab_branch_start = keydown_source.find("event.key === 'Tab'")
    tab_branch = keydown_source[tab_branch_start:]
    guard_index = tab_branch.find('hasActiveMentionSuggestion()')
    prevent_index = tab_branch.find('event.preventDefault()')
    assert -1 < guard_index < prevent_index, \
        'The Tab branch must bail out before calling preventDefault when nothing is highlighted.'

    print('Test passed!')
    return True


def test_enter_and_tab_share_one_selection_path():
    """Enter keeps working and reuses the shared selection helper."""
    print('Testing shared mention selection helper...')
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    keydown_source = extract_function_source(collaboration_source, 'handleComposerKeydown')
    select_source = extract_function_source(collaboration_source, 'selectActiveMentionSuggestion')

    assert "event.key === 'Enter' && activeMentionState.activeIndex >= 0" in keydown_source, \
        'Enter must keep its existing guard so unrelated Enter presses still send the message.'

    assert "collaborator.action === 'tag'" in select_source, \
        'The shared helper must still tag existing participants.'
    assert "collaborator.action === 'ai_tag'" in select_source, \
        'The shared helper must still route agent and model invocation targets.'
    assert 'openParticipantConfirmation(collaborator' in select_source, \
        'The shared helper must still open the invite confirmation for new collaborators.'
    assert "source: 'mention'" in select_source, \
        'The invite confirmation must still record the mention source.'

    # The old inline Enter implementation must be gone so the two keys cannot drift apart.
    assert 'insertParticipantMention(collaborator, activeMentionState)' not in keydown_source, \
        'handleComposerKeydown must delegate selection instead of inlining it.'

    print('Test passed!')
    return True


def test_mention_menu_exposes_listbox_semantics():
    """The mention menu announces which suggestion is highlighted."""
    print('Testing mention menu listbox semantics...')
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    template_source = read_text(CHATS_TEMPLATE_FILE)
    render_source = extract_function_source(collaboration_source, 'renderMentionMenu')
    update_source = extract_function_source(collaboration_source, 'updateMentionMenuActiveItem')
    hide_source = extract_function_source(collaboration_source, 'hideMentionMenu')
    apply_source = extract_function_source(collaboration_source, 'applyMentionComboboxState')
    clear_source = extract_function_source(collaboration_source, 'clearMentionComboboxState')

    assert 'role="listbox"' in template_source, \
        'The mention menu container is expected to remain a listbox.'
    assert 'id="collaboration-mention-menu"' in template_source, \
        'The mention menu needs a stable id so aria-controls can reference it.'

    assert "setAttribute('role', 'option')" in render_source, \
        'Every mention suggestion must be exposed as a listbox option.'
    assert "setAttribute('aria-selected'" in render_source, \
        'Mention suggestions must report their selected state.'
    assert 'MENTION_OPTION_ID_PREFIX' in render_source, \
        'Mention suggestions need stable ids so aria-activedescendant can reference them.'
    assert 'role="option" aria-disabled="true"' in render_source, \
        'The empty-results row must stay a valid, non-selectable listbox child.'

    assert "item.setAttribute('aria-selected', isActive ? 'true' : 'false')" in update_source, \
        'Keyboard navigation must keep aria-selected in sync with the highlighted item.'
    assert 'applyMentionComboboxState(activeItemId)' in update_source, \
        'The composer must point at the highlighted option while the menu is open.'
    assert 'clearMentionComboboxState()' in update_source, \
        'The composer must drop the option reference when nothing is highlighted.'
    assert 'scrollActiveIntoView' in update_source, \
        'The highlighted option must be scrolled into view inside the height-capped menu.'

    # ARIA 1.2 only resolves aria-activedescendant from a textbox when the referenced
    # option lives inside the element named by aria-controls. The mention menu is a
    # sibling of #user-input, so aria-controls is required for the reference to work.
    assert "userInput.setAttribute('aria-controls', mentionMenu.id)" in apply_source, \
        'aria-activedescendant on the composer is only valid alongside aria-controls.'
    assert "userInput.setAttribute('aria-autocomplete', 'list')" in apply_source, \
        'The composer must advertise its list popup while the mention menu is open.'
    assert "userInput.setAttribute('aria-activedescendant', activeItemId)" in apply_source, \
        'The composer must reference the highlighted option.'

    for attribute in ('aria-activedescendant', 'aria-autocomplete', 'aria-controls'):
        assert f"userInput.removeAttribute('{attribute}')" in clear_source, \
            f'Closing the mention menu must drop the stale {attribute} reference.'

    assert 'clearMentionComboboxState()' in hide_source, \
        'Closing the mention menu must reset the composer combobox state.'
    assert 'clearMentionComboboxState()' in render_source, \
        'The empty-results state must reset the composer combobox state.'

    print('Test passed!')
    return True


def test_composer_keydown_is_wired_to_the_chat_input():
    """The chat composer still delegates keydown handling to collaboration."""
    print('Testing composer keydown wiring...')
    messages_source = read_text(CHAT_MESSAGES_FILE)

    assert 'window.chatCollaboration?.handleComposerKeydown?.(e)' in messages_source, \
        'The chat composer must delegate keydown handling to the collaboration module.'

    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    assert 'handleComposerKeydown,' in collaboration_source, \
        'handleComposerKeydown must remain exported on window.chatCollaboration.'

    print('Test passed!')
    return True


def test_version_is_at_least_implementation_version():
    """The fix ships in 0.260.005 or later."""
    print('Testing application version...')
    assert_app_version_at_least(
        '0.260.005',
        reason='Tab autocomplete for collaborative @ mentions shipped in 0.260.005.',
    )
    print('Test passed!')
    return True


if __name__ == '__main__':
    tests = [
        test_mention_menu_accepts_tab,
        test_enter_and_tab_share_one_selection_path,
        test_mention_menu_exposes_listbox_semantics,
        test_composer_keydown_is_wired_to_the_chat_input,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            results.append(test())
        except Exception as error:
            print(f'Test failed: {error}')
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
