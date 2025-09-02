import json

def test_metadata_detection(metadata_value):
    """Test the metadata detection logic"""
    metadata = metadata_value.strip()
    
    try:
        metadata_obj = json.loads(metadata or '{}')
        has_metadata = len(metadata_obj) > 0
    except:
        has_metadata = len(metadata) > 0 and metadata != '{}'
    
    return has_metadata

# Test cases
test_cases = [
    ('{}', False, 'Empty object'),
    ('', False, 'Empty string'),
    ('{"key": "value"}', True, 'Object with data'),
    ('{"test": true}', True, 'Object with boolean'),
    ('{ }', False, 'Empty object with spaces'),
    ('invalid json', True, 'Invalid JSON but has content'),
    ('{"nested": {"data": 123}}', True, 'Nested object')
]

print('=== METADATA DETECTION TEST ===')
for value, expected, description in test_cases:
    result = test_metadata_detection(value)
    status = '✓ PASS' if result == expected else '✗ FAIL'
    print(f'{status} {description}: "{value}" -> {result} (expected {expected})')

print('=== TEST COMPLETE ===')
