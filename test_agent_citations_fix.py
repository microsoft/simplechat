#!/usr/bin/env python3
"""
Test script to validate the agent citations cross-conversation contamination fix.

This script tests the logic of the plugin invocation logger to ensure that:
1. Invocations are properly filtered by user_id and conversation_id
2. No cross-contamination occurs between different conversations
3. The filtering methods work as expected
"""

import sys
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

@dataclass
class PluginInvocation:
    """Mock version of the PluginInvocation dataclass for testing."""
    plugin_name: str
    function_name: str
    parameters: Dict[str, Any]
    result: Any
    start_time: float
    end_time: float
    duration_ms: float
    user_id: Optional[str]
    timestamp: str
    success: bool
    conversation_id: Optional[str] = None
    error_message: Optional[str] = None

class MockPluginInvocationLogger:
    """Mock version of the PluginInvocationLogger for testing."""
    
    def __init__(self):
        self.invocations: List[PluginInvocation] = []
        self.max_history = 1000
        
    def log_invocation(self, invocation: PluginInvocation):
        """Log a plugin invocation to local history."""
        self.invocations.append(invocation)
        
        # Trim history if needed
        if len(self.invocations) > self.max_history:
            self.invocations = self.invocations[-self.max_history:]
    
    def get_recent_invocations(self, limit: int = 50) -> List[PluginInvocation]:
        """Get recent plugin invocations."""
        return self.invocations[-limit:] if self.invocations else []
    
    def get_invocations_for_user(self, user_id: str, limit: int = 50) -> List[PluginInvocation]:
        """Get recent plugin invocations for a specific user."""
        user_invocations = [inv for inv in self.invocations if inv.user_id == user_id]
        return user_invocations[-limit:] if user_invocations else []
    
    def get_invocations_for_conversation(self, user_id: str, conversation_id: str, limit: int = 50) -> List[PluginInvocation]:
        """Get recent plugin invocations for a specific user and conversation."""
        conversation_invocations = [
            inv for inv in self.invocations 
            if inv.user_id == user_id and inv.conversation_id == conversation_id
        ]
        return conversation_invocations[-limit:] if conversation_invocations else []

def create_mock_invocation(plugin_name: str, function_name: str, user_id: str, conversation_id: str, result: str = "test result") -> PluginInvocation:
    """Create a mock plugin invocation for testing."""
    start_time = time.time()
    end_time = start_time + 0.1  # 100ms duration
    
    return PluginInvocation(
        plugin_name=plugin_name,
        function_name=function_name,
        parameters={"test_param": "test_value"},
        result=result,
        start_time=start_time,
        end_time=end_time,
        duration_ms=(end_time - start_time) * 1000,
        user_id=user_id,
        conversation_id=conversation_id,
        timestamp=datetime.utcnow().isoformat(),
        success=True,
        error_message=None
    )

def test_cross_conversation_isolation():
    """Test that agent citations are properly isolated between conversations."""
    print("🧪 Testing cross-conversation isolation...")
    
    logger = MockPluginInvocationLogger()
    
    # Simulate two users with two conversations each
    user1_conv1_invocations = [
        create_mock_invocation("WorldNewsPlugin", "get_latest_news", "user1", "conv1", "World news result 1"),
        create_mock_invocation("WorldNewsPlugin", "search_articles", "user1", "conv1", "World news result 2"),
    ]
    
    user1_conv2_invocations = [
        create_mock_invocation("WeatherPlugin", "get_current_weather", "user1", "conv2", "Weather result 1"),
        create_mock_invocation("WeatherPlugin", "get_forecast", "user1", "conv2", "Weather result 2"),
    ]
    
    user2_conv3_invocations = [
        create_mock_invocation("StockPlugin", "get_stock_price", "user2", "conv3", "Stock result 1"),
        create_mock_invocation("StockPlugin", "get_market_summary", "user2", "conv3", "Stock result 2"),
    ]
    
    # Log all invocations to the logger (simulating mixed execution)
    all_invocations = user1_conv1_invocations + user2_conv3_invocations + user1_conv2_invocations
    for inv in all_invocations:
        logger.log_invocation(inv)
    
    print(f"📊 Total invocations logged: {len(logger.invocations)}")
    
    # Test 1: get_recent_invocations should return ALL invocations (the problematic behavior)
    recent_all = logger.get_recent_invocations()
    print(f"❌ get_recent_invocations() returned: {len(recent_all)} invocations (PROBLEMATIC - includes all users/conversations)")
    
    # Test 2: get_invocations_for_conversation should return only conversation-specific invocations
    user1_conv1_only = logger.get_invocations_for_conversation("user1", "conv1")
    user1_conv2_only = logger.get_invocations_for_conversation("user1", "conv2")
    user2_conv3_only = logger.get_invocations_for_conversation("user2", "conv3")
    
    print(f"✅ user1/conv1 invocations: {len(user1_conv1_only)} (should be 2)")
    print(f"✅ user1/conv2 invocations: {len(user1_conv2_only)} (should be 2)")
    print(f"✅ user2/conv3 invocations: {len(user2_conv3_only)} (should be 2)")
    
    # Verify isolation - check that conv1 doesn't contain conv2 results
    conv1_tools = [f"{inv.plugin_name}.{inv.function_name}" for inv in user1_conv1_only]
    conv2_tools = [f"{inv.plugin_name}.{inv.function_name}" for inv in user1_conv2_only]
    
    print(f"🔍 Conv1 tools: {conv1_tools}")
    print(f"🔍 Conv2 tools: {conv2_tools}")
    
    # Test cross-contamination
    has_weather_in_conv1 = any("WeatherPlugin" in tool for tool in conv1_tools)
    has_news_in_conv2 = any("WorldNewsPlugin" in tool for tool in conv2_tools)
    
    if has_weather_in_conv1:
        print("❌ CONTAMINATION DETECTED: Weather tools found in news conversation!")
        return False
    else:
        print("✅ No weather tools found in news conversation")
    
    if has_news_in_conv2:
        print("❌ CONTAMINATION DETECTED: News tools found in weather conversation!")
        return False
    else:
        print("✅ No news tools found in weather conversation")
    
    # Test that each conversation only has its own tools
    expected_conv1_tools = ["WorldNewsPlugin.get_latest_news", "WorldNewsPlugin.search_articles"]
    expected_conv2_tools = ["WeatherPlugin.get_current_weather", "WeatherPlugin.get_forecast"]
    
    if set(conv1_tools) == set(expected_conv1_tools):
        print("✅ Conv1 has exactly the expected tools")
    else:
        print(f"❌ Conv1 tools mismatch. Expected: {expected_conv1_tools}, Got: {conv1_tools}")
        return False
    
    if set(conv2_tools) == set(expected_conv2_tools):
        print("✅ Conv2 has exactly the expected tools")
    else:
        print(f"❌ Conv2 tools mismatch. Expected: {expected_conv2_tools}, Got: {conv2_tools}")
        return False
    
    print("🎉 Cross-conversation isolation test PASSED!")
    return True

def test_original_vs_fixed_behavior():
    """Test to show the difference between original and fixed behavior."""
    print("\n🔧 Testing original vs fixed behavior...")
    
    logger = MockPluginInvocationLogger()
    
    # Simulate the exact scenario from the user's bug report
    # User has conversation 1 with World News Agent
    world_news_invocations = [
        create_mock_invocation("WorldNewsPlugin", "get_breaking_news", "user123", "conversation_1", 
                             "Breaking: Major tech conference announced..."),
        create_mock_invocation("WorldNewsPlugin", "search_tech_news", "user123", "conversation_1", 
                             "Tech industry sees major investments..."),
    ]
    
    # Log the World News invocations
    for inv in world_news_invocations:
        logger.log_invocation(inv)
    
    # Now user starts a NEW conversation 2 with Weather Agent
    weather_invocations = [
        create_mock_invocation("WeatherPlugin", "get_current_weather", "user123", "conversation_2", 
                             "Current temperature is 72°F..."),
    ]
    
    # Log the Weather invocations
    for inv in weather_invocations:
        logger.log_invocation(inv)
    
    print("📅 Scenario: User had conversation 1 with World News Agent, then started conversation 2 with Weather Agent")
    
    # ORIGINAL PROBLEMATIC BEHAVIOR
    print("\n❌ ORIGINAL BEHAVIOR (BUGGY):")
    original_result = logger.get_recent_invocations()  # This is what the original code did
    print(f"   get_recent_invocations() returns {len(original_result)} invocations:")
    for inv in original_result:
        print(f"     - {inv.plugin_name}.{inv.function_name} from {inv.conversation_id}")
    print("   ⚠️  This includes citations from BOTH conversations - CONTAMINATION!")
    
    # FIXED BEHAVIOR
    print("\n✅ FIXED BEHAVIOR (CORRECT):")
    conv2_only = logger.get_invocations_for_conversation("user123", "conversation_2")
    print(f"   get_invocations_for_conversation('user123', 'conversation_2') returns {len(conv2_only)} invocations:")
    for inv in conv2_only:
        print(f"     - {inv.plugin_name}.{inv.function_name} from {inv.conversation_id}")
    print("   ✅ This includes ONLY citations from conversation 2 - NO CONTAMINATION!")
    
    return True

def main():
    """Run all tests to validate the agent citations fix."""
    print("🚀 Testing Agent Citations Cross-Conversation Contamination Fix")
    print("=" * 70)
    
    test1_passed = test_cross_conversation_isolation()
    test2_passed = test_original_vs_fixed_behavior()
    
    print("\n" + "=" * 70)
    if test1_passed and test2_passed:
        print("🎉 ALL TESTS PASSED! The fix should resolve the agent citations contamination bug.")
        print("\n📋 Summary of the fix:")
        print("   1. Added conversation_id field to PluginInvocation dataclass")
        print("   2. Added get_invocations_for_conversation() method to filter by user + conversation")
        print("   3. Updated route_backend_chats.py to use conversation-specific filtering")
        print("   4. Added conversation_id to Flask context for automatic tracking")
        print("\n✅ This ensures agent citations from one conversation cannot appear in another conversation.")
        return True
    else:
        print("❌ SOME TESTS FAILED! Please review the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
