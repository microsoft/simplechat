---
applyTo: '**'
---

# Functional Tests Management Instructions

## 📍 **Location**
All functional tests are stored in: `.\simplechat\functional_tests\`

## 📂 **Directory Structure**
The functional tests directory contains:
- **Python test files** (`test_*.py`) - Executable test scripts
- **JavaScript test files** (`test_*.js`) - Client-side/browser test scripts  
- **Documentation files** (`*.md`) - Test documentation and fix summaries
- **flask_session/** - Session data for tests requiring authenticated state

## 🎯 **When to Create Functional Tests**

### **Always Create Tests For:**
✅ **Bug Fixes** - Validate the fix works and prevents regression  
✅ **New Features** - Ensure functionality works as designed  
✅ **API Changes** - Verify operation consistency and compatibility  
✅ **Plugin Integration** - Test plugin loading, operation calls, error handling  
✅ **Database Migration** - Validate data migration and container operations  
✅ **UI/UX Changes** - Test display logic, user interactions, data flow  
✅ **Authentication/Security** - Verify access controls and data isolation  

### **Test Categories:**
- **Integration Tests** - End-to-end functionality across multiple components
- **Regression Tests** - Prevent previously fixed bugs from returning
- **Consistency Tests** - Validate behavior remains consistent across iterations
- **Migration Tests** - Verify data and schema migrations work correctly

## 📝 **Naming Conventions**

### **File Naming:**
- **Python Tests**: `test_{feature_area}_{specific_test}.py`
- **JavaScript Tests**: `test_{feature_area}_{specific_test}.js` 
- **Documentation**: `{FEATURE_AREA}_{DESCRIPTION}.md`

### **Examples:**
```
test_agent_citations_fix.py              # Agent citation bug fix
test_semantic_kernel_operation_consistency.py  # SK operation reliability
test_openapi_operation_lookup.py         # OpenAPI plugin testing
test_conversation_id_display.py          # UI feature testing
test_migration.py                        # Database migration testing
AGENT_MODEL_DISPLAY_FIXES.md            # Fix documentation
```

## 🏗️ **Test Structure Patterns**

### **Python Test Template:**
```python
#!/usr/bin/env python3
"""
Brief description of what this test validates.

This test ensures [specific functionality] works correctly and 
prevents regression of [specific issue/bug].
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_primary_functionality():
    """Test the main functionality."""
    print("🔍 Testing [Feature Name]...")
    
    try:
        # Setup
        # Test execution  
        # Validation
        # Cleanup
        
        print("✅ Test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_primary_functionality()
    sys.exit(0 if success else 1)
```

### **Multi-Test Pattern:**
```python
def test_feature_a():
    """Test specific aspect A."""
    # Implementation
    
def test_feature_b():  
    """Test specific aspect B."""
    # Implementation

if __name__ == "__main__":
    tests = [test_feature_a, test_feature_b]
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
```

## 🔍 **Test Discovery & Reuse**

### **Before Creating New Tests:**
1. **Search existing tests**: `grep -r "test_.*{feature}" functional_tests/`
2. **Check for similar patterns**: Look for tests in the same feature area
3. **Review related documentation**: Check for `*.md` files describing fixes
4. **Examine imports**: See what modules/functions are already being tested

### **Reusable Test Components:**
- **OpenAPI Testing**: Use `OpenApiPluginFactory` patterns from `test_openapi_*.py`
- **Agent Testing**: Reference citation and model display test patterns
- **Database Testing**: Follow migration test patterns for Cosmos DB operations  
- **Plugin Testing**: Use plugin logging patterns for function call validation

## 🔧 **Common Testing Utilities**

### **Available Imports:**
```python
# OpenAPI Plugin Testing
from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory

# Database Operations (Personal Containers)
from functions_personal_agents import get_personal_agents, save_personal_agent
from functions_personal_actions import get_personal_actions, save_personal_action

# Plugin Logging
from semantic_kernel_plugins.plugin_logging import get_plugin_logger

# Conversation Management  
from conversation_manager import ConversationManager
```

### **Test Data Patterns:**
```python
# Test User ID
test_user_id = "test-user-12345" 

# Test Agent Configuration
test_agent = {
    "name": "TestAgent",
    "display_name": "Test Agent", 
    "description": "A test agent for validation",
    "instructions": "You are a test agent",
    "azure_openai_gpt_deployment": "gpt-4o"
}

# Test OpenAPI Plugin Configuration
test_config = {
    'name': 'test_plugin',
    'base_url': 'https://api.example.com',
    'openapi_spec_content': {
        'openapi': '3.0.0',
        'info': {'title': 'Test API', 'version': '1.0.0'},
        'paths': {
            '/test': {
                'get': {
                    'operationId': 'testOperation',
                    'summary': 'Test operation'
                }
            }
        }
    }
}
```

## 🎯 **Where to Store Tests**

### **Test Categories by Directory Usage:**
- **Core Functionality Tests** → Direct in `functional_tests/`
- **Fix Validation Tests** → `functional_tests/` with accompanying `.md` documentation
- **Plugin Integration Tests** → `functional_tests/` (follow `test_openapi_*.py` patterns)
- **Migration Tests** → `functional_tests/` (follow `test_migration.py` pattern)
- **UI/Display Tests** → `functional_tests/` (follow `test_*_display.py` patterns)

### **Documentation Requirements:**
- **For Bug Fixes**: Create accompanying `.md` file describing the issue and solution
- **For New Features**: Include comprehensive test documentation in docstrings
- **For Complex Integrations**: Add setup/teardown documentation

## ⚡ **Execution Patterns**

### **Standalone Execution:**
```bash
cd functional_tests
python test_specific_feature.py
```

### **Multiple Test Execution:**
```bash
# Run all Python tests
for test in test_*.py; do python $test; done

# Run specific test pattern  
python test_openapi_*.py
```

### **Integration with Development Workflow:**
- Run relevant tests after making changes in related areas
- Create/update tests as part of bug fix or feature development
- Use tests to validate fixes before marking issues as resolved

## 📋 **Best Practices**

### **Test Design:**
✅ **Independent Tests** - Each test should run standalone without dependencies  
✅ **Clear Output** - Use emojis and descriptive messages for test progress  
✅ **Proper Cleanup** - Clean up test data to avoid pollution  
✅ **Error Handling** - Include comprehensive error reporting with stack traces  
✅ **Validation** - Test both positive and negative scenarios  

### **Code Organization:**
✅ **Meaningful Names** - Test and function names should describe what they validate  
✅ **Documentation** - Include docstrings explaining test purpose and approach  
✅ **Imports** - Group imports logically and include only necessary dependencies  
✅ **Modularity** - Break complex tests into smaller, focused functions  

### **Maintenance:**
✅ **Regular Review** - Periodically review and update tests for relevance  
✅ **Refactoring** - Extract common patterns into reusable utilities  
✅ **Documentation Updates** - Keep test documentation current with code changes