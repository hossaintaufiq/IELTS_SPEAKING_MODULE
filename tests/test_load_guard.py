"""Overload safety (worker/load_guard.py): refuse a new test before the GPU is in trouble; give memory back when it is not returned."""
import asyncio
import subprocess

import pytest
from fastapi.testclient import TestClient

import worker.load_guard as lg
import worker.server as server
import worker.session as sess


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def guard(clock, monkeypatch):
    for name in ("SLOW_P95_S", "SLOW_CLEAR_P95_S", "REPLY_WINDOW_S", "REPLY_MIN_SAMPLES", "GPU_MIN_FREE_MB", "RECYCLE_ON_LEAK", "BASELINE_IDLE_S",
                 "CLEANUP_IDLE_S", "RECYCLE_IDLE_S", "RECYCLE_EXTRA_MB", "SAFE_MAX_SESSIONS", "ALLOW_UNSAFE_MAX_SESSIONS"):
        monkeypatch.delenv(name, raising=False)
    return lg.LoadGuard(clock=clock)


def feed(guard, clock, seconds, times=10, gap=1.0):
    for _ in range(times):
        guard.record_delay(seconds)
        clock.now += gap


# ---- the ceiling on tests ---------------------------------------------------------------------------------
def test_max_sessions_is_kept_at_the_safe_ceiling(monkeypatch, caplog):
    monkeypatch.delenv("ALLOW_UNSAFE_MAX_SESSIONS", raising=False)
    monkeypatch.delenv("SAFE_MAX_SESSIONS", raising=False)
    assert lg.safe_max_sessions(9) == 9 and lg.safe_max_sessions(20) == 20
    with caplog.at_level("WARNING", logger="speaking.load"):
        assert lg.safe_max_sessions(200) == 20
    assert "above the safe ceiling" in caplog.text
    monkeypatch.setenv("SAFE_MAX_SESSIONS", "12")
    assert lg.safe_max_sessions(15) == 12
    monkeypatch.setenv("ALLOW_UNSAFE_MAX_SESSIONS", "1")
    assert lg.safe_max_sessions(200) == 200                         # the load test looks for the breaking point on purpose


# ---- admission --------------------------------------------------------------------------------------------
def test_a_quiet_service_takes_tests_until_it_is_full(guard):
    assert guard.admit(0, 9).ok and guard.admit(8, 9).ok
    d = guard.admit(9, 9)
    assert not d.ok and d.reason == "full" and "Server is full (9 tests running)" == d.message


def test_slow_replies_close_the_door_and_recovery_opens_it(guard, clock):
    feed(guard, clock, 5.0)                                         # the measured single-test level (about 5 s): fine
    assert guard.admit(3, 9).ok
    feed(guard, clock, 13.0, times=12)                              # the measured 29-test level (p95 13 s)
    d = guard.admit(3, 9)
    assert not d.ok and d.reason == "slow" and "busy" in d.message
    feed(guard, clock, 9.0, times=15)                               # better, but not below the clear level yet: stays closed (no flapping)
    assert not guard.admit(3, 9).ok
    clock.now += 61                                                 # the slow replies age out of the window ...
    assert guard.admit(3, 9).ok                                     # ... and with too few replies to judge, the door opens


def test_a_few_slow_replies_are_not_enough_to_judge(guard, clock):
    feed(guard, clock, 30.0, times=5)                               # one candidate who paused a lot: below REPLY_MIN_SAMPLES
    assert guard.admit(1, 9).ok


def test_the_slow_level_is_settable(guard, clock, monkeypatch):
    monkeypatch.setenv("SLOW_P95_S", "6")
    monkeypatch.setenv("SLOW_CLEAR_P95_S", "4")
    feed(guard, clock, 7.0)
    assert guard.admit(1, 9).reason == "slow"


def test_low_gpu_memory_closes_the_door(guard):
    guard.update_gpu((22_000, 24_576))                              # 2.5 GB free
    assert guard.admit(5, 9).ok
    guard.update_gpu((23_600, 24_576))                              # 0.9 GB free: the 29-test state
    d = guard.admit(5, 9)
    assert not d.ok and d.reason == "gpu_memory"
    guard.update_gpu((19_000, 24_576))
    assert guard.admit(5, 9).ok


def test_an_old_or_missing_gpu_reading_never_blocks(guard, clock):
    assert guard.admit(0, 9).ok                                     # no GPU reading at all (a dev PC, or nvidia-smi is not there)
    guard.update_gpu((24_000, 24_576))
    clock.now += lg.GPU_READING_MAX_AGE_S + 1
    assert guard.admit(0, 9).ok                                     # a reading the watcher stopped refreshing is not trusted


def test_a_refusal_is_counted_but_asking_is_not(guard):
    guard.admit(9, 9)
    guard.admit(9, 9)
    guard.accepting(9, 9)
    assert guard.stats()["refused"] == {"full": 2}


def test_running_tests_are_never_touched(guard, clock):
    feed(guard, clock, 20.0, times=30)
    guard.update_gpu((24_500, 24_576))
    assert not guard.admit(4, 9).ok                                 # only the next test is refused; admit() has no way to stop one that runs


# ---- the nvidia-smi reading -------------------------------------------------------------------------------
def fake_run(output=None, error=None):
    def run(cmd, **kw):
        if error:
            raise error
        return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")
    return run


@pytest.mark.parametrize("output,expected", [("17912, 24576\n", (17912, 24576)), ("100, 200\n300, 400\n", (100, 200)), ("1.0, 2.0\n", (1, 2))])
def test_reading_the_gpu(monkeypatch, output, expected):
    monkeypatch.setattr(lg.subprocess, "run", fake_run(output))
    assert lg.read_gpu_memory() == expected


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("nvidia-smi", 5), subprocess.CalledProcessError(9, "nvidia-smi")])
def test_no_gpu_or_a_silent_nvidia_smi_gives_none(monkeypatch, error):
    monkeypatch.setattr(lg.subprocess, "run", fake_run(error=error))
    assert lg.read_gpu_memory() is None


@pytest.mark.parametrize("output", ["", "garbage", "5, 0\n", "x, y\n"])
def test_nonsense_from_nvidia_smi_gives_none(monkeypatch, output):
    monkeypatch.setattr(lg.subprocess, "run", fake_run(output))
    assert lg.read_gpu_memory() is None


# ---- memory that is not given back -------------------------------------------------------------------------
def idle_run(guard, clock, readings, *, recycle=True, cleanup=None, ready=True):
    """Step the watcher through (seconds_after_previous, running, used_mb) and return what it said each time."""
    said = []
    for gap, running, used in readings:
        clock.now += gap
        said.append(guard.watch_step(running, (used, 24_576), ready=ready, recycle=recycle, cleanup=cleanup or (lambda: None)))
    return said


def test_baseline_cleanup_then_restart_only_when_idle_and_still_high(guard, clock):
    cleaned = []
    steps = [(0, 0, 17_700),        # idle starts
             (31, 0, 17_700),       # 31 s idle: the baseline is taken (17.7 GB)
             (1, 3, 19_000),        # tests run
             (1, 29, 23_600),       # the overload
             (1, 0, 23_000),        # all finished; memory stays high (the measured problem)
             (21, 0, 23_000),       # 21 s idle: the cleanup is tried
             (5, 0, 23_000),        # judged after the cleanup: but not idle long enough yet
             (40, 0, 23_000)]       # 66 s idle, still 5.3 GB above the baseline: restart
    said = idle_run(guard, clock, steps, cleanup=lambda: cleaned.append(1))
    assert guard.baseline_mb == 17_700 and cleaned == [1]
    assert said[:-1] == [None] * 7 and said[-1] == "recycle"
    d = guard.admit(0, 9)
    assert not d.ok and d.reason == "restarting"                    # from now on no new test is taken


def test_memory_given_back_by_the_cleanup_means_no_restart(guard, clock):
    steps = [(0, 0, 17_700), (31, 0, 17_700), (1, 5, 22_000), (1, 0, 22_000), (21, 0, 22_000), (1, 0, 18_000), (70, 0, 18_000)]
    assert set(idle_run(guard, clock, steps)) == {None}
    assert not guard.restarting


def test_normal_growth_after_a_busy_hour_is_not_a_leak(guard, clock):
    steps = [(0, 0, 17_700), (31, 0, 17_700), (1, 20, 20_200), (1, 0, 20_200), (21, 0, 20_200), (100, 0, 20_200)]     # +2.5 GB, as measured at 26 tests
    assert set(idle_run(guard, clock, steps)) == {None}


def test_a_restart_is_never_decided_while_a_test_runs(guard, clock):
    steps = [(0, 0, 17_700), (31, 0, 17_700), (1, 1, 23_900), (500, 1, 23_900), (500, 2, 23_900)]
    assert set(idle_run(guard, clock, steps)) == {None}


def test_a_restart_needs_to_be_switched_on(guard, clock, monkeypatch):
    steps = [(0, 0, 17_700), (31, 0, 17_700), (1, 5, 23_000), (1, 0, 23_000), (21, 0, 23_000), (70, 0, 23_000)]
    assert set(idle_run(guard, clock, steps, recycle=None)) == {None}          # RECYCLE_ON_LEAK is not set
    monkeypatch.setenv("RECYCLE_ON_LEAK", "1")
    assert guard.watch_step(0, (23_000, 24_576), ready=True, cleanup=lambda: None) == "recycle"


def test_nothing_is_decided_before_the_models_are_loaded_or_without_a_gpu(guard, clock):
    assert set(idle_run(guard, clock, [(0, 0, 9_000), (100, 0, 9_000)], ready=False)) == {None} and guard.baseline_mb is None
    assert guard.watch_step(0, None, ready=True) is None


def test_the_cleanup_hands_back_python_memory(monkeypatch):
    calls = []
    fake_torch = type("T", (), {"cuda": type("C", (), {"is_available": staticmethod(lambda: True), "empty_cache": staticmethod(lambda: calls.append("empty"))})})
    monkeypatch.setitem(lg.sys.modules, "torch", fake_torch)
    lg.gpu_cleanup()
    assert calls == ["empty"]
    monkeypatch.delitem(lg.sys.modules, "torch")
    lg.gpu_cleanup()                                                # no PyTorch loaded: nothing to do, and it must not import it


# ---- in the service ---------------------------------------------------------------------------------------
@pytest.fixture
def service(monkeypatch, tmp_path, clock):
    g = lg.LoadGuard(clock=clock)
    monkeypatch.setattr(server, "GUARD", g)
    monkeypatch.setattr(server, "MOCK", True)
    monkeypatch.setattr(server, "SESSIONS", {})
    monkeypatch.setattr(server, "MAX_SESSIONS", 3)
    monkeypatch.setattr(sess, "RUNS", tmp_path)
    monkeypatch.setenv("SERVICE_API_KEYS", "k1")
    return g


def opens(c, url="/v1/session?external_user_id=u", **kw):
    with c.websocket_connect(url, headers={"Authorization": "Bearer k1"}, **kw) as ws:
        return ws.receive_json()["type"] == "test"


def test_health_says_whether_the_service_takes_tests(service, clock):
    c = TestClient(server.app)
    assert c.get("/health").json()["accepting"] is True and c.get("/health").json()["busy_reason"] == ""
    service.update_gpu((24_000, 24_576))
    h = c.get("/health").json()
    assert h["accepting"] is False and h["busy_reason"] == "gpu_memory" and h["ready"] is True
    assert service.stats()["refused"] == {}                          # asking /health is not a refusal


@pytest.mark.parametrize("make_busy,reason,words", [("gpu", "gpu_memory", "busy"), ("slow", "slow", "busy"), ("restart", "restarting", "restarting")])
def test_a_busy_service_closes_both_sockets_with_1013(service, clock, make_busy, reason, words):
    from starlette.websockets import WebSocketDisconnect

    if make_busy == "gpu":
        service.update_gpu((24_300, 24_576))
    elif make_busy == "slow":
        feed(service, clock, 15.0, times=12)
    else:
        service.restarting = True
    c = TestClient(server.app)
    for url in ("/v1/session?external_user_id=u", "/ws?device=x"):
        with pytest.raises(WebSocketDisconnect) as err:
            with c.websocket_connect(url, headers={"Authorization": "Bearer k1"}) as ws:
                ws.receive_json()
        assert err.value.code == 1013 and words in err.value.reason.lower(), url
    assert service.stats()["refused"] == {reason: 2} and not server.SESSIONS


def test_the_door_opens_again_when_the_gpu_recovers(service):
    c = TestClient(server.app)
    service.update_gpu((24_300, 24_576))
    with pytest.raises(Exception):
        opens(c)
    service.update_gpu((18_000, 24_576))
    assert opens(c)


def test_a_reply_delay_reaches_the_guard(monkeypatch, clock):
    g = lg.LoadGuard(clock=clock)
    monkeypatch.setattr(lg, "GUARD", g)
    s = sess.ExamSession(send=lambda e: asyncio.sleep(0))
    asyncio.run(s.on_latency(4.2))
    assert g.reply_p95() == (4.2, 1)


def test_the_monitor_shows_the_guard(service, monkeypatch):
    monkeypatch.setenv("MONITOR_KEY", "m")
    service.update_gpu((20_000, 24_576))
    body = TestClient(server.app).get("/api/monitor", headers={"Authorization": "Bearer m"}).json()
    assert body["load"]["gpu_used_mb"] == 20_000 and body["load"]["slow"] is False and body["load"]["refused"] == {}


# ---- the watcher loop (what really restarts the service) ----------------------------------------------------
class Stop(BaseException):
    """Raised by the fake os._exit so the endless loop can be left."""


@pytest.mark.skipif(not hasattr(server, "_watch_gpu"), reason="the app was imported in mock mode, so the watcher is not installed")
def test_the_watcher_restarts_with_code_75_and_survives_its_own_errors(monkeypatch):
    exits, steps = [], iter(["boom", None, "recycle"])

    def watch_step(running, reading, *, ready):
        step = next(steps)
        if step == "boom":
            raise RuntimeError("a bad reading")
        return step

    async def no_sleep(_):
        return None

    class Guard:
        pass

    g = Guard()
    g.watch_step = watch_step
    monkeypatch.setattr(server, "GUARD", g)
    monkeypatch.setattr(server.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(lg, "read_gpu_memory", lambda: (1, 2))
    monkeypatch.setattr(server.os, "_exit", lambda code: (exits.append(code), (_ for _ in ()).throw(Stop()))[0])
    monkeypatch.setattr(server.logging, "shutdown", lambda: None)
    with pytest.raises(Stop):
        asyncio.run(server._watch_gpu())
    assert exits == [75] and lg.RESTART_EXIT_CODE == 75              # an error in one look did not end the watcher; "recycle" exits with 75


def test_load_right_after_a_restart_does_not_hide_the_leak(guard, clock):
    """Seen on the GPU on 2026-11-26: tests arrived at once, the first quiet moment came after them, and the loaded card
    (20.0 GB) was taken as clean, so the restart could never trigger."""
    guard.record_baseline((17_000, 24_576))                      # the models have loaded; no test yet
    assert guard.admit(0, 10).ok                                  # a candidate arrives at once
    guard.watch_step(1, (20_000, 24_576), ready=True, recycle=True)
    said = idle_run(guard, clock, [(0, 0, 20_200), (31, 0, 20_200), (35, 0, 20_200)])   # quiet: 0, 31 (cleanup), 66 s
    assert said == [None, None, "recycle"]                        # 3.2 GB above clean, quiet long enough
    assert guard.baseline_mb == 17_000


@pytest.mark.parametrize("first", ["admitted", "seen"])
def test_a_loaded_card_is_never_taken_as_clean(guard, clock, first):
    if first == "admitted":
        assert guard.admit(0, 10).ok
    else:
        guard.watch_step(1, (19_000, 24_576), ready=True)
    guard.record_baseline((19_000, 24_576))                       # too late: refused
    assert set(idle_run(guard, clock, [(0, 0, 19_000), (100, 0, 19_000), (100, 0, 19_000)])) == {None}
    assert guard.baseline_mb is None


def test_asking_whether_tests_are_taken_does_not_count_as_a_test(guard, clock):
    assert guard.accepting(0, 10).ok
    guard.record_baseline((17_000, 24_576))
    assert guard.baseline_mb == 17_000
    guard.record_baseline((21_000, 24_576))                       # kept once set
    guard.record_baseline(None)
    assert guard.baseline_mb == 17_000


def test_the_service_reads_the_clean_level_before_it_says_it_is_ready(monkeypatch, clock):
    import worker.examiner.llm as llm

    g, ready = lg.LoadGuard(clock=clock), {"done": False, "error": ""}
    seen = []

    async def warm_up(*args, **kwargs):
        return {"ok": True}

    def read():
        seen.append(ready["done"])
        return (17_000, 24_576)

    monkeypatch.setattr(server, "GUARD", g)
    monkeypatch.setattr(server, "READY", ready)
    monkeypatch.setattr(server, "MOCK", False)
    monkeypatch.setattr(server.warm, "preload", lambda: None)
    monkeypatch.setattr(llm, "generate_json", warm_up)
    monkeypatch.setattr(lg, "read_gpu_memory", read)
    preload = next(h for h in server.app.router.on_startup if h.__name__ == "_preload_models")

    async def go():
        await preload()
        for _ in range(200):                         # the models load in a thread
            if ready["done"]:
                return
            await asyncio.sleep(0.01)

    asyncio.run(go())
    assert ready == {"done": True, "error": ""} and g.baseline_mb == 17_000
    assert seen == [False]                           # read while no test could be accepted yet
