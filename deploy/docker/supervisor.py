"""Runs the whole speaking service inside the container: the language model (vLLM) and the service, and keeps them running.

- The service is started only once vLLM answers, so `ready` on /health means all three models are there, and the "clean" GPU memory
  level the service reads at start-up includes the language model.
- A program that ends is started again: at once after exit code 75 (the service asking for a restart to free GPU memory), otherwise
  after a growing pause (2 s, 4 s ... at most 60 s). A program that stops answering, or never becomes ready, is killed and started again.
- Their output goes to LOG_DIR/<name>.log, one file per day, kept RETENTION_DAYS days (the service log contains what candidates said).
  Only this script's own messages go to the container's log.

Docker restarts the container if this script ends, and starts it after a reboot (restart: unless-stopped).
It needs no Docker: `python deploy/docker/supervisor.py` works on any Linux GPU box with the two Python environments.
"""
from __future__ import annotations

import glob
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

RESTART_NOW = 75             # worker/load_guard.py: restart me
STOP_WAIT_S = 20             # a program gets this long to end by itself before it is killed
HANG_AFTER = 12              # failed health checks in a row (about a minute) before a running program is restarted
STEADY_S = 600               # after running this long, the next failure starts from a short pause again
MAX_PAUSE_S = 60
STEP_S = 5
POSIX = os.name == "posix"


def say(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} supervisor: {message}", flush=True)


def log_to(directory: Path, name: str, days: float) -> logging.Logger:
    """A logger writing <directory>/<name>.log, a new file each day, `days` old files kept (0 keeps all)."""
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"supervised.{name}")
    for old in list(logger.handlers):
        logger.removeHandler(old)
        old.close()
    handler = logging.handlers.TimedRotatingFileHandler(directory / f"{name}.log", when="midnight",
                                                        backupCount=max(1, int(days)) if days > 0 else 0, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


class Program:
    def __init__(self, name: str, command: list[str], *, ready: Callable[[], bool], alive: Callable[[], bool], start_timeout: float,
                 needs: "Program | None" = None, env: dict | None = None, cwd: str | None = None, logger: logging.Logger | None = None):
        self.name, self.command, self.env, self.cwd, self.logger = name, command, env, cwd, logger
        self.ready, self.alive, self.start_timeout, self.needs = ready, alive, start_timeout, needs
        self.process: subprocess.Popen | None = None
        self.came_up = False
        self.started_at = 0.0
        self.next_start = 0.0
        self.failed_checks = 0
        self.failures = 0            # ends in a row without a steady run in between: sets the pause

    # ---- the process -----------------------------------------------------------------------------
    def start(self, now: float) -> None:
        self.process = subprocess.Popen(self.command, env=self.env, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        start_new_session=POSIX)       # its own group, so its helper processes can be ended with it
        threading.Thread(target=self._copy_output, args=(self.process,), daemon=True).start()
        self.started_at, self.came_up, self.failed_checks = now, False, 0
        say(f"started {self.name} (process {self.process.pid})")

    def _copy_output(self, process: subprocess.Popen) -> None:
        for raw in iter(process.stdout.readline, b""):
            if self.logger:
                self.logger.info(raw.decode("utf-8", "replace").rstrip())

    def stop(self, wait: float = STOP_WAIT_S) -> None:
        """End the program and everything it started: a left-over vLLM worker would keep the GPU memory."""
        process, self.process = self.process, None
        if process is None:
            return
        self._signal(process, gently=True)
        try:
            process.wait(wait)
        except subprocess.TimeoutExpired:
            say(f"{self.name} did not end in {wait:g} s: killing it")
        self._signal(process, gently=False)
        process.wait(10)

    @staticmethod
    def _signal(process: subprocess.Popen, *, gently: bool) -> None:
        try:
            if POSIX:
                os.killpg(process.pid, signal.SIGTERM if gently else signal.SIGKILL)
            elif process.poll() is None:
                process.terminate() if gently else process.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass                                                        # already gone


class Supervisor:
    def __init__(self, programs: list[Program], clock: Callable[[], float] = time.monotonic):
        self.programs, self.clock = programs, clock

    def step(self) -> None:
        """One look at every program: start what should run, restart what ended or stopped answering."""
        for program in self.programs:
            now = self.clock()
            if program.process is None:
                if now >= program.next_start and (program.needs is None or program.needs.came_up):
                    program.start(now)
                continue
            code = program.process.poll()
            if code is not None:
                self._ended(program, f"ended with code {code}", at_once=code == RESTART_NOW)
            elif not program.came_up:
                if program.ready():
                    program.came_up = True
                    say(f"{program.name} is ready after {now - program.started_at:.0f} s")
                elif now - program.started_at > program.start_timeout:
                    self._ended(program, f"was not ready after {program.start_timeout:g} s", at_once=False)
            elif program.alive():
                program.failed_checks = 0
            else:
                program.failed_checks += 1
                if program.failed_checks >= HANG_AFTER:
                    self._ended(program, "stopped answering", at_once=False)

    def _ended(self, program: Program, why: str, *, at_once: bool) -> None:
        now = self.clock()
        if program.came_up and now - program.started_at >= STEADY_S:
            program.failures = 0
        program.failures = 0 if at_once else program.failures + 1
        pause = 0 if at_once else min(MAX_PAUSE_S, 2 ** program.failures)
        say(f"{program.name} {why}: starting it again in {pause} s")
        program.stop(wait=5)
        program.came_up, program.next_start = False, now + pause

    def stop(self) -> None:
        for program in reversed(self.programs):                          # the service first, then what it depends on
            say(f"stopping {program.name}")
            program.stop()


# ---- the real programs -------------------------------------------------------------------------------
def fetch(url: str) -> dict | None:
    """The reply of a health address as a dict ({} for an empty 200 reply), or None when it does not answer with 200."""
    try:
        with urllib.request.urlopen(url, timeout=10) as reply:
            body = reply.read()
        return json.loads(body) if body.strip() else {}
    except (OSError, ValueError):
        return None


def gpu_fraction(total_mb: int) -> float:
    """The share of GPU memory for the language model: about 10 GB stay free for speech recognition, voice and CUDA."""
    return round(min(0.6, max(0.25, (total_mb - 10000) / total_mb)), 2)


def gpu_total_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True,
                         timeout=20, check=True)
    return int(out.stdout.split()[0])


def missing_settings(env: dict) -> list[str]:
    missing = [n for n in ("SERVICE_API_KEYS", "MONITOR_KEY") if not env.get(n, "").strip()]
    if len(env.get("TOKEN_SECRET", "").strip()) < 32:
        missing.append("TOKEN_SECRET (at least 32 characters)")
    return missing


def build_programs(env: dict, app_dir: Path) -> list[Program]:
    log_dir = Path(env.get("LOG_DIR", "/data/logs"))
    days = float(env.get("RETENTION_DAYS") or 30)
    app_python = env.get("APP_PYTHON", "/opt/app/bin/python")
    vllm_python = env.get("VLLM_PYTHON", "/opt/vllm/bin/python")
    model = env.get("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct-AWQ")
    llm_port = env.get("LLM_PORT", "8000")
    fraction = env.get("VLLM_GPU_FRACTION") or str(gpu_fraction(gpu_total_mb()))
    llm_health = f"http://127.0.0.1:{llm_port}/health"
    llm = Program(
        "vllm",
        [vllm_python, "-m", "vllm.entrypoints.openai.api_server", "--model", model, "--host", "127.0.0.1", "--port", llm_port,
         "--gpu-memory-utilization", fraction, "--max-model-len", env.get("VLLM_MAX_MODEL_LEN", "4096")],
        ready=lambda: fetch(llm_health) is not None, alive=lambda: fetch(llm_health) is not None,
        start_timeout=float(env.get("VLLM_START_TIMEOUT_S", "1800")),           # the first start downloads the model
        env=dict(env), logger=log_to(log_dir, "vllm", days))

    libraries = glob.glob(str(Path(app_python).parent.parent / "lib/python*/site-packages/nvidia/*/lib"))
    service_env = dict(env, LOG_DIR=str(log_dir), PYTHONUNBUFFERED="1", LLM_BASE_URL=f"http://127.0.0.1:{llm_port}/v1", LLM_MODEL=model,
                       LD_LIBRARY_PATH=os.pathsep.join(libraries + [env.get("LD_LIBRARY_PATH", "")]).strip(os.pathsep))
    health = f"http://127.0.0.1:{env.get('INTERNAL_PORT', '8081')}/health"
    service = Program(
        "web", [app_python, "-m", "worker.server"],
        ready=lambda: bool((fetch(health) or {}).get("ready")), alive=lambda: fetch(health) is not None,
        start_timeout=float(env.get("SERVICE_START_TIMEOUT_S", "900")),
        needs=llm, env=service_env, cwd=str(app_dir), logger=log_to(log_dir, "web", days))
    return [llm, service]


def main() -> int:
    env = dict(os.environ)
    missing = missing_settings(env)
    if missing:
        say(f"cannot start: set {', '.join(missing)} (deploy/docker/.env.example)")
        return 1
    supervisor = Supervisor(build_programs(env, Path(__file__).resolve().parents[2]))
    asked_to_stop = threading.Event()
    for name in ("SIGTERM", "SIGINT"):
        signal.signal(getattr(signal, name), lambda *_: asked_to_stop.set())
    say("starting")
    try:
        while not asked_to_stop.is_set():
            supervisor.step()
            asked_to_stop.wait(STEP_S)
    finally:
        supervisor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
