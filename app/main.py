import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers.apis import router as apis_router
from app.routers.events import router as events_router
from app.routers.snapshots import router as snapshots_router
from app.scheduler.bootstrap import (
    start_scheduler,
    stop_scheduler,
    sync_jobs_from_db,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("api_monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing API Monitor backend...")
    # Ensure tables exist on boot
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified.")

    # Initialize and synchronize scheduler
    start_scheduler()
    try:
        await sync_jobs_from_db()
    except Exception as e:
        logger.warning(f"Initial scheduler DB synchronization skipped: {e}")

    yield

    logger.info("Shutting down API Monitor backend...")
    stop_scheduler()
    await engine.dispose()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="API Change/Breakage Monitor",
    description="Continuously monitors 3rd-party APIs for contract breaks, rate limits, latency drift, and deprecations.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(apis_router)
app.include_router(events_router)
app.include_router(snapshots_router)


import os
from starlette.staticfiles import StaticFiles

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy"}

# Mount frontend static directory if present
if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
