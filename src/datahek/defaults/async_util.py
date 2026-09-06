"""Shared async-bridge helpers for sync classmethod constructors."""
import asyncio
import concurrent.futures


def run_sync(coro):
    """Run a coroutine from a sync classmethod, tolerating a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
