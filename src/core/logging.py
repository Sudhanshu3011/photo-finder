"""
src/core/logging.py — Structured high-performance console logging.
Zero external network dependencies: logs clean formatted events via Loguru.
"""
from loguru import logger as _loguru

# Remove default loguru handler and add clean custom format
_loguru.remove()
_loguru.add(
    lambda msg: print(msg, end=""),
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}\n",
    level="DEBUG",
    colorize=True,
)


async def init_logging_session():
    """No-op initialization for clean lifespan compatibility."""
    pass


async def close_logging_session():
    """No-op cleanup for clean lifespan compatibility."""
    pass


def log(level: str, event: str, **kwargs) -> None:
    """Structured event logging."""
    norm_level = level.upper()
    data_str = " ".join(f"{k}={v}" for k, v in kwargs.items())
    message = f"[{event}] {data_str}" if data_str else f"[{event}]"
    _loguru.log(norm_level, message)


def warn(msg: str) -> None:
    _loguru.warning(msg)