import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def run_with_isolation(
    tasks: dict[str, Awaitable[T]],
    timeout: float = 15.0,
) -> tuple[dict[str, T], dict[str, str]]:
    """Run named awaitables in parallel. Failures are isolated.

    Returns (results_by_name, errors_by_name).
    """

    async def _wrap(name: str, coro: Awaitable[T]) -> tuple[str, T | None, str | None]:
        try:
            value = await asyncio.wait_for(coro, timeout=timeout)
            return name, value, None
        except asyncio.TimeoutError:
            return name, None, f"timeout after {timeout}s"
        except Exception as e:
            return name, None, f"{type(e).__name__}: {e}"

    coros = [_wrap(name, coro) for name, coro in tasks.items()]
    completed = await asyncio.gather(*coros)

    results: dict[str, T] = {}
    errors: dict[str, str] = {}
    for name, value, err in completed:
        if err is None:
            results[name] = value  # type: ignore[assignment]
        else:
            errors[name] = err
    return results, errors


async def gather_limited(
    coros: list[Awaitable[T]],
    limit: int = 6,
) -> list[T | Exception]:
    """Run coroutines with a concurrency cap. Exceptions are returned, not raised."""
    sem = asyncio.Semaphore(limit)

    async def _bound(c: Awaitable[T]) -> T:
        async with sem:
            return await c

    return await asyncio.gather(*(_bound(c) for c in coros), return_exceptions=True)
