"""
src/core/tenant_context.py — Asynchronous Tenant Context Management.
Uses contextvars to propagate tenant_id across async coroutines and background tasks.
"""
import contextvars
from contextlib import contextmanager
from typing import Generator, Optional

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
