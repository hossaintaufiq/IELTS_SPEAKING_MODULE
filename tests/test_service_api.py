"""The service API of docs/API_CONTRACT_V1.md: API key, /v1/session, results, done.reason, health.

Mock mode (no models). examiner speech is queued through pipecat's TTSSpeakFrame; where pipecat is not installed (a dev PC) a
stand-in class is used for that one import, so these tests run anywhere.
"""
import asyncio
import json
import sys
import types

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import worker.server as server
import worker.service_api as svc
import worker.session as sess

KEY = "test-key-1"
AUTH = {"Authorization": f"Bearer {KEY}"}
URL = "/v1/session?external_user_id=student-42&hour=9"


@pytest.fixture(autouse=True)
def pipecat_stand_in(monkeypatch):
    try:
        import pipecat.frames.frames  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    frames = types.ModuleType("pipecat.frames.frames")
    frames.TTSSpeakFrame = type("TTSSpeakFrame", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    for name, mod in (("pipecat", types.ModuleType("pipecat")), ("pipecat.frames", types.ModuleType("pipecat.frames")),
                      ("pipecat.frames.frames", frames)):
        monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MOCK", True)
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    monkeypatch.setattr(server, "SESSIONS", {})
    monkeypatch.setenv("SERVICE_API_KEYS", KEY)
    return TestClient(server.app)


def read_until(ws, kind):
    seen = []
    while True:
        m = ws.receive()
        if m.get("type") == "websocket.close":
            raise AssertionError(f"socket closed before {kind!r}: {seen}")
        event = json.loads(m["text"]) if m.get("text") else {"type": "audio", "bytes": len(m["bytes"])}
        seen.append(event)
        if event["type"] == kind:
            return seen


# ---- API key ------------------------------------------------------------------------------------------
def test_check_bearer(monkeypatch):
    monkeypatch.setenv("SERVICE_API_KEYS", "alpha, beta")
    assert svc.check_bearer("Bearer alpha") == "ok"
    assert svc.check_bearer("bearer beta") == "ok"            # the scheme is not case sensitive, and every listed key works
    for bad in (None, "", "Bearer", "Bearer wrong", "alpha", "Basic alpha", "Bearer alph"):
        assert svc.check_bearer(bad) == "bad"
    monkeypatch.delenv("SERVICE_API_KEYS")
    assert svc.check_bearer("Bearer alpha") == "no_keys"      # a service started without keys is closed, not open


def test_http_routes_need_the_key(client):
    for path in ("/v1/tests/123", "/v1/tests/123/result", "/v1/tests/123/audio"):
        r = client.get(path)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized" and r.headers["www-authenticate"] == "Bearer"
        assert client.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_no_keys_configured_refuses_everything(client, monkeypatch):
    monkeypatch.delenv("SERVICE_API_KEYS")
    r = client.get("/v1/tests/123", headers=AUTH)
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_keys_configured"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(URL, headers=AUTH):
            pass


@pytest.mark.parametrize("url,headers", [
    ("/v1/session?external_user_id=s1", {}),                                # no key
    ("/v1/session?external_user_id=s1", {"Authorization": "Bearer nope"}),  # wrong key
    ("/v1/session", AUTH),                                                  # no external_user_id
    ("/v1/session?external_user_id=%20%20", AUTH),                          # blank external_user_id
    ("/v1/session?external_user_id=s1&hour=24", AUTH),                      # hour out of range
    ("/v1/session?external_user_id=s1&hour=abc", AUTH),
])
def test_session_refused_before_it_opens(client, url, headers):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url, headers=headers):
            pass
    assert server.SESSIONS == {}


def test_v1_is_not_behind_the_browser_access_code(client, monkeypatch):
    monkeypatch.setitem(server.ACCESS, "code", "browser-code")
    assert client.get("/").status_code == 401                              # the browser pages still need the code
    assert client.get("/v1/tests/1", headers=AUTH).status_code == 404       # the API only needs its own key


# ---- health, capacity ---------------------------------------------------------------------------------
def test_health_reports_ready_and_version(client, monkeypatch):
    body = client.get("/health").json()
    assert body["ok"] and body["ready"] and body["version"] == "1" and body["max_tests"] == server.MAX_SESSIONS
    monkeypatch.setattr(server, "MOCK", False)
    monkeypatch.setitem(server.READY, "done", False)
    assert client.get("/health").json()["ready"] is False                   # still loading
    monkeypatch.setitem(server.READY, "done", True)
    monkeypatch.setitem(server.READY, "error", "RuntimeError: no gpu")
    body = client.get("/health").json()
    assert body["ready"] is False and "no gpu" in body["models_error"]      # a failed start is not "ready"


def test_busy_and_starting_close_with_1013(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_SESSIONS", 0)
    with client.websocket_connect(URL, headers=AUTH) as ws:
        with pytest.raises(WebSocketDisconnect) as stop:
            ws.receive_json()
    assert stop.value.code == 1013
    monkeypatch.setattr(server, "MAX_SESSIONS", 6)
    monkeypatch.setattr(server, "MOCK", False)
    monkeypatch.setitem(server.READY, "done", False)
    with client.websocket_connect(URL, headers=AUTH) as ws:
        with pytest.raises(WebSocketDisconnect) as stop:
            ws.receive_json()
    assert stop.value.code == 1013 and server.SESSIONS == {}


# ---- one whole test, then its results -----------------------------------------------------------------
def test_a_test_from_start_to_result(client):
    with client.websocket_connect(URL, headers=AUTH) as ws:
        first = json.loads(ws.receive()["text"])
        assert first["type"] == "test" and first["id"].isdigit()           # the very first message is the test id
        test_id = first["id"]
        ws.send_text(json.dumps({"action": "start"}))
        read_until(ws, "transcript")                                        # the greeting
        assert client.get(f"/v1/tests/{test_id}", headers=AUTH).json()["status"] == "running"
        assert client.get(f"/v1/tests/{test_id}/result", headers=AUTH).json()["error"]["code"] == "not_finished"
        ws.send_bytes(b"\x10\x00" * 1600)                                   # some microphone audio
        ws.send_text(json.dumps({"action": "end"}))
        events = read_until(ws, "done")
        assert events[-1] == {k: events[-1][k] for k in ("type", "reason", "t", "at")} and events[-1]["reason"] == "ended_by_candidate"

    summary = client.get(f"/v1/tests/{test_id}", headers=AUTH).json()
    assert summary["id"] == test_id and summary["external_user_id"] == "student-42"
    assert summary["status"] == "completed" and summary["end_reason"] == "ended_by_candidate"
    assert summary["ended_at"] >= summary["started_at"] > 0

    result = client.get(f"/v1/tests/{test_id}/result", headers=AUTH).json()
    assert result["test_id"] == test_id and any(e["type"] == "done" for e in result["events"])
    assert any(e["type"] == "transcript" and e["role"] == "examiner" for e in result["events"])

    audio = client.get(f"/v1/tests/{test_id}/audio", headers=AUTH)
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav" and audio.content[:4] == b"RIFF"


def test_dropping_the_connection_saves_an_aborted_test(client):
    with client.websocket_connect(URL, headers=AUTH) as ws:
        test_id = json.loads(ws.receive()["text"])["id"]
        ws.send_text(json.dumps({"action": "start"}))
        read_until(ws, "transcript")
    summary = client.get(f"/v1/tests/{test_id}", headers=AUTH).json()
    assert summary["status"] == "aborted" and summary["end_reason"] == "aborted"


def test_unknown_or_unsafe_ids_are_not_found(client):
    for bad in ("12345678", "abc", "1" * 40, "..%2F..%2Fsecret"):
        for tail in ("", "/result", "/audio"):
            assert client.get(f"/v1/tests/{bad}{tail}", headers=AUTH).status_code == 404


# ---- done.reason --------------------------------------------------------------------------------------
class Task:
    async def queue_frames(self, frames):
        pass


def finished(reason=None, preset=""):
    events = []

    async def send(e):
        events.append(e)

    async def go():
        s = sess.ExamSession(send=send, seed=1)
        s.task, s.started, s.status, s.end_reason = Task(), True, "running", preset
        await (s.close(reason=reason) if reason else s.close())
        return s

    return asyncio.run(go()), events


@pytest.mark.parametrize("reason", ["off_topic", "no_response", "skipped_to_end", "ended_by_candidate"])
def test_done_carries_the_reason(reason, tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    s, events = finished(reason)
    assert [e for e in events if e["type"] == "done"][0]["reason"] == reason
    assert s.status == "completed"


def test_a_normal_ending_is_completed_and_the_first_reason_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    assert [e for e in finished()[1] if e["type"] == "done"][0]["reason"] == "completed"
    assert [e for e in finished("no_response", preset="off_topic")[1] if e["type"] == "done"][0]["reason"] == "off_topic"


def test_a_finished_test_stays_completed_when_the_socket_then_drops(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    s, _ = finished("completed")
    s.abort()
    assert s.status == "completed" and s.end_reason == "completed"
