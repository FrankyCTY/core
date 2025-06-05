"""Provide CORS support for the HTTP component."""

from __future__ import annotations

from typing import Final, cast

from aiohttp.hdrs import ACCEPT, AUTHORIZATION, CONTENT_TYPE, ORIGIN
from aiohttp.web import Application
from aiohttp.web_urldispatcher import (
    AbstractResource,
    AbstractRoute,
    Resource,
    ResourceRoute,
    StaticResource,
)
import aiohttp_cors

from homeassistant.const import HTTP_HEADER_X_REQUESTED_WITH
from homeassistant.core import callback
from homeassistant.helpers.http import (
    KEY_ALLOW_ALL_CORS,
    KEY_ALLOW_CONFIGURED_CORS,
    AllowCorsType,
)

ALLOWED_CORS_HEADERS: Final[list[str]] = [
    ORIGIN,
    ACCEPT,
    HTTP_HEADER_X_REQUESTED_WITH,
    CONTENT_TYPE,
    AUTHORIZATION,
]
VALID_CORS_TYPES: Final = (Resource, ResourceRoute, StaticResource)


@callback
def setup_cors(app: Application, origins: list[str]) -> None:
    """Set up CORS."""
    # USERNOTE: Installs CORS middleware into the aiohttp app.
    #  - Intercepts HTTP requests to that route,
    #  - Adds Access-Control-Allow-Origin, Access-Control-Allow-Methods, etc.
    #  - Handles OPTIONS preflight requests automatically.
    cors = aiohttp_cors.setup(
        app,
        # USERNOTE: DEFAULT CORS policies for all hosts.
        defaults={
            host: aiohttp_cors.ResourceOptions(  # type: ignore[no-untyped-call]
                allow_headers=ALLOWED_CORS_HEADERS, allow_methods="*"
            )
            for host in origins
        },
    )

    # USERNOTE: Track added cors routes to avoid adding the same route PATH multiple times.
    cors_added: set[str] = set()

    def _allow_cors(
        route: AbstractRoute | AbstractResource,
        # USERNOTE: CORS config is a dict of host -> ResourceOptions.
        config: dict[str, aiohttp_cors.ResourceOptions] | None = None,
    ) -> None:
        """Allow CORS on a route."""
        if isinstance(route, AbstractRoute):
            path = route.resource
        else:
            path = route

        if not isinstance(path, VALID_CORS_TYPES):
            return

        path_str = path.canonical

        if path_str.startswith("/api/hassio_ingress/"):
            return

        if path_str in cors_added:
            return

        # USERNOTE: Add the route to the cors config.
        # USERNOTE: If no config passed in: Registers default CORS policies.
        cors.add(route, config)  # type: ignore[arg-type]

        # USERNOTE: Add the route path str to local field "cors_added" to avoid adding the same route PATH multiple times.
        cors_added.add(path_str)

    # USERNOTE: For "KEY_ALLOW_ALL_CORS", store a callback that allows any origin ("*") with all methods and headers for the given route.
    app[KEY_ALLOW_ALL_CORS] = lambda route: _allow_cors(
        route,
        {
            "*": aiohttp_cors.ResourceOptions(  # type: ignore[no-untyped-call]
                allow_headers=ALLOWED_CORS_HEADERS, allow_methods="*"
            )
        },
    )

    # USERNOTE: For "KEY_ALLOW_CONFIGURED_CORS", use _allow_cors if specific origins are configured;
    #       otherwise, assign a no-op to skip CORS setup entirely.
    if origins:
        # USERNOTE: Allow consumer to specify the cors config for callback _allow_cors.
        # USERNOTE: If no config passed in: Registers default CORS policies.
        app[KEY_ALLOW_CONFIGURED_CORS] = cast(AllowCorsType, _allow_cors)
    else:
        app[KEY_ALLOW_CONFIGURED_CORS] = lambda _: None
