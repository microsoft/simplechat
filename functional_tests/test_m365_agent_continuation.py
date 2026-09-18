# test_m365_agent_continuation.py
"""
Real Semantic Kernel filter/thread regression for Microsoft 365 approvals.
Version: 0.261.029
Implemented in: 0.261.029

Completed calls, including concurrent siblings, are never changed into pending
calls or replayed when a saved thread resumes after approval.
"""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from uuid import uuid4

from flask import Flask, g

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Resolve repository modules only after the standalone test path is configured.
from semantic_kernel import Kernel  # noqa: E402
from semantic_kernel.agents import ChatHistoryAgentThread  # noqa: E402
from semantic_kernel.contents import (  # noqa: E402
    AuthorRole, ChatHistory, ChatMessageContent, FunctionCallContent, FunctionResultContent,
)
from semantic_kernel.functions import KernelArguments, kernel_function  # noqa: E402
import functions_m365_agent_continuation as continuation  # noqa: E402
from functions_m365_approvals import M365ApprovalRequired  # noqa: E402
from functions_m365_execution import M365ExecutionContext  # noqa: E402
from test_support.m365 import CosmosContainer  # noqa: E402


class Memory:
    def __init__(self):
        self.runs = {}
        self.sources = {}
        self.checkpoints = {}

    def create_run(self, context, **kwargs):
        run_id = uuid4().hex
        self.runs[run_id] = kwargs
        return {"run_id": run_id}

    def add_evidence(self, context, run_id, *, source, chunks):
        evidence_id = uuid4().hex
        self.sources[evidence_id] = [chunk.text for chunk in chunks]
        return {"evidence_id": evidence_id}

    def append_checkpoint(self, context, run_id, *, checkpoint):
        self.checkpoints[run_id] = {"checkpoint": checkpoint}

    def read_checkpoint(self, context, run_id):
        return self.checkpoints.get(run_id)

    def read_evidence_range(self, context, run_id, evidence_id, *, start=0):
        return {
            "chunks": [{"text": text} for text in self.sources[evidence_id][start:]],
            "next_start": None,
        }


class Tools:
    def __init__(self, concurrent=False):
        self.approved = False
        self.first_calls = 0
        self.second_calls = 0
        self.concurrent = concurrent
        self.release = asyncio.Event()

    @kernel_function
    async def first(self) -> str:
        self.first_calls += 1
        if self.concurrent:
            await self.release.wait()
        return "First operation completed"

    @kernel_function
    async def second(self) -> str:
        if not self.approved:
            self.release.set()
            raise M365ApprovalRequired({
                "id": "approval", "request_type": "m365_extended_analysis",
                "subject_user_id": "user-a", "group_id": "user-a",
                "approval_scope": "user", "status": "pending",
                "resume_key": "resume", "execution_status": "awaiting_approval",
                "sources": {"spo": {}},
            })
        self.second_calls += 1
        return "Second operation completed"


class AgentContinuationTests(unittest.TestCase):
    def setUp(self):
        self.previous_dependencies = dict(continuation._dependencies)
        self.memory = Memory()
        self.jobs = CosmosContainer(partition_field="user_id")
        self.context = M365ExecutionContext(
            actor_user_id="user-a", data_user_id="user-a", tenant_id="tenant-a",
            conversation_id="conversation-a", request_id="request-a",
            action_configs={"files": {"source": "spo"}},
        )
        continuation.configure_m365_agent_continuation(
            memory_resolver=lambda context: (self.memory, object()),
            jobs_factory=lambda: self.jobs,
            model_context_setter=lambda *args, **kwargs: None,
        )

    def tearDown(self):
        continuation._dependencies.clear()
        continuation._dependencies.update(self.previous_dependencies)

    def test_declined_sources_add_a_coverage_notice_without_mutating_messages(self):
        app = Flask(__name__)
        original = [ChatMessageContent(role=AuthorRole.USER, content="Answer from my sources")]
        with app.test_request_context():
            g.m365_declined_sources = ["email", "spo"]
            args, kwargs = continuation._add_declined_source_notice((), {"messages": original})
        self.assertEqual(args, ())
        self.assertEqual(len(original), 1)
        self.assertEqual(kwargs["messages"][0].role, AuthorRole.SYSTEM)
        self.assertIn("SharePoint Online", kwargs["messages"][0].content)
        self.assertIn("explicitly explain", kwargs["messages"][0].content)
        self.assertIs(kwargs["messages"][1], original[0])

    async def exercise_resume(self, concurrent):
        tools = Tools(concurrent)
        kernel = Kernel()
        first = kernel.add_function(plugin_name="tools", function=tools.first)
        second = kernel.add_function(plugin_name="tools", function=tools.second)
        calls = [
            FunctionCallContent(id="first", name=first.metadata.fully_qualified_name, arguments="{}"),
            FunctionCallContent(id="second", name=second.metadata.fully_qualified_name, arguments="{}"),
        ]
        agent = SimpleNamespace(
            name="agent", instructions="Use these tools", deployment_name="gpt-4o",
            kernel=kernel, arguments=KernelArguments(), function_choice_behavior=None,
        )
        journal = continuation.AgentContinuationJournal(agent, self.context)
        token = continuation._current_journal.set(journal)
        history = ChatHistory(messages=[ChatMessageContent(role=AuthorRole.ASSISTANT, items=calls)])
        try:
            if concurrent:
                await asyncio.gather(*(kernel.invoke_function_call(call, history) for call in calls))
            else:
                for call in calls:
                    await kernel.invoke_function_call(call, history)
            first_results = [
                item for message in history.messages for item in message.items
                if isinstance(item, FunctionResultContent) and item.id == "first"
            ]
            self.assertEqual(len(first_results), 1)
            self.assertFalse(continuation._is_paused_result(first_results[0]))
            journal.thread = ChatHistoryAgentThread(history)
            with self.assertRaises(M365ApprovalRequired):
                await journal.finish()
        finally:
            continuation._current_journal.reset(token)
        tools.approved = True
        resumed = continuation.AgentContinuationJournal(agent, self.context)
        token = continuation._current_journal.set(resumed)
        try:
            args, kwargs = await resumed.prepare(([],), {})
            self.assertEqual(args, ())
            self.assertIsNone(kwargs["messages"])
            self.assertEqual(tools.first_calls, 1)
            self.assertEqual(tools.second_calls, 1)
            pending = [
                item for message in resumed.history.messages for item in message.items
                if continuation._is_paused_result(item)
            ]
            self.assertEqual(pending, [])
        finally:
            continuation._current_journal.reset(token)

    def test_completed_tool_is_not_replayed(self):
        asyncio.run(self.exercise_resume(False))

    def test_concurrent_completed_tool_keeps_its_real_result(self):
        asyncio.run(self.exercise_resume(True))


if __name__ == "__main__":
    unittest.main()
