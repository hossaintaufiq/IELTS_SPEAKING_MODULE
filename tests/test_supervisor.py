"""The container's supervisor (deploy/docker/supervisor.py), with small real processes in place of the models."""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("supervisor", ROOT / "deploy/docker/supervisor.py")
sup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sup)

RUN = [sys.executable, "-c", "import time; print('hello from the program', flush=True); time.sleep(60)"]


def ends_with(code):
    return [sys.executable, "-c", f"raise SystemExit({code})"]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Health:
    def __init__(self, ready=True, alive=True):
        self.is_ready, self.is_alive = ready, alive

    def ready(self):
        return self.is_ready

    def alive(self):
        return self.is_alive


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def made():
    programs = []
    yield programs
    for p in programs:
        p.stop(wait=2)


def program(made, name="p", command=RUN, health=None, **kw):
    health = health or Health()
    p = sup.Program(name, command, ready=health.ready, alive=health.alive, start_timeout=kw.pop("start_timeout", 100), **kw)
    made.append(p)
    return p


def ended(p):
    p.process.wait(20)


def test_the_service_starts_only_when_the_language_model_is_ready(made, clock):
    llm_health = Health(ready=False)
    llm = program(made, "vllm", health=llm_health)
    web = program(made, "web", needs=llm)
    s = sup.Supervisor([llm, web], clock)
    s.step()
    s.step()
    assert llm.process is not None and web.process is None
    llm_health.is_ready = True
    s.step()
    assert llm.came_up and web.process is not None


def test_a_program_that_ends_is_started_again_after_a_growing_pause(made, clock):
    p = program(made, command=ends_with(1))
    s = sup.Supervisor([p], clock)
    pauses = []
    for _ in range(8):
        s.step()                                   # starts it
        ended(p)
        s.step()                                   # sees that it ended
        assert p.process is None
        pauses.append(p.next_start - clock.now)
        s.step()
        assert p.process is None                   # not before the pause is over
        clock.now = p.next_start
    assert pauses == [2, 4, 8, 16, 32, 60, 60, 60]


def test_exit_code_75_restarts_at_once(made, clock):
    p = program(made, command=ends_with(75))
    s = sup.Supervisor([p], clock)
    s.step()
    ended(p)
    s.step()
    assert p.next_start == clock.now and p.failures == 0
    s.step()
    assert p.process is not None


def test_after_a_steady_run_the_pause_is_short_again(made, clock):
    p = program(made)
    s = sup.Supervisor([p], clock)
    p.failures = 5
    s.step()
    s.step()                                       # ready
    clock.now += sup.STEADY_S
    p.process.kill()
    ended(p)
    s.step()
    assert p.next_start - clock.now == 2


def test_a_program_that_stops_answering_is_restarted_but_one_missed_check_is_not_enough(made, clock):
    health = Health()
    p = program(made, health=health)
    s = sup.Supervisor([p], clock)
    s.step()
    s.step()
    first = p.process
    health.is_alive = False
    for _ in range(sup.HANG_AFTER - 1):
        s.step()
    health.is_alive = True
    s.step()                                       # answered again: the count starts over
    health.is_alive = False
    for _ in range(sup.HANG_AFTER - 1):
        s.step()
    assert p.process is first and first.poll() is None
    s.step()
    assert p.process is None and first.poll() is not None


def test_a_program_that_never_becomes_ready_is_restarted(made, clock):
    p = program(made, health=Health(ready=False), start_timeout=30)
    s = sup.Supervisor([p], clock)
    s.step()
    first = p.process
    clock.now += 29
    s.step()
    assert p.process is first
    clock.now += 2
    s.step()
    assert p.process is None and first.poll() is not None


def test_the_service_keeps_running_while_the_language_model_restarts(made, clock):
    llm = program(made, "vllm")
    web = program(made, "web", needs=llm)
    s = sup.Supervisor([llm, web], clock)
    s.step()
    s.step()
    s.step()
    service = web.process
    llm.process.kill()
    ended(llm)
    s.step()
    assert web.process is service and service.poll() is None and llm.process is None


def test_stopping_ends_every_program(made, clock):
    a, b = program(made, "a"), program(made, "b")
    s = sup.Supervisor([a, b], clock)
    s.step()
    processes = [a.process, b.process]
    s.stop()
    assert all(p.poll() is not None for p in processes) and a.process is None and b.process is None


def test_output_goes_to_a_daily_log_file_that_keeps_as_many_days_as_the_tests(made, clock, tmp_path):
    logger = sup.log_to(tmp_path, "web", 30)
    handler = logger.handlers[0]
    assert handler.when == "MIDNIGHT" and handler.backupCount == 30
    p = program(made, logger=logger)
    sup.Supervisor([p], clock).step()
    path = tmp_path / "web.log"
    for _ in range(200):
        if "hello from the program" in path.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)
    assert "hello from the program" in path.read_text(encoding="utf-8")
    assert sup.log_to(tmp_path, "keep", 0).handlers[0].backupCount == 0
    assert sup.log_to(tmp_path, "short", 0.5).handlers[0].backupCount == 1
    for name in ("web", "keep", "short"):
        for h in list(sup.logging.getLogger(f"supervised.{name}").handlers):
            h.close()


@pytest.mark.parametrize("total, share", [(24576, 0.59), (16384, 0.39), (48000, 0.6), (11000, 0.25)])
def test_the_language_models_share_of_gpu_memory(total, share):
    assert sup.gpu_fraction(total) == share


def test_it_refuses_to_start_without_the_keys():
    assert sup.missing_settings({}) == ["SERVICE_API_KEYS", "MONITOR_KEY", "TOKEN_SECRET (at least 32 characters)"]
    assert sup.missing_settings({"SERVICE_API_KEYS": "a", "MONITOR_KEY": "b", "TOKEN_SECRET": "short"}) == ["TOKEN_SECRET (at least 32 characters)"]
    assert sup.missing_settings({"SERVICE_API_KEYS": "a", "MONITOR_KEY": "b", "TOKEN_SECRET": "x" * 32}) == []


def test_the_programs_and_their_settings(tmp_path):
    env = {"LOG_DIR": str(tmp_path), "VLLM_GPU_FRACTION": "0.5", "APP_PYTHON": "/opt/app/bin/python"}
    llm, web = sup.build_programs(env, ROOT)
    assert web.needs is llm and web.command == ["/opt/app/bin/python", "-m", "worker.server"]
    assert llm.command[llm.command.index("--host") + 1] == "127.0.0.1"          # the language model is never reachable from outside
    assert llm.command[llm.command.index("--gpu-memory-utilization") + 1] == "0.5"
    assert web.env["LLM_BASE_URL"] == "http://127.0.0.1:8000/v1" and web.env["LOG_DIR"] == str(tmp_path)
    for name in ("vllm", "web"):
        for h in list(sup.logging.getLogger(f"supervised.{name}").handlers):
            h.close()
