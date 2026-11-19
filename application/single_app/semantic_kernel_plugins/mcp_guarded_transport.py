# mcp_guarded_transport.py
"""MCP's WebSocket wire contract over a destination-guarded connection."""

from contextlib import asynccontextmanager

import anyio
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage
from pydantic import ValidationError
from semantic_kernel.connectors.mcp import MCPWebsocketPlugin

from functions_outbound_http import guarded_websocket_connection


@asynccontextmanager
async def guarded_mcp_websocket_client(url, timeout):
    incoming_sender, incoming = anyio.create_memory_object_stream(0)
    outgoing, outgoing_receiver = anyio.create_memory_object_stream(0)

    async with guarded_websocket_connection(url, timeout=timeout) as connection:
        async def receive_messages():
            async with incoming_sender:
                async for raw_message in connection:
                    try:
                        message = SessionMessage(JSONRPCMessage.model_validate_json(raw_message))
                    except ValidationError as exc:
                        await incoming_sender.send(exc)
                    else:
                        await incoming_sender.send(message)

        async def send_messages():
            async with outgoing_receiver:
                async for message in outgoing_receiver:
                    await connection.send(
                        message.message.model_dump_json(by_alias=True, exclude_none=True)
                    )

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(receive_messages)
            tasks.start_soon(send_messages)
            try:
                yield incoming, outgoing
            finally:
                tasks.cancel_scope.cancel()


class GuardedMcpWebsocketPlugin(MCPWebsocketPlugin):
    def __init__(self, *args, connect_timeout=10, **kwargs):
        super().__init__(*args, **kwargs)
        self.connect_timeout = connect_timeout

    def get_mcp_client(self):
        return guarded_mcp_websocket_client(self.url, self.connect_timeout)
