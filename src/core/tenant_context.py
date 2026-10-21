"""
src/core/tenant_context.py — Asynchronous Tenant Context Management.
Uses contextvars to propagate tenant_id across async coroutines and background tasks.
"""
import asyncio
import concurrent.futures
import contextvars
from contextlib import contextmanager
from typing import Any, Callable, Generator, Optional, TypeVar

T = TypeVar("T")

DEFAULT_TENANT_ID: str = "default"

# ContextVar storing the active tenant_id for the current coroutine/task
_current_tenant_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_tenant_id", default=DEFAULT_TENANT_ID
)


def set_current_tenant_id(tenant_id: Optional[str]) -> contextvars.Token:
    """Set the active tenant_id for the current asynchronous execution context."""
    tid = (tenant_id or DEFAULT_TENANT_ID).strip()
    if not tid:
        tid = DEFAULT_TENANT_ID
    return _current_tenant_id_var.set(tid)


def get_current_tenant_id() -> str:
    """Retrieve the active tenant_id for the current coroutine/task."""
    return _current_tenant_id_var.get()


def reset_current_tenant_id(token: contextvars.Token) -> None:
    """Reset the tenant context back to its previous state using token."""
    _current_tenant_id_var.reset(token)


def reset_tenant_context() -> None:
    """Reset the tenant context to the default tenant."""
    set_current_tenant_id(DEFAULT_TENANT_ID)


@contextmanager
def tenant_context(tenant_id: Optional[str]) -> Generator[str, None, None]:
    """Context manager to temporarily scope an execution block to a tenant."""
    token = set_current_tenant_id(tenant_id)
    try:
        yield get_current_tenant_id()
    finally:
        reset_current_tenant_id(token)


def run_in_tenant_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Execute a callable in a worker thread while strictly preserving tenant contextvars.
    Prevents silent context leakage or fallback to 'default' tenant in ThreadPoolExecutors.
    """
    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(ctx.run, func, *args, **kwargs)
        return future.result()


class TenantPreservingThreadPoolExecutor(concurrent.futures.ThreadPoolExecutor):
    """
    ThreadPoolExecutor that automatically snapshots caller's contextvars
    and restores them inside every submitted task.
    """

    def submit(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> concurrent.futures.Future[T]:
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)


async def run_async_in_tenant_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Asynchronously run a blocking CPU/IO function in a worker thread with preserved tenant context.
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    return await loop.run_in_executor(None, ctx.run, func, *args, **kwargs)

