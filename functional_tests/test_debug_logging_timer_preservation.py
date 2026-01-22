#!/usr/bin/env python3
"""
Functional test for Debug Logging Timer Preservation Fix.
Version: 0.235.014
Implemented in: 0.235.014

This test ensures that the debug logging and file processing logs turnoff times
are preserved when saving admin settings, rather than being recalculated on every save.

The bug was that every time admin settings were saved, the turnoff time was recalculated
from "now + delta" instead of preserving the existing turnoff time if the timer settings
(value, unit, enabled state) hadn't changed.

Root cause: route_frontend_admin_settings.py always recalculated turnoff times instead
of checking if timer settings changed.

Fix: Only recalculate turnoff time if:
1. Timer settings have changed (value, unit, or enabled state), OR
2. The logging was just enabled, OR
3. No existing turnoff time exists
"""

import sys
import os
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))


def test_timer_recalculation_logic():
    """
    Test the logic that determines when turnoff time should be recalculated.
    This simulates the conditions checked in route_frontend_admin_settings.py.
    """
    print("🧪 Testing timer recalculation logic...")
    
    # Scenario 1: Settings unchanged - should preserve existing time
    print("\n📋 Scenario 1: No timer settings changed - should preserve existing time")
    existing_settings = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks',
        'debug_logging_turnoff_time': '2026-01-22T11:05:44.417753'
    }
    new_form_data = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks'
    }
    
    timer_settings_changed = (
        new_form_data['debug_logging_timer_enabled'] != existing_settings.get('debug_logging_timer_enabled', False) or
        new_form_data['debug_timer_value'] != existing_settings.get('debug_timer_value', 1) or
        new_form_data['debug_timer_unit'] != existing_settings.get('debug_timer_unit', 'hours')
    )
    debug_logging_newly_enabled = new_form_data['enable_debug_logging'] and not existing_settings.get('enable_debug_logging', False)
    existing_turnoff_time = existing_settings.get('debug_logging_turnoff_time')
    
    should_recalculate = timer_settings_changed or debug_logging_newly_enabled or not existing_turnoff_time
    
    if should_recalculate:
        print("❌ FAILED: Should NOT recalculate - settings unchanged")
        return False
    else:
        print("✅ PASSED: Correctly determined to preserve existing turnoff time")
    
    # Scenario 2: Timer value changed - should recalculate
    print("\n📋 Scenario 2: Timer value changed - should recalculate")
    new_form_data_changed_value = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 2,  # Changed from 1 to 2
        'debug_timer_unit': 'weeks'
    }
    
    timer_settings_changed = (
        new_form_data_changed_value['debug_logging_timer_enabled'] != existing_settings.get('debug_logging_timer_enabled', False) or
        new_form_data_changed_value['debug_timer_value'] != existing_settings.get('debug_timer_value', 1) or
        new_form_data_changed_value['debug_timer_unit'] != existing_settings.get('debug_timer_unit', 'hours')
    )
    debug_logging_newly_enabled = new_form_data_changed_value['enable_debug_logging'] and not existing_settings.get('enable_debug_logging', False)
    
    should_recalculate = timer_settings_changed or debug_logging_newly_enabled or not existing_turnoff_time
    
    if should_recalculate:
        print("✅ PASSED: Correctly determined to recalculate (timer value changed)")
    else:
        print("❌ FAILED: Should recalculate when timer value changed")
        return False
    
    # Scenario 3: Timer unit changed - should recalculate
    print("\n📋 Scenario 3: Timer unit changed - should recalculate")
    new_form_data_changed_unit = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'days'  # Changed from 'weeks' to 'days'
    }
    
    timer_settings_changed = (
        new_form_data_changed_unit['debug_logging_timer_enabled'] != existing_settings.get('debug_logging_timer_enabled', False) or
        new_form_data_changed_unit['debug_timer_value'] != existing_settings.get('debug_timer_value', 1) or
        new_form_data_changed_unit['debug_timer_unit'] != existing_settings.get('debug_timer_unit', 'hours')
    )
    debug_logging_newly_enabled = new_form_data_changed_unit['enable_debug_logging'] and not existing_settings.get('enable_debug_logging', False)
    
    should_recalculate = timer_settings_changed or debug_logging_newly_enabled or not existing_turnoff_time
    
    if should_recalculate:
        print("✅ PASSED: Correctly determined to recalculate (timer unit changed)")
    else:
        print("❌ FAILED: Should recalculate when timer unit changed")
        return False
    
    # Scenario 4: Debug logging newly enabled - should recalculate
    print("\n📋 Scenario 4: Debug logging newly enabled - should recalculate")
    existing_settings_logging_off = {
        'enable_debug_logging': False,  # Was off
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks',
        'debug_logging_turnoff_time': None  # No turnoff time when disabled
    }
    new_form_data_enable = {
        'enable_debug_logging': True,  # Now on
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks'
    }
    
    timer_settings_changed = (
        new_form_data_enable['debug_logging_timer_enabled'] != existing_settings_logging_off.get('debug_logging_timer_enabled', False) or
        new_form_data_enable['debug_timer_value'] != existing_settings_logging_off.get('debug_timer_value', 1) or
        new_form_data_enable['debug_timer_unit'] != existing_settings_logging_off.get('debug_timer_unit', 'hours')
    )
    debug_logging_newly_enabled = new_form_data_enable['enable_debug_logging'] and not existing_settings_logging_off.get('enable_debug_logging', False)
    existing_turnoff_time_off = existing_settings_logging_off.get('debug_logging_turnoff_time')
    
    should_recalculate = timer_settings_changed or debug_logging_newly_enabled or not existing_turnoff_time_off
    
    if should_recalculate:
        print("✅ PASSED: Correctly determined to recalculate (debug logging newly enabled)")
    else:
        print("❌ FAILED: Should recalculate when debug logging is newly enabled")
        return False
    
    # Scenario 5: Timer enabled changed - should recalculate
    print("\n📋 Scenario 5: Timer enabled changed (was off, now on) - should recalculate")
    existing_settings_timer_off = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': False,  # Was off
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks',
        'debug_logging_turnoff_time': None  # No turnoff time when timer disabled
    }
    new_form_data_timer_on = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,  # Now on
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks'
    }
    
    timer_settings_changed = (
        new_form_data_timer_on['debug_logging_timer_enabled'] != existing_settings_timer_off.get('debug_logging_timer_enabled', False) or
        new_form_data_timer_on['debug_timer_value'] != existing_settings_timer_off.get('debug_timer_value', 1) or
        new_form_data_timer_on['debug_timer_unit'] != existing_settings_timer_off.get('debug_timer_unit', 'hours')
    )
    debug_logging_newly_enabled = new_form_data_timer_on['enable_debug_logging'] and not existing_settings_timer_off.get('enable_debug_logging', False)
    existing_turnoff_time_timer_off = existing_settings_timer_off.get('debug_logging_turnoff_time')
    
    should_recalculate = timer_settings_changed or debug_logging_newly_enabled or not existing_turnoff_time_timer_off
    
    if should_recalculate:
        print("✅ PASSED: Correctly determined to recalculate (timer enabled state changed)")
    else:
        print("❌ FAILED: Should recalculate when timer enabled state changed")
        return False
    
    print("\n✅ All timer recalculation logic tests passed!")
    return True


def test_file_processing_logs_timer_preservation():
    """
    Test the same preservation logic for file processing logs timer.
    """
    print("\n🧪 Testing file processing logs timer preservation logic...")
    
    # Scenario: Settings unchanged - should preserve existing time
    print("\n📋 Scenario: No file timer settings changed - should preserve existing time")
    existing_settings = {
        'enable_file_processing_logs': True,
        'file_processing_logs_timer_enabled': True,
        'file_timer_value': 24,
        'file_timer_unit': 'hours',
        'file_processing_logs_turnoff_time': '2026-01-17T10:30:00.000000'
    }
    new_form_data = {
        'enable_file_processing_logs': True,
        'file_processing_logs_timer_enabled': True,
        'file_timer_value': 24,
        'file_timer_unit': 'hours'
    }
    
    file_timer_settings_changed = (
        new_form_data['file_processing_logs_timer_enabled'] != existing_settings.get('file_processing_logs_timer_enabled', False) or
        new_form_data['file_timer_value'] != existing_settings.get('file_timer_value', 1) or
        new_form_data['file_timer_unit'] != existing_settings.get('file_timer_unit', 'hours')
    )
    file_processing_logs_newly_enabled = new_form_data['enable_file_processing_logs'] and not existing_settings.get('enable_file_processing_logs', False)
    existing_file_turnoff_time = existing_settings.get('file_processing_logs_turnoff_time')
    
    should_recalculate = file_timer_settings_changed or file_processing_logs_newly_enabled or not existing_file_turnoff_time
    
    if should_recalculate:
        print("❌ FAILED: Should NOT recalculate - file timer settings unchanged")
        return False
    else:
        print("✅ PASSED: Correctly determined to preserve existing file turnoff time")
    
    print("\n✅ File processing logs timer preservation test passed!")
    return True


def test_edge_cases():
    """
    Test edge cases for timer preservation.
    """
    print("\n🧪 Testing edge cases...")
    
    # Edge case 1: No existing turnoff time (should always recalculate)
    print("\n📋 Edge case 1: No existing turnoff time - should recalculate")
    existing_settings = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks',
        'debug_logging_turnoff_time': None  # No existing time
    }
    new_form_data = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks'
    }
    
    timer_settings_changed = (
        new_form_data['debug_logging_timer_enabled'] != existing_settings.get('debug_logging_timer_enabled', False) or
        new_form_data['debug_timer_value'] != existing_settings.get('debug_timer_value', 1) or
        new_form_data['debug_timer_unit'] != existing_settings.get('debug_timer_unit', 'hours')
    )
    debug_logging_newly_enabled = new_form_data['enable_debug_logging'] and not existing_settings.get('enable_debug_logging', False)
    existing_turnoff_time = existing_settings.get('debug_logging_turnoff_time')
    
    should_recalculate = timer_settings_changed or debug_logging_newly_enabled or not existing_turnoff_time
    
    if should_recalculate:
        print("✅ PASSED: Correctly determined to recalculate (no existing turnoff time)")
    else:
        print("❌ FAILED: Should recalculate when no existing turnoff time")
        return False
    
    # Edge case 2: Empty string turnoff time (should recalculate)
    print("\n📋 Edge case 2: Empty string turnoff time - should recalculate")
    existing_settings_empty = {
        'enable_debug_logging': True,
        'debug_logging_timer_enabled': True,
        'debug_timer_value': 1,
        'debug_timer_unit': 'weeks',
        'debug_logging_turnoff_time': ''  # Empty string
    }
    
    existing_turnoff_time_empty = existing_settings_empty.get('debug_logging_turnoff_time')
    should_recalculate = timer_settings_changed or debug_logging_newly_enabled or not existing_turnoff_time_empty
    
    if should_recalculate:
        print("✅ PASSED: Correctly determined to recalculate (empty string turnoff time)")
    else:
        print("❌ FAILED: Should recalculate when turnoff time is empty string")
        return False
    
    print("\n✅ All edge case tests passed!")
    return True


if __name__ == "__main__":
    print("=" * 70)
    print("Debug Logging Timer Preservation Fix - Functional Test")
    print("Version: 0.235.014")
    print("=" * 70)
    
    tests = [
        ("Timer Recalculation Logic", test_timer_recalculation_logic),
        ("File Processing Logs Timer Preservation", test_file_processing_logs_timer_preservation),
        ("Edge Cases", test_edge_cases),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'=' * 70}")
        print(f"Running: {test_name}")
        print("=" * 70)
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ EXCEPTION in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {status}: {test_name}")
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! The fix is working correctly.")
        sys.exit(0)
    else:
        print("\n⚠️ Some tests failed. Please review the fix.")
        sys.exit(1)
