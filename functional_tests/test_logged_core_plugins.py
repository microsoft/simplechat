# test_logged_core_plugins.py
"""
Functional test for logged core Semantic Kernel plugins.
Version: 0.261.380
Implemented in: 0.239.153

This test ensures that the SimpleChat subclasses for Semantic Kernel core plugins
emit plugin invocation logs for inherited and custom methods and that invocation
callbacks can be converted into thought records for both success and failure cases.
"""

from pathlib import Path
import subprocess
import sys
import types


def create_invocation(plugin_name, function_name, parameters, result=None, success=True, error_message=None, duration_ms=1234):
    """Create a lightweight invocation object for formatter tests."""
    return types.SimpleNamespace(
        plugin_name=plugin_name,
        function_name=function_name,
        parameters=parameters,
        result=result,
        success=success,
        error_message=error_message,
        duration_ms=duration_ms,
    )


class FakeThoughtTracker:
    """Capture thought writes in memory for assertions."""

    def __init__(self):
        self.events = []

    def add_thought(self, step_type, content, detail=None, activity=None):
        self.events.append({
            'step_type': step_type,
            'content': content,
            'detail': detail,
            'activity': activity,
        })


def test_logged_core_plugins():
    """Validate logged core plugin subclasses and thought callback mapping."""
    completed = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--probe"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _logged_core_plugins_probe(loop):
    """Imports are deferred until the fresh-process offline bootstrap is active."""
    from semantic_kernel_plugins.math_plugin import MathPlugin
    from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
    from semantic_kernel_plugins.plugin_invocation_thoughts import (
        format_plugin_invocation_start_thought,
        format_plugin_invocation_thought,
        register_plugin_invocation_thought_callback,
    )
    from semantic_kernel_plugins.text_plugin import TextPlugin
    from semantic_kernel_plugins.time_plugin import TimePlugin
    from semantic_kernel_plugins.wait_plugin import WaitPlugin

    plugin_logger = get_plugin_logger()
    plugin_logger.clear_history()
    plugin_logger.deregister_callbacks('None:None')

    thought_tracker = FakeThoughtTracker()
    callback_key = register_plugin_invocation_thought_callback(
        plugin_logger,
        thought_tracker,
        None,
        None,
        actor_label='Kernel'
    )

    math_plugin = MathPlugin()
    text_plugin = TextPlugin()
    time_plugin = TimePlugin()
    wait_plugin = WaitPlugin()

    print('Testing logged core plugin invocations...')
    addition = math_plugin.add('2', '3')
    multiplication = math_plugin.multiply(4, 5)
    trimmed = text_plugin.trim('  hello  ')
    date = time_plugin.date()
    assert addition == '5'
    assert multiplication == '20'
    assert trimmed == 'hello'
    assert isinstance(date, str)
    loop.run_until_complete(wait_plugin.wait('0'))

    try:
        math_plugin.divide('1', '0')
    except ValueError:
        print('Captured expected divide-by-zero failure')
    else:
        raise AssertionError('Expected divide-by-zero failure was not raised')

    plugin_logger.deregister_callbacks(callback_key)

    recent_invocations = plugin_logger.get_recent_invocations(10)
    recent_names = [f"{inv.plugin_name}.{inv.function_name}" for inv in recent_invocations]
    print(f'Recent invocations: {recent_names}')

    assert 'MathPlugin.Add' in recent_names
    assert 'MathPlugin.Multiply' in recent_names
    assert 'TextPlugin.trim' in recent_names
    assert 'TimePlugin.date' in recent_names
    assert 'WaitPlugin.wait' in recent_names
    assert 'MathPlugin.Divide' in recent_names

    divide_failure = next(inv for inv in recent_invocations if inv.plugin_name == 'MathPlugin' and inv.function_name == 'Divide')
    assert divide_failure.success is False
    assert divide_failure.error_message is not None
    assert 'divide by zero' in divide_failure.error_message.lower()

    thought_contents = [event['content'] for event in thought_tracker.events]
    print(f'Thought events: {thought_contents}')

    assert any('Invoking MathPlugin.Add' in content for content in thought_contents)
    assert any('Invoking WaitPlugin.wait' in content for content in thought_contents)
    assert any('Kernel performed math: 2 + 3 = 5' in content for content in thought_contents)
    assert any('Kernel invoked wait for 0 seconds' in content for content in thought_contents)
    assert any('Kernel performed math: 1 / 0' in content for content in thought_contents)
    assert any(
        event['detail'] and 'error=' in event['detail']
        for event in thought_tracker.events
        if 'Kernel performed math: 1 / 0' in event['content']
    )

    generic_thought = format_plugin_invocation_thought(
        create_invocation(
            'OpenApiPlugin',
            'topNews',
            {'query': 'latest space weather', 'limit': 5},
            result='ok',
            duration_ms=88,
        ),
        actor_label='Agent'
    )
    print(f"Generic thought payload: {generic_thought}")
    assert 'Agent executed OpenApiPlugin.topNews' in generic_thought['content']
    assert 'query=latest space weather' in generic_thought['content'] or 'query=latest space weat...' in generic_thought['content']

    start_thought = format_plugin_invocation_start_thought(
        create_invocation(
            'WaitPlugin',
            'wait',
            {'input': 30},
        )
    )
    print(f"Start thought payload: {start_thought}")
    assert start_thought['content'] == 'Invoking WaitPlugin.wait'
    assert 'input=30' in start_thought['detail']

    print('All logged core plugin checks passed')
    return True


if __name__ == '__main__':
    if sys.argv[1:] == ['--probe']:
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / 'functional_tests'))
        sys.path.insert(0, str(root / 'application' / 'single_app'))
        from test_support.offline_bootstrap import offline_app_imports

        with offline_app_imports() as offline:
            _logged_core_plugins_probe(offline.loop)
    else:
        test_logged_core_plugins()