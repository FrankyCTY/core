"""View to accept incoming websocket connection."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine
import datetime as dt
from functools import partial
import logging
from typing import TYPE_CHECKING, Any, Final

from aiohttp import WSMsgType, web
from aiohttp.http_websocket import WebSocketWriter

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, EVENT_LOGGING_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util.async_ import create_eager_task
from homeassistant.util.json import json_loads

from .auth import AUTH_REQUIRED_MESSAGE, AuthPhase
from .const import (
    DATA_CONNECTIONS,
    MAX_PENDING_MSG,
    PENDING_MSG_MAX_FORCE_READY,
    PENDING_MSG_PEAK,
    PENDING_MSG_PEAK_TIME,
    SIGNAL_WEBSOCKET_CONNECTED,
    SIGNAL_WEBSOCKET_DISCONNECTED,
    URL,
)
from .error import Disconnect
from .messages import message_to_json_bytes
from .util import describe_request

CLOSE_MSG_TYPES = {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING}

if TYPE_CHECKING:
    from .connection import ActiveConnection


_WS_LOGGER: Final = logging.getLogger(f"{__name__}.connection")


class WebsocketAPIView(HomeAssistantView):
    """View to serve a websockets endpoint."""

    name: str = "websocketapi"
    url: str = URL
    requires_auth: bool = False

    async def get(self, request: web.Request) -> web.WebSocketResponse:
        """Handle an incoming websocket connection."""
        return await WebSocketHandler(request.app[KEY_HASS], request).async_handle()


class WebSocketAdapter(logging.LoggerAdapter):
    """Add connection id to websocket messages."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Add connid to websocket log messages."""
        assert self.extra is not None
        return f"[{self.extra['connid']}] {msg}", kwargs


# USERNOTE: Used in /api/websocket GET() to handle an active websocket client connection.
class WebSocketHandler:
    """Handle an active websocket client connection."""

    __slots__ = (
        "_authenticated",
        "_closing",
        "_connection",
        "_debug",
        "_handle_task",
        "_hass",
        "_logger",
        "_loop",
        "_message_queue",
        "_peak_checker_unsub",
        "_ready_future",
        "_release_ready_queue_size",
        "_request",
        "_writer_task",
        "_wsock",
    )

    def __init__(self, hass: HomeAssistant, request: web.Request) -> None:
        """Initialize an active connection."""
        self._hass = hass
        self._loop = hass.loop
        self._request: web.Request = request
        # USERNOTE: HeartBeat: aiohttp will automatically send a ping frame every 55 seconds.
        self._wsock = web.WebSocketResponse(heartbeat=55)
        self._handle_task: asyncio.Task | None = None
        # USERNOTE: The task represents the writer task that is running in a loop to handle sending messages in the message queue to the client.
        # If this is canceld, the writing loop is canceled.
        self._writer_task: asyncio.Task | None = None
        self._closing: bool = False
        self._authenticated: bool = False
        self._logger = WebSocketAdapter(_WS_LOGGER, {"connid": id(self)})
        self._peak_checker_unsub: Callable[[], None] | None = None
        self._connection: ActiveConnection | None = None

        # The WebSocketHandler has a single consumer and path
        # to where messages are queued. This allows the implementation
        # to use a deque and an asyncio.Future to avoid the overhead of
        # an asyncio.Queue.
        self._message_queue: deque[bytes] = deque()
        # USERNOTE: Notify the WRITER to continue writing.
        self._ready_future: asyncio.Future[int] | None = None
        # USERNOTE: Queue size snapshot from last time the queue size has grown
        # USERNOTE: Would be reset to 0 when scheduler decides to unblock writer to send messages.
        self._release_ready_queue_size: int = 0
        self._async_logging_changed()

    # USERNOTE: Update _debug flag. This used as callback when the hass loglevel changed at runtime.
    @callback
    def _async_logging_changed(self, event: Event | None = None) -> None:
        """Handle logging change."""
        self._debug = self._logger.isEnabledFor(logging.DEBUG)

    def __repr__(self) -> str:
        """Return the representation."""
        return (
            "<WebSocketHandler "
            f"closing={self._closing} "
            f"authenticated={self._authenticated} "
            f"description={self.description}>"
        )

    @property
    def description(self) -> str:
        """Return a description of the connection."""
        if connection := self._connection:
            return connection.get_description(self._request)
        if request := self._request:
            return describe_request(request)
        return "finished connection"

    # USERNOTE: This is the writing loop that is established after the AUTH phase.
    # USERNOTE: It handles writing bytes text to the websocket and coalescing messages if coalescing is enabled.
    async def _writer(
        self,
        connection: ActiveConnection,
        send_bytes_text: Callable[[bytes], Coroutine[Any, Any, None]],
    ) -> None:
        """Write outgoing messages."""
        # Variables are set locally to avoid lookups in the loop
        message_queue = self._message_queue
        logger = self._logger
        wsock = self._wsock
        loop = self._loop
        debug = logger.debug
        can_coalesce = connection.can_coalesce
        ready_message_count = len(message_queue)
        # Exceptions if Socket disconnected or cancelled by connection handler
        try:
            while not wsock.closed:
                # USERNOTE: IF the message queue is empty, reset the ready_future and wait for it to be resolved to continue writing.
                if not message_queue:
                    self._ready_future = loop.create_future()
                    # USERNOTE: Wait for the ready_future to be resolved to continue writing.
                    ready_message_count = await self._ready_future

                if self._closing:
                    return

                # USERNOTE: Update can_coalesce flag in the while loop, as it can be changed.
                if not can_coalesce:
                    # coalesce may be enabled later in the connection
                    can_coalesce = connection.can_coalesce

                # USERNOTE: NO COALESCING or only 1 message to send
                # ACTION: Dequeue 1 message and send it.
                if not can_coalesce or ready_message_count == 1:
                    message = message_queue.popleft()
                    if self._debug:
                        debug("%s: Sending %s", self.description, message)
                    await send_bytes_text(message)
                    continue

                # USERNOTE: COALESCING enabled and multiple messages to send
                # ACTION: Join all messages in the queue into JSON array, THEN BATCH send them as a single message.
                coalesced_messages = b"".join((b"[", b",".join(message_queue), b"]"))
                message_queue.clear()
                if self._debug:
                    debug("%s: Sending %s", self.description, coalesced_messages)
                await send_bytes_text(coalesced_messages)
        except asyncio.CancelledError:
            debug("%s: Writer cancelled", self.description)
            raise
        except (RuntimeError, ConnectionResetError) as ex:
            debug("%s: Unexpected error in writer: %s", self.description, ex)
        finally:
            debug("%s: Writer done", self.description)
            # Clean up the peak checker when we shut down the writer
            self._cancel_peak_checker()

    @callback
    def _cancel_peak_checker(self) -> None:
        """Cancel the peak checker."""
        if self._peak_checker_unsub is not None:
            self._peak_checker_unsub()
            self._peak_checker_unsub = None

    # USERNOTE: A core function that is used to send messages to the client, and take important part of the HA core backpreasure management.
    # USERNOTE: BACKPRESSURE Management role: It does NOT direclty requesting writer to send message, but instead queue the message in the message queue.
    # USERNOTE: It defer the decision of unblocking the writer to the async _release_ready_future_or_reschedule() method to allow the potential async request on the event loop to invoke send_message() again for accumulating more messages before making decision to unblock the writer.
    @callback
    def _send_message(self, message: str | bytes | dict[str, Any]) -> None:
        """Queue sending a message to the client.

        Closes connection if the client is not reading the messages.

        Async friendly.
        """
        # USERNOTE: Websocket is closing, prevent new message being sent and flood logs.
        if self._closing:
            # Connection is cancelled, don't flood logs about exceeding
            # max pending messages.
            return

        # USERNOTE: Ensure message is in bytes type for aiohttp low-level websocket api needs, and for our _message_queue: deque[bytes].
        if type(message) is not bytes:
            if isinstance(message, dict):
                message = message_to_json_bytes(message)
            elif isinstance(message, str):
                # USERNOTE: Ensures any plain text becomes UTF-8 bytes
                message = message.encode("utf-8")

        message_queue = self._message_queue
        # USERNOTE: Add requested message to queue
        message_queue.append(message)
        # USERNOTE: Check is queue size HARD LIMIT exceeded
        if (queue_size_after_add := len(message_queue)) >= MAX_PENDING_MSG:
            self._logger.error(
                (
                    "%s: Client unable to keep up with pending messages. Reached %s pending"
                    " messages. The system's load is too high or an integration is"
                    " misbehaving; Last message was: %s"
                ),
                self.description,
                MAX_PENDING_MSG,
                message,
            )
            # USERNOTE: Cancel connection to protect system memory, CPU, and frontend responsiveness (especially in browsers).
            self._cancel()
            return

        # USERNOTE: Schedule batch messages check (_release_ready_future_or_reschedule)
        # Condition: No message in release ready queue
        if self._release_ready_queue_size == 0:
            # Try to coalesce more messages to reduce the number of writes
            # USERNOTE: Update _release_ready_queue_size with current queue size.
            self._release_ready_queue_size = queue_size_after_add
            # USERNOTE: Schedule check task to event loop
            self._loop.call_soon(self._release_ready_future_or_reschedule)

        peak_checker_active = self._peak_checker_unsub is not None

        # USERNOTE: Queue backpressure detection
        if queue_size_after_add <= PENDING_MSG_PEAK:
            # USERNOTE: Case 1 - Queue size was previously over warning PEAK threshold (1024), but now dropped back to normal.
            # ACTION: Cancel any scheduled peak checker task.
            if peak_checker_active:
                self._cancel_peak_checker()
            return

        # USERNOTE: Case 2 - Queue size accumulated over warning PEAK threshold (1024)
        # ACTION: Schedule a one-time call (via async_call_later) to _check_write_peak after PENDING_MSG_PEAK_TIME seconds.
        if not peak_checker_active:
            self._peak_checker_unsub = async_call_later(
                self._hass, PENDING_MSG_PEAK_TIME, self._check_write_peak
            )

    # USERNOTE: Messages coalesce feature: balances latency vs throughput
    # USERNOTE: - Delay waking up the writer to allow batching messages together (coalescing).
    # USERNOTE: - Continue writer process immediately if too many messages are pending (to avoid lag or memory blow-up) by releasing ready_future.
    @callback
    def _release_ready_future_or_reschedule(self) -> None:
        """Release the ready future or reschedule.

        We will release the ready future if the queue did not grow since the
        last time we tried to release the ready future.

        If we reach PENDING_MSG_MAX_FORCE_READY, we will release the ready future
        immediately so avoid the coalesced messages from growing too large.
        """
        # USERNOTE: Case 1 - No message to handle
        # Condition: No ready future or the queue is empty
        # Action: Do nothing
        if not (ready_future := self._ready_future) or not (
            queue_size := len(self._message_queue)
        ):
            self._release_ready_queue_size = 0
            return
        # If we are below the max pending to force ready, and there are new messages
        # in the queue since the last time we tried to release the ready future, we
        # try again later so we can coalesce more messages.
        # USERNOTE: Case 2 - No need to force send message yet
        # Condition
        # - If queue has grown since last check AND
        # - Queue size below force to send threshold
        # Action: Reschedule this method to postpone to re-check soon.
        if queue_size > self._release_ready_queue_size < PENDING_MSG_MAX_FORCE_READY:
            # USERNOTE: Capture the queue size snapshot as the queue size has grown (changed).
            self._release_ready_queue_size = queue_size
            self._loop.call_soon(self._release_ready_future_or_reschedule)
            return
        # USERNOTE: Case 3 - Continue writer process immediately by releasing the future
        # At this point:
        # - We either hit the force ready threshold (256 messages).
        # - Or the queue hasn't grown since last check.
        # So we assume batching is done, and wake the writer.
        self._release_ready_queue_size = 0
        if not ready_future.done():
            ready_future.set_result(queue_size)

    # USERNOTE: This function is scheduled for re-check if the message queue SOFT LIMIT is still exceeded
    # USERNOTE: If YES, cancel connection, something is wrong, either tons of messages sent in very short amount of time (unexpected), or writer/other components not working as expected.
    @callback
    def _check_write_peak(self, _utc_time: dt.datetime) -> None:
        """Check that we are no longer above the write peak."""
        # USERNOTE: Clear the unsub callback that is set when we schedule this task.
        # REASON: The checkWritePeak task is now started, and we don't want something to cancel it during this process.
        self._peak_checker_unsub = None

        # USERNOTE: Case 1 - The message queue now is now below warning threshold (1024)
        # - It was above the threshold, that's this task is scheduled to re-check & handle.
        # WHAT HAPPENED? Maybe the writer has writes the messages and remove from queue.
        if len(self._message_queue) < PENDING_MSG_PEAK:
            return

        self._logger.error(
            (
                "%s: Client unable to keep up with pending messages. Stayed over %s for %s"
                " seconds. The system's load is too high or an integration is"
                " misbehaving; Last message was: %s"
            ),
            self.description,
            PENDING_MSG_PEAK,
            PENDING_MSG_PEAK_TIME,
            self._message_queue[-1],
        )
        # USERNOTE: cancels the connection using _cancel()
        self._cancel()

    @callback
    def _cancel(self) -> None:
        """Cancel the connection."""
        self._closing = True
        self._cancel_peak_checker()
        if self._handle_task is not None:
            self._handle_task.cancel()
        if self._writer_task is not None:
            self._writer_task.cancel()

    @callback
    def _async_handle_hass_stop(self, event: Event) -> None:
        """Cancel this connection."""
        self._cancel()

    # LLM: Interface Documentation
    # Purpose: Main entry point for handling a new WebSocket connection, managing the entire lifecycle
    #          from connection establishment to cleanup.
    # Caveats & Side Effects:
    # - Sets up connection monitoring and cleanup handlers
    # - Manages authentication state
    # - Handles connection timeouts and errors
    # - Registers system event listeners
    # Role in Scope: Primary connection handler that orchestrates the WebSocket connection lifecycle
    async def async_handle(self) -> web.WebSocketResponse:
        """Handle a websocket response."""
        request = self._request
        wsock = self._wsock
        logger = self._logger
        hass = self._hass

        try:
            async with asyncio.timeout(10):
                # USERNOTE: This upgrades the HTTP connection to a WebSocket. (agree upgrade)
                await wsock.prepare(request)
        except ConnectionResetError:
            # Likely the client disconnected before we prepared the websocket
            logger.debug(
                "%s: Connection reset by peer while preparing WebSocket",
                self.description,
            )
            return wsock
        except TimeoutError:
            logger.warning("Timeout preparing request from %s", request.remote)
            return wsock

        logger.debug("%s: Connected from %s", self.description, request.remote)
        # USERNOTE: Register current task so that when hass stop, the task can be canceled in callback '_cancel()'.
        # - Current task = The task that is running WebSocketHandler.async_handle().
        self._handle_task = asyncio.current_task()

        # LLM: System Event Registration
        # - Registers handlers for system events (stop, logging changes)
        # - These handlers ensure proper cleanup and state management
        unsub_stop = hass.bus.async_listen(
            EVENT_HOMEASSISTANT_STOP, self._async_handle_hass_stop
        )
        cancel_logging_listener = hass.bus.async_listen(
            EVENT_LOGGING_CHANGED, self._async_logging_changed
        )

        # LLM: Writer Setup
        # - Initializes the WebSocket writer for sending messages
        # - Sets up text frame sending capability
        writer = wsock._writer  # noqa: SLF001
        if TYPE_CHECKING:
            assert writer is not None

        # USERNOTE: Once websocket upgrade accepted, we will TEXT FRAME to client for auth phase e.g.
        send_bytes_text = partial(writer.send_frame, opcode=WSMsgType.TEXT)
        # USERNOTE: Prepare to start auth phase
        auth = AuthPhase(
            logger, hass, self._send_message, self._cancel, request, send_bytes_text
        )
        connection: ActiveConnection | None = None
        disconnect_warn: str | None = None

        try:
            # LLM: Authentication Phase
            # - Handles client authentication
            # - Sets up connection state after successful auth
            # - Increases writer buffer limit for better performance
            connection = await self._async_handle_auth_phase(auth, send_bytes_text)
            # USERNOTE: Increase aiohttp writer write buffer limit to avoid backpressure on aiohttp to cause messages stall in queue and cause memory issue.
            # USERNOTE: NOTE: This is intended to be used after AUTH phrase which ensure user is not a malicious user before increasing the limit.
            self._async_increase_writer_limit(writer)
            await self._async_websocket_command_phase(connection)
        except asyncio.CancelledError:
            logger.debug("%s: Connection cancelled", self.description)
            raise
        except Disconnect as ex:
            if disconnect_msg := str(ex):
                disconnect_warn = disconnect_msg

            logger.debug("%s: Connection closed by client: %s", self.description, ex)
        except Exception:
            logger.exception(
                "%s: Unexpected error inside websocket API", self.description
            )
        finally:
            # LLM: Cleanup Phase
            # - Cancels event listeners
            # - Closes connection
            # - Cleans up resources
            # - Handles any pending messages
            cancel_logging_listener()
            unsub_stop()

            self._cancel_peak_checker()

            if connection is not None:
                connection.async_handle_close()

            self._closing = True
            if self._ready_future and not self._ready_future.done():
                self._ready_future.set_result(len(self._message_queue))

            await self._async_cleanup_writer_and_close(disconnect_warn, connection)

        return wsock

    async def _async_handle_auth_phase(
        self,
        auth: AuthPhase,
        send_bytes_text: Callable[[bytes], Coroutine[Any, Any, None]],
    ) -> ActiveConnection:
        """Handle the auth phase of the websocket connection."""
        # TODO Send auth message
        await send_bytes_text(AUTH_REQUIRED_MESSAGE)

        # Auth Phase
        try:
            # USERNOTE: Waits for up to 10 seconds for the client to respond with an auth message.
            msg = await self._wsock.receive(10)
        except TimeoutError as err:
            raise Disconnect("Did not receive auth message within 10 seconds") from err

        # USERNOTE: If the client closes the connection before authenticating, we disconnect.
        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
            raise Disconnect("Received close message during auth phase")

        # USERNOTE: Disconnect if WSMsgType.ERROR or unexpected non-text frames as well.
        if msg.type is not WSMsgType.TEXT:
            if msg.type is WSMsgType.ERROR:
                # msg.data is the exception
                raise Disconnect(
                    f"Received error message during auth phase: {msg.data}"
                )
            raise Disconnect(
                f"Received non-Text message of type {msg.type} during auth phase"
            )

        try:
            auth_msg_data = json_loads(msg.data)
        except ValueError as err:
            raise Disconnect("Received invalid JSON during auth phase") from err

        if self._debug:
            self._logger.debug("%s: Received %s", self.description, auth_msg_data)
        # USERNOTE: Pass client auth message to AUTH to handle.
        connection = await auth.async_handle(auth_msg_data)
        # As the webserver is now started before the start
        # event we do not want to block for websocket responses
        #
        # We only start the writer queue after the auth phase is completed
        # since there is no need to queue messages before the auth phase
        # USERNOTE: ======== POST AUTH PHASE ========
        self._connection = connection
        # USERNOTE: Start writer queue as AUTH phase is completed.
        self._writer_task = create_eager_task(self._writer(connection, send_bytes_text))
        # USERNOTE: Increment the authenticated connection count.
        self._hass.data[DATA_CONNECTIONS] = self._hass.data.get(DATA_CONNECTIONS, 0) + 1
        # USERNOTE: Execute the registered HASS jobs for SIGNAL_WEBSOCKET_CONNECTED.
        async_dispatcher_send(self._hass, SIGNAL_WEBSOCKET_CONNECTED)

        self._authenticated = True
        return connection

    # USERNOTE: Increase aiohttp writer write buffer limit to avoid backpressure on aiohttp to cause messages stall in queue and cause memory issue.
    # USERNOTE: NOTE: This is intended to be used after AUTH phrase which ensure user is not a malicious user before increasing the limit.
    @callback
    def _async_increase_writer_limit(self, writer: WebSocketWriter) -> None:
        #
        #
        # Our websocket implementation is backed by a deque
        #
        # As back-pressure builds, the queue will back up and use more memory
        # until we disconnect the client when the queue size reaches
        # MAX_PENDING_MSG. When we are generating a high volume of websocket messages,
        # we hit a bottleneck in aiohttp where it will wait for
        # the buffer to drain before sending the next message and messages
        # start backing up in the queue.
        #
        # https://github.com/aio-libs/aiohttp/issues/1367 added drains
        # to the websocket writer to handle malicious clients and network issues.
        # The drain causes multiple problems for us since the buffer cannot be
        # drained fast enough when we deliver a high volume or large messages:
        #
        # - We end up disconnecting the client. The client will then reconnect,
        # and the cycle repeats itself, which results in a significant amount of
        # CPU usage.
        #
        # - Messages latency increases because messages cannot be moved into
        # the TCP buffer because it is blocked waiting for the drain to happen because
        # of the low default limit of 16KiB. By increasing the limit, we instead
        # rely on the underlying TCP buffer and stack to deliver the messages which
        # can typically happen much faster.
        #
        # After the auth phase is completed, and we are not concerned about
        # the user being a malicious client, we set the limit to force a drain
        # to 1MiB. 1MiB is the maximum expected size of the serialized entity
        # registry, which is the largest message we usually send.
        #
        # https://github.com/aio-libs/aiohttp/commit/b3c80ee3f7d5d8f0b8bc27afe52e4d46621eaf99
        # added a way to set the limit, but there is no way to actually
        # reach the code to set the limit, so we have to set it directly.
        #
        # USERNOTE: This increases the internal buffer size to 1 MiB from the default 16kib, which effectively:
        # USERNOTE: - aiohttp won't stall writes until it hits 1 MiB in its own internal buffer.
        # USERNOTE: - This lets more data get flushed into the OS kernel's TCP buffer without waiting. (TCP buffer default to be quite large anyway)
        writer._limit = 2**20  # noqa: SLF001

    # LLM: Interface Documentation
    # Purpose: Handles the command phase of an authenticated websocket connection, processing incoming messages
    #          and routing them to appropriate handlers.
    # Caveats & Side Effects:
    # - Raises Disconnect for invalid messages or connection errors
    # - Logs debug messages if enabled
    # - Processes both text and binary messages
    # Role in Scope: Core message processing loop after authentication, responsible for maintaining
    #               the websocket connection and handling client commands
    async def _async_websocket_command_phase(
        self, connection: ActiveConnection
    ) -> None:
        """Handle the command phase of the websocket connection."""
        # LLM: Implementation Documentation
        # Cache frequently accessed methods to avoid attribute lookups in the hot loop
        wsock = self._wsock
        async_handle_str = connection.async_handle
        async_handle_binary = connection.async_handle_binary

        # LLM: Main command processing loop - continues until connection is closed
        while not wsock.closed:
            # LLM: Wait for next message from client
            # USERNOTE: This WebsocketResponse.receive() will swallow and auto-handle ping/pong frames automatically, so the msg we receive here is
            # the actual message from the client.
            msg = await wsock.receive()
            msg_type = msg.type
            msg_data = msg.data

            # LLM: Handle connection closure messages
            if msg_type in CLOSE_MSG_TYPES:
                break

            # LLM: Process binary messages - used for specialized handlers
            if msg_type is WSMsgType.BINARY:
                if len(msg_data) < 1:
                    raise Disconnect("Received invalid binary message.")

                # LLM: Binary messages use first byte as handler ID, rest as payload
                # USERNOTE: HA core specific protocol with frontend to add handle id
                handler = msg_data[0] # USERNOTE: handler id
                payload = msg_data[1:]
                async_handle_binary(handler, payload)
                continue

            # LLM: Validate message type - only TEXT and BINARY are supported
            # USERNOTE: ====== This ensure below are TEXT message handling flow ======
            if msg_type is not WSMsgType.TEXT:
                if msg_type is WSMsgType.ERROR:
                    # msg.data is the exception
                    raise Disconnect(
                        f"Received error message during command phase: {msg.data}"
                    )
                raise Disconnect(f"Received non-Text message of type {msg_type}.")

            # LLM: Parse JSON message - all text messages must be valid JSON
            try:
                command_msg_data = json_loads(msg_data)
            except ValueError as ex:
                raise Disconnect("Received invalid JSON.") from ex

            # LLM: Log received message if debug logging is enabled
            if self._debug:
                self._logger.debug(
                    "%s: Received %s", self.description, command_msg_data
                )

            # LLM: Handle single command or batch of commands
            # command_msg_data is always deserialized from JSON as a list
            if type(command_msg_data) is not list:
                # LLM: Single command - process directly
                async_handle_str(command_msg_data)
                continue

            # LLM: Batch of commands - process each one sequentially
            # USERNOTE: For the message coalescing featurem, this process each command 1 by 1 asynchronously.
            for split_msg in command_msg_data:
                async_handle_str(split_msg)

    async def _async_cleanup_writer_and_close(
        self, disconnect_warn: str | None, connection: ActiveConnection | None
    ) -> None:
        """Cleanup the writer and close the websocket."""
        # If the writer gets canceled we still need to close the websocket
        # so we have another finally block to make sure we close the websocket
        # if the writer gets canceled.
        wsock = self._wsock
        hass = self._hass
        logger = self._logger
        try:
            if self._writer_task:
                await self._writer_task
        finally:
            try:
                # Make sure all error messages are written before closing
                await wsock.close()
            finally:
                if disconnect_warn is None:
                    logger.debug("%s: Disconnected", self.description)
                else:
                    logger.warning(
                        "%s: Disconnected: %s", self.description, disconnect_warn
                    )

                if connection is not None:
                    hass.data[DATA_CONNECTIONS] -= 1
                    self._connection = None

                # USERNOTE: Execute the registered HASS jobs for SIGNAL_WEBSOCKET_DISCONNECTED.
                async_dispatcher_send(hass, SIGNAL_WEBSOCKET_DISCONNECTED)

                # Break reference cycles to make sure GC can happen sooner
                self._wsock = None  # type: ignore[assignment]
                self._request = None  # type: ignore[assignment]
                self._hass = None  # type: ignore[assignment]
                self._logger = None  # type: ignore[assignment]
                self._message_queue = None  # type: ignore[assignment]
                self._handle_task = None
                self._writer_task = None
                self._ready_future = None
