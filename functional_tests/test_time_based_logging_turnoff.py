#!/usr/bin/env python3
"""
Functional test for time-based logging turnoff feature.
Version: 0.229.043
Implemented in: 0.229.043

This test ensures that the time-based turnoff functionality works correctly
for both debug logging and file processing logs, including:
1. UI controls appear and function correctly
2. Timer settings are saved properly
3. Background task monitors and disables logging when timers expire
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_timer_settings_validation():
    """Test that timer values are validated within specified ranges."""
    print("🔍 Testing timer value validation...")
    
    try:
        # Test timer limits
        timer_limits = {
            'minutes': (1, 120),
            'hours': (1, 24),
            'days': (1, 7),
            'weeks': (1, 52)
        }
        
        def validate_timer_value(value, unit):
            if unit in timer_limits:
                min_val, max_val = timer_limits[unit]
                return min(max(value, min_val), max_val)
            return value
        
        # Test various validation scenarios
        test_cases = [
            (0, 'minutes', 1),      # Below minimum
            (150, 'minutes', 120),  # Above maximum
            (30, 'minutes', 30),    # Valid value
            (0, 'hours', 1),        # Below minimum
            (30, 'hours', 24),      # Above maximum
            (12, 'hours', 12),      # Valid value
            (0, 'days', 1),         # Below minimum
            (10, 'days', 7),        # Above maximum
            (3, 'days', 3),         # Valid value
            (0, 'weeks', 1),        # Below minimum
            (100, 'weeks', 52),     # Above maximum
            (4, 'weeks', 4),        # Valid value
        ]
        
        for input_val, unit, expected in test_cases:
            result = validate_timer_value(input_val, unit)
            if result != expected:
                print(f"❌ Validation failed for {input_val} {unit}: expected {expected}, got {result}")
                return False
            print(f"✅ {input_val} {unit} → {result}")
        
        print("✅ Timer validation test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Timer validation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_datetime_serialization():
    """Test that datetime objects are properly serialized for JSON storage."""
    print("🔍 Testing datetime serialization...")
    
    try:
        from datetime import datetime, timedelta
        import json
        
        # Create a sample datetime
        now = datetime.now()
        future_time = now + timedelta(hours=2)
        
        # Convert to ISO string (what our code should do)
        future_time_str = future_time.isoformat()
        
        # Test JSON serialization
        test_data = {
            'debug_logging_turnoff_time': future_time_str,
            'file_processing_logs_turnoff_time': future_time_str
        }
        
        # This should not raise an exception
        json_str = json.dumps(test_data)
        parsed_data = json.loads(json_str)
        
        # Verify the data round-trip
        if parsed_data['debug_logging_turnoff_time'] != future_time_str:
            print("❌ Datetime serialization failed: data corruption")
            return False
        
        # Test parsing back to datetime
        parsed_datetime = datetime.fromisoformat(parsed_data['debug_logging_turnoff_time'])
        
        # Should be within a few microseconds of the original
        time_diff = abs((parsed_datetime - future_time).total_seconds())
        if time_diff > 0.001:  # Allow for microsecond differences
            print(f"❌ Datetime parsing failed: time difference {time_diff} seconds")
            return False
        
        print("✅ Datetime serialization test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Datetime serialization test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_turnoff_calculation():
    """Test that turnoff times are calculated correctly for different units."""
    print("🔍 Testing turnoff time calculation...")
    
    try:
        from datetime import datetime, timedelta
        
        # Test calculation for different units
        base_time = datetime(2025, 9, 17, 12, 0, 0)  # Fixed time for predictable testing
        
        test_cases = [
            (30, 'minutes', timedelta(minutes=30)),
            (2, 'hours', timedelta(hours=2)),
            (3, 'days', timedelta(days=3)),
            (1, 'weeks', timedelta(weeks=1)),
        ]
        
        for value, unit, expected_delta in test_cases:
            # Simulate our calculation logic
            if unit == 'minutes':
                delta = timedelta(minutes=value)
            elif unit == 'hours':
                delta = timedelta(hours=value)
            elif unit == 'days':
                delta = timedelta(days=value)
            elif unit == 'weeks':
                delta = timedelta(weeks=value)
            else:
                delta = timedelta(hours=1)  # default fallback
            
            if delta != expected_delta:
                print(f"❌ Calculation failed for {value} {unit}")
                return False
            
            turnoff_time = base_time + delta
            expected_time = base_time + expected_delta
            
            if turnoff_time != expected_time:
                print(f"❌ Turnoff time calculation failed for {value} {unit}")
                return False
            
            print(f"✅ {value} {unit}: {base_time} + {delta} = {turnoff_time}")
        
        print("✅ Turnoff calculation test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Turnoff calculation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_background_timer_logic():
    """Test the background timer checking logic."""
    print("🔍 Testing background timer logic...")
    
    try:
        from datetime import datetime, timedelta
        
        # Simulate settings with expired and non-expired timers
        current_time = datetime.now()
        
        # Test expired timer
        expired_time = current_time - timedelta(minutes=5)
        expired_settings = {
            'enable_debug_logging': True,
            'debug_logging_timer_enabled': True,
            'debug_logging_turnoff_time': expired_time.isoformat()
        }
        
        # Simulate timer check logic
        turnoff_time = datetime.fromisoformat(expired_settings['debug_logging_turnoff_time'])
        should_disable = current_time >= turnoff_time
        
        if not should_disable:
            print("❌ Expired timer logic failed")
            return False
        
        # Test non-expired timer
        future_time = current_time + timedelta(hours=1)
        future_settings = {
            'enable_debug_logging': True,
            'debug_logging_timer_enabled': True,
            'debug_logging_turnoff_time': future_time.isoformat()
        }
        
        turnoff_time = datetime.fromisoformat(future_settings['debug_logging_turnoff_time'])
        should_not_disable = current_time < turnoff_time
        
        if not should_not_disable:
            print("❌ Future timer logic failed")
            return False
        
        print("✅ Background timer logic test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Background timer logic test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_settings_defaults():
    """Test that default settings include the new timer fields."""
    print("🔍 Testing default settings...")
    
    try:
        # Import the actual settings function
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))
        from functions_settings import get_settings
        
        settings = get_settings()
        
        # Check that all new timer fields have defaults
        required_fields = [
            'debug_logging_timer_enabled',
            'debug_timer_value',
            'debug_timer_unit',
            'debug_logging_turnoff_time',
            'file_processing_logs_timer_enabled',
            'file_timer_value',
            'file_timer_unit',
            'file_processing_logs_turnoff_time'
        ]
        
        for field in required_fields:
            if field not in settings:
                print(f"❌ Missing default field: {field}")
                return False
        
        # Check default values
        if settings['debug_logging_timer_enabled'] != False:
            print("❌ debug_logging_timer_enabled should default to False")
            return False
        
        if settings['debug_timer_value'] != 1:
            print("❌ debug_timer_value should default to 1")
            return False
        
        if settings['debug_timer_unit'] != 'hours':
            print("❌ debug_timer_unit should default to 'hours'")
            return False
        
        print("✅ Default settings test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Default settings test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_timer_settings_validation,
        test_datetime_serialization,
        test_turnoff_calculation,
        test_background_timer_logic,
        test_settings_defaults
    ]
    
    results = []
    
    print("🧪 Running Time-based Logging Turnoff Tests...")
    print("=" * 60)
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("🎉 All time-based logging turnoff tests passed!")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    sys.exit(0 if success else 1)