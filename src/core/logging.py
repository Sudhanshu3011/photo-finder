import asyncio
import json

from src.core.config import SUPABASE_URL, SUPABASE_SERVICE_KEY

_http_session = None

async def init_logging_session():
    global _http_session
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        import aiohttp
        _http_session = aiohttp.ClientSession(
            headers={
                "Content-Type":  "application/json",
                "apikey":        SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Prefer":        "return=minimal",
            }
        )

async def close_logging_session():
    global _http_session
    if _http_session:
        await _http_session.close()

try:
    from loguru import logger as _loguru
    _loguru.remove()
    _loguru.add(
        lambda msg: print(msg, end=""),
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
        level="DEBUG",
        colorize=True,
    )
    _log_fn = _loguru.log
except ImportError:
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    _stdlib = _logging.getLogger("vsl")

    def _log_fn(level: str, msg: str): 
        _stdlib.log(getattr(_logging, level, 20), msg)

async def _supabase_log(level: str, event: str, data: dict) -> None:
    if not _http_session:
        return
    try:
        import aiohttp
        row = {
            "level":       level.upper(),
            "event":       event,
            "user_id":     str(data.get("user_id", "anonymous")),
            "ip":          str(data.get("ip", "")),
            "mode":        str(data.get("mode", "")),
            "page":        str(data.get("page", "")),
            "duration_ms": int(data["duration_ms"]) if "duration_ms" in data else None,
            "error":       str(data["error"])       if "error"       in data else None,
            "data":        data,
        }
        async with _http_session.post(
            f"{SUPABASE_URL}/rest/v1/app_logs",
            json=row,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as r:
            if r.status not in (200, 201):
                body = await r.text()
                _log_fn("WARNING", f"Supabase log failed {r.status}: {body[:200]}")
    except Exception as exc:
        _log_fn("DEBUG", f"Supabase log push skipped: {exc}")

def log(level: str, event: str, **data) -> None:
    _log_fn(level.upper(), f"[{event}] {json.dumps(data, default=str)}")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_supabase_log(level, event, data))
    except RuntimeError:
        pass

def warn(msg: str) -> None:
    _log_fn("WARNING", msg)