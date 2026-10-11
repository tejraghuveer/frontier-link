"""
Mock Gamepad Adapter for simulated tests and headless development.
"""

from typing import Dict, List, Optional
import time
from .base import BaseGamepadAdapter, GamepadBackendStatus, InputState, VerificationLevel


class MockGamepadAdapter(BaseGamepadAdapter):
    """
    Mock virtual gamepad adapter simulating an Xbox 360 controller in memory.
    Logs every state change for automated test assertions.
    """

    def __init__(self, simulate_failure: bool = False, fail_on_init: bool = False):
        self.simulate_failure = simulate_failure
        self.fail_on_init = fail_on_init
        self.is_initialized = False
        self.current_state = InputState.neutral(0)
        self.update_history: List[InputState] = []
        self.release_all_count = 0
        self.last_update_ts: float = 0.0
        self.last_error: Optional[str] = None
        self.status = GamepadBackendStatus.NOT_INITIALIZED

    def initialize(self) -> bool:
        if self.fail_on_init:
            self.status = GamepadBackendStatus.INIT_FAILED
            self.last_error = "Simulated initialization failure in MockGamepadAdapter"
            self.is_initialized = False
            return False

        self.is_initialized = True
        self.status = GamepadBackendStatus.READY
        self.current_state = InputState.neutral(0)
        self.last_error = None
        return True

    def update_input(self, state: InputState) -> bool:
        if not self.is_initialized:
            self.last_error = "MockGamepadAdapter not initialized"
            return False

        if self.simulate_failure:
            self.last_error = "Simulated update failure in MockGamepadAdapter"
            return False

        self.current_state = state
        self.update_history.append(state)
        self.last_update_ts = time.time()
        return True

    def release_all(self) -> bool:
        self.release_all_count += 1
        seq = (self.current_state.seq + 1) if self.current_state else 0
        self.current_state = InputState.neutral(seq)
        self.update_history.append(self.current_state)
        self.last_update_ts = time.time()
        return True

    def get_status(self) -> Dict[str, any]:
        return {
            "backend_type": "MOCK",
            "is_real_hardware": False,
            "status": self.status.value,
            "is_initialized": self.is_initialized,
            "release_all_count": self.release_all_count,
            "total_updates": len(self.update_history),
            "last_error": self.last_error,
            "last_update_ts": self.last_update_ts,
            "current_state": {
                "seq": self.current_state.seq,
                "buttons": sorted(list(self.current_state.buttons)),
                "dpad": sorted(list(self.current_state.dpad)),
                "axes": dict(self.current_state.axes),
                "triggers": dict(self.current_state.triggers),
            },
            "verification_level": VerificationLevel.SIMULATED_PASS.value,
            "driver_instructions": "Using Mock Gamepad Adapter for simulation and testing."
        }

    def close(self) -> None:
        self.is_initialized = False
        self.status = GamepadBackendStatus.CLOSED
