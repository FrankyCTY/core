"""Helpers for Home Assistant dispatcher & internal component/platform."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Coroutine
from functools import partial
import logging
from typing import Any, overload

from homeassistant.core import (
    HassJob,
    HassJobType,
    HomeAssistant,
    callback,
    get_hassjob_callable_job_type,
)
from homeassistant.loader import bind_hass
from homeassistant.util.async_ import run_callback_threadsafe
from homeassistant.util.logging import catch_log_exception, log_exception

# Explicit reexport of 'SignalType' for backwards compatibility
from homeassistant.util.signal_type import SignalType as SignalType  # noqa: PLC0414

_LOGGER = logging.getLogger(__name__)
# USERNOTE: Key in hass.data to store the internal dispatcher.
DATA_DISPATCHER = "dispatcher"


# USERNOTE: Type of the Internal dispatcher registry
# USERNOTE: *_Ts: Allow to define argument types for the dispatcher callable.
# USERNOTE: TYPE: { [signal/str]: { callable → HassJob wrapped the callable for actual dispatching } }”
# USERNOTE: - Keyed by signal/str and the value is a dict of corresponding { [callable handler] →  HassJob wrapped the callable for actual dispatching }
type _DispatcherDataType[*_Ts] = dict[
    SignalType[*_Ts] | str,
    dict[
        Callable[[*_Ts], Any]
        | Callable[..., Any],  # USERNOTE: Original callable requested
        HassJob[..., None | Coroutine[Any, Any, None]]
        | None,  # USERNOTE: HassJob wrapped the callable for actual dispatching
    ],
]


@overload
@bind_hass
def dispatcher_connect[*_Ts](
    hass: HomeAssistant, signal: SignalType[*_Ts], target: Callable[[*_Ts], None]
) -> Callable[[], None]: ...


@overload
@bind_hass
def dispatcher_connect(
    hass: HomeAssistant, signal: str, target: Callable[..., None]
) -> Callable[[], None]: ...
@bind_hass  # type: ignore[misc]  # workaround; exclude typing of 2 overload in func def
def dispatcher_connect[*_Ts](
    hass: HomeAssistant,
    signal: SignalType[*_Ts],
    target: Callable[[*_Ts], None],
) -> Callable[[], None]:
    """Connect a callable function to a signal."""
    async_unsub = run_callback_threadsafe(
        hass.loop, async_dispatcher_connect, hass, signal, target
    ).result()

    def remove_dispatcher() -> None:
        """Remove signal listener."""
        run_callback_threadsafe(hass.loop, async_unsub).result()

    return remove_dispatcher


@callback
def _async_remove_dispatcher[*_Ts](
    dispatchers: _DispatcherDataType[*_Ts],
    signal: SignalType[*_Ts] | str,
    target: Callable[[*_Ts], Any] | Callable[..., Any],
) -> None:
    """Remove signal listener."""
    try:
        signal_dispatchers = dispatchers[signal]
        del signal_dispatchers[target]
        # Cleanup the signal dict if it is now empty
        # to prevent memory leaks
        if not signal_dispatchers:
            del dispatchers[signal]
    except (KeyError, ValueError):
        # KeyError is key target listener did not exist
        # ValueError if listener did not exist within signal
        _LOGGER.warning("Unable to remove unknown dispatcher %s", target)


@overload
@callback
@bind_hass
def async_dispatcher_connect[*_Ts](
    hass: HomeAssistant, signal: SignalType[*_Ts], target: Callable[[*_Ts], Any]
) -> Callable[[], None]: ...


@overload
@callback
@bind_hass
def async_dispatcher_connect(
    hass: HomeAssistant, signal: str, target: Callable[..., Any]
) -> Callable[[], None]: ...


@callback
@bind_hass
def async_dispatcher_connect[*_Ts](
    hass: HomeAssistant,
    signal: SignalType[*_Ts] | str,
    target: Callable[[*_Ts], Any] | Callable[..., Any],
) -> Callable[[], None]:
    """Connect a callable function to a signal.

    This method must be run in the event loop.
    """
    if DATA_DISPATCHER not in hass.data:
        hass.data[DATA_DISPATCHER] = defaultdict(dict)
    dispatchers: _DispatcherDataType[*_Ts] = hass.data[DATA_DISPATCHER]
    dispatchers[signal][target] = None
    # Use a partial for the remove since it uses
    # less memory than a full closure since a partial copies
    # the body of the function and we don't have to store
    # many different copies of the same function
    return partial(_async_remove_dispatcher, dispatchers, signal, target)


@overload
@bind_hass
def dispatcher_send[*_Ts](
    hass: HomeAssistant, signal: SignalType[*_Ts], *args: *_Ts
) -> None: ...


@overload
@bind_hass
def dispatcher_send(hass: HomeAssistant, signal: str, *args: Any) -> None: ...


@bind_hass  # type: ignore[misc]  # workaround; exclude typing of 2 overload in func def
def dispatcher_send[*_Ts](
    hass: HomeAssistant, signal: SignalType[*_Ts], *args: *_Ts
) -> None:
    """Send signal and data."""
    hass.loop.call_soon_threadsafe(async_dispatcher_send_internal, hass, signal, *args)


def _format_err[*_Ts](
    signal: SignalType[*_Ts] | str,
    target: Callable[[*_Ts], Any] | Callable[..., Any],
    *args: Any,
) -> str:
    """Format error message."""

    return (
        # Functions wrapped in partial do not have a __name__
        f"Exception in {getattr(target, '__name__', None) or target} "
        f"when dispatching '{signal}': {args}"
    )


def _generate_job[*_Ts](
    signal: SignalType[*_Ts] | str, target: Callable[[*_Ts], Any] | Callable[..., Any]
) -> HassJob[..., Coroutine[Any, Any, None] | None]:
    """Generate a HassJob for a signal and target."""
    # USERNOTE: Determine job type HassJobType for callback. (e.g. coroutine function, callback, executor)
    job_type = get_hassjob_callable_job_type(target)
    # USERNOTE: Prefix with "dispatcher" to identify it as an internal dispatcher job.
    name = f"dispatcher {signal}"
    if job_type is HassJobType.Callback:
        # We will catch exceptions in the callback to avoid
        # wrapping the callback since calling wraps() is more
        # expensive than the whole dispatcher_send process
        # USERNOTE: In HASS, the fn marked as Callback functions are expected to be small, safe, and fast. Wrapping them in catch_log_exception() adds measurable overhead, and isn’t worth it.
        return HassJob(target, name, job_type=job_type)
    return HassJob(
        catch_log_exception(
            target, partial(_format_err, signal, target), job_type=job_type
        ),
        name,
        job_type=job_type,
    )


@overload
@callback
@bind_hass
def async_dispatcher_send[*_Ts](
    hass: HomeAssistant, signal: SignalType[*_Ts], *args: *_Ts
) -> None: ...


@overload
@callback
@bind_hass
def async_dispatcher_send(hass: HomeAssistant, signal: str, *args: Any) -> None: ...


# USERNOTE: Execute the registered HASS jobs for the given SINGAL.
@callback
@bind_hass
def async_dispatcher_send[*_Ts](
    hass: HomeAssistant, signal: SignalType[*_Ts] | str, *args: *_Ts
) -> None:
    """Send signal and data.

    This method must be run in the event loop.
    """
    # We turned on asyncio debug in April 2024 in the dev containers
    # in the hope of catching some of the issues that have been
    # reported. It will take a while to get all the issues fixed in
    # custom components.
    #
    # In 2025.5 we should guard the `verify_event_loop_thread`
    # check with a check for the `hass.config.debug` flag being set as
    # long term we don't want to be checking this in production
    # environments since it is a performance hit.
    hass.verify_event_loop_thread("async_dispatcher_send")
    async_dispatcher_send_internal(hass, signal, *args)


# USERNOTE: Execute the registered HASS jobs for the given SINGAL.
# USERNOTE: If hass job is callable: Synchronously invoke the callback.
# USERNOTE: Otherwise:
@callback
@bind_hass
def async_dispatcher_send_internal[*_Ts](
    hass: HomeAssistant, signal: SignalType[*_Ts] | str, *args: *_Ts
) -> None:
    """Send signal and data.

    This method is intended to only be used by core internally
    and should not be considered a stable API. We will make
    breaking changes to this function in the future and it
    should not be used in integrations.

    This method must be run in the event loop.
    """
    # USERNOTE: If dispatch is NOT set up, exit silently.
    if (maybe_dispatchers := hass.data.get(DATA_DISPATCHER)) is None:
        return
    dispatchers: _DispatcherDataType[*_Ts] = maybe_dispatchers
    # USERNOTE: If nobody is listening to this signal, return
    if (target_list := dispatchers.get(signal)) is None:
        return

    # USERNOTE: target_list is a dict of { [callable handler] → HassJob return type }
    # USERNOTE: WHY use list()? So we create a shallow copy to iterate. AS Python raises a RuntimeError if the dict is modified while iterating over it.
    # USERNOTE: INTERNAL safeguard: Underlying structure reshuffles if the dict changes (key added/removed) cause iterator's internal index is no longer valid e.g.
    for target, job in list(target_list.items()):
        # USERNOTE: If hass job is not created for this target callback, create one.
        if job is None:
            job = _generate_job(signal, target)
            target_list[target] = job
        # We do not wrap Callback jobs in catch_log_exception since
        # single use dispatchers spend more time wrapping the callback
        # than the actual callback takes to run in many cases.
        # USERNOTE: In HASS, the fn marked as Callback functions are expected to be small, safe, and fast. Wrapping them in catch_log_exception() adds measurable overhead, and isn’t worth it.
        if job.job_type is HassJobType.Callback:
            try:
                # USERNOTE: Synchronously invoke the callback.
                job.target(*args)
            except Exception:  # noqa: BLE001
                log_exception(partial(_format_err, signal, target), *args)  # type: ignore[arg-type]
        else:
            # USERNOTE: Execute the hass job based on the job type to make the code more efficient.
            # USERNOTE: Track the task in hass core internal task list (background or foreground) list, and remove when it is done.
            hass.async_run_hass_job(job, *args)
