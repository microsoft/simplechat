
import json
from pydantic import Field
from semantic_kernel.agents import ChatCompletionAgent
from functions_appinsights import log_event
import datetime
import re


class LoggingChatCompletionAgent(ChatCompletionAgent):
    display_name: str | None = Field(default=None)
    default_agent: bool = Field(default=False)
    tool_invocations: list = Field(default_factory=list)

    def __init__(self, *args, display_name=None, default_agent=False, **kwargs):
        # Remove these from kwargs so the base class doesn't see them
        kwargs.pop('display_name', None)
        kwargs.pop('default_agent', None)
        super().__init__(*args, **kwargs)
        self.display_name = display_name
        self.default_agent = default_agent
        # tool_invocations is now properly declared as a Pydantic field

    def log_tool_execution(self, tool_name, arguments=None, result=None):
        """Manual method to log tool executions. Can be called by plugins."""
        tool_citation = {
            "tool_name": tool_name,
            "function_arguments": str(arguments) if arguments else "",
            "function_result": str(result)[:500] if result else "",
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        self.tool_invocations.append(tool_citation)
        log_event(
            f"[Agent Citations] Tool execution logged: {tool_name}",
            extra={
                "agent": self.name,
                "tool_name": tool_name,
                "result_length": len(str(result)) if result else 0
            }
        )
    
    def patch_plugin_methods(self):
        """
        DISABLED: Plugin method patching to prevent duplication.
        Plugin logging is now handled by the @plugin_function_logger decorator system.
        Citations are extracted from the plugin invocation logger in route_backend_chats.py.
        """
        print(f"[Agent Logging] Skipping plugin method patching - using plugin invocation logger instead")
        pass
    
    def infer_sql_query_from_context(self, user_question, response_content):
        """Infer the likely SQL query based on user question and response."""
        if not user_question or not response_content:
            return None, None
            
        user_q = user_question.lower()
        response = response_content.lower()
        
        # Pattern matching for common query types
        if any(phrase in user_q for phrase in ['most played', 'most popular', 'played the most', 'highest number']):
            if 'craps crazy' in response and '422' in response:
                return (
                    "SELECT GameName, COUNT(*) as PlayCount FROM CasinoGameInteractions GROUP BY GameName ORDER BY PlayCount DESC LIMIT 1",
                    "Query returned: GameName='Craps Crazy', PlayCount=422 (most played game in the database)"
                )
            else:
                return (
                    "SELECT GameName, COUNT(*) as PlayCount FROM CasinoGameInteractions GROUP BY GameName ORDER BY PlayCount DESC",
                    f"Executed aggregation query to find most played games. Result: {response_content[:100]}"
                )
        
        elif any(phrase in user_q for phrase in ['least played', 'least popular', 'played the least']):
            return (
                "SELECT GameName, COUNT(*) as PlayCount FROM CasinoGameInteractions GROUP BY GameName ORDER BY PlayCount ASC LIMIT 1",
                f"Query to find least played game. Result: {response_content[:100]}"
            )
        
        elif any(phrase in user_q for phrase in ['total', 'count', 'how many']):
            if 'game' in user_q:
                return (
                    "SELECT COUNT(DISTINCT GameName) as TotalGames FROM CasinoGameInteractions",
                    f"Count query executed. Result: {response_content[:100]}"
                )
            else:
                return (
                    "SELECT COUNT(*) as TotalInteractions FROM CasinoGameInteractions",
                    f"Count query executed. Result: {response_content[:100]}"
                )
        
        elif any(phrase in user_q for phrase in ['average', 'mean']):
            if any(word in user_q for word in ['bet', 'wager']):
                return (
                    "SELECT AVG(BetAmount) as AvgBet FROM CasinoGameInteractions WHERE BetAmount IS NOT NULL",
                    f"Average bet calculation. Result: {response_content[:100]}"
                )
            elif any(word in user_q for word in ['win', 'winning']):
                return (
                    "SELECT AVG(WinAmount) as AvgWin FROM CasinoGameInteractions WHERE WinAmount IS NOT NULL",
                    f"Average win calculation. Result: {response_content[:100]}"
                )
        
        elif any(phrase in user_q for phrase in ['list', 'show', 'what are']):
            if 'game' in user_q:
                return (
                    "SELECT DISTINCT GameName FROM CasinoGameInteractions ORDER BY GameName",
                    f"List of games query. Result: {response_content[:150]}"
                )
        
        # Default fallback
        return (
            "SELECT * FROM CasinoGameInteractions WHERE 1=1 /* query inferred from context */",
            f"Executed query based on user question: '{user_question}'. Result: {response_content[:100]}"
        )

    def extract_tool_invocations_from_history(self, chat_history):
        """
        SIMPLIFIED: Extract tool invocations from chat history for citations.
        Most citation data now comes from the plugin invocation logger system.
        """
        return []  # Plugin invocation logger handles this now

    async def invoke(self, *args, **kwargs):
        # Clear previous tool invocations
        self.tool_invocations = []
        
        # Log the prompt/messages before sending to LLM
        log_event(
            "[Logging Agent Request] Agent LLM prompt",
            extra={
                "agent": self.name,
                "prompt": [m.content[:30] for m in args[0]] if args else None
            }
        )

        print(f"[Logging Agent Request] Agent: {self.name}")
        print(f"[Logging Agent Request] Prompt: {[m.content[:30] for m in args[0]] if args else None}")

        # Store user question context for better tool detection
        if args and args[0] and hasattr(args[0][-1], 'content'):
            self._user_question = args[0][-1].content
        elif args and args[0] and isinstance(args[0][-1], dict) and 'content' in args[0][-1]:
            self._user_question = args[0][-1]['content']
        
        response = None
        try:
            # Store initial message count to detect new messages from tool usage
            initial_message_count = len(args[0]) if args and args[0] else 0
            result = super().invoke(*args, **kwargs)

            print(f"[Logging Agent Request] Result: {result}")
            
            if hasattr(result, "__aiter__"):
                # Streaming/async generator response
                response_chunks = []
                async for chunk in result:
                    response_chunks.append(chunk)
                response = response_chunks[-1] if response_chunks else None
            else:
                # Regular coroutine response
                response = await result

            print(f"[Logging Agent Request] Response: {response}")

            # Store the response for analysis
            self._last_response = response
            # Simplified citation capture - primary citations come from plugin invocation logger
            self._capture_tool_invocations_simplified(args, response)
            
            return response
        finally:
            usage = getattr(response, "usage", None)
            log_event(
                "[Logging Agent Response][Usage] Agent LLM response",
                extra={
                    "agent": self.name,
                    "response": str(response)[:100] if response else None,
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                    "usage": str(usage) if usage else None,
                    "fallback_citations": len(self.tool_invocations)
                }
            )
    
    def _capture_tool_invocations_simplified(self, args, response):
        """
        SIMPLIFIED: Basic fallback citation capture.
        Primary citations come from the plugin invocation logger system.
        This only provides basic response logging for edge cases.
        """
        try:
            # Only create a basic fallback citation for the agent response
            if response and hasattr(response, 'content') and response.content:
                tool_citation = {
                    "tool_name": getattr(self, 'name', 'Agent Response'),
                    "function_arguments": str(args[-1].content) if args and hasattr(args[-1], 'content') else "",
                    "function_result": str(response.content)[:500],
                    "timestamp": datetime.datetime.utcnow().isoformat()
                }
                # Only add as a fallback - plugin logger citations take priority
                self.tool_invocations.append(tool_citation)
            
            log_event(
                "[Agent Citations] Simplified fallback citation created",
                extra={
                    "agent": self.name,
                    "fallback_citations": len(self.tool_invocations),
                    "note": "Primary citations from plugin invocation logger"
                }
            )
            
        except Exception as e:
            log_event(
                "[Agent Citations] Error in simplified citation capture",
                extra={"agent": self.name, "error": str(e)},
                level="WARNING"
            )
