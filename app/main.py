from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.auth.routes import (
    create_auth_routes,
    create_protected_resource_routes,
)
from starlette.routing import Route

from app.config import get_auth_settings, get_settings
from app.mcp.server import create_mcp_app
from app.oauth.identity import DevIdentityProvider, create_login_route
from app.routers import entries, foods, goals, summary


def create_app() -> FastAPI:
    mcp_app, mcp_transport_app, oauth_provider = create_mcp_app()
    auth_settings = get_auth_settings()
    resource_server_url = auth_settings.resource_server_url
    assert resource_server_url is not None
    settings = get_settings()

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
    application.router.routes.extend(
        create_auth_routes(
            provider=oauth_provider,
            issuer_url=auth_settings.issuer_url,
            client_registration_options=auth_settings.client_registration_options,
            revocation_options=auth_settings.revocation_options,
        )
    )
    application.router.routes.extend(
        create_protected_resource_routes(
            resource_url=resource_server_url,
            authorization_servers=[auth_settings.issuer_url],
            scopes_supported=auth_settings.client_registration_options.valid_scopes
            if auth_settings.client_registration_options is not None
            else None,
        )
    )
    application.router.routes.append(
        create_login_route(oauth_provider, DevIdentityProvider(settings), settings)
    )
    application.router.routes.append(Route("/mcp", mcp_app))
    application.router.routes.append(Route("/mcp/", mcp_app))
    return application


app = create_app()
