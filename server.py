"""
FastAPI Server for RDR2 Mobile Controller.
Provides HTTP static file serving, diagnostic status API, and low-latency WebSocket input handling.
"""

import argparse
import asyncio
from contextlib import asynccontextmanager
import logging
import math
import os
import secrets
import socket
import string
import sys
import time
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from gamepad.base import (
    BaseGamepadAdapter,
    GamepadBackendStatus,
    InputState,
    SUPPORTED_BUTTONS,
    SUPPORTED_DPAD,
    VerificationLevel,
)
from gamepad.mock_adapter import MockGamepadAdapter
from gamepad.windows_adapter import WindowsGamepadAdapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("controller.server")

# Default network and timing constants
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
HEARTBEAT_INTERVAL_MS = 1000
INACTIVITY_TIMEOUT_SEC = 2.5
MAX_AUTH_FAILURES = 5
MAX_MESSAGE_SIZE = 4096


def get_local_ip_addresses() -> List[Dict[str, str]]:
    """Detect non-loopback IPv4 addresses on all active network interfaces."""
    interfaces = []
    try:
        # Standard socket connection trick to determine outbound default route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            primary_ip = s.getsockname()[0]
            interfaces.append({"alias": "Primary Route", "ip": primary_ip})
        except Exception:
            pass
        finally:
            s.close()
    except Exception:
        pass

    # Query all hostnames
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbynameex(hostname)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                if not any(iface["ip"] == ip for iface in interfaces):
                    interfaces.append({"alias": "Local Interface", "ip": ip})
    except Exception:
        pass

    if not interfaces:
        interfaces.append({"alias": "Loopback", "ip": "127.0.0.1"})

    return interfaces


def generate_pairing_pin() -> str:
    """Generate a cryptographically secure 6-digit numeric PIN."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


def check_port_in_use(host: str, port: int) -> tuple[bool, Optional[int]]:
    """
    Check if a TCP port is already in use by attempting a test bind.
    Returns (is_in_use, owning_pid).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind((host, port))
        s.close()
        return False, None
    except OSError:
        owning_pid = None
        try:
            import subprocess
            out = subprocess.check_output(f'netstat -ano | findstr ":{port} "', shell=True, text=True)
            for line in out.strip().splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and "LISTENING" in parts:
                    owning_pid = int(parts[-1])
                    break
        except Exception:
            pass
        return True, owning_pid


class SessionManager:
    """
    Manages active controller session, input-state sequencing,
    watchdog timers, metrics, and clean disconnect recovery.
    """

    def __init__(self, adapter: BaseGamepadAdapter, pairing_pin: str):
        self.adapter = adapter
        self.pairing_pin = pairing_pin
        self.active_websocket: Optional[WebSocket] = None
        self.active_session_id: Optional[str] = None
        self.last_seq: int = 0
        self.last_activity_ts: float = 0.0
        self.total_messages_received: int = 0
        self.total_messages_acknowledged: int = 0
        self.last_error: Optional[str] = None
        self.last_release_all_event: Optional[Dict[str, any]] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Reliability & diagnostics tracking
        self.total_disconnects: int = 0
        self.last_disconnect_reason: Optional[str] = None
        self.total_watchdog_activations: int = 0
        self.last_watchdog_event: Optional[Dict[str, any]] = None
        self._watchdog_neutralized: bool = False

        # Rejected packets breakdown
        self.rejected_packets: Dict[str, int] = {
            "stale_sequence": 0,
            "validation_error": 0,
            "invalid_sequence": 0,
            "expired_session": 0,
            "malformed_json": 0,
            "unauthorized": 0,
            "unknown_type": 0,
        }

        # Packet frequency tracking (rolling 1-second window)
        self._hz_window_start: float = time.time()
        self._hz_packet_count: int = 0
        self.current_packet_hz: float = 0.0

        # Input-processing latency tracking (ms)
        self.last_proc_ms: float = 0.0
        self.avg_proc_ms: float = 0.0
        self.min_proc_ms: float = float("inf")
        self.max_proc_ms: float = 0.0

    async def start_session(self, websocket: WebSocket) -> str:
        """Register a newly authenticated client session and invalidate prior session."""
        async with self._lock:
            if self.active_websocket is not None and self.active_websocket != websocket:
                logger.warning("Superseding prior active session with new client connection.")
                try:
                    await self.active_websocket.send_json({
                        "type": "session_replaced",
                        "message": "Another client has connected and claimed the controller session."
                    })
                    await self.active_websocket.close(code=1000)
                except Exception as e:
                    logger.debug("Error while closing replaced session: %s", e)
                # Ensure neutral state between session handovers
                self.release_all_inputs(reason="Session replacement")

            session_id = secrets.token_hex(8)
            self.active_websocket = websocket
            self.active_session_id = session_id
            self.last_seq = 0
            self.last_activity_ts = time.time()
            self._watchdog_neutralized = False
            return session_id

    def release_all_inputs(self, reason: str = "Unknown") -> bool:
        """Idempotently reset all gamepad buttons, axes, and triggers to neutral."""
        success = self.adapter.release_all()
        self.last_release_all_event = {
            "timestamp": time.time(),
            "reason": reason,
            "success": success
        }
        logger.info("Released all inputs (Reason: %s, Success: %s)", reason, success)
        return success

    async def handle_disconnect(self, websocket: WebSocket, reason: str = "Client disconnect") -> None:
        """Handle WebSocket close or drop safely."""
        async with self._lock:
            if self.active_websocket == websocket:
                self.active_websocket = None
                self.active_session_id = None
                self.total_disconnects += 1
                self.last_disconnect_reason = reason
                self.release_all_inputs(reason=reason)

    def touch_activity(self) -> None:
        """Update last seen timestamp for watchdog and compute rolling packet frequency."""
        now = time.time()
        self.last_activity_ts = now
        self._watchdog_neutralized = False
        self.total_messages_received += 1
        self._hz_packet_count += 1
        elapsed = now - self._hz_window_start
        if elapsed >= 1.0:
            self.current_packet_hz = round(self._hz_packet_count / elapsed, 1)
            self._hz_window_start = now
            self._hz_packet_count = 0

    def record_processing_latency(self, duration_ms: float) -> None:
        """Record processing duration and update min/max/avg statistics."""
        self.total_messages_acknowledged += 1
        self.last_proc_ms = round(duration_ms, 3)
        if self.min_proc_ms == float("inf") or duration_ms < self.min_proc_ms:
            self.min_proc_ms = round(duration_ms, 3)
        if duration_ms > self.max_proc_ms:
            self.max_proc_ms = round(duration_ms, 3)
        if self.avg_proc_ms == 0.0:
            self.avg_proc_ms = round(duration_ms, 3)
        else:
            self.avg_proc_ms = round(0.9 * self.avg_proc_ms + 0.1 * duration_ms, 3)

    def record_rejected_packet(self, category: str) -> None:
        """Increment count for a specific rejected packet category."""
        if category in self.rejected_packets:
            self.rejected_packets[category] += 1
        else:
            self.rejected_packets[category] = 1

    async def run_watchdog(self) -> None:
        """Background watchdog releasing controls if client connection goes silent."""
        while True:
            await asyncio.sleep(0.5)
            async with self._lock:
                if self.active_websocket is not None:
                    idle_duration = time.time() - self.last_activity_ts
                    if idle_duration > INACTIVITY_TIMEOUT_SEC:
                        if not self._watchdog_neutralized:
                            self._watchdog_neutralized = True
                            self.total_watchdog_activations += 1
                            self.last_watchdog_event = {
                                "timestamp": time.time(),
                                "idle_duration_sec": round(idle_duration, 2),
                            }
                            logger.warning(
                                "Watchdog triggered: no activity for %.2f seconds. Releasing all inputs.",
                                idle_duration
                            )
                            self.release_all_inputs(reason=f"Watchdog timeout ({idle_duration:.2f}s idle)")
                            try:
                                await self.active_websocket.send_json({
                                    "type": "warning",
                                    "message": "Inactivity timeout exceeded. Controls reset to neutral."
                                })
                            except Exception:
                                pass


def create_app(
    adapter: Optional[BaseGamepadAdapter] = None,
    pairing_pin: Optional[str] = None,
    use_mock: bool = False
) -> FastAPI:
    """Create and configure the FastAPI application."""

    # Select adapter
    if adapter is None:
        if use_mock:
            adapter = MockGamepadAdapter()
        else:
            adapter = WindowsGamepadAdapter()
        adapter.initialize()

    # Generate or set pairing PIN
    pin = pairing_pin or os.environ.get("CONTROLLER_PIN") or generate_pairing_pin()
    session_manager = SessionManager(adapter=adapter, pairing_pin=pin)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logger.info("=" * 60)
        logger.info("RDR2 Mobile Controller Server Started")
        logger.info("Pairing PIN: %s", session_manager.pairing_pin)
        for iface in get_local_ip_addresses():
            logger.info("Local Web URL: http://%s:%d (%s)", iface["ip"], DEFAULT_PORT, iface["alias"])
        logger.info("Gamepad Backend: %s", adapter.get_status()["backend_type"])
        logger.info("=" * 60)

        # Start watchdog
        session_manager._watchdog_task = asyncio.create_task(session_manager.run_watchdog())

        yield

        # Shutdown
        if session_manager._watchdog_task:
            session_manager._watchdog_task.cancel()
        session_manager.release_all_inputs(reason="Server shutdown")
        adapter.close()
        logger.info("Server shutdown complete. Gamepad resources released.")

    app = FastAPI(title="RDR2 Mobile Controller", lifespan=lifespan)

    # Attach session manager to app state for testing and endpoint access
    app.state.session_manager = session_manager
    app.state.adapter = adapter
    app.state.pin = pin

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/status")
    async def api_status():
        """Health check, diagnostic metrics, and adapter status endpoint."""
        adapter_status = adapter.get_status()
        return JSONResponse({
            "status": "online",
            "server_time": time.time(),
            "local_ips": get_local_ip_addresses(),
            "pairing_pin": session_manager.pairing_pin,
            "has_active_client": session_manager.active_websocket is not None,
            "active_session_id": session_manager.active_session_id,
            "total_messages_received": session_manager.total_messages_received,
            "total_messages_acknowledged": session_manager.total_messages_acknowledged,
            "total_rejected_packets": sum(session_manager.rejected_packets.values()),
            "rejected_packets": dict(session_manager.rejected_packets),
            "total_disconnects": session_manager.total_disconnects,
            "last_disconnect_reason": session_manager.last_disconnect_reason,
            "total_watchdog_activations": session_manager.total_watchdog_activations,
            "last_watchdog_event": session_manager.last_watchdog_event,
            "packet_frequency_hz": session_manager.current_packet_hz,
            "latency_stats": {
                "last_processing_ms": session_manager.last_proc_ms,
                "avg_processing_ms": session_manager.avg_proc_ms,
                "min_processing_ms": session_manager.min_proc_ms if session_manager.min_proc_ms != float("inf") else 0.0,
                "max_processing_ms": session_manager.max_proc_ms,
            },
            "last_release_all_event": session_manager.last_release_all_event,
            "heartbeat_interval_ms": HEARTBEAT_INTERVAL_MS,
            "inactivity_timeout_sec": INACTIVITY_TIMEOUT_SEC,
            "gamepad": adapter_status,
        })

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """Persistent WebSocket handling client authentication and low-latency input streaming."""
        await websocket.accept()
        is_authenticated = False
        client_session_id = None
        auth_failures = 0

        try:
            while True:
                # Receive client message
                try:
                    data = await websocket.receive_json()
                except ValueError:
                    session_manager.record_rejected_packet("malformed_json")
                    await websocket.send_json({
                        "type": "error",
                        "code": "INVALID_JSON",
                        "message": "Malformed JSON payload rejected"
                    })
                    continue

                if not isinstance(data, dict):
                    session_manager.record_rejected_packet("malformed_json")
                    await websocket.send_json({
                        "type": "error",
                        "code": "MALFORMED_MESSAGE",
                        "message": "Payload must be a JSON object"
                    })
                    continue

                msg_type = data.get("type")

                # Handle Authentication Handshake
                if not is_authenticated:
                    if msg_type == "auth":
                        client_pin = str(data.get("pin", "")).strip()
                        if client_pin == session_manager.pairing_pin:
                            is_authenticated = True
                            client_session_id = await session_manager.start_session(websocket)
                            await websocket.send_json({
                                "type": "auth_ok",
                                "session_id": client_session_id,
                                "heartbeat_interval_ms": HEARTBEAT_INTERVAL_MS,
                                "adapter": adapter.get_status()
                            })
                            logger.info("Client authenticated successfully (Session: %s)", client_session_id)
                        else:
                            auth_failures += 1
                            session_manager.record_rejected_packet("unauthorized")
                            logger.warning(
                                "Invalid pairing PIN attempt (%d/%d): received '%s'",
                                auth_failures, MAX_AUTH_FAILURES, client_pin
                            )
                            if auth_failures >= MAX_AUTH_FAILURES:
                                await websocket.send_json({
                                    "type": "auth_error",
                                    "code": "TOO_MANY_ATTEMPTS",
                                    "message": "Too many failed authentication attempts. Disconnecting."
                                })
                                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                                return
                            else:
                                await websocket.send_json({
                                    "type": "auth_error",
                                    "code": "INVALID_PIN",
                                    "message": f"Incorrect pairing PIN. Attempt {auth_failures} of {MAX_AUTH_FAILURES}"
                                })
                    else:
                        session_manager.record_rejected_packet("unauthorized")
                        await websocket.send_json({
                            "type": "auth_error",
                            "code": "UNAUTHORIZED",
                            "message": "Authentication required. Send {'type': 'auth', 'pin': '...'} first."
                        })
                    continue

                # Verify this session has not been superseded by another client connection
                if client_session_id != session_manager.active_session_id:
                    session_manager.record_rejected_packet("expired_session")
                    try:
                        if websocket.client_state != WebSocketState.DISCONNECTED and websocket.application_state != WebSocketState.DISCONNECTED:
                            await websocket.send_json({
                                "type": "error",
                                "code": "SESSION_EXPIRED",
                                "message": "This session has been replaced or expired."
                            })
                            await websocket.close(code=1000)
                    except Exception:
                        pass
                    return

                # Authenticated Message Processing
                session_manager.touch_activity()
                recv_time = time.time()

                if msg_type == "ping":
                    client_ts = data.get("client_ts", 0)
                    await websocket.send_json({
                        "type": "pong",
                        "client_ts": client_ts,
                        "server_ts": recv_time
                    })
                    continue

                elif msg_type == "release_all":
                    reason = data.get("reason", "Client Emergency Release All")
                    success = session_manager.release_all_inputs(reason=reason)
                    await websocket.send_json({
                        "type": "release_all_ack",
                        "success": success,
                        "timestamp": time.time(),
                        "reason": reason
                    })
                    continue

                elif msg_type == "input":
                    # Input sequence and freshness checks
                    raw_seq = data.get("seq")
                    if not isinstance(raw_seq, int):
                        session_manager.record_rejected_packet("invalid_sequence")
                        await websocket.send_json({
                            "type": "error",
                            "code": "INVALID_SEQUENCE",
                            "message": "'seq' must be an integer"
                        })
                        continue

                    if raw_seq <= session_manager.last_seq:
                        # Drop stale or duplicate packet
                        session_manager.record_rejected_packet("stale_sequence")
                        await websocket.send_json({
                            "type": "ack",
                            "seq": raw_seq,
                            "stale": True,
                            "last_seq": session_manager.last_seq,
                            "adapter_success": False
                        })
                        continue

                    # Validate and parse input state
                    try:
                        input_state = InputState.from_dict(data)
                    except ValueError as ve:
                        session_manager.record_rejected_packet("validation_error")
                        await websocket.send_json({
                            "type": "error",
                            "code": "VALIDATION_ERROR",
                            "message": str(ve),
                            "seq": raw_seq
                        })
                        continue

                    session_manager.last_seq = raw_seq

                    # Update Gamepad Adapter
                    t_before = time.perf_counter()
                    adapter_success = adapter.update_input(input_state)
                    t_after = time.perf_counter()
                    duration_ms = (t_after - t_before) * 1000.0

                    session_manager.record_processing_latency(duration_ms)

                    # Send authoritative acknowledgement
                    await websocket.send_json({
                        "type": "ack",
                        "seq": raw_seq,
                        "received_ts": recv_time,
                        "processed_duration_ms": round(duration_ms, 3),
                        "adapter_success": adapter_success,
                        "adapter_status": adapter.get_status()["status"],
                        "packet_hz": session_manager.current_packet_hz,
                        "rejected_count": sum(session_manager.rejected_packets.values()),
                    })

                else:
                    session_manager.record_rejected_packet("unknown_type")
                    await websocket.send_json({
                        "type": "error",
                        "code": "UNKNOWN_TYPE",
                        "message": f"Unsupported message type: {msg_type}"
                    })

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected (Session: %s)", client_session_id)
        except Exception as e:
            logger.error("Unhandled WebSocket exception: %s", e)
        finally:
            await session_manager.handle_disconnect(websocket, reason="WebSocket closed")

    # Mount static assets directory
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


def main():
    parser = argparse.ArgumentParser(description="RDR2 Mobile Controller Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host network interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on (default: 8000)")
    parser.add_argument("--pin", default=None, help="Fixed 6-digit pairing PIN (default: random secure PIN)")
    parser.add_argument("--mock", action="store_true", help="Force Mock Gamepad Adapter (bypasses Windows driver)")
    args = parser.parse_args()

    # Pre-check for duplicate server processes or port conflicts
    in_use, pid = check_port_in_use(args.host, args.port)
    if in_use:
        pid_msg = f" (PID {pid})" if pid else ""
        logger.error(
            "Port %d is already in use by another process%s. "
            "Please terminate the conflicting process before starting the server.",
            args.port, pid_msg
        )
        sys.exit(1)

    import uvicorn
    app = create_app(pairing_pin=args.pin, use_mock=args.mock)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
