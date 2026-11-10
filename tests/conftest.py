"""Test setup for media_control_ha.

The Home Assistant test plugin (pytest-homeassistant-custom-component)
is only loaded when it is installed — the flow tests are skipped when
it is missing (see test_config_flow.py).

When Home Assistant itself is not installed, minimal stub modules are
registered so the pure-client tests in test_api.py can still import
the integration package (its ``__init__`` imports HA names at module
level). The stubs are never used when real Home Assistant is present.
"""
from __future__ import annotations

import importlib.util
import sys
import types

if importlib.util.find_spec("pytest_homeassistant_custom_component") is not None:
    pytest_plugins = "pytest_homeassistant_custom_component"

    import asyncio
    import datetime
    import threading

    import pytest
    import respx
    from homeassistant.core import HassJob
    from homeassistant.util import dt as dt_util
    from homeassistant.util.async_ import get_scheduled_timer_handles
    from pytest_homeassistant_custom_component.common import INSTANCES
    from pytest_homeassistant_custom_component.plugins import long_repr_strings

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Allow the custom integration to load under test."""
        yield

    @pytest.fixture(autouse=True)
    def verify_cleanup(
        event_loop: asyncio.AbstractEventLoop,
        expected_lingering_tasks: bool,
        expected_lingering_timers: bool,
    ):
        """Same cleanup checks as the test plugin (0.13.x), with one fix.

        pycares (Home Assistant's DNS library) starts a daemon thread
        named ``_run_safe_shutdown_loop`` during event-loop teardown.
        The plugin's stock check treats it as a leak and fails the
        first Home Assistant test of every run, even though the thread
        is created by HA's own stack, not by the integration under
        test. This copy keeps every other check and only allows that
        one thread name through.
        """
        threads_before = frozenset(threading.enumerate())
        tasks_before = asyncio.all_tasks(event_loop)
        yield

        event_loop.run_until_complete(event_loop.shutdown_default_executor())

        if len(INSTANCES) >= 2:
            count = len(INSTANCES)
            for inst in INSTANCES:
                inst.stop()
            pytest.exit(f"Detected non stopped instances ({count}), aborting test run")

        tasks = asyncio.all_tasks(event_loop) - tasks_before
        for task in tasks:
            if expected_lingering_tasks:
                import logging

                logging.getLogger(__name__).warning(
                    "Lingering task after test %r", task
                )
            else:
                pytest.fail(f"Lingering task after test {task!r}")
            task.cancel()
        if tasks:
            event_loop.run_until_complete(asyncio.wait(tasks))

        for handle in get_scheduled_timer_handles(event_loop):
            if not handle.cancelled():
                with long_repr_strings():
                    if expected_lingering_timers:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Lingering timer after test %r", handle
                        )
                    elif handle._args and isinstance(
                        job := handle._args[-1], HassJob
                    ):
                        if job.cancel_on_shutdown:
                            continue
                        pytest.fail(f"Lingering timer after job {job!r}")
                    else:
                        pytest.fail(f"Lingering timer after test {handle!r}")
                    handle.cancel()

        # Verify no threads were left behind (except pycares' shutdown
        # helper, see the docstring above).
        threads = frozenset(threading.enumerate()) - threads_before
        for thread in threads:
            assert isinstance(thread, threading._DummyThread) or (
                thread.name.startswith("waitpid-")
                or "_run_safe_shutdown_loop" in thread.name
            )

        try:
            assert dt_util.DEFAULT_TIME_ZONE is datetime.UTC
        finally:
            dt_util.DEFAULT_TIME_ZONE = datetime.UTC

        try:
            assert not respx.mock.routes, (
                "respx.mock routes not cleaned up, maybe the test needs "
                "to be decorated with @respx.mock"
            )
        finally:
            respx.mock.clear()


def _ensure_stub(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


if importlib.util.find_spec("homeassistant") is None:
    _ha = _ensure_stub("homeassistant")

    _config_entries = _ensure_stub("homeassistant.config_entries")
    _config_entries.ConfigEntry = object

    _core = _ensure_stub("homeassistant.core")
    _core.HomeAssistant = object

    _data_entry_flow = _ensure_stub("homeassistant.data_entry_flow")
    _data_entry_flow.FlowResult = dict

    _helpers = _ensure_stub("homeassistant.helpers")
    _aiohttp_client = _ensure_stub("homeassistant.helpers.aiohttp_client")
    _aiohttp_client.async_get_clientsession = lambda hass: None
    _update_coordinator = _ensure_stub("homeassistant.helpers.update_coordinator")
    _update_coordinator.DataUpdateCoordinator = object

    class _UpdateFailed(Exception):
        pass

    _update_coordinator.UpdateFailed = _UpdateFailed

    _components = _ensure_stub("homeassistant.components")
    _media_player = _ensure_stub("homeassistant.components.media_player")

    class _MediaPlayerEntity:
        pass

    class _MediaPlayerEntityFeature(int):
        PLAY = 1
        PAUSE = 2
        NEXT_TRACK = 4
        PREVIOUS_TRACK = 8
        SEEK = 16

    class _MediaPlayerState(str):
        PLAYING = "playing"
        PAUSED = "paused"
        IDLE = "idle"
        OFF = "off"
        BUFFERING = "buffering"

    class _MediaType(str):
        MUSIC = "music"

    _media_player.MediaPlayerEntity = _MediaPlayerEntity
    _media_player.MediaPlayerEntityFeature = _MediaPlayerEntityFeature
    _media_player.MediaPlayerState = _MediaPlayerState
    _media_player.MediaType = _MediaType

    _entity = _ensure_stub("homeassistant.helpers.entity")
    _entity.DeviceInfo = dict
    _entity_platform = _ensure_stub("homeassistant.helpers.entity_platform")
    _entity_platform.AddEntitiesCallback = object
    _util = _ensure_stub("homeassistant.util")
    _dt = _ensure_stub("homeassistant.util.dt")
    _dt.utcnow = lambda: None
    _dt.parse_datetime = lambda value: None

    _ha.config_entries = _config_entries
    _ha.core = _core
    _ha.data_entry_flow = _data_entry_flow
    _ha.helpers = _helpers
