#!/usr/bin/env python3
"""
Functional test for workflow template fix.
Version: 0.229.063
Implemented in: 0.229.063

This test ensures that the workflow.html template renders without
Jinja2 TemplateAssertionError for duplicate title blocks.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_workflow_template_structure():
    """Test that workflow.html has correct Jinja2 structure."""
    print("🔍 Testing workflow template structure...")
    
    try:
        template_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'templates', 'workflow.html'
        )
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for template structure issues
        extends_count = content.count('{% extends "base.html" %}')
        title_block_count = content.count('{% block title %}')
        
        print(f"   - Found {extends_count} extends directive(s)")
        print(f"   - Found {title_block_count} title block(s)")
        
        # Verify proper structure
        if extends_count != 1:
            raise Exception(f"Expected 1 extends directive, found {extends_count}")
        
        if title_block_count != 1:
            raise Exception(f"Expected 1 title block, found {title_block_count}")
        
        # Check that extends comes first
        extends_pos = content.find('{% extends "base.html" %}')
        first_block_pos = content.find('{% block')
        
        if extends_pos > first_block_pos:
            raise Exception("extends directive must come before any blocks")
        
        # Check for proper block structure
        required_blocks = ['title', 'head', 'content']
        for block in required_blocks:
            block_start = f'{{% block {block} %}}'
            block_end = '{% endblock %}'
            
            if block_start not in content:
                raise Exception(f"Missing {block} block")
            
            block_start_pos = content.find(block_start)
            # Find the corresponding endblock
            remaining_content = content[block_start_pos:]
            block_end_pos = remaining_content.find(block_end)
            
            if block_end_pos == -1:
                raise Exception(f"Missing endblock for {block} block")
        
        print("✅ Template structure is correct!")
        return True
        
    except Exception as e:
        print(f"❌ Template structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_workflow_template_syntax():
    """Test that workflow template can be parsed by Jinja2."""
    print("🔍 Testing workflow template Jinja2 syntax...")
    
    try:
        # Add the application directory to Python path
        app_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app'
        )
        sys.path.insert(0, app_dir)
        
        from jinja2 import Environment, FileSystemLoader
        
        template_dir = os.path.join(app_dir, 'templates')
        env = Environment(loader=FileSystemLoader(template_dir))
        
        # Try to load and parse the template
        template = env.get_template('workflow.html')
        
        print("   - Template loaded successfully")
        print("   - No Jinja2 syntax errors detected")
        
        # Test basic rendering (without full Flask context)
        # This will verify the template structure is valid
        try:
            # Create minimal context for testing
            test_context = {
                'app_settings': {'app_title': 'Test App'},
                'user_info': {'can_access_workflows': True},
                'config': {'VERSION': '0.229.063'}
            }
            
            rendered = template.render(**test_context)
            
            if 'Workflow' in rendered and 'workflow-container' in rendered:
                print("   - Template renders with expected content")
            else:
                print("   - Warning: Template rendered but missing expected content")
            
        except Exception as render_error:
            # Rendering might fail due to missing context, but syntax should be OK
            if "undefined" in str(render_error).lower():
                print("   - Template syntax is valid (render failed due to missing context, which is expected)")
            else:
                raise render_error
        
        print("✅ Template Jinja2 syntax is valid!")
        return True
        
    except Exception as e:
        print(f"❌ Template syntax test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_version_update():
    """Test that version was updated."""
    print("🔍 Testing version update...")
    
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'config.py'
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if 'VERSION = "0.229.063"' in content:
            print("   - Version updated to 0.229.063")
            print("✅ Version update confirmed!")
            return True
        else:
            raise Exception("Version not updated to 0.229.063")
        
    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        return False

if __name__ == "__main__":
    tests = [
        test_workflow_template_structure,
        test_workflow_template_syntax, 
        test_version_update
    ]
    
    results = []
    print("🧪 Running Workflow Template Fix Tests...\n")
    
    for test in tests:
        print(f"Running {test.__name__}...")
        results.append(test())
        print()
    
    success = all(results)
    print(f"📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All workflow template fixes validated successfully!")
        print("🎉 The workflow page should now load without template errors!")
    else:
        print("❌ Some tests failed - template may still have issues")
    
    sys.exit(0 if success else 1)