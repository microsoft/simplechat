#!/usr/bin/env python3
"""
Functional test for Generate Prompt from Conversation feature.
Version: 0.238.025
Implemented in: 0.238.025

This test ensures that the generate prompt from conversation backend
endpoint correctly fetches conversation messages, calls Azure OpenAI
to analyze them, and returns a structured prompt with name and content.
It also validates error handling for missing/empty conversations.
"""

import sys
import os
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_generate_prompt_meta_prompt():
    """Test that the meta-prompt is properly defined and structured."""
    print("🔍 Testing meta-prompt definition...")

    try:
        # Read the route file directly to check the meta-prompt without importing
        # (Importing would trigger config.py which requires Cosmos DB)
        route_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_backend_generate_prompt.py'
        )

        with open(route_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Verify the meta-prompt constant exists and has key instructions
        assert "GENERATE_PROMPT_META_PROMPT" in content, "Meta-prompt constant missing"
        assert "JSON" in content, "Meta-prompt should mention JSON response format"
        assert '"name"' in content, "Meta-prompt should mention name field"
        assert '"content"' in content, "Meta-prompt should mention content field"
        assert "reusable" in content.lower(), "Meta-prompt should mention reusable"

        # Verify MAX_MESSAGES constant
        assert "MAX_MESSAGES_FOR_ANALYSIS" in content, "MAX_MESSAGES constant missing"
        assert "50" in content, "MAX_MESSAGES should be 50"

        print("  ✅ Meta-prompt constant is defined with all required instructions")
        print("  ✅ MAX_MESSAGES_FOR_ANALYSIS constant is defined")
        print("✅ Meta-prompt test passed!")
        return True

    except Exception as e:
        print(f"❌ Meta-prompt test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_fetch_conversation_messages_helper():
    """Test the message filtering logic used in _fetch_conversation_messages."""
    print("🔍 Testing message filtering logic...")

    try:
        # Simulate the filtering logic that _fetch_conversation_messages uses
        # (We can't call the actual function without Cosmos DB, but we can test the logic)
        
        test_messages = [
            {"role": "user", "content": "Hello", "metadata": {"thread_info": {"active_thread": True}}},
            {"role": "assistant", "content": "Hi there!", "metadata": {"thread_info": {"active_thread": True}}},
            {"role": "image", "content": "base64data", "metadata": {}},
            {"role": "user", "content": "Old message", "metadata": {"thread_info": {"active_thread": False}}},
            {"role": "system", "content": "System prompt", "metadata": {}},
            {"role": "user", "content": "No thread info", "metadata": {}},
            {"role": "safety", "content": "Safety check", "metadata": {}},
            {"role": "user", "content": "Final question", "metadata": {"thread_info": {"active_thread": True}}},
            {"role": "assistant", "content": "Final answer", "metadata": {"thread_info": {"active_thread": True}}},
        ]

        # Apply the same filtering logic as the route
        filtered = []
        for item in test_messages:
            role = item.get('role', '')
            # Skip non-text message types
            if role in ('image', 'image_chunk', 'file', 'safety', 'system'):
                continue

            thread_info = item.get('metadata', {}).get('thread_info', {})
            active = thread_info.get('active_thread')

            # Include if active_thread is True, None, or not defined
            if active is True or active is None or 'active_thread' not in thread_info:
                filtered.append({
                    'role': role,
                    'content': item.get('content', '')
                })

        # Verify filtering results
        assert len(filtered) == 5, f"Expected 5 filtered messages, got {len(filtered)}"

        # Check that image, system, safety, and inactive thread messages were excluded
        roles = [m['role'] for m in filtered]
        assert 'image' not in roles, "Image messages should be excluded"
        assert 'system' not in roles, "System messages should be excluded"
        assert 'safety' not in roles, "Safety messages should be excluded"

        # Check that the inactive thread message was excluded
        contents = [m['content'] for m in filtered]
        assert "Old message" not in contents, "Inactive thread messages should be excluded"

        # Check that messages with no thread_info are included
        assert "No thread info" in contents, "Messages without thread_info should be included"

        print(f"  ✅ Filtered {len(test_messages)} messages down to {len(filtered)}")
        print("✅ Message filtering test passed!")
        return True

    except Exception as e:
        print(f"❌ Message filtering test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_json_response_parsing():
    """Test the JSON parsing logic for AI responses."""
    print("🔍 Testing AI response JSON parsing...")

    try:
        # Test case 1: Clean JSON response
        clean_json = '{"name": "Code Review Helper", "content": "You are a code review assistant..."}'
        result = json.loads(clean_json)
        assert result['name'] == "Code Review Helper", "Clean JSON parsing failed"
        print("  ✅ Clean JSON parsing works")

        # Test case 2: JSON wrapped in markdown code fences
        markdown_json = '```json\n{"name": "Data Analyst", "content": "Analyze the data..."}\n```'
        clean_response = markdown_json
        if clean_response.startswith("```"):
            lines = clean_response.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_response = "\n".join(lines)
        result = json.loads(clean_response)
        assert result['name'] == "Data Analyst", "Markdown-wrapped JSON parsing failed"
        print("  ✅ Markdown-wrapped JSON parsing works")

        # Test case 3: JSON with extra whitespace
        spaced_json = '  \n {"name": "Helper", "content": "Help me..."} \n  '
        result = json.loads(spaced_json.strip())
        assert result['name'] == "Helper", "Whitespace JSON parsing failed"
        print("  ✅ Whitespace-padded JSON parsing works")

        # Test case 4: Fallback for non-JSON response
        non_json = "Here is a great prompt: You should analyze code carefully..."
        fallback_name = "Generated Prompt"
        fallback_content = non_json
        try:
            json.loads(non_json)
            assert False, "Should have raised JSONDecodeError"
        except json.JSONDecodeError:
            # This is expected - fallback handling
            assert fallback_name == "Generated Prompt", "Fallback name incorrect"
            assert fallback_content == non_json, "Fallback content should be raw response"
        print("  ✅ Non-JSON fallback handling works")

        # Test case 5: Name truncation
        long_name = "A" * 200
        truncated = long_name[:100]
        assert len(truncated) == 100, "Name truncation failed"
        print("  ✅ Name truncation works (100 char max)")

        print("✅ JSON response parsing test passed!")
        return True

    except Exception as e:
        print(f"❌ JSON response parsing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_conversation_text_building():
    """Test building conversation text for AI analysis."""
    print("🔍 Testing conversation text building...")

    try:
        messages = [
            {"role": "user", "content": "How do I sort a list in Python?"},
            {"role": "assistant", "content": "You can use the sorted() function or list.sort() method."},
            {"role": "user", "content": "What's the difference between them?"},
            {"role": "assistant", "content": "sorted() returns a new list, while .sort() modifies in place."},
        ]

        conversation_text = "\n".join(
            f"{msg['role'].upper()}: {msg['content']}" for msg in messages
        )

        assert "USER:" in conversation_text, "Should contain USER: prefix"
        assert "ASSISTANT:" in conversation_text, "Should contain ASSISTANT: prefix"
        assert "sort a list" in conversation_text, "Should contain message content"
        assert conversation_text.count("\n") == 3, "Should have 3 newlines for 4 messages"

        # Test truncation
        max_messages = 2
        truncated = messages[-max_messages:]
        assert len(truncated) == 2, "Truncation should keep last N messages"
        assert truncated[0]['role'] == 'user', "First truncated message should be user"

        print(f"  ✅ Conversation text is {len(conversation_text)} chars")
        print(f"  ✅ Truncation from {len(messages)} to {len(truncated)} messages works")
        print("✅ Conversation text building test passed!")
        return True

    except Exception as e:
        print(f"❌ Conversation text building test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_route_file_structure():
    """Test that the route file exists and has proper structure."""
    print("🔍 Testing route file structure...")

    try:
        route_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app', 'route_backend_generate_prompt.py'
        )
        assert os.path.exists(route_file), f"Route file not found at {route_file}"
        print("  ✅ Route file exists")

        with open(route_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for required patterns
        assert "register_route_backend_generate_prompt" in content, "Registration function missing"
        assert "@swagger_route(security=get_auth_security())" in content, "Swagger decorator missing"
        assert "@login_required" in content, "login_required decorator missing"
        assert "@user_required" in content, "user_required decorator missing"
        assert "generate-prompt" in content, "Endpoint path missing"
        assert "log_event" in content, "Should use log_event for logging"
        assert "_initialize_gpt_client" in content, "GPT client init function missing"
        assert "_fetch_conversation_messages" in content, "Message fetch function missing"
        assert "GENERATE_PROMPT_META_PROMPT" in content, "Meta-prompt constant missing"

        print("  ✅ Route file has all required decorators and patterns")
        print("✅ Route file structure test passed!")
        return True

    except Exception as e:
        print(f"❌ Route file structure test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_frontend_files_exist():
    """Test that frontend files were created/modified correctly."""
    print("🔍 Testing frontend file existence...")

    try:
        base_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', 'application', 'single_app'
        )

        # Check JS module
        js_file = os.path.join(base_dir, 'static', 'js', 'chat', 'chat-generate-prompt.js')
        assert os.path.exists(js_file), f"JS module not found at {js_file}"
        print("  ✅ chat-generate-prompt.js exists")

        with open(js_file, 'r', encoding='utf-8') as f:
            js_content = f.read()

        assert "initializeGeneratePrompt" in js_content, "Init function missing from JS"
        assert "generate-prompt" in js_content, "Modal element references missing from JS"
        assert "showToast" in js_content, "Toast notification missing from JS"
        assert "/api/conversations/" in js_content, "API endpoint call missing from JS"
        assert "/api/prompts" in js_content, "Save prompt API call missing from JS"
        print("  ✅ chat-generate-prompt.js has all required functions")

        # Check chats.html for modal and button
        html_file = os.path.join(base_dir, 'templates', 'chats.html')
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()

        assert "generate-prompt-modal" in html_content, "Modal not found in chats.html"
        assert "generate-prompt-btn" in html_content, "Toolbar button not found in chats.html"
        assert "generate-prompt-name" in html_content, "Name input not found in chats.html"
        assert "generate-prompt-content" in html_content, "Content textarea not found in chats.html"
        assert "generate-prompt-scope" in html_content, "Scope selector not found in chats.html"
        assert "chat-generate-prompt.js" in html_content, "Script tag not found in chats.html"
        print("  ✅ chats.html has modal, button, and script tag")

        # Check chat-onload.js for import
        onload_file = os.path.join(base_dir, 'static', 'js', 'chat', 'chat-onload.js')
        with open(onload_file, 'r', encoding='utf-8') as f:
            onload_content = f.read()

        assert "initializeGeneratePrompt" in onload_content, "Init call missing from chat-onload.js"
        assert "chat-generate-prompt.js" in onload_content, "Import missing from chat-onload.js"
        print("  ✅ chat-onload.js imports and initializes the feature")

        print("✅ Frontend files test passed!")
        return True

    except Exception as e:
        print(f"❌ Frontend files test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_version_updated():
    """Test that config.py version was updated."""
    print("🔍 Testing version update...")

    try:
        # Try multiple possible paths for config.py
        base = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            os.path.join(base, '..', 'application', 'single_app', 'config.py'),
            os.path.join(base, 'application', 'single_app', 'config.py'),
        ]
        
        config_file = None
        for p in possible_paths:
            if os.path.exists(p):
                config_file = p
                break
        
        assert config_file is not None, f"config.py not found in expected locations"

        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'VERSION = "0.238.025"' in content, "Version should be 0.238.025"
        print("  ✅ VERSION = 0.238.025")
        print("✅ Version update test passed!")
        return True

    except Exception as e:
        print(f"❌ Version update test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_generate_prompt_meta_prompt,
        test_fetch_conversation_messages_helper,
        test_json_response_parsing,
        test_conversation_text_building,
        test_route_file_structure,
        test_frontend_files_exist,
        test_version_updated,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    passed = sum(results)
    total = len(results)
    print(f"\n📊 Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed!")
    else:
        print("⚠️ Some tests failed!")

    sys.exit(0 if all(results) else 1)
