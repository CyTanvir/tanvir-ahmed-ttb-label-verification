from collections.abc import AsyncIterator
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import get_openai_vision_service, get_vision_service_factory, router

APP_VERSION = "0.1.0"
SERVICE_NAME = "ttb-label-verification"

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        service = get_vision_service_factory()()
        warm_up = getattr(service, "warm_up", None)
        if warm_up is not None:
            await asyncio.to_thread(warm_up)
    except Exception:
        pass
    yield


app = FastAPI(
    title="TTB Label Verification",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": APP_VERSION,
    }


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
