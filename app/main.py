from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from mcp.server.auth.routes import (
    create_auth_routes,
    create_protected_resource_routes,
)
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from app.config import get_auth_settings, get_settings
from app.mcp.server import create_mcp_app
from app.oauth.google import GoogleIdentityProvider, create_google_callback_route
from app.oauth.identity import (
    DevIdentityProvider,
    create_consent_routes,
    create_login_route,
)
from app.routers import account, entries, foods, goals, summary
from app.web.auth import WebAuth
from app.web.pages import router as web_pages_router


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
    application.state.settings = settings
    application.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(foods.router, prefix="/api")
    application.include_router(entries.router, prefix="/api")
    application.include_router(goals.router, prefix="/api")
    application.include_router(summary.router, prefix="/api")
    application.include_router(account.router, prefix="/api")
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
    identity_provider = (
        GoogleIdentityProvider(oauth_provider, settings)
        if settings.app_env.lower() == "production"
        or (settings.google_client_id and settings.google_client_secret)
        else DevIdentityProvider(settings)
    )
    application.router.routes.append(
        create_login_route(oauth_provider, identity_provider, settings)
    )
    application.router.routes.extend(create_consent_routes(oauth_provider))
    google_provider = GoogleIdentityProvider(oauth_provider, settings)
    web_auth = WebAuth(settings)
    application.router.routes.append(
        create_google_callback_route(
            google_provider,
            oauth_provider,
            settings,
            web_callback=web_auth.callback,
        )
    )
    application.include_router(web_pages_router)
    application.include_router(web_auth.router())
    application.router.routes.append(Route("/mcp", mcp_app))
    application.router.routes.append(Route("/mcp/", mcp_app))
    return application


app = create_app()
