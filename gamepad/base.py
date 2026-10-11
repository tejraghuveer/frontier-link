"""
Base Gamepad Adapter and Common Protocol Types for RDR2 Mobile Controller.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set
import math


class VerificationLevel(str, Enum):
    NOT_TESTED = "NOT TESTED"
    SIMULATED_PASS = "SIMULATED PASS"
    SERVER_VERIFIED = "SERVER VERIFIED"
    WINDOWS_VERIFIED = "WINDOWS VERIFIED"
    RDR2_VERIFIED = "RDR2 VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class GamepadBackendStatus(str, Enum):
    NOT_INITIALIZED = "NOT_INITIALIZED"
    READY = "READY"
    DRIVER_NOT_FOUND = "DRIVER_NOT_FOUND"
    INIT_FAILED = "INIT_FAILED"
    ERROR = "ERROR"
    CLOSED = "CLOSED"


SUPPORTED_BUTTONS: Set[str] = {
    "A", "B", "X", "Y",
    "LB", "RB",
    "L3", "R3",
    "VIEW", "MENU"
}

SUPPORTED_DPAD: Set[str] = {
    "UP", "DOWN", "LEFT", "RIGHT"
}


@dataclass
class InputState:
    seq: int
    buttons: Set[str] = field(default_factory=set)
    dpad: Set[str] = field(default_factory=set)
    axes: Dict[str, float] = field(default_factory=lambda: {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0})
    triggers: Dict[str, float] = field(default_factory=lambda: {"lt": 0.0, "rt": 0.0})

    @classmethod
    def neutral(cls, seq: int = 0) -> "InputState":
        return cls(
            seq=seq,
            buttons=set(),
            dpad=set(),
            axes={"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
            triggers={"lt": 0.0, "rt": 0.0}
        )

    @classmethod
    def from_dict(cls, data: dict) -> "InputState":
        seq = int(data.get("seq", 0))
        raw_buttons = data.get("buttons", [])
        if not isinstance(raw_buttons, (list, set)):
            raise ValueError("'buttons' must be a list or set")
        buttons = set(b for b in raw_buttons if b in SUPPORTED_BUTTONS)

        raw_dpad = data.get("dpad", [])
        if not isinstance(raw_dpad, (list, set)):
            raise ValueError("'dpad' must be a list or set")
        dpad = set(d for d in raw_dpad if d in SUPPORTED_DPAD)

        raw_axes = data.get("axes", {})
        if not isinstance(raw_axes, dict):
            raise ValueError("'axes' must be an object")

        def clamp_axis(val: any) -> float:
            try:
                num = float(val)
                if not math.isfinite(num):
                    return 0.0
                return max(-1.0, min(1.0, num))
            except (ValueError, TypeError):
                return 0.0

        axes = {
            "lx": clamp_axis(raw_axes.get("lx", 0.0)),
            "ly": clamp_axis(raw_axes.get("ly", 0.0)),
            "rx": clamp_axis(raw_axes.get("rx", 0.0)),
            "ry": clamp_axis(raw_axes.get("ry", 0.0)),
        }

        raw_triggers = data.get("triggers", {})
        if not isinstance(raw_triggers, dict):
            raise ValueError("'triggers' must be an object")

        def clamp_trigger(val: any) -> float:
            try:
                num = float(val)
                if not math.isfinite(num):
                    return 0.0
                return max(0.0, min(1.0, num))
            except (ValueError, TypeError):
                return 0.0

        triggers = {
            "lt": clamp_trigger(raw_triggers.get("lt", 0.0)),
            "rt": clamp_trigger(raw_triggers.get("rt", 0.0)),
        }

        return cls(
            seq=seq,
            buttons=buttons,
            dpad=dpad,
            axes=axes,
            triggers=triggers
        )


class BaseGamepadAdapter(ABC):
    """Abstract interface isolating gamepad hardware from server/network layer."""

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the virtual gamepad. Returns True if successfully initialized."""
        pass

    @abstractmethod
    def update_input(self, state: InputState) -> bool:
        """Apply the given authoritative input state to the virtual gamepad."""
        pass

    @abstractmethod
    def release_all(self) -> bool:
        """Reset all buttons, triggers, and sticks to neutral safe values."""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, any]:
        """Return diagnostic dictionary regarding backend driver and current hardware state."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Unregister device and free adapter resources."""
        pass
