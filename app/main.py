"""FastAPI app assembly."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.db import create_all, make_engine
from app.routers import oauth, webhook
from app.settings import get_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Idempotent, and means a fresh DB works without running the seed script first.
    create_all(make_engine(get_settings().database_url))
    yield


app = FastAPI(title="HumaraCart", lifespan=lifespan)
app.include_router(webhook.router)
app.include_router(oauth.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
