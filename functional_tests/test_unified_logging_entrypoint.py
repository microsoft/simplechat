# test_unified_logging_entrypoint.py
"""
Functional test for unified logging entry point and debug trace forwarding.
Version: 0.241.020
Implemented in: 0.241.020

This test ensures that debug-only logging can be routed through log_event,
that debug_print can forward tagged traces to Application Insights, and that
the legacy functions_debug compatibility shim continues to work.
"""

import importlib
import io
import logging
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


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


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


def test_debug_print_forwards_tagged_appinsights_trace():
    """Verify debug_print preserves console output and forwards a tagged debug trace."""
    print("🔍 Testing debug_print App Insights trace forwarding...")
    saved_modules = _install_logging_stubs(debug_enabled=True)

    try:
        functions_appinsights = importlib.import_module('functions_appinsights')
        parent_logger = logging.getLogger('azure_monitor')
        capture_handler = _CaptureHandler()
        original_level = parent_logger.level

        parent_logger.setLevel(logging.INFO)
        parent_logger.addHandler(capture_handler)

        functions_appinsights._azure_monitor_configured = True
        functions_appinsights._appinsights_logger = parent_logger

        captured_output = io.StringIO()
        with redirect_stdout(captured_output):
            functions_appinsights.debug_print(
                'Forward %s',
                'trace',
                category='TRACE',
                operation='debug-forward',
            )

        output = captured_output.getvalue()
        if '[DEBUG] [TRACE]: Forward trace (operation=debug-forward)' not in output:
            print(f"❌ Unexpected debug_print console output: {output!r}")
            return False

        if '[DEBUG][Log]' in output:
            print(f"❌ App Insights forwarding should not duplicate structured console logs: {output!r}")
            return False

        if len(capture_handler.records) != 1:
            print(f"❌ Expected exactly one forwarded trace, saw {len(capture_handler.records)}")
            return False

        record = capture_handler.records[0]
        if record.levelno != logging.DEBUG:
            print(f"❌ Expected DEBUG trace level, got {record.levelno}")
            return False

        if record.getMessage() != '[debug] [TRACE] Forward trace':
            print(f"❌ Unexpected forwarded trace message: {record.getMessage()!r}")
            return False

        if getattr(record, 'debug_tag', None) != '[debug]':
            print(f"❌ Missing debug tag on forwarded trace: {record.__dict__}")
            return False

        if getattr(record, 'debug_category', None) != 'TRACE':
            print(f"❌ Missing debug category on forwarded trace: {record.__dict__}")
            return False

        if getattr(record, 'operation', None) != 'debug-forward':
            print(f"❌ Missing forwarded custom dimensions: {record.__dict__}")
            return False

        print('✅ debug_print App Insights trace forwarding verified')
        return True
    except Exception as exc:
        print(f"❌ debug_print App Insights trace forwarding failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        parent_logger = logging.getLogger('azure_monitor')
        for handler in list(parent_logger.handlers):
            if isinstance(handler, _CaptureHandler):
                parent_logger.removeHandler(handler)
        parent_logger.setLevel(logging.NOTSET)
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
        test_debug_print_forwards_tagged_appinsights_trace,
        test_debug_disabled_suppresses_debug_only_output,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)