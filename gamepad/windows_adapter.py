"""
Windows Virtual Xbox 360 Gamepad Adapter using ViGEmBus and vgamepad.
"""

from typing import Dict, Optional, Set
import logging
import time

from .base import (
    BaseGamepadAdapter,
    GamepadBackendStatus,
    InputState,
    SUPPORTED_BUTTONS,
    SUPPORTED_DPAD,
    VerificationLevel,
)

logger = logging.getLogger("gamepad.windows")

VIGEM_DOWNLOAD_URL = "https://github.com/nefarius/ViGEmBus/releases/latest"


class WindowsGamepadAdapter(BaseGamepadAdapter):
    """
    Virtual Xbox 360 controller outputting to Windows XInput via ViGEmBus driver.
    Provides diagnostic status, error detection, and safe fallback if the driver is not installed.
    """

    def __init__(self):
        self.is_initialized: bool = False
        self.status: GamepadBackendStatus = GamepadBackendStatus.NOT_INITIALIZED
        self.last_error: Optional[str] = None
        self.driver_instructions: str = ""
        self._gamepad = None
        self._vg_module = None
        self._button_map = {}
        self._dpad_map = {}
        self._currently_held_buttons: Set[str] = set()
        self._currently_held_dpad: Set[str] = set()
        self.current_state: InputState = InputState.neutral(0)
        self.total_updates: int = 0
        self.last_update_ts: float = 0.0

    def initialize(self) -> bool:
        """Attempt to load vgamepad and initialize the virtual Xbox 360 device."""
        try:
            # Dynamic import so missing module or driver doesn't crash the server process
            import vgamepad as vg
            self._vg_module = vg
        except ModuleNotFoundError:
            self.status = GamepadBackendStatus.DRIVER_NOT_FOUND
            self.last_error = "vgamepad package not installed."
            self.driver_instructions = (
                f"Install vgamepad and ensure ViGEmBus driver is installed from: {VIGEM_DOWNLOAD_URL}"
            )
            logger.warning("WindowsGamepadAdapter: %s", self.last_error)
            return False
        except Exception as e:
            err_msg = str(e)
            if "VIGEM_ERROR_BUS_NOT_FOUND" in err_msg or "VBus" in err_msg:
                self.status = GamepadBackendStatus.DRIVER_NOT_FOUND
                self.last_error = "ViGEmBus kernel driver not found on Windows system."
                self.driver_instructions = (
                    f"Action Required: Download and install the ViGEmBus 1.22.0 installer from: {VIGEM_DOWNLOAD_URL}. "
                    "After installation, reboot or restart the controller server."
                )
            else:
                self.status = GamepadBackendStatus.INIT_FAILED
                self.last_error = f"ViGEm initialization error: {err_msg}"
                self.driver_instructions = f"Check Windows Device Manager or reinstall driver from {VIGEM_DOWNLOAD_URL}"
            logger.warning("WindowsGamepadAdapter init failed: %s", self.last_error)
            return False

        try:
            # Map buttons to XUSB flags
            vg = self._vg_module
            self._button_map = {
                "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
                "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
                "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
                "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
                "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
                "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
                "L3": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
                "R3": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
                "VIEW": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
                "MENU": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
            }
            self._dpad_map = {
                "UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
                "DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
                "LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
                "RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
            }

            self._gamepad = vg.VX360Gamepad()
            self._gamepad.reset()
            self._gamepad.update()
            self.is_initialized = True
            self.status = GamepadBackendStatus.READY
            self.last_error = None
            self.driver_instructions = "Virtual Xbox 360 gamepad successfully attached to Windows bus."
            logger.info("WindowsGamepadAdapter initialized successfully.")
            return True

        except Exception as e:
            self.status = GamepadBackendStatus.INIT_FAILED
            self.last_error = f"Failed to instantiate VX360Gamepad: {e}"
            self.driver_instructions = f"Reinstall ViGEmBus from {VIGEM_DOWNLOAD_URL}"
            logger.error("WindowsGamepadAdapter instantiation failed: %s", e)
            return False

    def update_input(self, state: InputState) -> bool:
        """Apply input state to the virtual gamepad."""
        if not self.is_initialized or self._gamepad is None:
            self.last_error = "Virtual controller device not ready"
            return False

        try:
            # Diff buttons to press newly pressed and release newly released
            new_buttons = state.buttons & SUPPORTED_BUTTONS
            buttons_to_press = new_buttons - self._currently_held_buttons
            buttons_to_release = self._currently_held_buttons - new_buttons

            for btn in buttons_to_press:
                flag = self._button_map.get(btn)
                if flag:
                    self._gamepad.press_button(flag)

            for btn in buttons_to_release:
                flag = self._button_map.get(btn)
                if flag:
                    self._gamepad.release_button(flag)

            self._currently_held_buttons = new_buttons

            # Diff DPAD
            new_dpad = state.dpad & SUPPORTED_DPAD
            dpad_to_press = new_dpad - self._currently_held_dpad
            dpad_to_release = self._currently_held_dpad - new_dpad

            for d in dpad_to_press:
                flag = self._dpad_map.get(d)
                if flag:
                    self._gamepad.press_button(flag)

            for d in dpad_to_release:
                flag = self._dpad_map.get(d)
                if flag:
                    self._gamepad.release_button(flag)

            self._currently_held_dpad = new_dpad

            # Update triggers (0.0 to 1.0)
            self._gamepad.left_trigger_float(state.triggers["lt"])
            self._gamepad.right_trigger_float(state.triggers["rt"])

            # Update joysticks (-1.0 to 1.0)
            self._gamepad.left_joystick_float(state.axes["lx"], state.axes["ly"])
            self._gamepad.right_joystick_float(state.axes["rx"], state.axes["ry"])

            # Send state report to the Windows driver
            self._gamepad.update()

            self.current_state = state
            self.total_updates += 1
            self.last_update_ts = time.time()
            return True

        except Exception as e:
            self.last_error = f"Failed to update virtual gamepad: {e}"
            self.status = GamepadBackendStatus.ERROR
            logger.error(self.last_error)
            return False

    def release_all(self) -> bool:
        """Reset all inputs to neutral safe state."""
        if not self.is_initialized or self._gamepad is None:
            self.current_state = InputState.neutral(0)
            self._currently_held_buttons.clear()
            self._currently_held_dpad.clear()
            return True

        try:
            self._gamepad.reset()
            self._gamepad.left_trigger_float(0.0)
            self._gamepad.right_trigger_float(0.0)
            self._gamepad.left_joystick_float(0.0, 0.0)
            self._gamepad.right_joystick_float(0.0, 0.0)
            self._gamepad.update()

            self._currently_held_buttons.clear()
            self._currently_held_dpad.clear()
            self.current_state = InputState.neutral((self.current_state.seq + 1) if self.current_state else 0)
            self.last_update_ts = time.time()
            return True
        except Exception as e:
            self.last_error = f"Error during release_all: {e}"
            logger.error(self.last_error)
            return False

    def get_status(self) -> Dict[str, any]:
        verification_level = (
            VerificationLevel.WINDOWS_VERIFIED.value
            if self.is_initialized
            else VerificationLevel.BLOCKED.value
        )
        return {
            "backend_type": "WINDOWS_VIGEM",
            "is_real_hardware": True,
            "status": self.status.value,
            "is_initialized": self.is_initialized,
            "total_updates": self.total_updates,
            "last_error": self.last_error,
            "last_update_ts": self.last_update_ts,
            "driver_instructions": self.driver_instructions,
            "current_state": {
                "seq": self.current_state.seq,
                "buttons": sorted(list(self.current_state.buttons)),
                "dpad": sorted(list(self.current_state.dpad)),
                "axes": dict(self.current_state.axes),
                "triggers": dict(self.current_state.triggers),
            },
            "verification_level": verification_level,
        }

    def close(self) -> None:
        if self._gamepad is not None:
            try:
                self.release_all()
                del self._gamepad
                self._gamepad = None
            except Exception as e:
                logger.warning("Error while closing gamepad: %s", e)
        self.is_initialized = False
        self.status = GamepadBackendStatus.CLOSED
