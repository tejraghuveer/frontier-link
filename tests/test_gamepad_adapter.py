"""
Tests for Gamepad Adapters (MockGamepadAdapter and WindowsGamepadAdapter).
Verifies driver isolation, state updates, simulated testing, and error handling.
"""

import pytest
from gamepad.base import (
    GamepadBackendStatus,
    InputState,
    SUPPORTED_BUTTONS,
    SUPPORTED_DPAD,
    VerificationLevel,
)
from gamepad.mock_adapter import MockGamepadAdapter
from gamepad.windows_adapter import WindowsGamepadAdapter


def test_mock_adapter_lifecycle():
    """Verify mock adapter initializes, reports status, and closes."""
    adapter = MockGamepadAdapter()
    assert adapter.status == GamepadBackendStatus.NOT_INITIALIZED
    assert not adapter.is_initialized

    assert adapter.initialize() is True
    assert adapter.status == GamepadBackendStatus.READY
    assert adapter.is_initialized is True

    status = adapter.get_status()
    assert status["backend_type"] == "MOCK"
    assert status["is_real_hardware"] is False
    assert status["verification_level"] == VerificationLevel.SIMULATED_PASS.value

    adapter.close()
    assert adapter.status == GamepadBackendStatus.CLOSED
    assert not adapter.is_initialized


def test_mock_adapter_every_button_individually():
    """Verify each supported button can be pressed and released individually."""
    adapter = MockGamepadAdapter()
    adapter.initialize()

    for idx, btn in enumerate(SUPPORTED_BUTTONS, start=1):
        # Press button
        state_press = InputState(seq=idx * 2 - 1, buttons={btn})
        assert adapter.update_input(state_press) is True
        assert btn in adapter.current_state.buttons

        # Release button
        state_release = InputState(seq=idx * 2, buttons=set())
        assert adapter.update_input(state_release) is True
        assert btn not in adapter.current_state.buttons


def test_mock_adapter_all_dpad_directions():
    """Verify each D-pad direction can be set and cleared."""
    adapter = MockGamepadAdapter()
    adapter.initialize()

    for idx, direction in enumerate(SUPPORTED_DPAD, start=1):
        state = InputState(seq=idx, dpad={direction})
        assert adapter.update_input(state) is True
        assert direction in adapter.current_state.dpad

    # Clear D-pad
    assert adapter.update_input(InputState.neutral(99)) is True
    assert len(adapter.current_state.dpad) == 0


def test_mock_adapter_simultaneous_combinations():
    """Verify simultaneous buttons, triggers, and dual joysticks."""
    adapter = MockGamepadAdapter()
    adapter.initialize()

    combo_state = InputState(
        seq=50,
        buttons={"A", "LB", "L3"},
        dpad={"UP"},
        axes={"lx": -0.8, "ly": 0.5, "rx": 0.2, "ry": -0.9},
        triggers={"lt": 0.75, "rt": 1.0}
    )
    assert adapter.update_input(combo_state) is True
    assert adapter.current_state.buttons == {"A", "LB", "L3"}
    assert adapter.current_state.dpad == {"UP"}
    assert adapter.current_state.triggers["lt"] == 0.75
    assert adapter.current_state.triggers["rt"] == 1.0
    assert adapter.current_state.axes["lx"] == -0.8


def test_mock_adapter_emergency_release_all():
    """Verify release_all clears held buttons, zeroes triggers, and centers axes."""
    adapter = MockGamepadAdapter()
    adapter.initialize()

    active_state = InputState(
        seq=10,
        buttons={"A", "B", "X"},
        dpad={"DOWN"},
        axes={"lx": 1.0, "ly": 1.0, "rx": 1.0, "ry": 1.0},
        triggers={"lt": 1.0, "rt": 1.0}
    )
    adapter.update_input(active_state)
    assert len(adapter.current_state.buttons) == 3

    assert adapter.release_all() is True
    assert adapter.release_all_count == 1
    assert len(adapter.current_state.buttons) == 0
    assert len(adapter.current_state.dpad) == 0
    assert adapter.current_state.axes == {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
    assert adapter.current_state.triggers == {"lt": 0.0, "rt": 0.0}


def test_mock_adapter_simulated_failures():
    """Verify error resilience when simulated adapter failure is triggered."""
    # Fail on initialization
    fail_init_adapter = MockGamepadAdapter(fail_on_init=True)
    assert fail_init_adapter.initialize() is False
    assert fail_init_adapter.status == GamepadBackendStatus.INIT_FAILED
    assert fail_init_adapter.last_error is not None

    # Fail on update
    fail_update_adapter = MockGamepadAdapter(simulate_failure=True)
    fail_update_adapter.initialize()
    assert fail_update_adapter.update_input(InputState.neutral(1)) is False
    assert "Simulated update failure" in fail_update_adapter.last_error


def test_windows_adapter_missing_driver_behavior():
    """
    Verify WindowsGamepadAdapter gracefully detects absence of ViGEmBus kernel driver
    without raising unhandled exceptions or crashing the host process.
    """
    adapter = WindowsGamepadAdapter()
    res = adapter.initialize()

    status = adapter.get_status()
    assert status["backend_type"] == "WINDOWS_VIGEM"
    assert status["is_real_hardware"] is True

    # On this test machine without ViGEmBus kernel driver, it must report DRIVER_NOT_FOUND or BLOCKED
    if not res:
        assert status["status"] in (
            GamepadBackendStatus.DRIVER_NOT_FOUND.value,
            GamepadBackendStatus.INIT_FAILED.value
        )
        assert status["verification_level"] == VerificationLevel.BLOCKED.value
        assert "ViGEm" in status["driver_instructions"] or "vgamepad" in status["driver_instructions"]
        # Calling update_input safely returns False with clear message
        assert adapter.update_input(InputState.neutral(1)) is False
        assert adapter.last_error is not None
        # Calling release_all safely returns True and clears internal state
        assert adapter.release_all() is True
    else:
        # If the driver happened to be installed, status must be READY
        assert status["status"] == GamepadBackendStatus.READY.value
        assert status["verification_level"] == VerificationLevel.WINDOWS_VERIFIED.value
