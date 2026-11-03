"""Check cross-process session reuse and retry timing without a live account."""

import stat
import tempfile
from dataclasses import replace
from pathlib import Path

import httpx

from libre_polling import (
    PollDeferred,
    RateLimited,
    cached_fetch,
    private_read,
    retry_seconds,
    session_state,
)
from libre_sync import SyncConfig, SyncError

config = SyncConfig(
    "fixture@example.test", "private-fixture", "us", "4.16.0", "patient-fixture", 1
)
point = {"FactoryTimestamp": "11/02/2026 01:00:00 PM", "ValueInMgPerDl": 123}
graph = {
    "connection": {"patientId": "patient-fixture", "glucoseMeasurement": point},
    "graphData": [point],
}
clock = [1000]
calls = []
mode = ["ok"]
rejected = [False]


def response(request):
    calls.append(request.url.path)
    if mode[0] == "limit":
        return httpx.Response(429, headers={"Retry-After": "1800"}, json={})
    if mode[0] == "unavailable":
        return httpx.Response(503, json={})
    if request.url.path.endswith("/login"):
        return httpx.Response(
            200,
            headers={"Set-Cookie": "session=private-cookie; Path=/; Secure"},
            json={
                "status": 0,
                "data": {
                    "user": {"id": "account-fixture"},
                    "authTicket": {
                        "token": "private-token",
                        "expires": clock[0] + 3600,
                    },
                },
            },
        )
    if mode[0] == "reject-once" and not rejected[0]:
        rejected[0] = True
        return httpx.Response(401, json={})
    if mode[0] == "reject-always":
        return httpx.Response(401, json={})
    assert "session=private-cookie" in request.headers.get("cookie", "")
    data = (
        [{"patientId": "patient-fixture"}]
        if request.url.path.endswith("/connections")
        else graph
    )
    return httpx.Response(200, json={"status": 0, "data": data})


def fetch(state, selected=config):
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        return cached_fetch(selected, client, state, now=lambda: clock[0])


with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "state/session.json"
    with session_state(path) as state:
        assert len(fetch(state)) == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(calls) == 3
    with session_state(path) as state:
        fetch(state)
        try:
            with session_state(path):
                raise AssertionError("Overlapping collection was allowed")
        except PollDeferred:
            pass
    assert len(calls) == 5 and sum(p.endswith("/login") for p in calls) == 1
    mode[0] = "reject-once"
    with session_state(path) as state:
        fetch(state)
    assert sum(p.endswith("/login") for p in calls) == 2
    mode[0] = "ok"
    clock[0] += 4000
    with session_state(path) as state:
        fetch(state)
    assert sum(p.endswith("/login") for p in calls) == 3
    mode[0] = "limit"
    with session_state(path) as state:
        try:
            fetch(state)
        except RateLimited:
            assert state["retry_at"] == clock[0] + 1800
        else:
            raise AssertionError("Rate limit accepted")
    before = len(calls)
    with session_state(path) as state:
        try:
            fetch(state)
        except PollDeferred:
            pass
        else:
            raise AssertionError("Cooldown was bypassed")
    assert len(calls) == before
    clock[0] += 1801
    mode[0] = "unavailable"
    with session_state(path) as state:
        try:
            fetch(state)
        except SyncError:
            assert state["failures"] == 2 and state["retry_at"] == clock[0] + 1800
    clock[0] += 1801
    mode[0] = "ok"
    with session_state(path) as state:
        fetch(state)
        assert state["failures"] == 0 and state["retry_at"] == 0
        fetch(state, replace(config, email="different@example.test"))
    assert sum(p.endswith("/login") for p in calls) == 5
    path.chmod(0o644)
    try:
        private_read(path)
    except SyncError:
        pass
    else:
        raise AssertionError("Insecure state file accepted")

mode[0] = "reject-always"
before = len(calls)
state = {}
try:
    fetch(state)
except SyncError:
    assert len(calls) - before == 4 and state["retry_at"] > clock[0]
else:
    raise AssertionError("Unbounded auth renewal")
assert retry_seconds("not-a-date", 0) == 900
assert retry_seconds("NaN", 0) == 900
assert retry_seconds("3600", 0) == 3600
assert retry_seconds("Thu, 01 Jan 1970 01:00:00 GMT", 0) == 3600
print(
    "PASS: persisted ticket/cookies, expiry and single renewal, credential binding, rate/backoff cooldown across runs, recovery, overlap lock, and owner-only state."
)
