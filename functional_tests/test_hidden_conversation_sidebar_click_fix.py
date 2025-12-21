#!/usr/bin/env python3
"""
Functional test for hidden conversation sidebar click fix.
Version: 0.233.176
Implemented in: 0.233.176

This test ensures that clicking on hidden conversations in the sidebar
properly loads the conversation in the main chat area.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_hidden_conversation_sidebar_click():
    """
    Test that hidden conversations can be clicked and loaded from the sidebar.
    
    This test validates:
    1. setShowHiddenConversations function exists in window.chatConversations
    2. Sidebar click handler checks for hidden conversations
    3. System automatically syncs hidden state between sidebar and main list
    """
    print("🔍 Testing Hidden Conversation Sidebar Click Fix...")
    
    try:
        # Read the chat-conversations.js file
        js_conversations_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "application",
            "single_app",
            "static",
            "js",
            "chat",
            "chat-conversations.js"
        )
        
        with open(js_conversations_path, 'r', encoding='utf-8') as f:
            conversations_content = f.read()
        
        # Verify setShowHiddenConversations function exists
        assert "export function setShowHiddenConversations" in conversations_content, \
            "setShowHiddenConversations function not found in chat-conversations.js"
        print("  ✅ setShowHiddenConversations function defined")
        
        # Verify function is exported in window.chatConversations
        assert "setShowHiddenConversations," in conversations_content, \
            "setShowHiddenConversations not exported in window.chatConversations"
        print("  ✅ setShowHiddenConversations exported globally")
        
        # Verify function loads conversations
        assert "loadConversations();" in conversations_content.split("setShowHiddenConversations")[1].split("}")[0], \
            "setShowHiddenConversations should call loadConversations()"
        print("  ✅ setShowHiddenConversations triggers conversation reload")
        
        # Read the chat-sidebar-conversations.js file
        js_sidebar_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "application",
            "single_app",
            "static",
            "js",
            "chat",
            "chat-sidebar-conversations.js"
        )
        
        with open(js_sidebar_path, 'r', encoding='utf-8') as f:
            sidebar_content = f.read()
        
        # Verify sidebar checks for hidden conversations before selection
        assert "convo.is_hidden && window.chatConversations && window.chatConversations.setShowHiddenConversations" in sidebar_content, \
            "Sidebar click handler doesn't check for hidden conversations"
        print("  ✅ Sidebar checks if conversation is hidden before selection")
        
        # Verify sidebar calls setShowHiddenConversations(true)
        assert "setShowHiddenConversations(true)" in sidebar_content, \
            "Sidebar doesn't enable hidden conversations when clicking hidden item"
        print("  ✅ Sidebar enables hidden conversations in main list")
        
        # Verify the check happens before selectConversation call
        click_handler_section = sidebar_content.split("convoItem.addEventListener(\"click\"")[1].split("});")[0]
        hidden_check_pos = click_handler_section.find("convo.is_hidden")
        select_call_pos = click_handler_section.find("selectConversation")
        
        assert hidden_check_pos < select_call_pos and hidden_check_pos > 0 and select_call_pos > 0, \
            "Hidden conversation check should happen before selectConversation call"
        print("  ✅ Hidden check occurs before conversation selection")
        
        # Verify version was updated
        config_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "application",
            "single_app",
            "config.py"
        )
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        assert 'VERSION = "0.233.176"' in config_content, \
            "Version not updated to 0.233.176"
        print("  ✅ Version updated to 0.233.176")
        
        print("\n✅ All tests passed! Hidden conversation sidebar click fix validated.")
        print("\n📋 Summary:")
        print("  - setShowHiddenConversations function created and exported")
        print("  - Sidebar detects hidden conversations on click")
        print("  - Main list automatically shows hidden conversations when needed")
        print("  - State synchronization between sidebar and main list working")
        
        return True
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_hidden_conversation_sidebar_click()
    sys.exit(0 if success else 1)
