"""Advanced timeout handling.

Set of helper classes to handle timeouts of tasks with advanced options
like zones and freezing of timeouts.
"""

from __future__ import annotations

import asyncio
import enum
from types import TracebackType
from typing import Any, Self

from .async_ import run_callback_threadsafe

ZONE_GLOBAL = "global"


class _State(enum.Enum):
    """States of a task."""

    INIT = "INIT"
    ACTIVE = "ACTIVE"
    TIMEOUT = "TIMEOUT"
    EXIT = "EXIT"


class _GlobalFreezeContext:
    """Context manager that freezes the global timeout."""

    def __init__(self, manager: TimeoutManager) -> None:
        """Initialize internal timeout context manager."""
        self._loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._manager: TimeoutManager = manager

    async def __aenter__(self) -> Self:
        self._enter()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._exit()
        return None

    def __enter__(self) -> Self:
        self._loop.call_soon_threadsafe(self._enter)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._loop.call_soon_threadsafe(self._exit)
        return None

    def _enter(self) -> None:
        """Run freeze."""
        if self._manager.freezes_done:
            # Global reset
            for task in self._manager.global_tasks:
                task.pause()

            # Zones reset
            for zone in self._manager.zones.values():
                if not zone.freezes_done:
                    continue
                zone.pause()

        self._manager.global_freezes.append(self)

    def _exit(self) -> None:
        """Finish freeze."""
        self._manager.global_freezes.remove(self)
        if not self._manager.freezes_done:
            return

        # Global reset
        for task in self._manager.global_tasks:
            task.reset()

        # Zones reset
        for zone in self._manager.zones.values():
            if not zone.freezes_done:
                continue
            zone.reset()


class _ZoneFreezeContext:
    """Context manager that freezes a zone timeout."""

    def __init__(self, zone: _ZoneTimeoutManager) -> None:
        """Initialize internal timeout context manager."""
        self._loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._zone: _ZoneTimeoutManager = zone

    async def __aenter__(self) -> Self:
        self._enter()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._exit()
        return None

    def __enter__(self) -> Self:
        self._loop.call_soon_threadsafe(self._enter)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._loop.call_soon_threadsafe(self._exit)
        return None

    def _enter(self) -> None:
        """Run freeze."""
        if self._zone.freezes_done:
            self._zone.pause()
        self._zone.enter_freeze(self)

    def _exit(self) -> None:
        """Finish freeze."""
        self._zone.exit_freeze(self)
        if not self._zone.freezes_done:
            return
        self._zone.reset()


class _GlobalTaskContext:
    """Context manager that tracks a global task."""

    def __init__(
        self,
        manager: TimeoutManager,
        task: asyncio.Task[Any],
        timeout: float,
        cool_down: float,
        cancel_message: str | None,
    ) -> None:
        """Initialize internal timeout context manager."""
        self._loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._manager: TimeoutManager = manager
        self._task: asyncio.Task[Any] = task
        self._time_left: float = timeout
        self._expiration_time: float | None = None
        self._timeout_handler: asyncio.Handle | None = None
        self._on_wait_task: asyncio.Task | None = None
        self._wait_zone: asyncio.Event = asyncio.Event()
        self._state: _State = _State.INIT
        self._cool_down: float = cool_down
        # USERNOTE: This records the number of external cancellation requests already pending before the timeout manager starts its own monitoring.
        self._cancelling = 0
        self._cancel_message = cancel_message

    async def __aenter__(self) -> Self:
        self._manager.global_tasks.append(self)
        # USERNOTE: Set up callback for timeout e.g.
        self._start_timer()
        self._state = _State.ACTIVE
        # USERNOTE: Remember if the task was already cancelling
        # so when we __aexit__ we can decide if we should
        # raise asyncio.TimeoutError or let the cancellation propagate
        self._cancelling = self._task.cancelling()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._stop_timer()
        self._manager.global_tasks.remove(self)

        # Timeout on exit
        # USERNOTE: Only when this context manager has determine a timeout in `_on_timeout`.
        if exc_type is asyncio.CancelledError and self.state is _State.TIMEOUT:
            # The timeout was hit, and the task was cancelled
            # so we need to uncancel the task since the cancellation
            # should not leak out of the context manager
            # USERNOTE: Prevent the asyncio.CancelledError from propagating out of the context manager as we want to customize the time out handling.
            # USERNOTE: If after decrementing 1 cancel request, still have more than the snapshot external cancel requests, it means SOMETHING is cancelling the task, likely caused by external.
            # USERNOTE: This means the cancellation was caused externally and this manager should not handle it as the external would have handled it.
            if self._task.uncancel() > self._cancelling:
                # If the task was already cancelling don't raise
                # asyncio.TimeoutError and instead return None
                # to allow the cancellation to propagate
                return None
            # USERNOTE: Raise error as we know this context manger has rasied timeout, and then after uncancel the task, it has same or less cancel requests than the snapshot, it means the context manager is the one that raised the timeout, not caused by external.
            raise TimeoutError

        # USERNOTE: Exit peacefully without timeout, update wait zone flag as the corresponding zones are done at this point.
        self._state = _State.EXIT
        # USERNOTE: This context has exited and itself has not timed out.
        # USERNOTE: _on_wait coroutine is waiting for this signal, so we need to set it, which then will cancel the task.
        self._wait_zone.set()
        return None

    @property
    def state(self) -> _State:
        """Return state of the Global task."""
        return self._state

    def zones_done_signal(self) -> None:
        """Signal that all zones are done."""
        self._wait_zone.set()

    def _start_timer(self) -> None:
        """Start timeout handler."""
        if self._timeout_handler:
            return

        # USERNOTE: The time will expire
        # FIXME: Why not use monotonic time? Because the call_at is based on loop time, not monotonic time.
        self._expiration_time = self._loop.time() + self._time_left
        # USERNOTE: Schedule a task to run at the expiration time.
        self._timeout_handler = self._loop.call_at(
            self._expiration_time, self._on_timeout
        )

    def _stop_timer(self) -> None:
        """Stop zone timer."""
        if self._timeout_handler is None:
            return

        self._timeout_handler.cancel()
        self._timeout_handler = None
        # Calculate new timeout
        assert self._expiration_time
        self._time_left = self._expiration_time - self._loop.time()

    # USERNOTE: This is called when the timeout expires.
    # Update state to TIMEOUT, which trigger different exit handling for this context manager.
    def _on_timeout(self) -> None:
        """Process timeout."""
        self._state = _State.TIMEOUT
        self._timeout_handler = None

        # Reset timer if zones are running
        if not self._manager.zones_done:
            # USERNOTE: Create a task to run the _on_wait coroutine to wait for all zones to finish.
            self._on_wait_task = asyncio.create_task(self._on_wait())
        else:
            # USERNOTE: If all zones are done (or no zones), cancel the task.
            self._cancel_task()

    def _cancel_task(self) -> None:
        """Cancel own task."""
        if self._task.done():
            return
        self._task.cancel(
            f"Global task timeout{': ' + self._cancel_message if self._cancel_message else ''}"
        )

    def pause(self) -> None:
        """Pause timers while it freeze."""
        self._stop_timer()

    def reset(self) -> None:
        """Reset timer after freeze."""
        self._start_timer()

    # USERNOTE: Wait the signal from the asyncio.Event object indicate all zones are done.
    # USERNOTE: Set scenario 1: That flag is set when the context exited without this context manager raising timeout.
    # USERNOTE: Set scenario 2: It's also set when the last zone completes and is dropped from the timeout manager.
    async def _on_wait(self) -> None:
        """Wait until zones are done."""
        await self._wait_zone.wait()
        # USERNOTE: Yield control back to the event loop, enabling other tasks to run.
        await asyncio.sleep(self._cool_down)  # Allow context switch
        self._on_wait_task = None
        # USERNOTE: If this context manager has not timed out, do not cancel the task.
        if self.state != _State.TIMEOUT:
            return
        self._cancel_task()


class _ZoneTaskContext:
    """Context manager that tracks an active task for a zone."""

    def __init__(
        self,
        zone: _ZoneTimeoutManager,
        task: asyncio.Task[Any],
        timeout: float,
        cancel_message: str | None,
    ) -> None:
        """Initialize internal timeout context manager."""
        self._loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._zone: _ZoneTimeoutManager = zone
        self._task: asyncio.Task[Any] = task
        self._state: _State = _State.INIT
        self._time_left: float = timeout
        self._expiration_time: float | None = None
        self._timeout_handler: asyncio.Handle | None = None
        self._cancelling = 0
        self._cancel_message = cancel_message

    @property
    def state(self) -> _State:
        """Return state of the Zone task."""
        return self._state

    async def __aenter__(self) -> Self:
        self._zone.enter_task(self)
        self._state = _State.ACTIVE

        # Zone is on freeze
        if self._zone.freezes_done:
            self._start_timer()

        # Remember if the task was already cancelling
        # so when we __aexit__ we can decide if we should
        # raise asyncio.TimeoutError or let the cancellation propagate
        # USERNOTE: This records the number of external cancellation requests already pending before the timeout manager starts its own monitoring.
        self._cancelling = self._task.cancelling()

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._zone.exit_task(self)
        self._stop_timer()

        # Timeout on exit
        if exc_type is asyncio.CancelledError and self.state is _State.TIMEOUT:
            # The timeout was hit, and the task was cancelled
            # so we need to uncancel the task since the cancellation
            # should not leak out of the context manager
            if self._task.uncancel() > self._cancelling:
                # If the task was already cancelling don't raise
                # asyncio.TimeoutError and instead return None
                # to allow the cancellation to propagate
                return None
            raise TimeoutError

        self._state = _State.EXIT
        return None

    def _start_timer(self) -> None:
        """Start timeout handler."""
        if self._timeout_handler:
            return

        self._expiration_time = self._loop.time() + self._time_left
        self._timeout_handler = self._loop.call_at(
            self._expiration_time, self._on_timeout
        )

    def _stop_timer(self) -> None:
        """Stop zone timer."""
        if self._timeout_handler is None:
            return

        self._timeout_handler.cancel()
        self._timeout_handler = None
        # Calculate new timeout
        assert self._expiration_time
        self._time_left = self._expiration_time - self._loop.time()

    def _on_timeout(self) -> None:
        """Process timeout."""
        self._state = _State.TIMEOUT
        self._timeout_handler = None

        # Timeout
        if self._task.done():
            return
        self._task.cancel(
            f"Zone timeout{': ' + self._cancel_message if self._cancel_message else ''}"
        )

    def pause(self) -> None:
        """Pause timers while it freeze."""
        self._stop_timer()

    def reset(self) -> None:
        """Reset timer after freeze."""
        self._start_timer()


class _ZoneTimeoutManager:
    """Manage the timeouts for a zone."""

    def __init__(self, manager: TimeoutManager, zone: str) -> None:
        """Initialize internal timeout context manager."""
        self._manager: TimeoutManager = manager
        self._zone: str = zone
        self._tasks: list[_ZoneTaskContext] = []
        self._freezes: list[_ZoneFreezeContext] = []

    def __repr__(self) -> str:
        """Representation of a zone."""
        return f"<{self.name}: {len(self._tasks)} / {len(self._freezes)}>"

    @property
    def name(self) -> str:
        """Return Zone name."""
        return self._zone

    @property
    def active(self) -> bool:
        """Return True if zone is active."""
        return len(self._tasks) > 0 or len(self._freezes) > 0

    @property
    def freezes_done(self) -> bool:
        """Return True if all freeze are done."""
        return len(self._freezes) == 0 and self._manager.freezes_done

    def enter_task(self, task: _ZoneTaskContext) -> None:
        """Start into new Task."""
        self._tasks.append(task)

    def exit_task(self, task: _ZoneTaskContext) -> None:
        """Exit a running Task."""
        self._tasks.remove(task)

        # On latest listener
        if not self.active:
            self._manager.drop_zone(self.name)

    def enter_freeze(self, freeze: _ZoneFreezeContext) -> None:
        """Start into new freeze."""
        self._freezes.append(freeze)

    def exit_freeze(self, freeze: _ZoneFreezeContext) -> None:
        """Exit a running Freeze."""
        self._freezes.remove(freeze)

        # On latest listener
        if not self.active:
            self._manager.drop_zone(self.name)

    def pause(self) -> None:
        """Stop timers while it freeze."""
        if not self.active:
            return

        # Forward pause
        for task in self._tasks:
            task.pause()

    def reset(self) -> None:
        """Reset timer after freeze."""
        if not self.active:
            return

        # Forward reset
        for task in self._tasks:
            task.reset()


class TimeoutManager:
    """Class to manage timeouts over different zones.

    Manages both global and zone based timeouts.
    """

    def __init__(self) -> None:
        """Initialize TimeoutManager."""
        self._loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._zones: dict[str, _ZoneTimeoutManager] = {}
        self._globals: list[_GlobalTaskContext] = []
        self._freezes: list[_GlobalFreezeContext] = []

    @property
    def zones_done(self) -> bool:
        """Return True if all zones are finished."""
        return not bool(self._zones)

    @property
    def freezes_done(self) -> bool:
        """Return True if all freezes are finished."""
        return not self._freezes

    @property
    def zones(self) -> dict[str, _ZoneTimeoutManager]:
        """Return all Zones."""
        return self._zones

    @property
    def global_tasks(self) -> list[_GlobalTaskContext]:
        """Return all global Tasks."""
        return self._globals

    @property
    def global_freezes(self) -> list[_GlobalFreezeContext]:
        """Return all global Freezes."""
        return self._freezes

    def drop_zone(self, zone_name: str) -> None:
        """Drop a zone out of scope."""
        self._zones.pop(zone_name, None)
        if self._zones:
            return

        # Signal Global task, all zones are done
        for task in self._globals:
            task.zones_done_signal()

    def async_timeout(
        self,
        timeout: float,
        zone_name: str = ZONE_GLOBAL,
        cool_down: float = 0,
        cancel_message: str | None = None,
    ) -> _ZoneTaskContext | _GlobalTaskContext:
        """Timeout based on a zone.

        For using as Async Context Manager.
        """
        current_task: asyncio.Task[Any] | None = asyncio.current_task()
        assert current_task

        # Global Zone
        if zone_name == ZONE_GLOBAL:
            return _GlobalTaskContext(
                self, current_task, timeout, cool_down, cancel_message
            )

        # Zone Handling
        if zone_name in self.zones:
            zone: _ZoneTimeoutManager = self.zones[zone_name]
        else:
            self.zones[zone_name] = zone = _ZoneTimeoutManager(self, zone_name)

        # Create Task
        return _ZoneTaskContext(zone, current_task, timeout, cancel_message)

    def async_freeze(
        self, zone_name: str = ZONE_GLOBAL
    ) -> _ZoneFreezeContext | _GlobalFreezeContext:
        """Freeze all timer until job is done.

        For using as Async Context Manager.
        """
        # Global Freeze
        if zone_name == ZONE_GLOBAL:
            return _GlobalFreezeContext(self)

        # Zone Freeze
        if zone_name in self.zones:
            zone: _ZoneTimeoutManager = self.zones[zone_name]
        else:
            self.zones[zone_name] = zone = _ZoneTimeoutManager(self, zone_name)

        return _ZoneFreezeContext(zone)

    def freeze(
        self, zone_name: str = ZONE_GLOBAL
    ) -> _ZoneFreezeContext | _GlobalFreezeContext:
        """Freeze all timer until job is done.

        For using as Context Manager.
        """
        return run_callback_threadsafe(
            self._loop, self.async_freeze, zone_name
        ).result()
