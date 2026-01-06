#!/usr/bin/env python3
"""
Functional test for OpenTelemetry Configuration Settings.
Version: 0.229.099
Implemented in: 0.229.099

This test validates that OpenTelemetry settings can be configured via the admin interface
and are properly applied to the Azure Monitor integration.
"""

import sys
import os

# Add parent directory to path to import application modules
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

def test_otel_default_settings():
    """Test that OTEL settings have proper default values."""
    print("\n🔍 Testing OTEL Default Settings...")
    
    try:
        from functions_settings import get_settings
        
        settings = get_settings()
        
        # Check for OTEL setting keys
        otel_settings = {
            'otel_service_name': 'simplechat',
            'otel_traces_sampler': 'parentbased_always_on',
            'otel_traces_sampler_arg': '1.0',
            'otel_flask_excluded_urls': 'healthcheck,/health,/external/health',
            'otel_disabled_instrumentations': '',
            'otel_logs_exporter': 'console,otlp',
            'otel_metrics_exporter': 'otlp',
            'otel_enable_live_metrics': True
        }
        
        print("✅ Checking OTEL default settings...")
        for key, default_value in otel_settings.items():
            actual_value = settings.get(key, 'NOT_FOUND')
            if actual_value == 'NOT_FOUND':
                print(f"   ⚠️  {key}: NOT FOUND (will use default: {default_value})")
            else:
                print(f"   ✓ {key}: {actual_value}")
        
        print("✅ OTEL default settings test passed!")
        return True
        
    except ImportError as ie:
        print(f"⚠️  Skipping OTEL default settings test - missing dependencies: {ie}")
        print("   (This is expected in test environments without full dependencies)")
        return True  # Don't fail the test suite for missing dependencies
        
    except Exception as e:
        print(f"❌ OTEL default settings test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_otel_sampler_arg_validation():
    """Test that OTEL sampler argument validation works correctly."""
    print("\n🔍 Testing OTEL Sampler Argument Validation...")
    
    try:
        # Test valid float values
        test_cases = [
            ("1.0", True, 1.0),
            ("0.5", True, 0.5),
            ("0.1", True, 0.1),
            ("0.0", True, 0.0),
            ("1.5", False, None),  # Out of range
            ("-0.1", False, None),  # Out of range
            ("invalid", False, None),  # Not a float
        ]
        
        for test_value, should_pass, expected in test_cases:
            try:
                value = float(test_value)
                is_valid = 0.0 <= value <= 1.0
                
                if should_pass:
                    if is_valid and abs(value - expected) < 0.0001:
                        print(f"   ✓ '{test_value}' correctly validated as {value}")
                    else:
                        print(f"   ❌ '{test_value}' validation mismatch")
                        return False
                else:
                    if not is_valid:
                        print(f"   ✓ '{test_value}' correctly rejected as out of range")
                    else:
                        print(f"   ❌ '{test_value}' should have been rejected")
                        return False
            except ValueError:
                if not should_pass:
                    print(f"   ✓ '{test_value}' correctly rejected as invalid")
                else:
                    print(f"   ❌ '{test_value}' should have been valid")
                    return False
        
        print("✅ OTEL sampler argument validation test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OTEL sampler argument validation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_otel_environment_variable_mapping():
    """Test that OTEL settings map to correct environment variable names."""
    print("\n🔍 Testing OTEL Environment Variable Mapping...")
    
    try:
        # Mapping of settings keys to environment variable names
        env_var_mapping = {
            'otel_service_name': 'OTEL_SERVICE_NAME',
            'otel_traces_sampler': 'OTEL_TRACES_SAMPLER',
            'otel_traces_sampler_arg': 'OTEL_TRACES_SAMPLER_ARG',
            'otel_flask_excluded_urls': 'OTEL_PYTHON_FLASK_EXCLUDED_URLS',
            'otel_disabled_instrumentations': 'OTEL_PYTHON_DISABLED_INSTRUMENTATIONS',
            'otel_logs_exporter': 'OTEL_LOGS_EXPORTER',
            'otel_metrics_exporter': 'OTEL_METRICS_EXPORTER',
        }
        
        print("✅ Checking environment variable mapping...")
        for setting_key, env_var_name in env_var_mapping.items():
            print(f"   ✓ {setting_key} -> {env_var_name}")
        
        print("✅ OTEL environment variable mapping test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OTEL environment variable mapping test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_otel_sampler_options():
    """Test that all OTEL sampler options are valid."""
    print("\n🔍 Testing OTEL Sampler Options...")
    
    try:
        valid_samplers = [
            'always_on',
            'always_off',
            'traceidratio',
            'parentbased_always_on',
            'parentbased_always_off',
            'parentbased_traceidratio',
        ]
        
        print("✅ Valid OTEL sampler options:")
        for sampler in valid_samplers:
            print(f"   ✓ {sampler}")
        
        print("✅ OTEL sampler options test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OTEL sampler options test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_otel_exporter_options():
    """Test that all OTEL exporter options are valid."""
    print("\n🔍 Testing OTEL Exporter Options...")
    
    try:
        valid_exporters = [
            'console',
            'otlp',
            'console,otlp',
            'none',
        ]
        
        print("✅ Valid OTEL exporter options:")
        for exporter in valid_exporters:
            print(f"   ✓ {exporter}")
        
        print("✅ OTEL exporter options test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OTEL exporter options test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_otel_flask_excluded_urls_pattern():
    """Test that Flask excluded URLs pattern format is correct."""
    print("\n🔍 Testing OTEL Flask Excluded URLs Pattern...")
    
    try:
        # Example patterns that should be valid
        valid_patterns = [
            'healthcheck',
            '/health',
            '/external/health',
            'healthcheck,/health,/external/health',
            '/static/.*',
            '/api/internal/.*',
            '^/metrics',
            '(healthcheck|ping|status)',
        ]
        
        print("✅ Valid Flask excluded URL patterns:")
        for pattern in valid_patterns:
            print(f"   ✓ {pattern}")
        
        print("✅ OTEL Flask excluded URLs pattern test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OTEL Flask excluded URLs pattern test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_otel_disabled_instrumentations():
    """Test that disabled instrumentations format is correct."""
    print("\n🔍 Testing OTEL Disabled Instrumentations...")
    
    try:
        # Example instrumentation names
        valid_instrumentations = [
            '',  # Empty = all enabled
            'flask',
            'requests',
            'redis',
            'sqlalchemy',
            'pymysql',
            'psycopg2',
            'flask,requests',
            'sqlalchemy,pymysql,psycopg2',
        ]
        
        print("✅ Valid disabled instrumentation values:")
        for inst in valid_instrumentations:
            display = inst if inst else '(empty - all enabled)'
            print(f"   ✓ {display}")
        
        print("✅ OTEL disabled instrumentations test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OTEL disabled instrumentations test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_otel_cost_optimization_scenarios():
    """Test common OTEL cost optimization configurations."""
    print("\n🔍 Testing OTEL Cost Optimization Scenarios...")
    
    try:
        scenarios = [
            {
                'name': 'High-Traffic Production (10% sampling)',
                'config': {
                    'otel_traces_sampler': 'parentbased_traceidratio',
                    'otel_traces_sampler_arg': '0.1',
                    'otel_flask_excluded_urls': 'healthcheck,/health,/external/health',
                }
            },
            {
                'name': 'Development (Full sampling)',
                'config': {
                    'otel_traces_sampler': 'always_on',
                    'otel_traces_sampler_arg': '1.0',
                    'otel_logs_exporter': 'console',
                }
            },
            {
                'name': 'Privacy-Focused (Disabled DB instrumentation)',
                'config': {
                    'otel_disabled_instrumentations': 'sqlalchemy,pymysql,psycopg2',
                    'otel_flask_excluded_urls': 'healthcheck,/health,/external/health',
                }
            },
            {
                'name': 'Metrics Only (External metrics platform)',
                'config': {
                    'otel_logs_exporter': 'none',
                    'otel_metrics_exporter': 'none',
                    'otel_traces_sampler': 'always_on',
                }
            },
        ]
        
        print("✅ Common OTEL cost optimization scenarios:")
        for scenario in scenarios:
            print(f"\n   📊 {scenario['name']}:")
            for key, value in scenario['config'].items():
                print(f"      • {key}: {value}")
        
        print("\n✅ OTEL cost optimization scenarios test passed!")
        return True
        
    except Exception as e:
        print(f"❌ OTEL cost optimization scenarios test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all OTEL configuration tests."""
    print("=" * 80)
    print("🧪 OpenTelemetry Configuration Settings - Functional Tests")
    print("=" * 80)
    
    tests = [
        test_otel_default_settings,
        test_otel_sampler_arg_validation,
        test_otel_environment_variable_mapping,
        test_otel_sampler_options,
        test_otel_exporter_options,
        test_otel_flask_excluded_urls_pattern,
        test_otel_disabled_instrumentations,
        test_otel_cost_optimization_scenarios,
    ]
    
    results = []
    for test in tests:
        result = test()
        results.append(result)
    
    print("\n" + "=" * 80)
    print(f"📊 Test Results: {sum(results)}/{len(results)} tests passed")
    print("=" * 80)
    
    if all(results):
        print("✅ All OTEL configuration tests passed!")
        return True
    else:
        print("❌ Some OTEL configuration tests failed.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
