from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.mcp.server import create_mcp_app
from app.routers import entries, foods, goals, summary


def create_app() -> FastAPI:
    mcp_app, mcp_transport_app = create_mcp_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_transport_app.router.lifespan_context(mcp_transport_app):
            yield

    application = FastAPI(title="Macro Tracker", lifespan=lifespan)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(foods.router, prefix="/api")
    application.include_router(entries.router, prefix="/api")
    application.include_router(goals.router, prefix="/api")
    application.include_router(summary.router, prefix="/api")
    application.mount("/", mcp_app)
    return application


app = create_app()
