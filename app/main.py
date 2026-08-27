from fastapi import FastAPI

from app.routers import entries, foods, goals, summary


def create_app() -> FastAPI:
    application = FastAPI(title="Macro Tracker")

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(foods.router, prefix="/api")
    application.include_router(entries.router, prefix="/api")
    application.include_router(goals.router, prefix="/api")
    application.include_router(summary.router, prefix="/api")
    return application


app = create_app()
