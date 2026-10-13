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

## 2. Western Tactical & Console Ergonomics (Premium Redesign)

### A. Visual Style & Atmosphere
Inspired by Red Dead Redemption 2's Western atmosphere combined with high-precision modern console ergonomics:
- **Palette**: Deep charcoal and near-black canvas (`#07080b`), brushed steel plates (`#242934`), and antique-brass rims (`#d4a743`).
- **Accent Signals**: Electric cyan highlights for navigation and active analog sticks, red-orange flame glow for firing, and distinct PlayStation geometric accents.
- **Surface Detailing**: Tactile mechanical sink pressed states, knurled thumb grips, dashed concentric guides, and zero distracting visual clutter.

### B. Control Zone Architecture
1. **Left Thumb Pod**:
   - **LT Aim Scope Trigger**: Tactical unit with an intuitive circular crosshair/scope icon, "LT" badge, and "L2 • AIM" subtitle. Includes a responsive vertical fill meter (`#meter-lt`) and supports both instant tap and smooth vertical drag depth modulation (0.00 – 1.00).
   - **LB Bumper**: Tactile shoulder bumper ("LB / L1").
   - **Tactile D-Pad Dish**: Directional cross dish with embossed faceted directional indicators (`▲`, `◀`, `▼`, `▶`) and antique-brass center hub pin. Supports independent and diagonal inputs.
   - **Left Analog Stick**: High-precision movement stick with knurled grip, brass rim, cyan active glow on touch, real-time coordinate readout (`LX`, `LY`), and user-adjustable diameter (115px–165px via Settings).
   - **Precision Slider Dock**: Optional slider dock for fine calibration (toggleable in Settings).

2. **Center Utility & Safety Hub**:
   - **View & Menu Buttons**: Quick access map/share (`⧉ VIEW`) and pause options (`☰ MENU`).
   - **Prominent Emergency Release Module**: High-contrast, shielded red neutralizer button (`⚡ RELEASE ALL`) with live `Neutral` / `Active` status badge.
   - **L3 & R3 Click Pills**: Dedicated stick-click buttons located centrally between thumb areas.

3. **Right Thumb Pod**:
   - **RT Fire Trigger**: Tactical unit featuring a bullet/flame icon with red-orange accent glow, "RT" badge, "R2 • FIRE" subtitle, vertical fill meter (`#meter-rt`), and drag modulation.
   - **RB Bumper**: Tactile shoulder bumper ("RB / R1").
   - **Right Analog Stick**: Dedicated camera stick with knurled grip, cyan touch halo, and real-time coordinates (`RX`, `RY`).
   - **PlayStation Geometric Face Diamond**:
     - **△ Triangle (Emerald Green)**: Mount / Contextual (`Y`)
     - **□ Square (Hot Pink)**: Reload / Dive (`X`)
     - **◯ Circle (Crimson Red)**: Crouch / Cancel (`B`)
     - **✕ Cross (Sky Blue)**: Jump / Sprint (`A`)

### C. Touch Quality & Failsafe Guarantees
- **Multi-Touch Pointer Capture**: Every button, trigger, and joystick uses `setPointerCapture(pointerId)` for simultaneous multi-finger operation without cross-finger interference.
- **Lost Pointer Capture Failsafe**: Binds `lostpointercapture` alongside `pointerup` and `pointercancel` so controls snap back to neutral immediately if system gestures interrupt touch.
- **Context Menu Suppression**: `contextmenu` is prevented on all interactive controller surfaces.
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
