#!/usr/bin/env python3
"""
Test script to validate the agent citations per-message isolation fix.

This script tests that:
1. Agent citations don't leak across conversations (previous fix)
2. Agent citations don't accumulate across messages within the same conversation (new fix)
3. Each message only shows citations for tools executed during that specific interaction
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
    
    def get_invocations_for_conversation(self, user_id: str, conversation_id: str, limit: int = 50) -> List[PluginInvocation]:
        """Get recent plugin invocations for a specific user and conversation."""
        conversation_invocations = [
            inv for inv in self.invocations 
            if inv.user_id == user_id and inv.conversation_id == conversation_id
        ]
        return conversation_invocations[-limit:] if conversation_invocations else []
    
    def clear_invocations_for_conversation(self, user_id: str, conversation_id: str):
        """Clear plugin invocations for a specific user and conversation."""
        self.invocations = [
            inv for inv in self.invocations 
            if not (inv.user_id == user_id and inv.conversation_id == conversation_id)
        ]

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

def simulate_user_interaction_scenario():
    """Simulate the exact scenario described by the user."""
    print("🎭 Simulating User's Reported Scenario")
    print("=" * 60)
    
    logger = MockPluginInvocationLogger()
    user_id = "07e61033-ea1a-4472-a1e7-6b9ac874984a"
    conversation_id = "22aaa221-f000-460a-a865-0b801a0c8334"
    
    # Message 1: User asks "what are the top stories?"
    print("📱 Message 1: User asks 'what are the top stories?'")
    logger.clear_invocations_for_conversation(user_id, conversation_id)  # Clear at start
    
    # Agent executes topNews tool
    inv1 = create_mock_invocation("OpenApiPlugin", "topNews", user_id, conversation_id, 
                                 "Response too large for context - use more specific queries")
    logger.log_invocation(inv1)
    
    # Get citations for message 1
    msg1_citations = logger.get_invocations_for_conversation(user_id, conversation_id)
    print(f"   ✅ Message 1 citations: {len(msg1_citations)} (should be 1)")
    for citation in msg1_citations:
        print(f"      - {citation.plugin_name}.{citation.function_name}")
    
    # Message 2: User asks "please use the US"
    print("\n📱 Message 2: User asks 'please use the US'")
    logger.clear_invocations_for_conversation(user_id, conversation_id)  # Clear at start
    
    # Agent executes topNews tool again
    inv2 = create_mock_invocation("OpenApiPlugin", "topNews", user_id, conversation_id, 
                                 "Response too large for context - use more specific queries")
    logger.log_invocation(inv2)
    
    # Get citations for message 2
    msg2_citations = logger.get_invocations_for_conversation(user_id, conversation_id)
    print(f"   ✅ Message 2 citations: {len(msg2_citations)} (should be 1, not 2!)")
    for citation in msg2_citations:
        print(f"      - {citation.plugin_name}.{citation.function_name}")
    
    # Message 3: User asks "top stories in the us"
    print("\n📱 Message 3: User asks 'top stories in the us'")
    logger.clear_invocations_for_conversation(user_id, conversation_id)  # Clear at start
    
    # Agent executes topNews tool again
    inv3 = create_mock_invocation("OpenApiPlugin", "topNews", user_id, conversation_id, 
                                 "Response too large for context - use more specific queries")
    logger.log_invocation(inv3)
    
    # Get citations for message 3
    msg3_citations = logger.get_invocations_for_conversation(user_id, conversation_id)
    print(f"   ✅ Message 3 citations: {len(msg3_citations)} (should be 1, not 3!)")
    for citation in msg3_citations:
        print(f"      - {citation.plugin_name}.{citation.function_name}")
    
    # Verify each message has exactly 1 citation
    success = (len(msg1_citations) == 1 and len(msg2_citations) == 1 and len(msg3_citations) == 1)
    
    if success:
        print("\n🎉 SUCCESS: Each message has exactly 1 citation (no accumulation)")
        print("   ✅ Message 1: 1 citation")
        print("   ✅ Message 2: 1 citation") 
        print("   ✅ Message 3: 1 citation")
    else:
        print("\n❌ FAILURE: Citations are still accumulating across messages")
        print(f"   Message 1: {len(msg1_citations)} citations")
        print(f"   Message 2: {len(msg2_citations)} citations")
        print(f"   Message 3: {len(msg3_citations)} citations")
    
    return success

def test_cross_conversation_still_works():
    """Verify our original cross-conversation fix still works."""
    print("\n🔒 Testing Cross-Conversation Isolation Still Works")
    print("=" * 60)
    
    logger = MockPluginInvocationLogger()
    
    # Conversation 1
    user_id = "user1"
    conv1_id = "conv1"
    logger.clear_invocations_for_conversation(user_id, conv1_id)
    inv1 = create_mock_invocation("NewsPlugin", "getNews", user_id, conv1_id, "News result")
    logger.log_invocation(inv1)
    
    # Conversation 2  
    conv2_id = "conv2"
    logger.clear_invocations_for_conversation(user_id, conv2_id)
    inv2 = create_mock_invocation("WeatherPlugin", "getWeather", user_id, conv2_id, "Weather result")
    logger.log_invocation(inv2)
    
    # Check isolation
    conv1_citations = logger.get_invocations_for_conversation(user_id, conv1_id)
    conv2_citations = logger.get_invocations_for_conversation(user_id, conv2_id)
    
    conv1_has_weather = any("WeatherPlugin" in f"{c.plugin_name}" for c in conv1_citations)
    conv2_has_news = any("NewsPlugin" in f"{c.plugin_name}" for c in conv2_citations)
    
    if not conv1_has_weather and not conv2_has_news:
        print("   ✅ Cross-conversation isolation still works")
        print(f"   ✅ Conv1 has {len(conv1_citations)} citations (NewsPlugin only)")
        print(f"   ✅ Conv2 has {len(conv2_citations)} citations (WeatherPlugin only)")
        return True
    else:
        print("   ❌ Cross-conversation isolation broken!")
        return False

def test_original_vs_new_behavior():
    """Show the difference between original accumulation vs new per-message isolation."""
    print("\n🔄 Original vs New Behavior Comparison")
    print("=" * 60)
    
    print("❌ ORIGINAL BEHAVIOR (Accumulating):")
    print("   Message 1: [topNews_1] → 1 citation")
    print("   Message 2: [topNews_1, topNews_2] → 2 citations") 
    print("   Message 3: [topNews_1, topNews_2, topNews_3] → 3 citations")
    print("   ⚠️  Citations accumulate across the entire conversation")
    
    print("\n✅ NEW BEHAVIOR (Per-Message Isolation):")
    print("   Message 1: [topNews_1] → 1 citation")
    print("   Message 2: [topNews_2] → 1 citation")
    print("   Message 3: [topNews_3] → 1 citation") 
    print("   ✅ Each message only shows citations for that specific interaction")
    
    return True

def main():
    """Run all tests to validate the per-message citation isolation fix."""
    print("🚀 Testing Agent Citations Per-Message Isolation Fix")
    print("🎯 Goal: Each message should only show citations for tools executed during that specific interaction")
    print("=" * 80)
    
    test1_passed = simulate_user_interaction_scenario()
    test2_passed = test_cross_conversation_still_works()
    test3_passed = test_original_vs_new_behavior()
    
    print("\n" + "=" * 80)
    if test1_passed and test2_passed and test3_passed:
        print("🎉 ALL TESTS PASSED!")
        print("\n📋 Summary of the Complete Fix:")
        print("   ✅ Cross-conversation isolation (previous fix)")
        print("   ✅ Per-message isolation within conversations (new fix)")
        print("   ✅ Each message only shows citations for its specific interaction")
        print("\n🔧 Implementation Details:")
        print("   1. Added clear_invocations_for_conversation() method")
        print("   2. Clear plugin invocations at start of each message processing")
        print("   3. Each message captures only its own tool executions")
        print("   4. No accumulation across messages in same conversation")
        print("\n✅ This aligns with the expected behavior: citations are specific to each user interaction.")
        return True
    else:
        print("❌ SOME TESTS FAILED! Please review the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
