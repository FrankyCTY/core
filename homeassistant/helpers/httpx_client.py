"""Helper for httpx."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
import sys
from types import TracebackType
from typing import Any, Self

# httpx dynamically imports httpcore, so we need to import it
# to avoid it being imported later when the event loop is running
import httpcore  # noqa: F401
import httpx

from homeassistant.const import APPLICATION_NAME, EVENT_HOMEASSISTANT_CLOSE, __version__
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.loader import bind_hass
from homeassistant.util.hass_dict import HassKey
from homeassistant.util.ssl import (
    SSLCipherList,
    client_context,
    create_no_verify_ssl_context,
)

from .frame import warn_use

# We have a lot of integrations that poll every 10-30 seconds
# and we want to keep the connection open for a while so we
# don't have to reconnect every time so we use 15s to match aiohttp.
KEEP_ALIVE_TIMEOUT = 15
DATA_ASYNC_CLIENT: HassKey[httpx.AsyncClient] = HassKey("httpx_async_client")
DATA_ASYNC_CLIENT_NOVERIFY: HassKey[httpx.AsyncClient] = HassKey(
    "httpx_async_client_noverify"
)
DEFAULT_LIMITS = limits = httpx.Limits(keepalive_expiry=KEEP_ALIVE_TIMEOUT)
SERVER_SOFTWARE = (
    f"{APPLICATION_NAME}/{__version__} "
    f"httpx/{httpx.__version__} Python/{sys.version_info[0]}.{sys.version_info[1]}"
)
USER_AGENT = "User-Agent"


@callback
@bind_hass
def get_async_client(hass: HomeAssistant, verify_ssl: bool = True) -> httpx.AsyncClient:
    """Return default httpx AsyncClient.

    This method must be run in the event loop.
    """
    key = DATA_ASYNC_CLIENT if verify_ssl else DATA_ASYNC_CLIENT_NOVERIFY

    if (client := hass.data.get(key)) is None:
        client = hass.data[key] = create_async_httpx_client(hass, verify_ssl)

    return client


class HassHttpXAsyncClient(httpx.AsyncClient):
    """httpx AsyncClient that suppresses context management."""

    async def __aenter__(self) -> Self:
        """Prevent an integration from reopen of the client via context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        """Prevent an integration from close of the client via context manager."""


@callback
# LLM: HTTP client factory for Home Assistant integrations
# Purpose: Creates a configured httpx.AsyncClient with HA-specific defaults and lifecycle management
# Caveats: Must be called from event loop; auto_cleanup=False requires manual client management
# Side Effects: Registers shutdown handlers when auto_cleanup=True, modifies client.aclose behavior
# Role in Scope: Central factory for all HTTP clients in HA, ensures consistent configuration and cleanup
def create_async_httpx_client(
    hass: HomeAssistant,
    verify_ssl: bool = True,
    auto_cleanup: bool = True,
    ssl_cipher_list: SSLCipherList = SSLCipherList.PYTHON_DEFAULT,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Create a new httpx.AsyncClient with kwargs, i.e. for cookies.

    If auto_cleanup is False, the client will be
    automatically closed on homeassistant_stop.

    This method must be run in the event loop.
    """
    # LLM: Configure SSL context based on verification requirements
    # Determines whether to use secure SSL verification or bypass for testing/development
    ssl_context = (
        client_context(ssl_cipher_list)
        if verify_ssl
        else create_no_verify_ssl_context(ssl_cipher_list)
    )
    # LLM: Create client with HA-specific configuration and user-provided overrides
    # Uses custom HassHttpXAsyncClient to prevent integrations from managing lifecycle
    client = HassHttpXAsyncClient(
        verify=ssl_context,
        headers={USER_AGENT: SERVER_SOFTWARE},
        limits=DEFAULT_LIMITS,
        **kwargs,
    )

    # LLM: Preserve original close method before wrapping it with warning
    # Needed for proper cleanup during shutdown while preventing integration misuse
    original_aclose = client.aclose

    # LLM: Wrap close method to warn developers about improper client lifecycle management
    # Prevents integrations from closing shared HTTP clients which could break other components
    client.aclose = warn_use(  # type: ignore[method-assign]
        client.aclose, "closes the Home Assistant httpx client"
    )

    # LLM: Register automatic cleanup on HA shutdown if requested
    # Ensures HTTP connections are properly closed when HA stops, preventing resource leaks
    if auto_cleanup:
        _async_register_async_client_shutdown(hass, client, original_aclose)

    return client


@callback
def _async_register_async_client_shutdown(
    hass: HomeAssistant,
    client: httpx.AsyncClient,
    original_aclose: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    """Register httpx AsyncClient aclose on Home Assistant shutdown.

    This method must be run in the event loop.
    """

    async def _async_close_client(event: Event) -> None:
        """Close httpx client."""
        await original_aclose()

    # USERNOTE: Invoke close handler to close the client on HA shutdown.
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_CLOSE, _async_close_client)
