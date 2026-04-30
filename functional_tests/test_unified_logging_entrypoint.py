# test_unified_logging_entrypoint.py
"""
Functional test for unified logging entry point.
Version: 0.239.189
Implemented in: 0.239.189

This test ensures that debug-only logging can be routed through log_event
while the legacy functions_debug compatibility shim continues to work.
"""

import importlib
import io
import os
import sys
import types
from contextlib import redirect_stdout


APP_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..',
    'application',
    'single_app',
)

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


def _install_logging_stubs(debug_enabled):
    saved_modules = {
        name: sys.modules.get(name)
        for name in [
            'azure',
            'azure.monitor',
            'azure.monitor.opentelemetry',
            'app_settings_cache',
            'functions_settings',
            'functions_appinsights',
            'functions_debug',
        ]
    }

    azure_module = types.ModuleType('azure')
    azure_monitor_module = types.ModuleType('azure.monitor')
    azure_monitor_otel_module = types.ModuleType('azure.monitor.opentelemetry')
    azure_monitor_otel_module.configure_azure_monitor = lambda **kwargs: None

    app_settings_cache_module = types.ModuleType('app_settings_cache')
    app_settings_cache_module.get_settings_cache = lambda: {
        'enable_debug_logging': debug_enabled,
    }

    functions_settings_module = types.ModuleType('functions_settings')
    functions_settings_module.get_settings = lambda: {
        'enable_debug_logging': debug_enabled,
    }

    sys.modules['azure'] = azure_module
    sys.modules['azure.monitor'] = azure_monitor_module
    sys.modules['azure.monitor.opentelemetry'] = azure_monitor_otel_module
    sys.modules['app_settings_cache'] = app_settings_cache_module
    sys.modules['functions_settings'] = functions_settings_module
    sys.modules.pop('functions_appinsights', None)
    sys.modules.pop('functions_debug', None)

    return saved_modules


def _restore_modules(saved_modules):
    for name, module in saved_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def test_log_event_debug_only_path():
    """Verify log_event can act as the sole debug-only entry point."""
    print("🔍 Testing log_event debug-only mode...")
    saved_modules = _install_logging_stubs(debug_enabled=True)

    try:
        functions_appinsights = importlib.import_module('functions_appinsights')
        captured_output = io.StringIO()
        with redirect_stdout(captured_output):
            functions_appinsights.log_event(
                'Unified debug %s',
                extra={'step': 1},
                debug_only=True,
                category='TRACE',
                flush=True,
                message_args=('trace',),
            )

        output = captured_output.getvalue()
        if '[DEBUG] [TRACE]: Unified debug trace (step=1)' not in output:
            print(f"❌ Unexpected debug-only output: {output!r}")
            return False

        if '[Log]' in output:
            print(f"❌ Debug-only path should not emit structured log output: {output!r}")
            return False

        print('✅ log_event debug-only mode verified')
        return True
    except Exception as exc:
        print(f"❌ log_event debug-only mode failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        _restore_modules(saved_modules)


def test_functions_debug_compatibility_shim():
    """Verify the legacy functions_debug API still delegates correctly."""
    print("🔍 Testing functions_debug compatibility shim...")
    saved_modules = _install_logging_stubs(debug_enabled=True)

    try:
        functions_debug = importlib.import_module('functions_debug')
        captured_output = io.StringIO()
        with redirect_stdout(captured_output):
            functions_debug.debug_print('Legacy %s', 'shim')

        output = captured_output.getvalue()
        if '[DEBUG] [INFO]: Legacy shim' not in output:
            print(f"❌ Unexpected shim output: {output!r}")
            return False

        if functions_debug.is_debug_enabled() is not True:
            print('❌ Compatibility shim did not report debug enabled state correctly')
            return False

        print('✅ functions_debug compatibility shim verified')
        return True
    except Exception as exc:
        print(f"❌ functions_debug compatibility shim failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        _restore_modules(saved_modules)


def test_debug_disabled_suppresses_debug_only_output():
    """Verify debug-only logging stays silent when debug logging is disabled."""
    print("🔍 Testing debug-only suppression when disabled...")
    saved_modules = _install_logging_stubs(debug_enabled=False)

    try:
        functions_appinsights = importlib.import_module('functions_appinsights')
        captured_output = io.StringIO()
        with redirect_stdout(captured_output):
            functions_appinsights.log_event(
                'Suppressed debug event',
                debug_only=True,
            )

        output = captured_output.getvalue()
        if output:
            print(f"❌ Debug-only output should be suppressed when disabled: {output!r}")
            return False

        print('✅ Debug-only suppression verified')
        return True
    except Exception as exc:
        print(f"❌ Debug-only suppression test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        _restore_modules(saved_modules)


if __name__ == '__main__':
    tests = [
        test_log_event_debug_only_path,
        test_functions_debug_compatibility_shim,
        test_debug_disabled_suppresses_debug_only_output,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)