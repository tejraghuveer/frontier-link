/**
 * Universal PC Gamepad — Frontier Link Client Logic
 * Multi-touch Pointer-based controller interface with WebSocket streaming,
 * authoritative complete-state messaging, latency measurement, diagnostics,
 * 5 dynamic layout presets (Xbox, PS5, Switch, Claw, Steam Deck), and failsafe safety.
 */

(function () {
  "use strict";

  // --- Configuration & Constants ---
  const DEFAULT_DEADZONE = 0.12;       // 12% default deadzone
  const DEFAULT_SENSITIVITY = 1.0;     // 1.0x default sensitivity
  const DEFAULT_SCALE = 100;           // 100% default scale
  const DEFAULT_STICK_SIZE = 144;      // 144px default stick diameter
  const DEFAULT_OPACITY = 95;          // 95% default opacity
  const DEFAULT_LAYOUT = "ps5";        // Default: PS5 DualSense High-Stick
  const PING_INTERVAL_MS = 1000;
  const INPUT_THROTTLE_MS = 16;        // ~60 Hz max transmission rate

  // Dynamic user preferences (loaded from localStorage)
  let activeDeadzone = DEFAULT_DEADZONE;
  let activeSensitivity = DEFAULT_SENSITIVITY;
  let activeScale = DEFAULT_SCALE;
  let activeStickSize = DEFAULT_STICK_SIZE;
  let activeOpacity = DEFAULT_OPACITY;
  let activeLayout = DEFAULT_LAYOUT;
  let hapticEnabled = true;
  let sliderDocksEnabled = false;

  // --- State Variables ---
  let socket = null;
  let isConnected = false;
  let isAuthenticated = false;
  let currentSessionId = null;
  let seqCounter = 1;
  let lastAckSeq = 0;
  let messagesSent = 0;
  let messagesAcked = 0;
  let lastInputSendTime = 0;
  let pingTimer = null;
  let lastRttMs = null;
  let lastProcTimeMs = null;
  let lastErrorMsg = null;
  let lastReleaseAllInfo = null;
  let inputSendScheduled = false;

  // Authoritative local input state
  const heldButtons = new Set();
  const heldDpad = new Set();
  const axes = { lx: 0.0, ly: 0.0, rx: 0.0, ry: 0.0 };
  const triggers = { lt: 0.0, rt: 0.0 };

  // DOM Elements
  const connectionPill = document.getElementById("connection-pill");
  const hudLatency = document.getElementById("hud-latency");
  const serverHostInput = document.getElementById("server-host");
  const pairingPinInput = document.getElementById("pairing-pin");
  const btnConnect = document.getElementById("btn-connect");
  const btnDisconnect = document.getElementById("btn-disconnect");
  const btnFullscreen = document.getElementById("btn-fullscreen");
  const layoutPicker = document.getElementById("layout-picker");
  const settingLayoutDrawer = document.getElementById("setting-layout-drawer");
  const controllerStage = document.getElementById("controller-stage");

  // Dynamic Button Labels
  const labelBtnY = document.getElementById("label-btn-y");
  const labelBtnX = document.getElementById("label-btn-x");
  const labelBtnB = document.getElementById("label-btn-b");
  const labelBtnA = document.getElementById("label-btn-a");
  const labelLt = document.getElementById("label-lt");
  const labelRt = document.getElementById("label-rt");
  const labelLb = document.getElementById("label-lb");
  const labelRb = document.getElementById("label-rb");

  const statusWs = document.getElementById("status-ws");
  const statusAuth = document.getElementById("status-auth");
  const statusBackend = document.getElementById("status-backend");
  const statusDriver = document.getElementById("status-driver");
  const driverAlert = document.getElementById("driver-alert");

  const btnEmergencyRelease = document.getElementById("btn-emergency-release");
  const emergencyIndicator = document.getElementById("emergency-indicator");

  const sliderLt = document.getElementById("slider-lt");
  const sliderRt = document.getElementById("slider-rt");
  const valLt = document.getElementById("val-lt");
  const valRt = document.getElementById("val-rt");

  const valLx = document.getElementById("val-lx");
  const valLy = document.getElementById("val-ly");
  const valRx = document.getElementById("val-rx");
  const valRy = document.getElementById("val-ry");

  // Settings DOM Elements
  const btnOpenSettings = document.getElementById("btn-open-settings");
  const btnCloseSettings = document.getElementById("btn-close-settings");
  const btnResetSettings = document.getElementById("btn-reset-settings");
  const settingsModal = document.getElementById("settings-modal");
  const settingScaleSlider = document.getElementById("setting-ui-scale");
  const settingStickSizeSlider = document.getElementById("setting-stick-size");
  const settingOpacitySlider = document.getElementById("setting-ui-opacity");
  const settingDeadzoneSlider = document.getElementById("setting-deadzone");
  const settingSensitivitySlider = document.getElementById("setting-sensitivity");
  const settingHapticCheck = document.getElementById("setting-haptic");
  const settingSliderDocksCheck = document.getElementById("setting-slider-docks");
  const valSettingScale = document.getElementById("val-setting-scale");
  const valSettingStickSize = document.getElementById("val-setting-stick-size");
  const valSettingOpacity = document.getElementById("val-setting-opacity");
  const valSettingDeadzone = document.getElementById("val-setting-deadzone");
  const valSettingSensitivity = document.getElementById("val-setting-sensitivity");

  // Diagnostics DOM Elements
  const diagWsStatus = document.getElementById("diag-ws-status");
  const diagAuthStatus = document.getElementById("diag-auth-status");
  const diagBackendInit = document.getElementById("diag-backend-init");
  const diagBackendType = document.getElementById("diag-backend-type");
  const diagRtt = document.getElementById("diag-rtt");
  const diagOnewayNet = document.getElementById("diag-oneway-net");
  const diagProcTime = document.getElementById("diag-proc-time");
  const diagEstE2e = document.getElementById("diag-est-e2e");
  const diagPacketHz = document.getElementById("diag-packet-hz");
  const diagRejectedPkts = document.getElementById("diag-rejected-pkts");
  const diagWatchdogActs = document.getElementById("diag-watchdog-acts");
  const diagDisconnects = document.getElementById("diag-disconnects");
  const diagMsgCounts = document.getElementById("diag-msg-counts");
  const diagLastInputTime = document.getElementById("diag-last-input-time");
  const diagAxes = document.getElementById("diag-axes");
  const diagTriggers = document.getElementById("diag-triggers");
  const diagHeldButtons = document.getElementById("diag-held-buttons");
  const diagHeldDpad = document.getElementById("diag-held-dpad");
  const diagLastError = document.getElementById("diag-last-error");
  const diagLastRelease = document.getElementById("diag-last-release");
  const diagVerifLevel = document.getElementById("diag-verif-level");

  // Telemetry metrics from server
  let serverPacketHz = 0;
  let serverRejectedCount = 0;
  let serverWatchdogCount = 0;
  let serverDisconnectCount = 0;

  // --- Auto-detect Server Address ---
  if (window.location.host) {
    serverHostInput.value = window.location.host;
  }

  // --- Haptic Feedback Helper ---
  function triggerHaptic(ms = 15) {
    if (hapticEnabled && navigator.vibrate) {
      try {
        navigator.vibrate(ms);
      } catch (_) {}
    }
  }

  // --- Fullscreen Toggle Helper ---
  if (btnFullscreen) {
    btnFullscreen.addEventListener("click", () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    });
  }

  // --- Dynamic Layout Switching Architecture ---
  function applyLayout(layoutKey) {
    if (!controllerStage) return;
    activeLayout = layoutKey;
    controllerStage.className = `controller-stage layout-${layoutKey}`;

    if (layoutPicker) layoutPicker.value = layoutKey;
    if (settingLayoutDrawer) settingLayoutDrawer.value = layoutKey;

    // Adapt button face glyphs to matching platform conventions
    if (layoutKey === "ps5") {
      if (labelBtnY) labelBtnY.textContent = "△";
      if (labelBtnX) labelBtnX.textContent = "□";
      if (labelBtnB) labelBtnB.textContent = "◯";
      if (labelBtnA) labelBtnA.textContent = "✕";
      if (labelLt) labelLt.textContent = "L2";
      if (labelRt) labelRt.textContent = "R2";
      if (labelLb) labelLb.textContent = "L1";
      if (labelRb) labelRb.textContent = "R1";
    } else if (layoutKey === "switch") {
      if (labelBtnY) labelBtnY.textContent = "X";
      if (labelBtnX) labelBtnX.textContent = "Y";
      if (labelBtnB) labelBtnB.textContent = "A";
      if (labelBtnA) labelBtnA.textContent = "B";
      if (labelLt) labelLt.textContent = "ZL";
      if (labelRt) labelRt.textContent = "ZR";
      if (labelLb) labelLb.textContent = "L";
      if (labelRb) labelRb.textContent = "R";
    } else {
      // Standard Xbox, Mobile Claw, and Steam Deck labels
      if (labelBtnY) labelBtnY.textContent = "Y";
      if (labelBtnX) labelBtnX.textContent = "X";
      if (labelBtnB) labelBtnB.textContent = "B";
      if (labelBtnA) labelBtnA.textContent = "A";
      if (labelLt) labelLt.textContent = "LT";
      if (labelRt) labelRt.textContent = "RT";
      if (labelLb) labelLb.textContent = "LB";
      if (labelRb) labelRb.textContent = "RB";
    }

    saveSettings();
  }

  if (layoutPicker) {
    layoutPicker.addEventListener("change", e => {
      applyLayout(e.target.value);
    });
  }

  if (settingLayoutDrawer) {
    settingLayoutDrawer.addEventListener("change", e => {
      applyLayout(e.target.value);
    });
  }

  // --- Settings Persistence & Loading ---
  const PREFS_STORAGE_KEY = "universal_controller_prefs";

  function applySettingsToUI() {
    document.documentElement.style.setProperty("--ui-scale", (activeScale / 100).toString());
    document.documentElement.style.setProperty("--stick-size", `${activeStickSize}px`);
    document.documentElement.style.setProperty("--ui-opacity", (activeOpacity / 100).toString());

    document.body.classList.toggle("show-slider-docks", sliderDocksEnabled);

    if (settingScaleSlider) settingScaleSlider.value = activeScale;
    if (settingStickSizeSlider) settingStickSizeSlider.value = activeStickSize;
    if (settingOpacitySlider) settingOpacitySlider.value = activeOpacity;
    if (settingDeadzoneSlider) settingDeadzoneSlider.value = Math.round(activeDeadzone * 100);
    if (settingSensitivitySlider) settingSensitivitySlider.value = Math.round(activeSensitivity * 100);
    if (settingHapticCheck) settingHapticCheck.checked = hapticEnabled;
    if (settingSliderDocksCheck) settingSliderDocksCheck.checked = sliderDocksEnabled;

    if (valSettingScale) valSettingScale.textContent = `${activeScale}%`;
    if (valSettingStickSize) valSettingStickSize.textContent = `${activeStickSize}px`;
    if (valSettingOpacity) valSettingOpacity.textContent = `${activeOpacity}%`;
    if (valSettingDeadzone) valSettingDeadzone.textContent = `${Math.round(activeDeadzone * 100)}%`;
    if (valSettingSensitivity) valSettingSensitivity.textContent = `${activeSensitivity.toFixed(1)}x`;

    applyLayout(activeLayout);
  }

  function saveSettings() {
    try {
      const prefs = {
        scale: activeScale,
        stickSize: activeStickSize,
        opacity: activeOpacity,
        deadzone: Math.round(activeDeadzone * 100),
        sensitivity: Math.round(activeSensitivity * 100),
        haptic: hapticEnabled,
        sliderDocks: sliderDocksEnabled,
        layout: activeLayout
      };
      localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(prefs));
    } catch (_) {}
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem(PREFS_STORAGE_KEY);
      if (raw) {
        const prefs = JSON.parse(raw);
        if (typeof prefs.scale === "number" && prefs.scale >= 80 && prefs.scale <= 130) {
          activeScale = prefs.scale;
        }
        if (typeof prefs.stickSize === "number" && prefs.stickSize >= 115 && prefs.stickSize <= 165) {
          activeStickSize = prefs.stickSize;
        }
        if (typeof prefs.opacity === "number" && prefs.opacity >= 50 && prefs.opacity <= 100) {
          activeOpacity = prefs.opacity;
        }
        if (typeof prefs.deadzone === "number" && prefs.deadzone >= 5 && prefs.deadzone <= 25) {
          activeDeadzone = prefs.deadzone / 100;
        }
        if (typeof prefs.sensitivity === "number" && prefs.sensitivity >= 70 && prefs.sensitivity <= 150) {
          activeSensitivity = prefs.sensitivity / 100;
        }
        if (typeof prefs.haptic === "boolean") {
          hapticEnabled = prefs.haptic;
        }
        if (typeof prefs.sliderDocks === "boolean") {
          sliderDocksEnabled = prefs.sliderDocks;
        }
        if (typeof prefs.layout === "string" && ["xbox", "ps5", "switch", "claw", "deck"].includes(prefs.layout)) {
          activeLayout = prefs.layout;
        }
      }
    } catch (_) {
      activeScale = DEFAULT_SCALE;
      activeStickSize = DEFAULT_STICK_SIZE;
      activeOpacity = DEFAULT_OPACITY;
      activeDeadzone = DEFAULT_DEADZONE;
      activeSensitivity = DEFAULT_SENSITIVITY;
      activeLayout = DEFAULT_LAYOUT;
      hapticEnabled = true;
      sliderDocksEnabled = false;
    }
    applySettingsToUI();
  }

  loadSettings();

  // Settings Event Handlers
  if (btnOpenSettings && settingsModal) {
    btnOpenSettings.addEventListener("click", () => {
      settingsModal.classList.add("open");
      settingsModal.setAttribute("aria-hidden", "false");
    });
  }

  if (btnCloseSettings && settingsModal) {
    btnCloseSettings.addEventListener("click", () => {
      settingsModal.classList.remove("open");
      settingsModal.setAttribute("aria-hidden", "true");
    });
  }

  if (settingsModal) {
    settingsModal.addEventListener("click", (e) => {
      if (e.target === settingsModal) {
        settingsModal.classList.remove("open");
        settingsModal.setAttribute("aria-hidden", "true");
      }
    });
  }

  if (settingScaleSlider) {
    settingScaleSlider.addEventListener("input", (e) => {
      activeScale = parseInt(e.target.value, 10);
      applySettingsToUI();
      saveSettings();
    });
  }

  if (settingStickSizeSlider) {
    settingStickSizeSlider.addEventListener("input", (e) => {
      activeStickSize = parseInt(e.target.value, 10);
      applySettingsToUI();
      saveSettings();
    });
  }

  if (settingOpacitySlider) {
    settingOpacitySlider.addEventListener("input", (e) => {
      activeOpacity = parseInt(e.target.value, 10);
      applySettingsToUI();
      saveSettings();
    });
  }

  if (settingDeadzoneSlider) {
    settingDeadzoneSlider.addEventListener("input", (e) => {
      activeDeadzone = parseInt(e.target.value, 10) / 100;
      applySettingsToUI();
      saveSettings();
    });
  }

  if (settingSensitivitySlider) {
    settingSensitivitySlider.addEventListener("input", (e) => {
      activeSensitivity = parseInt(e.target.value, 10) / 100;
      applySettingsToUI();
      saveSettings();
    });
  }

  if (settingHapticCheck) {
    settingHapticCheck.addEventListener("change", (e) => {
      hapticEnabled = e.target.checked;
      saveSettings();
    });
  }

  if (settingSliderDocksCheck) {
    settingSliderDocksCheck.addEventListener("change", (e) => {
      sliderDocksEnabled = e.target.checked;
      applySettingsToUI();
      saveSettings();
    });
  }

  if (btnResetSettings) {
    btnResetSettings.addEventListener("click", () => {
      activeScale = DEFAULT_SCALE;
      activeStickSize = DEFAULT_STICK_SIZE;
      activeOpacity = DEFAULT_OPACITY;
      activeDeadzone = DEFAULT_DEADZONE;
      activeSensitivity = DEFAULT_SENSITIVITY;
      activeLayout = DEFAULT_LAYOUT;
      hapticEnabled = true;
      sliderDocksEnabled = false;
      applySettingsToUI();
      saveSettings();
    });
  }

  // --- Tab Navigation ---
  const tabButtons = document.querySelectorAll(".tab-btn");
  const screens = document.querySelectorAll(".screen");

  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-tab");
      if (targetId !== "screen-ctrl") {
        resetAllInputControls();
        if (isConnected && isAuthenticated) {
          sendInputStateImmediate();
        }
      }

      tabButtons.forEach(b => b.classList.remove("active"));
      screens.forEach(s => s.classList.remove("active"));
      btn.classList.add("active");
      const targetScreen = document.getElementById(targetId);
      if (targetScreen) targetScreen.classList.add("active");
    });
  });

  // --- Context Menu Suppression on Interactive Elements ---
  document.querySelectorAll(".gamepad-btn, .gamepad-dpad-btn, .gamepad-trigger-tap, .joystick-pad, .trigger-slider-dock, .btn-emergency").forEach(el => {
    el.addEventListener("contextmenu", e => e.preventDefault());
  });

  // --- Status API Polling ---
  async function fetchServerStatus() {
    try {
      const host = serverHostInput.value.trim() || window.location.host;
      const protocol = window.location.protocol === "https:" ? "https:" : "http:";
      const res = await fetch(`${protocol}//${host}/api/status`);
      if (res.ok) {
        const data = await res.json();
        updateBackendStatusUI(data.gamepad);
        if (data.pairing_pin && !pairingPinInput.value) {
          pairingPinInput.value = data.pairing_pin;
        }
        if (data.total_rejected_packets !== undefined) {
          serverRejectedCount = data.total_rejected_packets;
        }
        if (data.total_watchdog_activations !== undefined) {
          serverWatchdogCount = data.total_watchdog_activations;
        }
        if (data.total_disconnects !== undefined) {
          serverDisconnectCount = data.total_disconnects;
        }
        if (data.packet_frequency_hz !== undefined && data.packet_frequency_hz > 0) {
          serverPacketHz = data.packet_frequency_hz;
        }
      }
    } catch (_) {
      statusBackend.textContent = "Cannot reach server HTTP API";
      statusDriver.textContent = "Offline or unreachable";
    }
  }

  function updateBackendStatusUI(gamepad) {
    if (!gamepad) return;
    statusBackend.textContent = gamepad.backend_type || "Unknown";
    statusDriver.textContent = gamepad.status || "Unknown";
    diagBackendInit.textContent = gamepad.is_initialized ? "YES" : "NO";
    diagBackendType.textContent = gamepad.backend_type || "Unknown";
    diagVerifLevel.textContent = gamepad.verification_level || "NOT TESTED";

    if (gamepad.status === "DRIVER_NOT_FOUND" || gamepad.status === "INIT_FAILED") {
      driverAlert.style.display = "block";
      driverAlert.innerHTML = `<strong>Driver Notice:</strong> ${gamepad.last_error || "Driver error"}<br>${gamepad.driver_instructions || ""}`;
    } else {
      driverAlert.style.display = "none";
    }
  }

  fetchServerStatus();
  setInterval(fetchServerStatus, 5000);

  // --- WebSocket Connection Handling ---
  function connectWebSocket() {
    const host = serverHostInput.value.trim();
    const pin = pairingPinInput.value.trim();

    if (!host) {
      alert("Please enter a valid server host address.");
      return;
    }
    if (!pin || pin.length !== 6) {
      alert("Please enter the 6-digit numeric pairing PIN.");
      return;
    }

    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${host}/ws`;

    updateConnectionUI("connecting");
    statusWs.textContent = `Connecting to ${wsUrl}...`;

    try {
      socket = new WebSocket(wsUrl);
    } catch (err) {
      updateConnectionUI("disconnected");
      statusWs.textContent = `Connection error: ${err.message}`;
      return;
    }

    socket.onopen = function () {
      isConnected = true;
      statusWs.textContent = "Socket Open. Authenticating...";
      socket.send(JSON.stringify({
        type: "auth",
        pin: pin
      }));
    };

    socket.onmessage = function (event) {
      try {
        const msg = JSON.parse(event.data);
        handleServerMessage(msg);
      } catch (e) {
        console.error("Malformed message from server:", event.data);
      }
    };

    socket.onclose = function (event) {
      handleSocketClose(`Socket closed (code: ${event.code}, reason: ${event.reason || "none"})`);
    };

    socket.onerror = function () {
      lastErrorMsg = "WebSocket encountered an error";
      diagLastError.textContent = lastErrorMsg;
    };
  }

  function disconnectWebSocket() {
    if (socket) {
      emergencyReleaseAll("Manual Disconnect");
      socket.close(1000, "User disconnected");
    }
    handleSocketClose("Disconnected by user");
  }

  function handleSocketClose(reason) {
    isConnected = false;
    isAuthenticated = false;
    currentSessionId = null;
    socket = null;
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }

    updateConnectionUI("disconnected");
    statusWs.textContent = reason;
    statusAuth.textContent = "Not Authenticated";
    resetAllInputControls();
  }

  function handleServerMessage(msg) {
    switch (msg.type) {
      case "auth_ok":
        isAuthenticated = true;
        currentSessionId = msg.session_id;
        updateConnectionUI("connected");
        statusAuth.textContent = `Authenticated (Session: ${currentSessionId.substring(0, 8)})`;
        if (msg.adapter) updateBackendStatusUI(msg.adapter);
        startPingTimer();
        sendInputStateImmediate();
        break;

      case "auth_error":
        isAuthenticated = false;
        lastErrorMsg = `Auth failed: ${msg.message}`;
        statusAuth.textContent = lastErrorMsg;
        diagLastError.textContent = lastErrorMsg;
        alert(lastErrorMsg);
        break;

      case "session_replaced":
        alert("This session was replaced by another client connection.");
        disconnectWebSocket();
        break;

      case "ack":
        messagesAcked++;
        lastAckSeq = msg.seq;
        if (msg.processed_duration_ms !== undefined) {
          lastProcTimeMs = msg.processed_duration_ms;
        }
        if (msg.adapter_status) {
          statusDriver.textContent = msg.adapter_status;
        }
        if (msg.packet_hz !== undefined) {
          serverPacketHz = msg.packet_hz;
        }
        if (msg.rejected_count !== undefined) {
          serverRejectedCount = msg.rejected_count;
        }
        break;

      case "pong":
        if (msg.client_ts) {
          lastRttMs = Math.round(performance.now() - msg.client_ts);
          if (hudLatency) {
            hudLatency.textContent = `${lastRttMs} ms`;
            hudLatency.style.color = lastRttMs < 30 ? "#4ade80" : (lastRttMs < 75 ? "#facc15" : "#f87171");
          }
        }
        break;

      case "release_all_ack":
        lastReleaseAllInfo = `Released at ${new Date(msg.timestamp * 1000).toLocaleTimeString()} (${msg.reason})`;
        diagLastRelease.textContent = lastReleaseAllInfo;
        emergencyIndicator.textContent = "Neutral";
        break;

      case "error":
      case "warning":
        lastErrorMsg = `[${msg.code || "ERR"}] ${msg.message}`;
        diagLastError.textContent = lastErrorMsg;
        break;

      default:
        console.log("Unhandled server message:", msg);
    }
  }

  function updateConnectionUI(state) {
    if (state === "connected") {
      connectionPill.className = "pill status-connected";
      connectionPill.textContent = "CONNECTED";
      btnConnect.disabled = true;
      btnDisconnect.disabled = false;
      diagWsStatus.textContent = "Connected";
      diagAuthStatus.textContent = "Authenticated";
    } else if (state === "connecting") {
      connectionPill.className = "pill status-connecting";
      connectionPill.textContent = "CONNECTING";
      btnConnect.disabled = true;
      btnDisconnect.disabled = false;
      diagWsStatus.textContent = "Connecting...";
      diagAuthStatus.textContent = "Authenticating...";
    } else {
      connectionPill.className = "pill status-disconnected";
      connectionPill.textContent = "DISCONNECTED";
      btnConnect.disabled = false;
      btnDisconnect.disabled = true;
      diagWsStatus.textContent = "Disconnected";
      diagAuthStatus.textContent = "Not Authenticated";
      if (hudLatency) hudLatency.textContent = "-- ms";
    }
  }

  function startPingTimer() {
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (isConnected && socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          type: "ping",
          client_ts: performance.now()
        }));
      }
    }, PING_INTERVAL_MS);
  }

  // --- Input State Transmission ---
  function scheduleInputSend() {
    if (inputSendScheduled) return;
    const now = performance.now();
    const elapsed = now - lastInputSendTime;

    if (elapsed >= INPUT_THROTTLE_MS) {
      sendInputStateImmediate();
    } else {
      inputSendScheduled = true;
      setTimeout(() => {
        inputSendScheduled = false;
        sendInputStateImmediate();
      }, INPUT_THROTTLE_MS - elapsed);
    }
  }

  function sendInputStateImmediate() {
    if (!isConnected || !isAuthenticated || !socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }

    const payload = {
      type: "input",
      seq: seqCounter++,
      buttons: Array.from(heldButtons),
      dpad: Array.from(heldDpad),
      axes: {
        lx: Number(axes.lx.toFixed(3)),
        ly: Number(axes.ly.toFixed(3)),
        rx: Number(axes.rx.toFixed(3)),
        ry: Number(axes.ry.toFixed(3))
      },
      triggers: {
        lt: Number(triggers.lt.toFixed(3)),
        rt: Number(triggers.rt.toFixed(3))
      }
    };

    try {
      socket.send(JSON.stringify(payload));
      messagesSent++;
      lastInputSendTime = performance.now();
      const isActive = (heldButtons.size > 0 || heldDpad.size > 0 || axes.lx !== 0 || axes.ly !== 0 || axes.rx !== 0 || axes.ry !== 0 || triggers.lt !== 0 || triggers.rt !== 0);
      emergencyIndicator.textContent = isActive ? "Active" : "Neutral";
      emergencyIndicator.style.color = isActive ? "#f87171" : "";
    } catch (err) {
      console.error("Failed to send input state:", err);
    }
  }

  function emergencyReleaseAll(reason = "Emergency button") {
    resetAllInputControls();
    triggerHaptic(40);
    if (isConnected && socket && socket.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({
          type: "release_all",
          reason: reason
        }));
      } catch (e) {
        console.error("Error sending release_all:", e);
      }
    }
    emergencyIndicator.textContent = "Neutral";
    emergencyIndicator.style.color = "";
  }

  function updateTriggerUI(trig, val) {
    const clamped = Math.max(0.0, Math.min(1.0, val));
    triggers[trig] = clamped;
    const meter = document.getElementById(`meter-${trig}`);
    if (meter) {
      meter.style.height = `${(clamped * 100).toFixed(0)}%`;
    }
    if (trig === "lt") {
      if (sliderLt) sliderLt.value = clamped;
      if (valLt) valLt.textContent = clamped.toFixed(2);
    } else if (trig === "rt") {
      if (sliderRt) sliderRt.value = clamped;
      if (valRt) valRt.textContent = clamped.toFixed(2);
    }
  }

  function resetAllInputControls() {
    heldButtons.clear();
    heldDpad.clear();
    axes.lx = 0.0;
    axes.ly = 0.0;
    axes.rx = 0.0;
    axes.ry = 0.0;
    updateTriggerUI("lt", 0.0);
    updateTriggerUI("rt", 0.0);

    // Reset visual controls
    document.querySelectorAll(".gamepad-btn, .gamepad-dpad-btn, .gamepad-trigger-tap").forEach(el => {
      el.classList.remove("pressed");
    });
    document.querySelectorAll(".joystick-pad").forEach(p => p.classList.remove("active"));

    if (valLx) valLx.textContent = "0.00";
    if (valLy) valLy.textContent = "0.00";
    if (valRx) valRx.textContent = "0.00";
    if (valRy) valRy.textContent = "0.00";

    const leftKnob = document.getElementById("joystick-left-knob");
    if (leftKnob) {
      leftKnob.style.left = "50%";
      leftKnob.style.top = "50%";
    }
    const rightKnob = document.getElementById("joystick-right-knob");
    if (rightKnob) {
      rightKnob.style.left = "50%";
      rightKnob.style.top = "50%";
    }
  }

  // --- Button & Trigger Pointer Handlers (Multi-Touch + lostpointercapture + Haptic) ---
  function setupButton(el, btnName) {
    el.addEventListener("pointerdown", e => {
      try { el.setPointerCapture(e.pointerId); } catch (_) {}
      el.classList.add("pressed");
      heldButtons.add(btnName);
      triggerHaptic(12);
      scheduleInputSend();
    });

    const release = e => {
      try { el.releasePointerCapture(e.pointerId); } catch (_) {}
      if (heldButtons.has(btnName)) {
        el.classList.remove("pressed");
        heldButtons.delete(btnName);
        scheduleInputSend();
      }
    };

    el.addEventListener("pointerup", release);
    el.addEventListener("pointercancel", release);
    el.addEventListener("lostpointercapture", release);
  }

  document.querySelectorAll(".gamepad-btn").forEach(btn => {
    const name = btn.getAttribute("data-btn");
    if (name) setupButton(btn, name);
  });

  // D-Pad Pointer Handlers
  document.querySelectorAll(".gamepad-dpad-btn").forEach(btn => {
    const dir = btn.getAttribute("data-dpad");
    if (!dir) return;

    btn.addEventListener("pointerdown", e => {
      try { btn.setPointerCapture(e.pointerId); } catch (_) {}
      btn.classList.add("pressed");
      heldDpad.add(dir);
      triggerHaptic(14);
      scheduleInputSend();
    });

    const release = e => {
      try { btn.releasePointerCapture(e.pointerId); } catch (_) {}
      if (heldDpad.has(dir)) {
        btn.classList.remove("pressed");
        heldDpad.delete(dir);
        scheduleInputSend();
      }
    };

    btn.addEventListener("pointerup", release);
    btn.addEventListener("pointercancel", release);
    btn.addEventListener("lostpointercapture", release);
  });

  // Trigger Sliders
  if (sliderLt) {
    sliderLt.addEventListener("input", e => {
      const v = parseFloat(e.target.value);
      updateTriggerUI("lt", v);
      scheduleInputSend();
    });
  }
  if (sliderRt) {
    sliderRt.addEventListener("input", e => {
      const v = parseFloat(e.target.value);
      updateTriggerUI("rt", v);
      scheduleInputSend();
    });
  }

  // Quick Trigger Tap & Drag Buttons (LT Aim & RT Fire)
  document.querySelectorAll(".gamepad-trigger-tap").forEach(btn => {
    const trig = btn.getAttribute("data-trigger");
    if (!trig) return;
    const targetVal = parseFloat(btn.getAttribute("data-value") || "1.0");
    let activePointerId = null;

    btn.addEventListener("pointerdown", e => {
      if (activePointerId !== null) return;
      activePointerId = e.pointerId;
      try { btn.setPointerCapture(e.pointerId); } catch (_) {}
      btn.classList.add("pressed");
      updateTriggerUI(trig, targetVal);
      triggerHaptic(18);
      scheduleInputSend();
    });

    btn.addEventListener("pointermove", e => {
      if (e.pointerId !== activePointerId) return;
      const rect = btn.getBoundingClientRect();
      if (rect.height > 0) {
        const pull = Math.max(0.0, Math.min(1.0, (rect.bottom - e.clientY) / rect.height));
        updateTriggerUI(trig, pull);
        scheduleInputSend();
      }
    });

    const release = e => {
      if (e.pointerId !== activePointerId && activePointerId !== null) return;
      try { btn.releasePointerCapture(e.pointerId); } catch (_) {}
      activePointerId = null;
      btn.classList.remove("pressed");
      updateTriggerUI(trig, 0.0);
      scheduleInputSend();
    };

    btn.addEventListener("pointerup", release);
    btn.addEventListener("pointercancel", release);
    btn.addEventListener("lostpointercapture", release);
  });

  // --- Analog Joysticks Implementation ---
  function setupJoystick(padId, knobId, axisXKey, axisYKey, labelX, labelY) {
    const pad = document.getElementById(padId);
    const knob = document.getElementById(knobId);
    if (!pad || !knob) return;

    let activePointerId = null;

    pad.addEventListener("pointerdown", e => {
      if (activePointerId !== null) return;
      activePointerId = e.pointerId;
      try { pad.setPointerCapture(e.pointerId); } catch (_) {}
      pad.classList.add("active");
      triggerHaptic(8);
      updateJoystickPosition(e);
    });

    pad.addEventListener("pointermove", e => {
      if (e.pointerId !== activePointerId) return;
      updateJoystickPosition(e);
    });

    const release = e => {
      if (e.pointerId !== activePointerId && activePointerId !== null) return;
      try { pad.releasePointerCapture(e.pointerId); } catch (_) {}
      activePointerId = null;
      pad.classList.remove("active");

      // Reset to center
      knob.style.left = "50%";
      knob.style.top = "50%";
      axes[axisXKey] = 0.0;
      axes[axisYKey] = 0.0;
      if (labelX) labelX.textContent = "0.00";
      if (labelY) labelY.textContent = "0.00";
      scheduleInputSend();
    };

    pad.addEventListener("pointerup", release);
    pad.addEventListener("pointercancel", release);
    pad.addEventListener("lostpointercapture", release);

    function updateJoystickPosition(e) {
      const rect = pad.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const maxRadius = (rect.width / 2) - 10;
      if (maxRadius <= 0) return;

      let dx = e.clientX - centerX;
      let dy = e.clientY - centerY;
      const dist = Math.hypot(dx, dy);

      if (dist > maxRadius) {
        dx = (dx / dist) * maxRadius;
        dy = (dy / dist) * maxRadius;
      }

      // Visual knob position (pixels)
      knob.style.left = `${(rect.width / 2) + dx}px`;
      knob.style.top = `${(rect.height / 2) + dy}px`;

      // Normalized coordinates [-1.0, 1.0]
      let normX = dx / maxRadius;
      let normY = -(dy / maxRadius);

      // Deadzone clamping with user-customizable deadzone
      const normMag = Math.hypot(normX, normY);
      if (normMag < activeDeadzone) {
        normX = 0.0;
        normY = 0.0;
      } else {
        const scale = (normMag - activeDeadzone) / (1.0 - activeDeadzone) / normMag;
        normX = Math.max(-1.0, Math.min(1.0, normX * scale * activeSensitivity));
        normY = Math.max(-1.0, Math.min(1.0, normY * scale * activeSensitivity));
      }

      axes[axisXKey] = normX;
      axes[axisYKey] = normY;
      if (labelX) labelX.textContent = normX.toFixed(2);
      if (labelY) labelY.textContent = normY.toFixed(2);
      scheduleInputSend();
    }
  }

  setupJoystick("joystick-left", "joystick-left-knob", "lx", "ly", valLx, valLy);
  setupJoystick("joystick-right", "joystick-right-knob", "rx", "ry", valRx, valRy);

  // --- Emergency Release Button ---
  if (btnEmergencyRelease) {
    btnEmergencyRelease.addEventListener("click", () => {
      emergencyReleaseAll("Emergency Button Pressed");
    });
  }

  // --- Connect / Disconnect Buttons ---
  btnConnect.addEventListener("click", connectWebSocket);
  btnDisconnect.addEventListener("click", disconnectWebSocket);

  // --- Hardware Test Buttons (Screen C) ---
  document.querySelectorAll(".test-pulse-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const testType = btn.getAttribute("data-test");
      if (testType === "btn") {
        const name = btn.getAttribute("data-name");
        heldButtons.add(name);
        sendInputStateImmediate();
        setTimeout(() => {
          heldButtons.delete(name);
          sendInputStateImmediate();
        }, 150);
      } else if (testType === "dpad") {
        const name = btn.getAttribute("data-name");
        heldDpad.add(name);
        sendInputStateImmediate();
        setTimeout(() => {
          heldDpad.delete(name);
          sendInputStateImmediate();
        }, 150);
      } else if (testType === "trigger") {
        const name = btn.getAttribute("data-name");
        const val = parseFloat(btn.getAttribute("data-val") || "1.0");
        updateTriggerUI(name, val);
        sendInputStateImmediate();
        setTimeout(() => {
          updateTriggerUI(name, 0.0);
          sendInputStateImmediate();
        }, 150);
      } else if (testType === "axis") {
        const axis = btn.getAttribute("data-axis");
        const val = parseFloat(btn.getAttribute("data-val") || "1.0");
        axes[axis] = val;
        sendInputStateImmediate();
        setTimeout(() => {
          axes[axis] = 0.0;
          sendInputStateImmediate();
        }, 150);
      } else if (testType === "reset") {
        emergencyReleaseAll("Test Panel Center All");
      }
    });
  });

  // --- Window Blur, Visibility, & Unload Safety Cleanup ---
  window.addEventListener("blur", () => {
    if (isConnected) {
      emergencyReleaseAll("Window blur safety reset");
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && isConnected) {
      emergencyReleaseAll("Tab hidden safety reset");
    }
  });

  window.addEventListener("pagehide", () => {
    if (isConnected) {
      emergencyReleaseAll("Page hide safety reset");
    }
  });

  window.addEventListener("beforeunload", () => {
    if (isConnected) {
      emergencyReleaseAll("Beforeunload safety reset");
    }
  });

  // --- Diagnostics Update Timer ---
  setInterval(() => {
    if (diagRtt) diagRtt.textContent = lastRttMs !== null ? `${lastRttMs} ms` : "-- ms";
    if (diagProcTime) diagProcTime.textContent = lastProcTimeMs !== null ? `${lastProcTimeMs} ms` : "-- ms";

    const oneWayNetMs = lastRttMs !== null ? (lastRttMs / 2.0).toFixed(1) : "--";
    if (diagOnewayNet) diagOnewayNet.textContent = oneWayNetMs !== "--" ? `${oneWayNetMs} ms` : "-- ms";

    if (diagEstE2e) {
      if (lastRttMs !== null && lastProcTimeMs !== null) {
        const estE2e = ((lastRttMs / 2.0) + lastProcTimeMs).toFixed(2);
        diagEstE2e.textContent = `${estE2e} ms`;
      } else {
        diagEstE2e.textContent = "-- ms";
      }
    }

    if (diagPacketHz) diagPacketHz.textContent = `${serverPacketHz} Hz`;
    if (diagRejectedPkts) diagRejectedPkts.textContent = `${serverRejectedCount}`;
    if (diagWatchdogActs) diagWatchdogActs.textContent = `${serverWatchdogCount}`;
    if (diagDisconnects) diagDisconnects.textContent = `${serverDisconnectCount}`;

    if (diagMsgCounts) diagMsgCounts.textContent = `${messagesSent} / ${messagesAcked} (Last Ack Seq: ${lastAckSeq})`;
    if (diagLastInputTime) diagLastInputTime.textContent = lastInputSendTime ? `${new Date().toLocaleTimeString()}` : "--";
    if (diagAxes) diagAxes.textContent = `${axes.lx.toFixed(2)}, ${axes.ly.toFixed(2)}, ${axes.rx.toFixed(2)}, ${axes.ry.toFixed(2)}`;
    if (diagTriggers) diagTriggers.textContent = `${triggers.lt.toFixed(2)}, ${triggers.rt.toFixed(2)}`;
    if (diagHeldButtons) diagHeldButtons.textContent = heldButtons.size > 0 ? Array.from(heldButtons).join(", ") : "None";
    if (diagHeldDpad) diagHeldDpad.textContent = heldDpad.size > 0 ? Array.from(heldDpad).join(", ") : "None";
  }, 200);

})();
