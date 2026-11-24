"""Capacity work: the live-caption limits (worker/caption_budget.py) and the load-test tool (eval/load_test.py)."""
import asyncio
import json
import logging
import socket
import sys
import threading
import time
import types
import wave

import pytest
from fastapi.testclient import TestClient

import eval.load_test as lt
import worker.caption_budget as caps
import worker.server as server
import worker.session as sess


# ---- live caption limits ------------------------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [("on", True), ("", True), ("yes", True), ("off", False), ("OFF", False), ("0", False), ("false", False), (" no ", False)])
def test_captions_switch(monkeypatch, value, expected):
    monkeypatch.setenv("CAPTIONS", value)
    assert caps.enabled() is expected


def test_caption_defaults_are_lighter_than_before_and_have_floors(monkeypatch):
    for name in ("CAPTIONS", "CAPTION_WINDOW_S", "CAPTION_INTERVAL_S", "CAPTION_MAX_CONCURRENT"):
        monkeypatch.delenv(name, raising=False)
    assert caps.window_s() == 8 < 15 and caps.interval_s() == 1.2 > 0.9 and caps.CaptionBudget().max_concurrent == 2
    monkeypatch.setenv("CAPTION_WINDOW_S", "0")
    monkeypatch.setenv("CAPTION_INTERVAL_S", "0")
    monkeypatch.setenv("CAPTION_MAX_CONCURRENT", "0")
    assert caps.window_s() == 1.0 and caps.interval_s() == 0.3 and caps.CaptionBudget().max_concurrent == 1     # never zero: no spinning, no deadlock


def test_budget_lets_only_a_few_decode_at_once_and_counts_skips(caplog):
    b = caps.CaptionBudget(max_concurrent=2, warn_every=3)
    assert b.try_acquire() and b.try_acquire()
    with caplog.at_level(logging.WARNING, logger="speaking.captions"):
        assert [b.try_acquire() for _ in range(3)] == [False, False, False]
    assert b.skipped == 3 and b.in_flight == 2
    assert len([r for r in caplog.records if "skipped" in r.getMessage()]) == 1            # one warning per 3 skips, not one per skip
    b.release()
    assert b.try_acquire() and b.in_flight == 2 and b.decoded == 1
    b.release(), b.release(), b.release()
    assert b.in_flight == 0 and b.decoded == 4                                             # releasing too often cannot go below zero
    assert b.stats()["skipped"] == 3 and b.stats()["max_concurrent"] == 2


def test_the_monitor_data_carries_the_caption_figures(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MOCK", True)
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    monkeypatch.setattr(server, "SESSIONS", {})
    monkeypatch.setenv("MONITOR_KEY", "k")
    monkeypatch.setattr(caps, "BUDGET", caps.CaptionBudget(max_concurrent=3))
    monkeypatch.setattr(server.caption_budget, "BUDGET", caps.BUDGET)
    body = TestClient(server.app).get("/api/monitor", headers={"Authorization": "Bearer k"}).json()
    assert body["captions"]["max_concurrent"] == 3 and body["captions"]["enabled"] is True and body["captions"]["skipped"] == 0


# ---- load-test numbers --------------------------------------------------------------------------------
def test_percentile_and_stats():
    assert lt.percentile([], 95) is None and lt.percentile([4], 50) == 4
    assert lt.percentile(list(range(1, 101)), 95) == 95
    assert lt.stats([1, 2, 3]) == {"n": 3, "p50": 2, "p95": 3, "max": 3}


def result(delays=(2.0,), **kw):
    return {"n": 0, "delays": list(delays), "server_delays": [1.0], "no_reply": 0, "errors": [], "first_audio_s": 1.5, "ended": "completed", **kw}


def test_summary_leaves_refused_and_failed_sessions_out_of_the_delays():
    s = lt.summarise([result([2.0, 3.0]), result([4.0]), {"n": 2, "refused": True, "delays": [], "server_delays": [], "no_reply": 0, "errors": []},
                      {"n": 3, "failed": "connect: boom", "delays": [], "server_delays": [], "no_reply": 0, "errors": []}])
    assert s["sessions"] == 4 and s["ran"] == 2 and s["refused"] == 1 and s["failed"] == ["connect: boom"]
    assert s["reply_delay"]["n"] == 3 and s["reply_delay"]["max"] == 4.0 and s["ended"] == {"completed": 2}


@pytest.mark.parametrize("delays,baseline,extra,limit,passed", [
    ([2.0, 2.4], 2.0, 1.0, None, True),          # a little slower than one session: fine
    ([2.0, 3.5], 2.0, 1.0, None, False),         # more than 1 s above the baseline
    ([2.0, 3.5], None, 1.0, 3.0, False),         # over an absolute limit
    ([2.0, 2.4], None, 1.0, None, True),         # no yardstick given: nothing to fail on
])
def test_verdict_on_delay(delays, baseline, extra, limit, passed):
    ok, why = lt.verdict(lt.summarise([result(delays)]), baseline, extra, limit)
    assert ok is passed and bool(why) is not passed


def test_verdict_fails_on_refusals_errors_missing_replies_and_no_data():
    base = result()
    assert not lt.verdict(lt.summarise([base, {"n": 1, "refused": True, "delays": [], "server_delays": [], "no_reply": 0, "errors": []}]), None, 1, None)[0]
    assert not lt.verdict(lt.summarise([result(errors=["internal: KeyError"])]), None, 1, None)[0]
    assert "no reply" in " ".join(lt.verdict(lt.summarise([result(no_reply=2)]), None, 1, None)[1])
    assert "no reply delay was measured" in lt.verdict(lt.summarise([result(delays=[])]), None, 1, None)[1]


def test_wav_must_be_16k_mono(tmp_path):
    def write(name, rate, channels):
        path = tmp_path / name
        with wave.open(str(path), "wb") as w:
            w.setnchannels(channels), w.setsampwidth(2), w.setframerate(rate), w.writeframes(b"\x01\x00" * 100 * channels)
        return str(path)

    assert lt.read_wav(write("ok.wav", 16000, 1)) == [1] * 100
    for bad in (write("rate.wav", 44100, 1), write("stereo.wav", 16000, 2)):
        with pytest.raises(SystemExit) as stop:
            lt.read_wav(bad)
        assert "16000 Hz mono" in str(stop.value)


def test_bank_hands_out_different_utterances():
    bank = lt.Bank(["a", "b", "c"], ["LONG"])
    assert bank.talk() == "LONG"
    assert len({bank.next(offset=o) for o in range(3)}) > 1 and {bank.next() for _ in range(6)} == {"a", "b", "c"}


# ---- the tool against a real (mock) server ------------------------------------------------------------
@pytest.fixture
def mock_server(tmp_path, monkeypatch):
    """The real app over a real socket, mock examiner (it greets and answers control messages; it cannot answer speech)."""
    try:
        import pipecat.frames.frames  # noqa: F401
    except ModuleNotFoundError:
        frames = types.ModuleType("pipecat.frames.frames")
        frames.TTSSpeakFrame = type("TTSSpeakFrame", (), {"__init__": lambda self, text: None})
        for name, mod in (("pipecat", types.ModuleType("pipecat")), ("pipecat.frames", types.ModuleType("pipecat.frames")), ("pipecat.frames.frames", frames)):
            monkeypatch.setitem(sys.modules, name, mod)
    import uvicorn

    monkeypatch.setattr(server, "MOCK", True)
    monkeypatch.setattr(server, "SESSIONS", {})
    monkeypatch.setattr(server, "MAX_SESSIONS", 2)
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    monkeypatch.setitem(server.ACCESS, "code", "")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started
    yield f"ws://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)


def test_the_tool_runs_sessions_and_sees_the_server_refuse_the_extra_ones(mock_server, tmp_path):
    cfg = lt.parse(["--base", mock_server, "--sessions", "4", "--turns", "1", "--ramp-s", "0.3", "--audio", "fake",
                    "--reply-timeout", "1.5", "--report", str(tmp_path / "r.json")])
    report = asyncio.run(lt.run(cfg))
    s = report["summary"]
    assert s["sessions"] == 4 and s["ran"] == 2 and s["refused"] == 2                  # the server allows 2 at once
    assert s["first_audio"]["n"] == 2                                                  # both that ran heard the greeting
    assert s["no_reply"] == 2 and s["turns"] == 2                                      # the mock examiner cannot answer speech
    assert s["ended"] == {"ended_by_candidate": 2}                                   # the tool ends each test itself after its turns
    assert report["passed"] is False and any("refused" in w for w in report["why_not"])


def test_the_tool_passes_when_there_is_room(mock_server, monkeypatch):
    monkeypatch.setattr(server, "MAX_SESSIONS", 6)
    cfg = lt.parse(["--base", mock_server, "--sessions", "2", "--turns", "0", "--ramp-s", "0.2", "--audio", "fake"])
    report = asyncio.run(lt.run(cfg))
    assert report["summary"]["ran"] == 2 and report["summary"]["refused"] == 0 and report["summary"]["no_reply"] == 0
    assert "no reply delay was measured" in report["why_not"]            # nothing was asked, so it cannot claim a pass on delays
