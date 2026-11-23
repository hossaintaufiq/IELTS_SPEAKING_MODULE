"""The run log in the page: saved runs are listed and readable, and every examiner line says where it came from."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import worker.server as server
import worker.session as sess
from worker.session import ExamSession
from tests.test_listening import FakeTask, to_part1, llm_ok


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    (tmp_path / "run_20261122_071217.json").write_text(json.dumps({"events": [{"type": "done", "t": 1}]}), encoding="utf-8")
    return tmp_path


def test_saved_runs_are_listed_and_can_be_opened(runs):
    c = TestClient(server.app)
    listing = c.get("/api/runs").json()
    assert [r["name"] for r in listing] == ["run_20261122_071217"]
    assert c.get("/api/runs/run_20261122_071217").json()["events"][0]["type"] == "done"


@pytest.mark.parametrize("name", ["../secret", "..%2Fsecret", "run_1", "run_20261122_071217.wav", "x"])
def test_run_names_cannot_reach_other_files(runs, name):
    (runs.parent / "secret.json").write_text("{}", encoding="utf-8")
    assert TestClient(server.app).get(f"/api/runs/{name}").status_code == 404


def test_every_examiner_line_carries_its_origin():
    events = []

    async def go():
        async def send(e):
            events.append(e)
        s = ExamSession(send, seed=3, llm=llm_ok, hour=9)
        s.test_mode()
        s.task = FakeTask()
        await to_part1(s)
        await s.on_candidate_turn("I live in a small town near the river and I have lived there all my life.")
        await s.settle()

    asyncio.run(go())
    lines = [e for e in events if e["type"] == "transcript" and e["role"] == "examiner"]
    assert lines and all("origin" in e for e in lines)
    assert lines[0]["origin"] == "script"                       # the greeting
    assert lines[-1]["origin"].split(":")[0] in ("ai", "script", "bank")


def test_server_logs_are_tailed_cleaned_and_filterable(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "LOG_DIR", tmp_path)
    (tmp_path / "web.log").write_text("\n".join([
        "\x1b[32m2026-11-22 INFO started\x1b[0m",
        "2026-11-22 | DEBUG    | pipecat: noisy line",
        "2026-11-22 ERROR the LLM did not answer",
    ]), encoding="utf-8")
    c = TestClient(server.app)
    r = c.get("/api/serverlog/web").json()
    assert r["exists"] and r["lines"] == ["2026-11-22 INFO started", "2026-11-22 ERROR the LLM did not answer"]    # colours and debug removed
    assert c.get("/api/serverlog/web", params={"hide_debug": "false"}).json()["lines"][1].endswith("noisy line")
    assert c.get("/api/serverlog/web", params={"q": "error"}).json()["lines"] == ["2026-11-22 ERROR the LLM did not answer"]
    assert c.get("/api/serverlog/vllm").json()["exists"] is False                         # a missing log is reported, not an error
    assert c.get("/api/serverlog/passwd").status_code == 404                              # only the three known logs can be read
    assert c.get("/api/serverlog/..%2Fweb").status_code == 404


def test_logs_page_is_served_and_the_main_page_links_to_it():
    c = TestClient(server.app)
    page = c.get("/logs")
    assert page.status_code == 200 and "Run log" in page.text and "Server log" in page.text
    for asset in ("logs.js", "logs.css"):
        assert c.get(f"/static/{asset}").status_code == 200
    main = c.get("/").text
    assert 'href="/logs"' in main and 'target="speaking-logs"' in main       # opens in its own window
    assert "runlog" not in main and "serverlog" not in main                  # the log views no longer crowd the test window


def test_live_endpoint_shows_the_current_or_last_test(monkeypatch):
    monkeypatch.setattr(server, "LIVE", {"session": None})
    c = TestClient(server.app)
    assert c.get("/api/live").json() == {"active": False, "started": False, "events": [], "sessions": []}

    async def go():
        async def send(e):
            pass
        s = ExamSession(send, seed=3, llm=llm_ok, hour=9)
        s.test_mode()
        s.task = FakeTask()
        await to_part1(s)
        return s

    s = asyncio.run(go())
    server.LIVE["session"] = s
    d = c.get("/api/live").json()
    assert d["active"] is True and d["phase"] == "part1"
    assert any(e["type"] == "transcript" and e["role"] == "examiner" and "origin" in e for e in d["events"])


# ---- several devices at the same time ---------------------------------------------------------------------
def _started_session(device):
    async def go():
        async def send(e):
            pass
        s = ExamSession(send, seed=None, llm=llm_ok, hour=9)
        s.test_mode()
        s.task = FakeTask()
        s.device = device
        await to_part1(s)
        return s
    return asyncio.run(go())


def test_every_connected_device_can_be_followed_alone_or_all_together(monkeypatch):
    a, b = _started_session("Laptop"), _started_session("Phone")
    monkeypatch.setattr(server, "SESSIONS", {a.test_id: a, b.test_id: b})
    monkeypatch.setattr(server, "LIVE", {"session": b})
    c = TestClient(server.app)
    listing = c.get("/api/live").json()["sessions"]
    assert {x["device"] for x in listing} == {"Laptop", "Phone"} and all(x["active"] for x in listing)
    assert c.get(f"/api/live?id={a.test_id}").json()["device"] == "Laptop"
    merged = c.get("/api/live?id=all").json()["events"]
    assert {e["dev"] for e in merged} == {"Laptop", "Phone"}
    assert [e["at"] for e in merged] == sorted(e["at"] for e in merged)          # one timeline, oldest first
    assert c.get("/health").json()["tests_running"] == 2


def test_two_tests_ending_in_the_same_second_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    a, b = _started_session("Laptop"), _started_session("Phone")
    pa, pb = a.save(), b.save()
    assert pa != pb and pa.exists() and pb.exists()
    monkeypatch.setattr(server.sess, "RUNS", tmp_path)
    names = [r["name"] for r in TestClient(server.app).get("/api/runs").json()]
    assert len(names) == 2 and TestClient(server.app).get(f"/api/runs/{names[0]}").status_code == 200
    assert {r["device"] for r in TestClient(server.app).get("/api/runs").json()} == {"Laptop", "Phone"}


def test_the_server_turns_away_a_test_when_it_is_full(monkeypatch):
    s = _started_session("Laptop")
    monkeypatch.setattr(server, "SESSIONS", {s.test_id: s})
    monkeypatch.setattr(server, "MAX_SESSIONS", 1)
    monkeypatch.setattr(server, "MOCK", True)
    with TestClient(server.app).websocket_connect("/ws?device=Tablet") as ws:
        with pytest.raises(Exception):
            ws.receive_text()                                     # closed at once with "Server is full"
