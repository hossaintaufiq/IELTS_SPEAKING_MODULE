import pytest

from control_plane.gpu_provisioner.base import CapacityError, FakeProvisioner, LeaseState


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_lease_becomes_ready_after_boot_then_ends():
    c = Clock()
    p = FakeProvisioner(max_seats=12, boot_s=30, clock=c)
    lease = p.acquire(10, 3600)
    assert p.poll(lease.id).state == LeaseState.PENDING
    c.t = 31
    assert p.poll(lease.id).state == LeaseState.READY
    c.t = 3601
    assert p.poll(lease.id).state == LeaseState.ENDED


def test_capacity_is_enforced_and_freed_on_release():
    p = FakeProvisioner(max_seats=12)
    a = p.acquire(10, 3600)
    with pytest.raises(CapacityError):
        p.acquire(3, 3600)
    p.release(a.id)
    p.acquire(12, 3600)


def test_extend_moves_expiry():
    c = Clock()
    p = FakeProvisioner(clock=c)
    lease = p.acquire(1, 100)
    assert p.extend(lease.id, 50).expires_at == 150
