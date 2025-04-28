## Set up

The websocket_api `__init__.py:async_setup()` is invoked in `setup.py's _async_setup_component()` when components/integrations are set up in the loop.

## Websocket API Set up operations
1. Register view: The websocketAPI View's route (Get()) is used for establish websocket connection with client, and it is processed and added to the `HomeAssistantApplication`'s router during this phase.
2. Register command handlers: Register all the websocket api command handlers with the websocket api.
   - At the end is stored into hass.data[websocket_api domain] = { [command]: (handler, schema) }


## Related HA core http classes
### HomeAssistantHTTP
Provides a higher-level API (e.g. register_view, register_static_path), this abstracts away complexities like SSL, middleware stacking, and routing.

- Hold reference to app (HomeAssistantApplication)
- SSL, SERVER host e.g.


### HomeAssistantApplication (Instance of aiohttp.Application)
The web.Application class from aiohttp is a container for an asynchronous web application, it manges:
- Routes (HTTP endpoints)
- Middlewares
- Lifecycle hooks (startup/shutdown)
- Shared state
- Request handling infrastructure


## Establish Connection
0. `WebsocketAPIView` has been registered, meaning it's route (GET()) has been registered into the `HomeAssistantApplication`'s routes e.g. via http.register_view(WebsocketAPIView()).
1. Client sends GET request to `/api/websocket`
2. `WebsocketAPIView`'s `Get()` invoked
3. `WebSocketHandler.async_handle()` invoked
   - WebSocketResponse.prepare() is called to upgrade the HTTP connection to a WebSocket.
	 - A heartbeat=55 is configured to keep the connection alive.
4. Ready for `Auth Phase` as the server sends the AUTH_REQUIRED message to the client.
