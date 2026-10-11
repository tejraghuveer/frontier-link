# RDR2 Mobile Controller (Mobile Gaming Touch Edition)

A high-reliability, low-latency mobile gamepad server allowing you to control **Red Dead Redemption 2 (RDR2)** on a Windows laptop (such as an Acer ALG) using any modern Android smartphone connected to the same Wi-Fi network.

The project features a **landscape-first, two-thumb gaming touch interface**, **strict multi-touch pointer capture**, **zero-stuck-control failsafes**, and **deep diagnostic telemetry**.

---

## 1. System Architecture

```
Android Phone Browser (Multi-Touch Pointer Events & LostPointerCapture Failsafes)
  │ (Authoritative Input State: Dual Joysticks, Triggers, Face Buttons, D-Pad)
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
   ViGEmBus Kernel Driver (Virtual Xbox 360 Controller)
        │
        ▼
   Windows XInput Subsystem (`joy.cpl`)
        │
        ▼
   Red Dead Redemption 2 (RDR2)
```

---

## 2. Touch UI/UX & Ergonomics

### A. Three-Zone Landscape Layout
Designed specifically for playing RDR2 comfortably with two thumbs without thumb cramping or awkward stretches:
1. **Left Thumb Wing (Movement & Aim)**:
   - **LB Bumper**: Weapon/Item wheel toggle.
   - **LT Trigger**: Weapon Aim with dual-mode input: instant full-pull tap button + fine analog slider (0.00 – 1.00).
   - **Left Analog Joystick**: Large 134px touch disc with concentric deadzone guide, tactile center-dot knob, and live LX/LY readouts.
   - **L3 Click**: Sprint toggle directly below the left stick.
   - **4-Way D-Pad**: Horse whistle (Up), Radar map zoom (Down), Left, and Right.
2. **Right Thumb Wing (Camera & Actions)**:
   - **RB Bumper**: Take Cover toggle.
   - **RT Trigger**: Fire Weapon / Attack with instant full-pull tap button + fine analog slider.
   - **A / B / X / Y Diamond**: Distinct Xbox button styling with color-coded borders and clear RDR2 starter action subtitles:
     - **A (Green)**: Jump / Action
     - **B (Red)**: Crouch / Cancel
     - **X (Blue)**: Reload / Dive
     - **Y (Amber)**: Mount Horse / Loot
   - **Right Analog Joystick**: Camera control with live RX/RY readouts.
   - **R3 Click**: Eagle Eye / Look Behind directly below the right stick.
3. **Top Utility Strip**:
   - **VIEW (Map)**: Centers on map screen.
   - **MENU (Pause)**: In-game pause menu.
   - **EMERGENCY RELEASE ALL**: High-visibility crimson button with live neutral/active status badge.
   - **Top Navigation Bar**: Persistent connection pill (`CONNECTED` / `CONNECTING` / `DISCONNECTED`) and quick Settings gear (`⚙️`).

### B. Mobile Touch Quality & Safety
- **Multi-Touch Pointer Capture**: Each button, slider, and joystick thumb uses `setPointerCapture(pointerId)` for independent simultaneous multi-finger operation.
- **Lost Pointer Capture Protection**: Binds `lostpointercapture` alongside `pointerup` and `pointercancel` to ensure buttons and sticks spring back to neutral even if Android edge gestures or notification drawers interrupt the touch.
- **Context Menu Suppression**: `contextmenu` is suppressed on interactive buttons and pads, preventing long-press menus from interrupting gameplay.
- **Scoped `touch-action: none`**: Applied strictly to game controls so that the Connection and Diagnostics screens remain freely scrollable.
- **Portrait Orientation Hint**: Automatically surfaces a polite rotation banner when the phone is held vertically without blocking tab navigation or forcing browser screen-orientation APIs.

### C. In-Game Comfort & Settings Drawer
Tap the gear icon (`⚙️`) in the header to customize your controller ergonomics:
- **Control Scale (80% – 125%)**: Adjusts button and joystick sizes to match your phone's screen size and thumb reach.
- **Button Opacity (50% – 100%)**: Adjusts controller opacity for distraction-free visibility.
- **Stick Deadzone (5% – 25%)**: Fine-tunes inner stick deadband (default: 12%).
- **Stick Sensitivity (0.7x – 1.5x)**: Scales joystick response outside the deadzone.
- **RDR2 Starter Mappings Cheat Sheet**: Collapsible quick reference of all default actions.
- **Safe Persistence**: Preferences are saved to `localStorage` under `rdr2_controller_prefs`. The pairing PIN is **never** saved to `localStorage`.

---

## 3. Windows Gamepad Backend & Driver Status

* **Virtual Xbox 360 Controller Backend**:
  * Powered by `WindowsGamepadAdapter` via `vgamepad` and the **ViGEmBus** kernel driver (v1.22.0).
  * **Driver Status**: Installed and operational (`WINDOWS_VIGEM` reports `READY`).
  * Emulates a genuine XInput Xbox 360 controller natively recognized by Windows `joy.cpl` and Red Dead Redemption 2.
* **Driver Safety Policy**:
  * The server **never** silently installs kernel drivers or alters Windows security settings.
  * If the ViGEmBus driver is ever uninstalled or missing, the server automatically enters a safe fallback state, reports `DRIVER_NOT_FOUND`, and guides the user to the official download link:
    👉 **[Download ViGEmBus v1.22.0 Installer](https://github.com/nefarius/ViGEmBus/releases/latest)**.

---

## 4. Reliability & Failsafe Architecture

### A. Input Neutralization & Disconnect Safety
* **Multi-Layer Neutralization**:
  1. **Immediate Socket Drop**: When the WebSocket closes, disconnects, or errors, `release_all_inputs()` instantly clears all held buttons and D-pad directions, resets analog triggers to `0.0`, and centers both joysticks to `(0.0, 0.0)`.
  2. **Browser Page Navigation / Unload**: Handlers for `window.blur`, `document.visibilitychange`, `window.pagehide`, `window.beforeunload`, and tab switching immediately neutralize inputs before the page can disconnect.
  3. **Watchdog Fallback**: If the client connection goes silent for more than 2.5 seconds (e.g., sudden Wi-Fi loss or phone battery death), the background watchdog fires once to neutralize all controls.
  4. **Emergency Release**: Prominent button on the UI sends a high-priority `{ "type": "release_all" }` message and resets local controls immediately.
  5. **Server Shutdown**: The FastAPI lifespan shutdown handler executes `release_all()` and `close()` on the virtual gamepad before process exit.

### B. Session Handover & Racing Packet Protection
* Only one client can hold an active controller session at a time.
* If a new client authenticates, the prior session is immediately notified with `session_replaced`, its WebSocket is closed with code 1000, and controls are neutralized.
* Any lingering or delayed packets arriving from superseded sessions are rejected with `SESSION_EXPIRED` and counted in the rejected packets telemetry.

### C. Port Conflict & Duplicate Process Prevention
* Before starting `uvicorn`, the server runs a pre-flight TCP bind check.
* If port 8000 is already in use by another process, it logs the conflicting PID and process name and exits cleanly instead of crashing.
* `scripts\start.ps1` runs the same pre-check in PowerShell prior to launching Python.

### D. Distinguished Latency & Diagnostic Telemetry
Screen C displays live real-time metrics:
* **Measured Network RTT**: Round-trip time measured via WebSocket ping/pong messages.
* **Estimated One-Way Network Latency**: `RTT / 2`.
* **Server Processing Duration**: Time taken by backend to validate and pass state to the gamepad adapter (measured via `time.perf_counter()`).
* **Estimated Touch-to-Gamepad Latency**: `(RTT / 2) + Server Processing Duration`.
* **Input Packet Frequency**: Rolling 1-second packet reception rate in Hz.
* **Rejected Packets**: Total and categorized breakdown (`stale_sequence`, `validation_error`, `invalid_sequence`, `expired_session`, `malformed_json`, `unauthorized`, `unknown_type`).
* **Watchdog Activations**: Count of times the watchdog neutralized an idle session.
* **Total Disconnects**: Counter and last disconnect reason.

---

## 5. Quick Start Guide

### Step 1: Open Windows Firewall (Private Network)
Run PowerShell as Administrator once:
```powershell
New-NetFirewallRule -DisplayName "RDR2 Controller Port 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow -Profile Private
```

### Step 2: Launch the Server
In PowerShell, run:
```powershell
cd C:\controller
.\scripts\start.ps1
```
Or run directly with Python:
```powershell
python server.py --host 0.0.0.0 --port 8000
```
*(Use `--mock` to run without requiring the Windows driver for testing).*

The terminal will display:
* Your 6-digit pairing PIN (e.g., `584920`).
* Local Wi-Fi web URL (e.g., `http://10.146.157.160:8000`).

### Step 3: Connect on Android Phone
1. Connect your phone to the same Wi-Fi network as the laptop.
2. Open Chrome (or any mobile browser) and navigate to `http://<LAPTOP_IP>:8000`.
3. Enter the 6-digit PIN and tap **Connect & Authenticate**.
4. Rotate your phone to **Landscape** orientation.
5. Tap the **Controller** tab to begin playing, or tap `⚙️` to adjust scale, deadzone, and sensitivity.

---

## 6. Real-Device Verification Checklist

### Test A: Network & Authentication
1. Launch `scripts\start.ps1`.
2. Open the URL on your Android phone.
3. Enter an incorrect PIN: verify the server rejects it.
4. Enter the correct PIN: verify the status changes to `CONNECTED` and a green indicator appears.

### Test B: Windows Gamepad Presence (`joy.cpl`)
1. On your Windows laptop, press `Win + R`, type `joy.cpl`, and hit Enter.
2. Verify that **Controller (XBOX 360 For Windows)** is listed in the Game Controllers window.
3. Select it and click **Properties** to open the Windows calibration/test dialog.

### Test C: Complete Multi-Touch Verification
Keep `joy.cpl` open alongside the phone or laptop screen:
1. **Left Analog Stick**: Drag the left stick; verify the X/Y Axis crosshair moves smoothly.
2. **Right Analog Stick**: Drag the right stick; verify the Z Rotation / Z Axis dials move.
3. **Simultaneous Multi-Touch**: While moving the left stick, tap `A` or hold `RT`; verify both inputs register independently without interference.
4. **Buttons**: Tap `A`, `B`, `X`, `Y`, `LB`, `RB`, `L3`, `R3`, `VIEW`, `MENU`. Verify buttons 1 through 10 light up in `joy.cpl`.
5. **D-Pad**: Tap `UP`, `DOWN`, `LEFT`, `RIGHT`. Verify the Point of View Hat switch updates.
6. **Triggers (LT / RT)**: Slide or tap LT and RT; verify the Z-axis analog trigger bars deflect.

### Test D: Touch Failsafes & Lost Pointer Capture
1. Drag the left stick towards the screen edge and slide your thumb completely off the browser window; verify the stick snaps back to center immediately (`(0.0, 0.0)`).
2. Pull down the Android notification shade while holding a button; verify inputs return to neutral immediately.
3. Tap **EMERGENCY RELEASE ALL**; verify all controls reset to neutral.
4. Turn off phone Wi-Fi; verify the server watchdog neutralizes all controls within 2.5 seconds.

### Test E: In-Game Verification in RDR2
1. Launch Red Dead Redemption 2.
2. In RDR2 Settings > Controls > Controller, verify Gamepad input is detected.
3. Test core actions:
   * **Left Stick**: Arthur walks / runs.
   * **Right Stick**: Camera pans smoothly.
   * **LT**: Aim weapon.
   * **RT**: Fire weapon / punch.
   * **A**: Sprint / jump.
   * **B**: Crouch / take cover.
   * **X**: Reload / dive.
   * **Y**: Mount horse.
   * **D-Pad Up**: Whistle for horse.
   * **L3**: Sprint toggle.
   * **R3**: Eagle Eye / Look behind.

---

## 7. Running the Automated Test Suite

Run all tests via pytest:
```powershell
python -m pytest tests/ -v
```
All **42 automated unit and integration tests** pass in ~1.1 seconds.
