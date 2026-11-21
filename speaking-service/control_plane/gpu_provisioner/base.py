"""GPU provisioner interface.

Phase 1 rents GPUs from data centres (start/stop per lease). Phase 2 uses owned GPUs that stay
on (a "lease" becomes a capacity reservation). Both implement this interface so the public API
does not change between phases.
"""
from __future__ import annotations

import enum
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class LeaseState(str, enum.Enum):
    PENDING = "pending"      # requested, GPU/models not ready
    READY = "ready"          # accepting sessions
    DRAINING = "draining"    # no new sessions, existing ones finishing
    ENDED = "ended"


class CapacityError(Exception):
    """Raised when the requested seats exceed what the GPU can serve."""


@dataclass
class Lease:
    id: str
    seats: int
    duration_s: int
    state: LeaseState = LeaseState.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    worker_url: str | None = None


class GpuProvisioner(ABC):
    @abstractmethod
    def acquire(self, seats: int, duration_s: int) -> Lease: ...

    @abstractmethod
    def poll(self, lease_id: str) -> Lease: ...

    @abstractmethod
    def extend(self, lease_id: str, extra_s: int) -> Lease: ...

    @abstractmethod
    def release(self, lease_id: str) -> Lease: ...


class FakeProvisioner(GpuProvisioner):
    """In-memory provisioner for tests and local development. No real GPU is touched."""

    def __init__(self, max_seats: int = 12, boot_s: float = 0.0, clock=time.time):
        self.max_seats, self.boot_s, self._clock = max_seats, boot_s, clock
        self._leases: dict[str, Lease] = {}

    def _used(self) -> int:
        return sum(l.seats for l in self._leases.values() if l.state != LeaseState.ENDED)

    def acquire(self, seats: int, duration_s: int) -> Lease:
        if seats < 1:
            raise ValueError("seats must be >= 1")
        if self._used() + seats > self.max_seats:
            raise CapacityError(f"{seats} seats requested, {self.max_seats - self._used()} free")
        now = self._clock()
        lease = Lease(str(uuid.uuid4()), seats, duration_s, created_at=now, expires_at=now + duration_s)
        self._leases[lease.id] = lease
        return lease

    def poll(self, lease_id: str) -> Lease:
        lease = self._leases[lease_id]
        now = self._clock()
        if lease.state == LeaseState.PENDING and now - lease.created_at >= self.boot_s:
            lease.state, lease.worker_url = LeaseState.READY, "ws://fake-worker"
        if lease.state in (LeaseState.READY, LeaseState.DRAINING) and now >= lease.expires_at:
            lease.state = LeaseState.ENDED
        return lease

    def extend(self, lease_id: str, extra_s: int) -> Lease:
        lease = self.poll(lease_id)
        if lease.state == LeaseState.ENDED:
            raise ValueError("lease already ended")
        lease.expires_at += extra_s
        return lease

    def release(self, lease_id: str) -> Lease:
        lease = self._leases[lease_id]
        lease.state = LeaseState.ENDED
        return lease
