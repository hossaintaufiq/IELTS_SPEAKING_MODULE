"""The outside-in checker (eval/check_public.py), run against the real server: a good setup passes, a bad one is caught."""
import pytest

import eval.check_public as cp
from tests.test_public import free_port, start, wait_up

SITE = "https://ieltsup.org"
KEY = "k1"


def serve(extra: dict):
    pytest.importorskip("uvicorn")
    pytest.importorskip("websockets")
    pub = free_port()
    proc = start({"MOCK": "1", "PORT": str(pub), "INTERNAL_PORT": str(free_port()), "SERVICE_API_KEYS": KEY, "TOKEN_SECRET": "z" * 40,
                  "ALLOWED_ORIGINS": SITE, **extra})
    wait_up(f"http://127.0.0.1:{pub}/health", proc)
    return proc, f"http://127.0.0.1:{pub}"


def stop(proc):
    proc.terminate()
    proc.wait(timeout=15)


def by_name(report):
    return {r.name: r for r in report.results}


def test_a_correct_deployment_passes_every_check():
    proc, base = serve({})
    try:
        report = cp.run(base, origin=SITE, api_key=KEY, allow_http=True)
    finally:
        stop(proc)
    r = by_name(report)
    assert not report.failed, [(x.name, x.detail) for x in report.results if x.status == "FAIL"]
    for name in ("GET /health", "internal pages hidden", "bench socket /ws closed", "POST /v1/tokens without key", "POST /v1/tokens with a wrong key",
                 "socket without key or token", "listed website can read /health", "unlisted website cannot read /health", "security headers",
                 "POST /v1/tokens with the key", "socket opens with a token", "a token works only once", "unlisted website refused"):
        assert r[name].status == "PASS", (name, r[name].detail)
    assert r["https certificate"].status == "WARN"            # plain http is allowed for a local check, but flagged


def test_plain_http_fails_unless_it_is_allowed():
    proc, base = serve({})
    try:
        report = cp.run(base, origin=None, api_key="", allow_http=False)
    finally:
        stop(proc)
    assert by_name(report)["https certificate"].status == "FAIL" and report.failed


def test_without_a_key_or_origin_those_parts_are_skipped_not_passed():
    proc, base = serve({})
    try:
        report = cp.run(base, origin=None, api_key="", allow_http=True)
    finally:
        stop(proc)
    r = by_name(report)
    assert r["listed website can read /health"].status == "SKIP" and r["browser round trip"].status == "SKIP" and not report.failed


def test_a_server_that_exposes_the_bench_and_monitor_is_caught():
    proc, base = serve({"SINGLE_PORT": "1"})                  # the old one-port mode: everything is on the public address
    try:
        report = cp.run(base, origin=SITE, api_key=KEY, allow_http=True)
    finally:
        stop(proc)
    r = by_name(report)
    assert report.failed
    assert r["internal pages hidden"].status == "FAIL" and "/monitor" in r["internal pages hidden"].detail
    assert r["bench socket /ws closed"].status == "FAIL"


def test_a_wrong_origin_list_is_caught():
    proc, base = serve({"ALLOWED_ORIGINS": "https://somewhere-else.example"})
    try:
        report = cp.run(base, origin=SITE, api_key=KEY, allow_http=True)         # ieltsup's site is not in the list
    finally:
        stop(proc)
    r = by_name(report)
    assert r["listed website can read /health"].status == "FAIL" and r["socket opens with a token"].status == "FAIL"


def test_a_wrong_key_is_reported_not_crashed():
    proc, base = serve({})
    try:
        report = cp.run(base, origin=SITE, api_key="not-the-key", allow_http=True)
    finally:
        stop(proc)
    assert by_name(report)["POST /v1/tokens with the key"].status == "FAIL"


def test_an_address_that_does_not_answer_is_a_failure_with_a_reason():
    report = cp.run(f"http://127.0.0.1:{free_port()}", origin=None, api_key="", allow_http=True)
    assert report.failed and any("GET /health" == r.name for r in report.results)


def test_a_bad_address_is_refused():
    assert cp.run("speaking.example.org", origin=None, api_key="", allow_http=True).failed
    assert cp.main(["--base", "ftp://x", "--allow-http"]) == 1


def test_the_responses_carry_the_security_headers_and_are_not_cacheable():
    import httpx

    proc, base = serve({})
    try:
        for path, headers in (("/health", {}), ("/nothing", {}), ("/v1/tests/1", {}), ("/health", {"origin": SITE})):
            r = httpx.get(base + path, headers=headers)
            assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer", path
            assert r.headers["cache-control"] == "no-store" and "max-age" in r.headers["strict-transport-security"], path
        minted = httpx.post(base + "/v1/tokens", json={"external_user_id": "u"}, headers={"Authorization": f"Bearer {KEY}"})
        assert minted.headers["cache-control"] == "no-store"            # set once, not doubled
    finally:
        stop(proc)
