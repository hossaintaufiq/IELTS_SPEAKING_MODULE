"""The monitoring page: its numbers (worker/monitor.py) and who may open it (MONITOR_KEY)."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

import worker.monitor as mon
import worker.server as server
import worker.session as sess

SECRET_WORDS = "my private story about the rickshaw"       # a candidate's words: must never reach the monitoring page


def write_run(folder, name, **fields):
    record = {"test_id": name.rsplit("_", 1)[-1], "status": "completed", "end_reason": "completed", "latencies_s": [1.0, 2.0],
              "events": [{"type": "transcript", "role": "user", "text": SECRET_WORDS, "t": 1, "at": 1000.0},
                         {"type": "done", "t": 60, "at": 1060.0}], **fields}
    path = folder / f"{name}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def fresh_cache():
    mon._CACHE.clear()


# ---- numbers ------------------------------------------------------------------------------------------
def test_percentiles():
    assert mon.percentile([], 95) is None
    assert mon.percentile([5], 50) == 5
    values = list(range(1, 101))
    assert mon.percentile(values, 50) == 50 and mon.percentile(values, 95) == 95 and mon.percentile(values, 100) == 100
    stats = mon.latency_stats([1.0, 2.0, 5.0])
    assert stats["n"] == 3 and stats["max"] == 5.0 and stats["slow"] == 1 and stats["slow_over_s"] == mon.SLOW_REPLY_S
    assert mon.latency_stats([])["p95"] is None


def test_a_run_summary_names_its_problems():
    good = mon.summarise_run({"test_id": "11", "status": "completed", "latencies_s": [1.0], "events": [{"type": "note", "text": "x", "at": 5.0}]}, "run_a_11")
    assert good["problems"] == [] and good["failed"] is False and good["id"] == "11"
    bad = mon.summarise_run({"test_id": "22", "status": "aborted", "latencies_s": [1.0, 9.0], "mic_seconds": 30, "mic_rms": 0.0005,
                             "events": [{"type": "note", "text": "error in this turn: KeyError", "at": 5.0}, {"type": "done", "at": 65.0}]}, "run_b_22")
    assert bad["failed"] and set(bad["problems"]) == {"aborted", "1 error", "1 slow reply", "silent microphone"}
    assert bad["duration_s"] == 60.0 and bad["errors"] == 1
    old = mon.summarise_run({"events": []}, "run_20261122_071217")           # saved before status existed
    assert old["status"] == "unknown" and old["failed"] is False


def test_recent_runs_lists_a_test_once_skips_broken_files_and_reuses_what_it_read(tmp_path):
    write_run(tmp_path, "run_20261124_100000_111")
    write_run(tmp_path, "run_20261124_100005_111")         # the same test saved a second time when the socket closed
    write_run(tmp_path, "run_20261124_100100_222", status="failed", end_reason="error")
    (tmp_path / "run_20261124_100200_333.json").write_text("{not json", encoding="utf-8")
    runs, delays = mon.recent_runs(tmp_path)
    assert sorted(r["id"] for r in runs) == ["111", "222"] and len(delays) == 4
    assert len(mon._CACHE) == 3                              # the three good files were read once; the broken one is never cached
    assert not any("333" in k for k in mon._CACHE)
    assert mon.recent_runs(tmp_path / "missing") == ([], [])


# ---- failures feed ------------------------------------------------------------------------------------
def test_failure_feed_keeps_warnings_and_errors_only():
    mon.install_failure_log()
    mon.install_failure_log()                                 # twice must not double every line
    mon.FAILURES.rows.clear()
    logging.getLogger("speaking.session").info("fine")
    logging.getLogger("speaking.server").warning("slow thing")
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("speaking.server").exception("test 9 failed")
    rows = mon.recent_failures()
    assert [r["message"].split(" [")[0] for r in rows] == ["test 9 failed", "slow thing"]      # newest first, no INFO
    assert rows[0]["level"] == "ERROR" and "ValueError: boom" in rows[0]["message"]


# ---- live tests ---------------------------------------------------------------------------------------
def test_live_rows():
    async def send(e):
        pass

    s = sess.ExamSession(send=send, seed=3)
    s.external_user_id, s.device, s.started, s.status = "student-7", "Laptop", True, "running"
    s.log = [{"type": "latency", "seconds": 1.5}, {"type": "latency", "seconds": 8.0}, {"type": "note", "text": "error in this turn: X"}]
    [row] = mon.live_rows({s.test_id: s})
    assert row["user"] == "student-7" and row["last_reply_s"] == 8.0 and row["slow_replies"] == 1 and row["errors"] == 1
    assert SECRET_WORDS not in json.dumps(row)


# ---- who may open it ----------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MOCK", False)
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    monkeypatch.setattr(server, "SESSIONS", {})
    monkeypatch.setitem(server.READY, "done", True)
    monkeypatch.setitem(server.READY, "error", "")
    monkeypatch.delenv("MONITOR_KEY", raising=False)
    return TestClient(server.app)


def test_closed_without_a_key_but_open_in_mock_mode(client, monkeypatch):
    for path in ("/monitor", "/api/monitor"):
        r = client.get(path)
        assert r.status_code == 503 and "MONITOR_KEY" in r.text
    monkeypatch.setattr(server, "MOCK", True)
    assert client.get("/api/monitor").status_code == 200


def test_key_by_header_or_by_link_then_cookie(client, monkeypatch):
    monkeypatch.setenv("MONITOR_KEY", "s3cret")
    assert client.get("/monitor").status_code == 401 and client.get("/api/monitor").status_code == 401
    assert client.get("/api/monitor", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/monitor", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/monitor?key=s3cret").status_code == 401            # a key in the URL is only for opening the page once
    page = client.get("/monitor?key=s3cret")
    assert page.status_code == 200 and "Service monitor" in page.text and "monitor=s3cret" in page.headers["set-cookie"]
    assert "httponly" in page.headers["set-cookie"].lower()
    assert client.get("/api/monitor").status_code == 200                       # the cookie now opens the data too


def test_the_monitor_is_not_behind_the_browser_access_code(client, monkeypatch):
    monkeypatch.setenv("MONITOR_KEY", "s3cret")
    monkeypatch.setitem(server.ACCESS, "code", "browser-code")
    assert client.get("/api/monitor", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/").status_code == 401


def test_the_snapshot_and_no_private_words(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_KEY", "s3cret")
    write_run(tmp_path, "run_20261124_100000_111")
    write_run(tmp_path, "run_20261124_100100_222", status="aborted", end_reason="aborted")
    mon.FAILURES.rows.clear()
    logging.getLogger("speaking.server").warning("disk almost full")
    body = client.get("/api/monitor", headers={"Authorization": "Bearer s3cret"}).json()
    assert body["server"]["ready"] is True and body["server"]["max_tests"] == server.MAX_SESSIONS and body["server"]["version"] == "1"
    assert body["counts"] == {"completed": 1, "aborted": 1, "failed": 0, "unknown": 0}
    assert {r["id"]: r["failed"] for r in body["recent"]} == {"111": False, "222": True}
    assert body["latency"]["n"] == 4 and body["failures"][0]["message"] == "disk almost full"
    assert SECRET_WORDS not in json.dumps(body)                                # ids, phases and timings only: never what anyone said


def test_a_failed_model_load_shows_on_the_page_data(client, monkeypatch):
    monkeypatch.setenv("MONITOR_KEY", "s3cret")
    monkeypatch.setitem(server.READY, "error", "RuntimeError: no gpu")
    body = client.get("/api/monitor", headers={"Authorization": "Bearer s3cret"}).json()
    assert body["server"]["ready"] is False and "no gpu" in body["server"]["models_error"]
