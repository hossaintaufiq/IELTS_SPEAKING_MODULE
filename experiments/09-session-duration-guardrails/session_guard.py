from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

Hangup = Callable[[str], Awaitable[None]]


@dataclass
class Session:
    call_id: str
    user_id: str
    started_at: float
    last_activity: float


@dataclass
class GuardConfig:
    max_session_s: float = 15 * 60
    idle_timeout_s: float = 60
    max_sessions_per_user_per_day: int = 3
    max_concurrent_total: int = 20


@dataclass
class SessionGuard:
    hangup: Hangup
    config: GuardConfig = field(default_factory=GuardConfig)
    clock: Callable[[], float] = time.monotonic
    sessions: dict[str, Session] = field(default_factory=dict)
    daily_counts: dict[tuple[str, int], int] = field(default_factory=dict)

    def admit(self, call_id: str, user_id: str, day: int) -> tuple[bool, str]:
        if len(self.sessions) >= self.config.max_concurrent_total:
            return False, "capacity"
        if self.daily_counts.get((user_id, day), 0) >= self.config.max_sessions_per_user_per_day:
            return False, "daily_limit"
        now = self.clock()
        self.sessions[call_id] = Session(call_id, user_id, now, now)
        self.daily_counts[(user_id, day)] = self.daily_counts.get((user_id, day), 0) + 1
        return True, "ok"

    def touch(self, call_id: str) -> None:
        if call_id in self.sessions:
            self.sessions[call_id].last_activity = self.clock()

    def release(self, call_id: str) -> None:
        self.sessions.pop(call_id, None)

    async def sweep(self) -> list[tuple[str, str]]:
        now = self.clock()
        ended = []
        for call_id, s in list(self.sessions.items()):
            if now - s.started_at >= self.config.max_session_s:
                reason = "max_duration"
            elif now - s.last_activity >= self.config.idle_timeout_s:
                reason = "idle"
            else:
                continue
            await self.hangup(call_id)
            self.release(call_id)
            ended.append((call_id, reason))
        return ended
