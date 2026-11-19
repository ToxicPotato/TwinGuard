"""TwinGuard Backend API — FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import attack as attack_router
from .routers import config as config_router
from .routers import datasets as datasets_router
from .routers import recording as recording_router
from .routers import recordings as recordings_router
from .routers import streaming as streaming_router
from .routers import system_risk as system_risk_router
from .routers.streaming import broadcaster

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start live broadcaster (MQTT polling + frame consumer)
    await broadcaster.start()
    yield
    await broadcaster.stop()


app = FastAPI(title="TwinGuard API", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets_router.router, prefix="/datasets", tags=["datasets"])
app.include_router(streaming_router.router, prefix="/live", tags=["live"])
app.include_router(streaming_router.ws_router, tags=["live"])
app.include_router(recording_router.router, prefix="/live", tags=["recording"])
app.include_router(recordings_router.router, prefix="/recordings", tags=["recordings"])
app.include_router(config_router.router, prefix="/config", tags=["config"])
app.include_router(attack_router.router, prefix="/attack", tags=["attack"])
app.include_router(system_risk_router.router, prefix="/risk", tags=["risk"])
