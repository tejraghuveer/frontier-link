"""
Tests for input-state validation, clamping, type safety, and protocol schemas.
"""

import math
import pytest
from gamepad.base import InputState, SUPPORTED_BUTTONS, SUPPORTED_DPAD


def test_neutral_input_state():
    """Verify neutral state centers axes, resets triggers, and clears buttons."""
    state = InputState.neutral(seq=1)
    assert state.seq == 1
    assert len(state.buttons) == 0
    assert len(state.dpad) == 0
    assert state.axes == {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
    assert state.triggers == {"lt": 0.0, "rt": 0.0}


def test_valid_input_state_parsing():
    """Verify standard compliant payload parses accurately."""
    payload = {
        "type": "input",
        "seq": 101,
        "buttons": ["A", "LB"],
        "dpad": ["UP"],
        "axes": {
            "lx": 0.25,
            "ly": -0.6,
            "rx": 0.0,
            "ry": 0.15
        },
        "triggers": {
            "lt": 0.5,
            "rt": 0.0
        }
    }
    state = InputState.from_dict(payload)
    assert state.seq == 101
    assert state.buttons == {"A", "LB"}
    assert state.dpad == {"UP"}
    assert state.axes["lx"] == 0.25
    assert state.axes["ly"] == -0.6
    assert state.axes["rx"] == 0.0
    assert state.axes["ry"] == 0.15
    assert state.triggers["lt"] == 0.5
    assert state.triggers["rt"] == 0.0


def test_axis_clamping_and_normalization():
    """Verify axes outside [-1.0, 1.0] are strictly clamped."""
    payload = {
        "seq": 102,
        "axes": {
            "lx": 2.5,
            "ly": -99.9,
            "rx": 1.0,
            "ry": -1.0
        }
    }
    state = InputState.from_dict(payload)
    assert state.axes["lx"] == 1.0
    assert state.axes["ly"] == -1.0
    assert state.axes["rx"] == 1.0
    assert state.axes["ry"] == -1.0


def test_nan_and_infinity_handling():
    """Verify NaN, Infinity, and non-numeric values in axes or triggers are converted to safe defaults."""
    payload = {
        "seq": 103,
        "axes": {
            "lx": float("nan"),
            "ly": float("inf"),
            "rx": float("-inf"),
            "ry": "not-a-number"
        },
        "triggers": {
            "lt": float("nan"),
            "rt": float("inf")
        }
    }
    state = InputState.from_dict(payload)
    assert state.axes["lx"] == 0.0
    assert state.axes["ly"] == 0.0
    assert state.axes["rx"] == 0.0
    assert state.axes["ry"] == 0.0
    assert state.triggers["lt"] == 0.0
    assert state.triggers["rt"] == 0.0


def test_trigger_clamping():
    """Verify triggers outside [0.0, 1.0] are strictly clamped."""
    payload = {
        "seq": 104,
        "triggers": {
            "lt": -0.5,
            "rt": 3.7
        }
    }
    state = InputState.from_dict(payload)
    assert state.triggers["lt"] == 0.0
    assert state.triggers["rt"] == 1.0


def test_partial_and_full_analog_triggers():
    """Verify precision for partial trigger pulls (e.g. half-press aim)."""
    for val in [0.0, 0.25, 0.5, 0.75, 1.0]:
        state = InputState.from_dict({"seq": 1, "triggers": {"lt": val, "rt": val}})
        assert pytest.approx(state.triggers["lt"], 0.001) == val
        assert pytest.approx(state.triggers["rt"], 0.001) == val


def test_unsupported_buttons_ignored():
    """Verify unsupported arbitrary button strings are filtered out without error."""
    payload = {
        "seq": 105,
        "buttons": ["A", "INVALID_BTN", "HACK_COMMAND", "B"]
    }
    state = InputState.from_dict(payload)
    assert state.buttons == {"A", "B"}


def test_all_supported_buttons():
    """Verify all 10 supported buttons parse correctly."""
    all_buttons = ["A", "B", "X", "Y", "LB", "RB", "L3", "R3", "VIEW", "MENU"]
    payload = {"seq": 1, "buttons": all_buttons}
    state = InputState.from_dict(payload)
    assert state.buttons == SUPPORTED_BUTTONS


def test_all_dpad_directions():
    """Verify all 4 D-pad directions parse correctly."""
    payload = {"seq": 1, "dpad": ["UP", "DOWN", "LEFT", "RIGHT"]}
    state = InputState.from_dict(payload)
    assert state.dpad == SUPPORTED_DPAD


def test_invalid_types_raise_value_error():
    """Verify non-list buttons or non-dict axes raise ValueError for clean validation handling."""
    with pytest.raises(ValueError, match="'buttons' must be a list or set"):
        InputState.from_dict({"seq": 1, "buttons": "A"})

    with pytest.raises(ValueError, match="'dpad' must be a list or set"):
        InputState.from_dict({"seq": 1, "dpad": 123})

    with pytest.raises(ValueError, match="'axes' must be an object"):
        InputState.from_dict({"seq": 1, "axes": ["lx", 0.5]})

    with pytest.raises(ValueError, match="'triggers' must be an object"):
        InputState.from_dict({"seq": 1, "triggers": 0.5})
