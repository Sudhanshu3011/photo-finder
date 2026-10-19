import asyncio
import os
from contextlib import asynccontextmanager

# CPU thread tuning — must happen BEFORE torch/onnxruntime import.
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import MAX_CONCURRENT_INFERENCES, CORS_ORIGINS
from src.core.logging import log, init_logging_session, close_logging_session
from src.api import (
    auth_router,
    tenant_router,
    folder_router,
    upload_router,
    processing_router,
    search_router,
    system_router,
    ui_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_logging_session()
    log("INFO", "server.startup", message="Initializing Visual Search API...")

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

    app.state.ai_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)
    app.state.face_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)
    app.state.object_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCES)

    log("INFO", "server.ready", message="AI Models and FAISS stores loaded. API ready.")
    yield

    log("INFO", "server.shutdown", message="API shutting down.")
    await close_logging_session()


app = FastAPI(
    title="Visual Search API",
    description="Modular Microservices-style Visual Search Engine with Face Clustering and Multimodal Vector Matching",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("saved_images", exist_ok=True)

# Mount Clean Modular API Routers
app.include_router(ui_router)
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(tenant_router)
app.include_router(folder_router)
app.include_router(upload_router)
app.include_router(processing_router)
app.include_router(search_router)