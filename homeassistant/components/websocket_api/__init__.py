"""WebSocket based API for Home Assistant."""

from __future__ import annotations

from typing import Final, cast

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType, VolSchemaType
from homeassistant.loader import bind_hass

from . import commands, connection, const, decorators, http, messages  # noqa: F401
from .connection import ActiveConnection, current_connection  # noqa: F401
from .const import (  # noqa: F401
    ERR_HOME_ASSISTANT_ERROR,
    ERR_INVALID_FORMAT,
    ERR_NOT_ALLOWED,
    ERR_NOT_FOUND,
    ERR_NOT_SUPPORTED,
    ERR_SERVICE_VALIDATION_ERROR,
    ERR_TEMPLATE_ERROR,
    ERR_TIMEOUT,
    ERR_UNAUTHORIZED,
    ERR_UNKNOWN_COMMAND,
    ERR_UNKNOWN_ERROR,
    TYPE_RESULT,
    AsyncWebSocketCommandHandler,
    WebSocketCommandHandler,
)
from .decorators import (  # noqa: F401
    async_response,
    require_admin,
    websocket_command,
    ws_require_user,
)
from .messages import (  # noqa: F401
    BASE_COMMAND_MESSAGE_SCHEMA,
    error_message,
    event_message,
    result_message,
)

DOMAIN: Final = const.DOMAIN

DEPENDENCIES: Final[tuple[str]] = ("http",)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


@bind_hass
@callback
def async_register_command(
    hass: HomeAssistant,
    command_or_handler: str | const.WebSocketCommandHandler,
    handler: const.WebSocketCommandHandler | None = None,
    schema: VolSchemaType | None = None,
) -> None:
    """Register a websocket command."""
    if handler is None:
        handler = cast(const.WebSocketCommandHandler, command_or_handler)
        # USERNOTE: Extract command and schema from the handler attributes set by the @websocket_command decorator.
        command = handler._ws_command  # type: ignore[attr-defined]  # noqa: SLF001
        schema = handler._ws_schema  # type: ignore[attr-defined]  # noqa: SLF001
    else:
        # USERNOTE: command_or_handler is a command name, use it as KEY in HASS data cache.
        command = command_or_handler
    if (handlers := hass.data.get(DOMAIN)) is None:
        handlers = hass.data[DOMAIN] = {}
    # USERNOTE: Updates hass.data[websocket_api domain] = {
    #     [command]: (handler, schema)
    # }
    handlers[command] = (handler, schema)


# USERNOTE: Invoked in setup.py's async_setup_component() when components/integrations are set up.
# USERNOTE: During integrations set up in `setup.py`, they will invoke this function to register commands to the websocket api singleton instance (singleton as in Python Module Singleton Behavior).
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialize the websocket API."""
    # USERNOTE: Register view: The websocketAPI View's route (Get()) is used for establish websocket connection with client, and it is processed and added to the `HomeAssistantApplication`'s router during this phase.
    hass.http.register_view(http.WebsocketAPIView())
    # USERNOTE: Register all the websocket api command handlers with the websocket api, At the end is stored into hass.data[websocket_api domain] = { [command]: (handler, schema) }
    commands.async_register_commands(hass, async_register_command)
    return True
