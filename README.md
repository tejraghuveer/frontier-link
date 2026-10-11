# Universal Mobile Gamepad (Frontier Link)

A high-reliability, low-latency mobile gamepad server allowing you to control any PC game on a Windows computer using an Android smartphone connected to the same local Wi-Fi network.

The project features a **PS5 DualSense High-Stick layout**, **large 142px analog thumbsticks elevated to natural thumb position**, **iconic PlayStation geometric symbols (△, □, ◯, ✕)**, **integrated Touchpad reset surface**, **strict multi-touch pointer capture**, **zero-stuck-control failsafes**, and **deep diagnostic telemetry**.

---

## 1. System Architecture

```
Android Phone Browser (Multi-Touch Pointer Events & LostPointerCapture Failsafes)
  │ (Authoritative Input State: Elevated Dual Joysticks, Triggers, Face Buttons, D-Pad)
  ▼
WebSocket (/ws, Local Wi-Fi, Monotonic Sequence Numbers)
  │ (6-digit Pairing PIN, Latency Ping/Pong)
  ▼
FastAPI Server (Validation, Clamping, Watchdog Timeout, Telemetry)
  │
  ├── MockGamepadAdapter (Automated Tests, In-Memory State)
  └── WindowsGamepadAdapter (vgamepad / ViGEmClient C-API)
        │
        ▼
   ViGEmBus Kernel Driver (Virtual XInput Xbox 360 Controller)
        │
        ▼
   Windows Game Controller Subsystem (`joy.cpl`)
        │
        ▼
   Any PC Game (Steam, Epic, Xbox Game Pass, Standalone)
```

---

## 2. PS5 DualSense High-Stick Layout & Ergonomics

### A. Elevated High-Stick Architecture
Designed specifically for natural thumb resting posture during handheld mobile gameplay:
1. **Left Thumb Wing**:
   - **L2 Trigger & L1 Bumper**: Top-left corner with instant tap button + fine analog slider (0.00 – 1.00).
   - **Left Analog Joystick (HIGH)**: Elevated to the upper resting zone, enlarged to 142px diameter with cyan LED halo lighting, deadzone guide ring, and L3 stick-click indicator.
   - **4-Way D-Pad (LOW)**: Directional cross positioned below and inward from the high stick for fast thumb-rolling access.
2. **Right Thumb Wing**:
   - **R2 Trigger & R1 Bumper**: Top-right corner with instant tap button + fine analog slider.
   - **Right Analog Joystick (HIGH)**: Elevated to the upper resting zone for effortless camera control.
   - **PlayStation Geometric Face Buttons (LOW)**:
     - **△ Triangle (Emerald)**: Top action
     - **□ Square (Pink)**: Left action
     - **◯ Circle (Red)**: Right action
     - **✕ Cross (Blue)**: Bottom action
3. **Center Touchpad & System Hub**:
   - **PS5 Touchpad Card**: Center touch surface with cyan illuminated lightbar and integrated **RESET ALL** emergency neutralization button.
   - **Create / Share (`|<<`)** & **Options (`☰`)** buttons.
   - **L3 & R3 Click Pills**: Dedicated stick click buttons for games requiring frequent thumbstick presses.

### B. Dynamic 5-Layout Presets
Switch between layout presets on the fly via the top navigation dropdown:
1. **PS5 DualSense (High-Sticks)**: Symmetrical elevated sticks, PlayStation geometric symbols, touchpad reset.
2. **Xbox Official (Asymmetrical)**: Left stick high, D-Pad low, face buttons high, right stick low.
3. **Switch Pro (Classic Arcade)**: Large circular buttons, classic cross D-pad.
4. **Mobile Claw (Esports Touch)**: Corner-docked triggers, curved thumb sweep arcs.
5. **Steam Deck (Top Dual-Sticks)**: Dual top thumbsticks with inward D-pad and buttons.

### C. Touch Quality & Failsafe Guarantees
- **Multi-Touch Pointer Capture**: Every button and joystick uses `setPointerCapture(pointerId)` for simultaneous multi-finger operation without cross-finger interference.
- **Lost Pointer Capture Failsafe**: Binds `lostpointercapture` alongside `pointerup` and `pointercancel` so controls snap back to neutral immediately if system gestures interrupt touch.
- **Context Menu Suppression**: `contextmenu` is prevented on interactive game buttons and joystick surfaces.
- **Haptic Vibration**: Integrated Web Vibration API (`navigator.vibrate`) for physical tactile feedback on button press.

---

## 3. Windows Gamepad Backend & Driver Status

* **Virtual Controller Backend**:
  * Powered by `WindowsGamepadAdapter` via `vgamepad` and the **ViGEmBus** kernel driver (v1.22.0).
  * **Driver Status**: Installed and operational (`WINDOWS_VIGEM` reports `READY`).
  * Emulates a genuine XInput controller natively recognized by Windows `joy.cpl` and all PC games.
* **Driver Safety Policy**:
  * The server **never** silently installs kernel drivers or alters Windows security settings.
  * If the ViGEmBus driver is missing, the server enters a safe fallback state and reports `DRIVER_NOT_FOUND`.

---

## 4. Quick Start Guide

### Step 1: Launch the Server
In PowerShell:
```powershell
cd C:\controller
.\scripts\start.ps1
```
Or directly with Python:
```powershell
python server.py --host 0.0.0.0 --port 8000
```

### Step 2: Connect on Android Phone
1. Connect your phone to the same local Wi-Fi network as the laptop.
2. Open Chrome (or any mobile browser) and navigate to `http://<LAPTOP_IP>:8000`.
3. Enter the 6-digit PIN and tap **Connect & Authenticate**.
4. Rotate your phone to **Landscape** orientation.
5. Tap the **Controller** tab to begin playing.

---

## 5. Verification Checklist

### Test A: Windows Gamepad Presence (`joy.cpl`)
1. On your Windows laptop, press `Win + R`, type `joy.cpl`, and hit Enter.
2. Verify that **Controller (XBOX 360 For Windows)** is listed in the Game Controllers window.
3. Select it and click **Properties** to open the Windows calibration/test dialog.

### Test B: Multi-Touch & Input Verification
Keep `joy.cpl` open alongside the phone:
1. **Left Analog Stick**: Drag the elevated left stick; verify smooth axis motion.
2. **Right Analog Stick**: Drag the elevated right stick; verify Z-axis rotation.
3. **Face Buttons**: Tap `✕`, `◯`, `□`, `△`; verify corresponding buttons 1 through 4 light up in `joy.cpl`.
4. **Shoulders & Triggers**: Tap or slide `L1`, `R1`, `L2`, `R2`; verify bumper and trigger bars deflect.
5. **Slide-Off Failsafe**: Slide your finger completely off the phone screen while moving a stick; verify it immediately snaps to center `(0.0, 0.0)`.

---

## 6. Running the Automated Test Suite

Run all tests via pytest:
```powershell
python -m pytest tests/ -v
```
All **42 automated unit and integration tests** pass in under 1 second.
