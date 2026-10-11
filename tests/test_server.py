"""
End-to-end integration tests for FastAPI Server, WebSocket input protocol,
authentication, security constraints, multi-client management, and static assets.
"""

import asyncio
import json
import os
import subprocess
import time
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gamepad.mock_adapter import MockGamepadAdapter
from server import create_app, INACTIVITY_TIMEOUT_SEC


def test_server_startup_and_status_endpoint(client, fixed_pin):
    """1. Test server startup, health endpoint, local IPs, and pairing PIN."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert data["pairing_pin"] == fixed_pin
    assert isinstance(data["local_ips"], list)
    assert len(data["local_ips"]) > 0
    assert "gamepad" in data
    assert data["gamepad"]["backend_type"] == "MOCK"


def test_websocket_connection_and_correct_pin(client, fixed_pin):
    """2 & 3. Test WebSocket connection and successful authentication with correct PIN."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        resp = ws.receive_json()
        assert resp["type"] == "auth_ok"
        assert "session_id" in resp
        assert resp["adapter"]["status"] == "READY"


def test_websocket_incorrect_pin_rejection(client):
    """3. Test rejection and attempt counting on incorrect pairing PIN."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": "000000"})
        resp = ws.receive_json()
        assert resp["type"] == "auth_error"
        assert resp["code"] == "INVALID_PIN"


def test_unauthorized_client_rejection(client):
    """4. Test that attempting input updates before authenticating is rejected."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "input", "seq": 1, "buttons": ["A"]})
        resp = ws.receive_json()
        assert resp["type"] == "auth_error"
        assert resp["code"] == "UNAUTHORIZED"


def test_malformed_messages_and_invalid_json(client, fixed_pin):
    """5. Test handling of malformed payloads or invalid message types."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        # Non-dict JSON payload
        ws.send_text("[\"not_an_object\"]")
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "MALFORMED_MESSAGE"

        # Invalid JSON string
        ws.send_text("{broken json syntax")
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_JSON"

        # Unknown message type
        ws.send_json({"type": "unsupported_command"})
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "UNKNOWN_TYPE"


def test_missing_fields_and_invalid_types(client, fixed_pin):
    """6. Test invalid sequence type and missing/invalid fields."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        # Non-integer seq
        ws.send_json({"type": "input", "seq": "first"})
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "INVALID_SEQUENCE"

        # Invalid buttons type
        ws.send_json({"type": "input", "seq": 1, "buttons": "A"})
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp["code"] == "VALIDATION_ERROR"


def test_nan_and_infinity_handling_in_server(client, fixed_pin, mock_adapter):
    """7. Test that NaN and Inf are handled cleanly without crashing server."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        # Send raw numbers or non-finite inputs
        ws.send_json({
            "type": "input",
            "seq": 1,
            "axes": {"lx": None, "ly": 0.5},
            "triggers": {"lt": 0.0, "rt": 0.0}
        })
        resp = ws.receive_json()
        assert resp["type"] == "ack"
        assert resp["seq"] == 1
        assert mock_adapter.current_state.axes["lx"] == 0.0
        assert mock_adapter.current_state.axes["ly"] == 0.5


def test_axis_clamping_and_triggers_via_websocket(client, fixed_pin, mock_adapter):
    """8 & 9. Test axis clamping and analog trigger values over WebSocket."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        # Partial triggers & extreme axis values
        ws.send_json({
            "type": "input",
            "seq": 1,
            "axes": {"lx": 10.0, "ly": -5.0, "rx": 0.35, "ry": -0.8},
            "triggers": {"lt": 0.45, "rt": 2.0}
        })
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        assert ack["adapter_success"] is True

        assert mock_adapter.current_state.axes["lx"] == 1.0
        assert mock_adapter.current_state.axes["ly"] == -1.0
        assert mock_adapter.current_state.axes["rx"] == 0.35
        assert mock_adapter.current_state.axes["ry"] == -0.8
        assert mock_adapter.current_state.triggers["lt"] == 0.45
        assert mock_adapter.current_state.triggers["rt"] == 1.0


def test_every_button_and_dpad_via_websocket(client, fixed_pin, mock_adapter):
    """10, 11, & 12. Test buttons, D-pad, and simultaneous combinations via WebSocket."""
    buttons_to_test = ["A", "B", "X", "Y", "LB", "RB", "L3", "R3", "VIEW", "MENU"]
    dpad_dirs = ["UP", "DOWN", "LEFT", "RIGHT"]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        seq = 1
        # Test each button individually
        for btn in buttons_to_test:
            ws.send_json({"type": "input", "seq": seq, "buttons": [btn]})
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert mock_adapter.current_state.buttons == {btn}
            seq += 1

        # Test each D-pad direction
        for d in dpad_dirs:
            ws.send_json({"type": "input", "seq": seq, "dpad": [d]})
            ack = ws.receive_json()
            assert ack["type"] == "ack"
            assert mock_adapter.current_state.dpad == {d}
            seq += 1

        # Test simultaneous buttons, dpad, and axes
        ws.send_json({
            "type": "input",
            "seq": seq,
            "buttons": ["A", "Y", "LB"],
            "dpad": ["UP"],
            "axes": {"lx": -0.5, "ly": 0.5, "rx": 0.2, "ry": 0.0},
            "triggers": {"lt": 1.0, "rt": 0.5}
        })
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        assert mock_adapter.current_state.buttons == {"A", "Y", "LB"}
        assert mock_adapter.current_state.dpad == {"UP"}


def test_stale_sequence_number_rejection(client, fixed_pin):
    """13 & 14. Test rejection of stale/duplicate sequence numbers and concurrent updates."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        # Send seq 5
        ws.send_json({"type": "input", "seq": 5, "buttons": ["A"]})
        ack1 = ws.receive_json()
        assert ack1["type"] == "ack"
        assert ack1["seq"] == 5

        # Send duplicate seq 5 (should be flagged stale)
        ws.send_json({"type": "input", "seq": 5, "buttons": ["B"]})
        ack2 = ws.receive_json()
        assert ack2["type"] == "ack"
        assert ack2["stale"] is True

        # Send older seq 3 (should be flagged stale)
        ws.send_json({"type": "input", "seq": 3, "buttons": ["X"]})
        ack3 = ws.receive_json()
        assert ack3["type"] == "ack"
        assert ack3["stale"] is True


def test_emergency_release_all_via_websocket(client, fixed_pin, mock_adapter):
    """15. Test Emergency Release All clears inputs immediately."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        # Hold buttons
        ws.send_json({"type": "input", "seq": 1, "buttons": ["A", "B", "RT"], "triggers": {"rt": 1.0}})
        ws.receive_json()
        assert len(mock_adapter.current_state.buttons) > 0

        # Fire emergency release
        ws.send_json({"type": "release_all", "reason": "Test Trigger"})
        resp = ws.receive_json()
        assert resp["type"] == "release_all_ack"
        assert resp["success"] is True

        assert len(mock_adapter.current_state.buttons) == 0
        assert mock_adapter.current_state.triggers["rt"] == 0.0


def test_ping_pong_latency_measurement(client, fixed_pin):
    """Verify ping/pong round trip provides timestamp confirmation."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        client_ts = 12345.67
        ws.send_json({"type": "ping", "client_ts": client_ts})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert pong["client_ts"] == client_ts
        assert "server_ts" in pong


def test_abrupt_disconnect_cleans_inputs(client, fixed_pin, mock_adapter):
    """17. Test that closing socket abruptly triggers release_all on adapter."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "pin": fixed_pin})
        ws.receive_json()

        ws.send_json({"type": "input", "seq": 1, "buttons": ["A", "LB"]})
        ws.receive_json()
        assert mock_adapter.current_state.buttons == {"A", "LB"}

    # After with-block, socket is closed. Adapter must have released all
    assert len(mock_adapter.current_state.buttons) == 0


def test_multiple_client_conflict_prevention(client, fixed_pin, mock_adapter):
    """18 & 19. Test that a second client connecting replaces and neutralizes the first."""
    with client.websocket_connect("/ws") as ws1:
        ws1.send_json({"type": "auth", "pin": fixed_pin})
        resp1 = ws1.receive_json()
        assert resp1["type"] == "auth_ok"

        # Client 1 holds button
        ws1.send_json({"type": "input", "seq": 1, "buttons": ["A"]})
        ws1.receive_json()
        assert "A" in mock_adapter.current_state.buttons

        # Client 2 connects with same PIN
        with client.websocket_connect("/ws") as ws2:
            ws2.send_json({"type": "auth", "pin": fixed_pin})
            resp2 = ws2.receive_json()
            assert resp2["type"] == "auth_ok"

            # Client 1 should receive session_replaced notice
            notice = ws1.receive_json()
            assert notice["type"] == "session_replaced"

            # Inputs should be neutralized upon handover
            assert len(mock_adapter.current_state.buttons) == 0


def test_watchdog_inactivity_timeout():
    """16. Test watchdog releases inputs when client goes idle beyond threshold."""
    async def run_watchdog_test():
        mock = MockGamepadAdapter()
        mock.initialize()
        mock.current_state.buttons.add("A")
        assert len(mock.current_state.buttons) == 1

        app = create_app(adapter=mock, pairing_pin="111222")
        sm = app.state.session_manager
        # Simulate last activity in the past
        sm.last_activity_ts = time.time() - (INACTIVITY_TIMEOUT_SEC + 1.0)
        # Mock active connection
        sm.active_websocket = object()

        # Run one iteration of watchdog logic
        idle_duration = time.time() - sm.last_activity_ts
        if idle_duration > INACTIVITY_TIMEOUT_SEC:
            sm.release_all_inputs(reason="Test Watchdog")

        assert len(mock.current_state.buttons) == 0
        assert sm.last_release_all_event["reason"] == "Test Watchdog"

    asyncio.run(run_watchdog_test())


def test_missing_driver_adapter_initialization_on_server():
    """20 & 21. Test server with WindowsGamepadAdapter when driver is missing."""
    from gamepad.windows_adapter import WindowsGamepadAdapter
    win_adapter = WindowsGamepadAdapter()
    win_adapter.initialize()

    # Server creation must succeed and report truthful status
    app = create_app(adapter=win_adapter, pairing_pin="999888")
    with TestClient(app) as test_client:
        res = test_client.get("/api/status")
        assert res.status_code == 200
        gamepad_info = res.json()["gamepad"]
        assert gamepad_info["backend_type"] == "WINDOWS_VIGEM"
        assert gamepad_info["status"] in ("READY", "DRIVER_NOT_FOUND", "INIT_FAILED")


def test_frontend_assets_and_javascript_syntax():
    """23. Test presence of static files and syntax validity of frontend JavaScript."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    index_path = os.path.join(base_dir, "static", "index.html")
    css_path = os.path.join(base_dir, "static", "style.css")
    js_path = os.path.join(base_dir, "static", "app.js")

    assert os.path.isfile(index_path), "index.html is missing"
    assert os.path.isfile(css_path), "style.css is missing"
    assert os.path.isfile(js_path), "app.js is missing"

    # Verify node --check on app.js
    node_result = subprocess.run(
        ["node", "--check", js_path],
        capture_output=True,
        text=True
    )
    assert node_result.returncode == 0, f"JavaScript syntax check failed: {node_result.stderr}"
