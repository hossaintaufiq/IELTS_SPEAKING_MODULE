import time

import pytest
from fastapi.testclient import TestClient

from control_plane.app import create_app, sign_token, verify_token
from control_plane.gpu_provisioner.base import FakeProvisioner

H = {"Authorization": "Bearer dev-service-key"}


@pytest.fixture
def client():
    return TestClient(create_app(FakeProvisioner(max_seats=12)))


def test_requires_service_key(client):
    assert client.post("/leases", json={"seats": 5, "duration_s": 3600}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.post("/leases", json={"seats": 5, "duration_s": 3600}, headers=bad).status_code == 401


def test_lease_capacity_conflict(client):
    assert client.post("/leases", json={"seats": 10, "duration_s": 3600}, headers=H).status_code == 201
    r = client.post("/leases", json={"seats": 5, "duration_s": 3600}, headers=H)
    assert r.status_code == 409 and r.headers["retry-after"]


def test_session_flow_and_seat_limit(client):
    lease = client.post("/leases", json={"seats": 2, "duration_s": 3600}, headers=H).json()
    assert client.get(f"/leases/{lease['lease_id']}", headers=H).json()["state"] == "ready"
    for i in range(2):
        r = client.post("/sessions", json={"lease_id": lease["lease_id"], "external_user_id": f"u{i}"}, headers=H)
        assert r.status_code == 201
        claims = verify_token(r.json()["ws_token"])
        assert claims["sid"] == r.json()["session_id"]
    r = client.post("/sessions", json={"lease_id": lease["lease_id"], "external_user_id": "u3"}, headers=H)
    assert r.status_code == 429


def test_session_needs_ready_lease():
    c = TestClient(create_app(FakeProvisioner(boot_s=999)))
    lease = c.post("/leases", json={"seats": 1, "duration_s": 3600}, headers=H).json()
    r = c.post("/sessions", json={"lease_id": lease["lease_id"], "external_user_id": "u"}, headers=H)
    assert r.status_code == 409


def test_token_tamper_and_expiry():
    t = sign_token({"sid": "x", "exp": time.time() + 60})
    assert verify_token(t)["sid"] == "x"
    with pytest.raises(ValueError):
        verify_token(t[:-1] + ("0" if t[-1] != "0" else "1"))
    with pytest.raises(ValueError):
        verify_token(sign_token({"sid": "x", "exp": 1}))
    with pytest.raises(ValueError):
        verify_token("garbage")
