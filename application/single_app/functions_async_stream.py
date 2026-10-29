# functions_async_stream.py
"""Consume asynchronous streams synchronously without losing scoped execution state."""

from asyncio import AbstractEventLoop
from collections.abc import AsyncIterable, Awaitable, Callable, Iterator
from contextvars import copy_context
from typing import TypeVar


_Item = TypeVar("_Item")
_Result = TypeVar("_Result")


class SyncAsyncStream(Iterator[_Item]):
    """Keep iterator pulls and cleanup in the same isolated Context."""

    def __init__(self, stream: AsyncIterable[_Item], loop: AbstractEventLoop):
        if loop.is_closed() or loop.is_running():
            raise RuntimeError("Synchronous stream consumption requires an open, idle event loop.")
        self._context = copy_context()
        self._iterator = self._context.run(aiter, stream)
        self._loop = loop
        self._closed = False

    def _run(self, operation: Callable[[], Awaitable[_Result]]) -> _Result:
        async def await_operation():
            return await operation()

        task = self._loop.create_task(await_operation(), context=self._context)
        return self._loop.run_until_complete(task)

    def __iter__(self):
        return self

    def __next__(self) -> _Item:
        if self._closed:
            raise StopIteration
        try:
            return self._run(self._iterator.__anext__)
        except StopAsyncIteration:
            self.close()
            raise StopIteration from None

    def close(self):
        if self._closed:
            return
        self._closed = True
        close = getattr(self._iterator, "aclose", None)
        if close is not None:
            self._run(close)

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback):
        self.close()
