"""Bounded blocking work. The executor, rather than a cancelled coroutine, owns slots."""
import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from config import settings

_pool = ThreadPoolExecutor(max_workers=settings.WORKER_LIMIT, thread_name_prefix='qubit')


async def run_blocking(function, *args, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(
        _pool, functools.partial(function, *args, **kwargs))
