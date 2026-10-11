# RDR2 Mobile Controller (Functional MVP)

A high-reliability, low-latency mobile gamepad server allowing you to control **Red Dead Redemption 2 (RDR2)** on a Windows laptop (such as an Acer ALG) using any modern Android smartphone connected to the same Wi-Fi network.

The project prioritizes **functional correctness, input safety, and hardware verification** before visual styling.

---

## 1. System Architecture

```
Android Phone Browser (Pointer Events)
  │ (Authoritative Input State: Joysticks, Triggers, Buttons)
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

## 2. Windows Gamepad Backend & Driver Status

* **Virtual Xbox 360 Controller Backend**:
  * Powered by `WindowsGamepadAdapter` via `vgamepad` and the **ViGEmBus** kernel driver (v1.22.0).
  * **Driver Status**: Installed and operational (`WINDOWS_VIGEM` reports `READY`).
  * Emulates a genuine XInput Xbox 360 controller natively recognized by Windows `joy.cpl` and Red Dead Redemption 2.
* **Driver Safety Policy**:
  * The server **never** silently installs kernel drivers or alters Windows security settings.
  * If the ViGEmBus driver is ever uninstalled or missing, the server automatically enters a safe fallback state, reports `DRIVER_NOT_FOUND`, and guides the user to the official download link:
    👉 **[Download ViGEmBus v1.22.0 Installer](https://github.com/nefarius/ViGEmBus/releases/latest)**.

---

## 3. Reliability & Failsafe Architecture

### A. Input Neutralization & Disconnect Safety
* **Multi-Layer Neutralization**:
  1. **Immediate Socket Drop**: When the WebSocket closes, disconnects, or errors, `release_all_inputs()` instantly clears all held buttons and D-pad directions, resets analog triggers to `0.0`, and centers both joysticks to `(0.0, 0.0)`.
  2. **Browser Page Navigation / Unload**: Handlers for `window.blur`, `document.visibilitychange`, `window.pagehide`, and `window.beforeunload` immediately neutralize inputs before the page can disconnect.
  3. **Watchdog Fallback**: If the client connection goes silent for more than 2.5 seconds (e.g., sudden Wi-Fi loss or phone battery death), the background watchdog fires once to neutralize all controls.
  4. **Emergency Release**: A prominent button on the UI sends a high-priority `{ "type": "release_all" }` message and resets local controls immediately.
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

## 4. Quick Start Guide

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
4. Switch to **Screen 2: Controller** to play, or **Screen 3: Diagnostics** to test inputs.

---

## 5. Real-Device Verification Checklist

### Test A: Network & Authentication
1. Launch `scripts\start.ps1`.
2. Open the URL on your Android phone.
3. Enter an incorrect PIN: verify the server rejects it with an attempt counter.
4. Enter the correct PIN: verify the status changes to `CONNECTED` and a green indicator appears.

### Test B: Windows Gamepad Presence (`joy.cpl`)
1. On your Windows laptop, press `Win + R`, type `joy.cpl`, and hit Enter.
2. Verify that **Controller (XBOX 360 For Windows)** is listed in the Game Controllers window.
3. Select it and click **Properties** to open the Windows calibration/test dialog.

### Test C: Complete Control Verification
Keep `joy.cpl` open alongside the phone or laptop screen:
1. **Left Analog Stick**: Drag the left circle on the phone; verify the X/Y Axis crosshair moves smoothly in `joy.cpl`.
2. **Right Analog Stick**: Drag the right circle; verify the Z Rotation / Z Axis dials move.
3. **Buttons**: Tap `A`, `B`, `X`, `Y`, `LB`, `RB`, `L3`, `R3`, `VIEW`, `MENU`. Verify buttons 1 through 10 light up on `joy.cpl`.
4. **D-Pad**: Tap `UP`, `DOWN`, `LEFT`, `RIGHT`. Verify the Point of View Hat switch updates.
5. **Triggers (LT / RT)**: Slide or tap LT and RT; verify the Z-axis analog trigger bars deflect.

### Test D: Disconnect & Failsafe Recovery
1. While holding down a button or joystick on your phone, turn off your phone's Wi-Fi.
2. Verify that within 2.5 seconds, the server watchdog triggers and `joy.cpl` shows all buttons released and sticks centered.
3. Tap **EMERGENCY RELEASE ALL** on the controller; verify immediate neutralization.

### Test E: In-Game Verification in RDR2
1. Launch Red Dead Redemption 2.
2. In RDR2 Settings > Controls > Controller, verify Gamepad input is detected.
3. Test core actions:
   * **Left Stick**: Arthur moves / walks.
   * **Right Stick**: Camera pans.
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

## 6. Project Structure

```
C:\controller\
├── server.py              # FastAPI server, WebSockets, PIN auth, Watchdog, Telemetry
├── requirements.txt       # Core dependencies (FastAPI, uvicorn, websockets, pytest)
├── gamepad/
│   ├── base.py            # BaseGamepadAdapter, InputState, verification levels
│   ├── mock_adapter.py    # Mock adapter for automated unit & CI tests
│   └── windows_adapter.py # Windows XInput adapter via ViGEmBus and vgamepad
├── static/
│   ├── index.html         # 3 screens: Connection, Controller, Diagnostics
│   ├── style.css          # Functional, responsive touch CSS
│   └── app.js             # Pointer events, WebSocket streaming, RTT ping/pong
├── tests/
│   ├── conftest.py        # Pytest fixtures and mock setup
│   ├── test_input_state.py# Input validation, clamping, and error resilience
│   ├── test_gamepad_adapter.py # Adapter lifecycle and driver failure handling
│   ├── test_server.py     # E2E server, WebSocket, security, and static asset tests
│   └── test_reliability.py# Disconnect neutralization, watchdog, telemetry tests
├── scripts/
│   ├── start.ps1          # One-click Windows launcher with port pre-check
│   └── test_setup.ps1     # Automated test runner and environment checker
├── README.md              # Documentation and manual verification guide
└── TEST-REPORT.md         # Comprehensive test results and verification statuses
```

---

## 7. Running the Automated Test Suite

Run all tests via pytest:
```powershell
python -m pytest tests/ -v
```
Or execute the automated setup script:
```powershell
.\scripts\test_setup.ps1
```
All **42 automated unit and integration tests** run in under 1 second.
