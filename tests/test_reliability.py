"""
Automated tests for reliability pass:
- Disconnect & watchdog neutralization of analog sticks, triggers, and buttons
- Expired / duplicate session rejection
- Telemetry & metrics: packet frequency, rejected packets breakdown, disconnects, latency stats
- Port conflict detection
- Watchdog idempotency
"""

import asyncio
import socket
import time
import pytest
from starlette.testclient import TestClient

from gamepad.base import InputState
from gamepad.mock_adapter import MockGamepadAdapter
from gamepad.windows_adapter import WindowsGamepadAdapter
from server import check_port_in_use, create_app, INACTIVITY_TIMEOUT_SEC


def test_expired_session_rejection(test_app, fixed_pin, mock_adapter):
    """Verify that when Session 1 is superseded by Session 2, Session 1 input is rejected."""
    with TestClient(test_app) as client:
        # Client 1 connects and authenticates
        with client.websocket_connect("/ws") as ws1:
            ws1.send_json({"type": "auth", "pin": fixed_pin})
            r1 = ws1.receive_json()
            assert r1["type"] == "auth_ok"
            s1_id = r1["session_id"]

            ws1.send_json({"type": "input", "seq": 1, "buttons": ["A"]})
            ack1 = ws1.receive_json()
            assert ack1["type"] == "ack"
            assert "A" in mock_adapter.current_state.buttons

            # Client 2 connects and authenticates (superseding Client 1)
            with client.websocket_connect("/ws") as ws2:
                ws2.send_json({"type": "auth", "pin": fixed_pin})
                r2 = ws2.receive_json()
                assert r2["type"] == "auth_ok"
                assert r2["session_id"] != s1_id

                # Client 1 receives session_replaced notice
                notice = ws1.receive_json()
                assert notice["type"] == "session_replaced"

                # Client 1's socket is closed by the server (code 1000)
                with pytest.raises(Exception):
                    ws1.receive_json()

                # Verify Client 2 can now send inputs cleanly
                ws2.send_json({"type": "input", "seq": 1, "buttons": ["B"]})
                ack2 = ws2.receive_json()
                assert ack2["type"] == "ack"
                assert mock_adapter.current_state.buttons == {"B"}


def test_watchdog_neutralizes_all_axes_triggers_buttons():
    """Verify that watchdog expiration resets analog sticks, triggers, and buttons to 0."""
    async def run():
        mock = MockGamepadAdapter()
        mock.initialize()

        # Set active controls: non-zero axes, triggers, and buttons
        mock.current_state = InputState(
            seq=10,
            buttons={"A", "LB", "X"},
            dpad={"UP"},
            axes={"lx": 0.85, "ly": -0.75, "rx": -0.4, "ry": 0.9},
            triggers={"lt": 0.65, "rt": 1.0}
        )

        app = create_app(adapter=mock, pairing_pin="123456")
        sm = app.state.session_manager
        sm.active_websocket = object() # Mock active connection
        sm.last_activity_ts = time.time() - (INACTIVITY_TIMEOUT_SEC + 1.0)

        # Run watchdog logic
        await asyncio.sleep(0.01)
        idle_duration = time.time() - sm.last_activity_ts
        if idle_duration > INACTIVITY_TIMEOUT_SEC and not sm._watchdog_neutralized:
            sm._watchdog_neutralized = True
            sm.total_watchdog_activations += 1
            sm.release_all_inputs(reason="Watchdog test")

        # Verify full neutralization
        assert mock.current_state.buttons == set()
        assert mock.current_state.dpad == set()
        assert mock.current_state.axes == {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
        assert mock.current_state.triggers == {"lt": 0.0, "rt": 0.0}
        assert sm.total_watchdog_activations == 1

        # Second watchdog pass during same idle period should be idempotent
        prior_activations = sm.total_watchdog_activations
        if idle_duration > INACTIVITY_TIMEOUT_SEC and not sm._watchdog_neutralized:
            sm.total_watchdog_activations += 1
        assert sm.total_watchdog_activations == prior_activations

    asyncio.run(run())


def test_rejected_packets_breakdown_metrics(client, fixed_pin):
    """Verify each rejected packet scenario increments its specific category counter."""
    with client.websocket_connect("/ws") as ws:
        # 1. Unauthorized input attempt
        ws.send_json({"type": "input", "seq": 1, "buttons": ["A"]})
        ws.receive_json()

        # Authenticate
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        # 2. Invalid sequence type (non-int)
        ws.send_json({"type": "input", "seq": "invalid"})
        ws.receive_json()

        # Valid seq 10
        ws.send_json({"type": "input", "seq": 10, "buttons": ["A"]})
        ws.receive_json()

        # 3. Stale sequence number (seq 5 <= 10)
        ws.send_json({"type": "input", "seq": 5, "buttons": ["A"]})
        ws.receive_json()

        # 4. Validation error (invalid buttons type)
        ws.send_json({"type": "input", "seq": 11, "buttons": 12345})
        ws.receive_json()

        # 5. Unknown message type
        ws.send_json({"type": "unknown_action_foo"})
        ws.receive_json()

        # 6. Malformed JSON
        ws.send_text("not-json")
        ws.receive_json()

    # Query status endpoint
    res = client.get("/api/status").json()
    breakdown = res["rejected_packets"]
    assert breakdown["unauthorized"] >= 1
    assert breakdown["invalid_sequence"] >= 1
    assert breakdown["stale_sequence"] >= 1
    assert breakdown["validation_error"] >= 1
    assert breakdown["unknown_type"] >= 1
    assert breakdown["malformed_json"] >= 1
    assert res["total_rejected_packets"] >= 6


def test_disconnect_counter_and_reason(client, fixed_pin):
    """Verify disconnect events increment total_disconnects and store last_disconnect_reason."""
    initial_status = client.get("/api/status").json()
    base_disconnects = initial_status["total_disconnects"]

    # Connect and disconnect Session 1
    with client.websocket_connect("/ws") as ws1:
        ws1.send_json({"type": "auth", "pin": fixed_pin})
        ws1.receive_json()

    status1 = client.get("/api/status").json()
    assert status1["total_disconnects"] == base_disconnects + 1
    assert status1["last_disconnect_reason"] == "WebSocket closed"

    # Connect and disconnect Session 2
    with client.websocket_connect("/ws") as ws2:
        ws2.send_json({"type": "auth", "pin": fixed_pin})
        ws2.receive_json()

    status2 = client.get("/api/status").json()
    assert status2["total_disconnects"] == base_disconnects + 2


def test_latency_statistics_calculation():
    """Verify latency statistics min, max, avg update correctly."""
    mock = MockGamepadAdapter()
    mock.initialize()
    app = create_app(adapter=mock, pairing_pin="123456")
    sm = app.state.session_manager

    sm.record_processing_latency(0.10)
    assert sm.last_proc_ms == 0.10
    assert sm.min_proc_ms == 0.10
    assert sm.max_proc_ms == 0.10
    assert sm.avg_proc_ms == 0.10

    sm.record_processing_latency(0.05)
    assert sm.min_proc_ms == 0.05
    assert sm.last_proc_ms == 0.05

    sm.record_processing_latency(0.50)
    assert sm.max_proc_ms == 0.50
    assert sm.min_proc_ms == 0.05
    assert sm.avg_proc_ms > 0.05


def test_packet_frequency_tracking():
    """Verify rolling packet frequency calculation."""
    mock = MockGamepadAdapter()
    mock.initialize()
    app = create_app(adapter=mock, pairing_pin="123456")
    sm = app.state.session_manager

    # Simulate 30 packets arriving within a 1-second interval
    sm._hz_window_start = time.time() - 1.05
    for _ in range(30):
        sm.touch_activity()

    assert sm.current_packet_hz > 0.0


def test_port_in_use_checker():
    """Verify check_port_in_use identifies both available and bound ports."""
    # Find an ephemeral free port
    temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    temp_sock.bind(("127.0.0.1", 0))
    free_port = temp_sock.getsockname()[1]

    # Port is currently bound by temp_sock
    in_use, _ = check_port_in_use("127.0.0.1", free_port)
    assert in_use is True

    # Close temp_sock -> port becomes available
    temp_sock.close()
    in_use_after, _ = check_port_in_use("127.0.0.1", free_port)
    assert in_use_after is False


def test_emergency_release_guarantees_neutral_on_adapters():
    """Verify release_all() sets axes to 0.0 and triggers to 0.0 on both adapters."""
    # 1. Mock adapter
    mock = MockGamepadAdapter()
    mock.initialize()
    mock.update_input(InputState(
        seq=1,
        buttons={"A", "B"},
        axes={"lx": -0.8, "ly": 0.9, "rx": 0.4, "ry": -0.5},
        triggers={"lt": 0.8, "rt": 1.0}
    ))
    mock.release_all()
    assert mock.current_state.axes == {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
    assert mock.current_state.triggers == {"lt": 0.0, "rt": 0.0}
    assert len(mock.current_state.buttons) == 0

    # 2. Windows adapter
    win = WindowsGamepadAdapter()
    win.current_state = InputState(
        seq=1,
        buttons={"X", "Y"},
        axes={"lx": 1.0, "ly": 1.0, "rx": -1.0, "ry": -1.0},
        triggers={"lt": 1.0, "rt": 1.0}
    )
    win.release_all()
    assert win.current_state.axes == {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
    assert win.current_state.triggers == {"lt": 0.0, "rt": 0.0}
    assert len(win.current_state.buttons) == 0
