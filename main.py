import asyncio
import os
from contextlib import asynccontextmanager

# CPU thread tuning — must happen BEFORE torch/onnxruntime import.
# HF free tier = 2 vCPU; we want to use both but not oversubscribe.
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import MAX_CONCURRENT_INFERENCES, USE_ASYNC_UPLOADS
from src.core.logging import log, init_logging_session, close_logging_session
from src.api import admin, gallery, search, system, upload, ui
from src.api import people
from src.api import jobs as jobs_api


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_logging_session()
    log("INFO", "server.startup", message="Loading AI models...")

    if os.getenv("TESTING", "false").lower() == "true":
        log("INFO", "server.startup", message="Running in TESTING mode — skipping heavy AI models")
        app.state.ai = None
        app.state.ai_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)
        app.state.face_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)
        app.state.object_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)
        yield
        return

    from src.services.ai_manager import AIModelManager

    loop = asyncio.get_event_loop()
    app.state.ai = await loop.run_in_executor(None, AIModelManager)

    # Split semaphores: face detection and object embedding can overlap
    # without fighting for the same CPU cores.
    app.state.ai_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)
    app.state.face_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)
    app.state.object_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)

    # Phase 3: start background job worker if async uploads are enabled
    worker_task = None
    if USE_ASYNC_UPLOADS:
        from src.services.jobs import run_worker
        worker_task = asyncio.create_task(run_worker(app.state))
        log("INFO", "server.worker_started", message="Async upload worker running")

    log("INFO", "server.ready", message="All models loaded. API ready.")
    yield

    # Graceful shutdown
    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    log("INFO", "server.shutdown", message="API shutting down.")
    await close_logging_session()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://photofinderv2.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("temp_uploads", exist_ok=True)

# Routers
app.include_router(ui.router)
app.include_router(system.router)
app.include_router(upload.router)
app.include_router(search.router)
app.include_router(gallery.router)
app.include_router(admin.router)

# Face clustering and job routers
app.include_router(people.router)
app.include_router(jobs_api.router)