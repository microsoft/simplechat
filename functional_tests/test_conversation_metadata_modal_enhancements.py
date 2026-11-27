#!/usr/bin/env python3
# test_conversation_metadata_modal_enhancements.py
"""
Test to verify that the conversation metadata modal width enhancements work correctly.

This test ensures that:
1. The conversation details modal uses modal-xl instead of modal-lg
2. The CSS is updated to support the wider modal
3. The code styling prevents conversation ID wrapping

Enhancement: Made conversation metadata modal wider to prevent conversation ID wrapping
Version: 0.261.474
Implemented in: 0.229.001
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_modal_width_enhancement():
    """Test that the conversation details modal has been made wider."""
    print("🔍 Testing conversation details modal width enhancement...")
    
    try:
        # Read the chats template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/chats.html")
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for modal-xl class in the conversation details modal
        modal_start = content.find('id="conversation-details-modal"')
        if modal_start == -1:
            print("❌ conversation-details-modal not found")
            return False
        
        # Find the modal-dialog section after the modal
        dialog_start = content.find('modal-dialog', modal_start)
        dialog_end = content.find('>', dialog_start)
        if dialog_start == -1 or dialog_end == -1:
            print("❌ modal-dialog section not found")
            return False
        
        dialog_section = content[dialog_start:dialog_end]
        
        # Check for modal-xl and not modal-lg
        if 'modal-xl' in dialog_section and 'modal-lg' not in dialog_section:
            print("✅ Modal width enhanced to modal-xl")
            return True
        elif 'modal-lg' in dialog_section:
            print("❌ Modal still using modal-lg instead of modal-xl")
            return False
        else:
            print("❌ modal-xl class not found for conversation details modal")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_css_modal_xl_support():
    """Test that the CSS has been updated to support modal-xl."""
    print("🔍 Testing CSS modal-xl support...")
    
    try:
        # Read the chats template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/chats.html")
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for modal-xl CSS styling
        if '#conversation-details-modal .modal-xl' in content:
            # Check that it has appropriate max-width (should be wider than 900px)
            if 'max-width: 1200px' in content or 'max-width: 1140px' in content:
                print("✅ CSS updated to support modal-xl with appropriate width")
                return True
            else:
                print("❌ CSS found for modal-xl but may not have appropriate width")
                return False
        else:
            print("❌ CSS for modal-xl not found")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_code_element_styling():
    """Test that code elements have styling to prevent wrapping."""
    print("🔍 Testing code element styling for conversation ID...")
    
    try:
        # Read the chats template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/chats.html")
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for code styling that prevents wrapping
        if '#conversation-details-modal code' in content:
            # Find the code CSS block
            code_css_start = content.find('#conversation-details-modal code')
            code_css_end = content.find('}', code_css_start)
            if code_css_end == -1:
                print("❌ Code CSS block not properly closed")
                return False
            
            code_css_block = content[code_css_start:code_css_end]
            
            # Check for wrap prevention properties
            wrap_prevention_properties = [
                'white-space: nowrap',
                'overflow-x: auto',
                'display: inline-block',
                'max-width: 100%'
            ]
            
            missing_properties = []
            for prop in wrap_prevention_properties:
                if prop not in code_css_block:
                    missing_properties.append(prop)
            
            if not missing_properties:
                print("✅ Code elements have proper styling to prevent wrapping")
                return True
            else:
                print(f"❌ Missing CSS properties for wrap prevention: {missing_properties}")
                return False
        else:
            print("❌ CSS for code elements not found")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_no_modal_lg_references():
    """Test that old modal-lg references have been removed."""
    print("🔍 Testing removal of old modal-lg references...")
    
    try:
        # Read the chats template
        template_path = os.path.join(os.path.dirname(__file__), "../application/single_app/templates/chats.html")
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for any remaining modal-lg references in conversation details modal context
        conversation_modal_start = content.find('id="conversation-details-modal"')
        if conversation_modal_start == -1:
            print("❌ conversation-details-modal not found")
            return False
        
        # Look for modal-lg in CSS or HTML after the modal definition
        modal_section_end = content.find('</div>', conversation_modal_start + 1000)  # Rough end of modal
        modal_section = content[conversation_modal_start:modal_section_end] if modal_section_end != -1 else content[conversation_modal_start:]
        
        # Also check CSS section
        css_start = content.find('#conversation-details-modal', 100)  # Should be in CSS section
        css_section = content[css_start:conversation_modal_start] if css_start != -1 and css_start < conversation_modal_start else ""
        
        combined_section = css_section + modal_section
        
        if 'modal-lg' not in combined_section:
            print("✅ No old modal-lg references found in conversation details modal")
            return True
        else:
            print("❌ Found remaining modal-lg references that should be updated")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Testing Conversation Metadata Modal Width Enhancements...")
    print("=" * 70)
    
    tests = [
        test_modal_width_enhancement,
        test_css_modal_xl_support,
        test_code_element_styling,
        test_no_modal_lg_references
    ]
    
    results = []
    
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())
    
    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    
    if success:
        print("✅ All tests passed! Conversation metadata modal enhancements are working correctly.")
        print("\n🎯 Enhancement Summary:")
        print("   • Modal width increased from modal-lg to modal-xl")
        print("   • CSS updated to support the wider modal (1200px max-width)")
        print("   • Code elements styled to prevent conversation ID wrapping")
        print("   • Old modal-lg references properly updated")
    else:
        print("❌ Some tests failed. Please review the enhancements.")
    
    sys.exit(0 if success else 1)
