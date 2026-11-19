"""Entrypoint for the MQTT tamper relay — runs MQTT loop + HTTP control API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .deps import service
from .routers import attack as attack_router
from .routers import config as config_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.start()
    yield
    service.stop()


# Internal service — no CORS. Browser cross-origin access to this API is intentionally blocked.
app = FastAPI(title="TwinGuard Tamper API", version="1.0.0", lifespan=lifespan)

app.include_router(attack_router.router, tags=["attack"])
app.include_router(config_router.router, tags=["config"])


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")


if __name__ == "__main__":
    main()
