"""Private cross-run Libre session cache, lock, and persistent retry cooldown."""

import fcntl
import hashlib
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from libre_sync import SyncError, fetch_readings


class PollDeferred(SyncError):
    pass


class ExpiredSession(Exception):
    pass


class RateLimited(SyncError):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__(
            "LibreLinkUp rate limited collection; a retry cooldown has been saved."
        )


def retry_seconds(value, now):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            seconds = 900
    if not __import__("math").isfinite(seconds):
        seconds = 900
    return max(900, seconds)


def private_read(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd) as file:
        info = os.fstat(file.fileno())
        if (
            info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or not stat.S_ISREG(info.st_mode)
        ):
            raise SyncError("Libre session state must be an owner-only regular file.")
        try:
            result = json.load(file)
            return result if isinstance(result, dict) else {}
        except (ValueError, TypeError):
            return {}


def private_write(path, state):
    fd, temporary = tempfile.mkstemp(prefix=".libre-session-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(state, file)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SessionClient:
    def __init__(self, client, state, now):
        self.client, self.state, self.now = client, state, now

    def post(self, url, **kwargs):
        ticket = self.state.get("login", {})
        if ticket and ticket.get("expires", 0) > self.now() + 60:
            return httpx.Response(
                200,
                json={
                    "status": 0,
                    "data": {
                        "user": {"id": ticket["account"]},
                        "authTicket": {"token": ticket["token"]},
                    },
                },
            )
        response = self.client.post(url, **kwargs)
        self.check(response)
        try:
            payload = response.json()
            data = payload["data"]
            auth = data["authTicket"]
            expires = float(auth.get("expires", 0))
            if not expires and auth.get("duration"):
                expires = self.now() + float(auth["duration"])
            token, account = auth["token"], data["user"]["id"]
            if (
                payload.get("status") == 0
                and isinstance(token, str)
                and isinstance(account, str)
                and expires > self.now() + 60
            ):
                self.state["login"] = dict(
                    token=token, account=account, expires=expires
                )
        except (KeyError, TypeError, ValueError):
            pass
        return response

    def get(self, url, **kwargs):
        response = self.client.get(url, **kwargs)
        self.check(response)
        if response.status_code == 401:
            self.state.pop("login", None)
            raise ExpiredSession()
        return response

    def check(self, response):
        if response.status_code == 429:
            raise RateLimited(
                retry_seconds(response.headers.get("Retry-After"), self.now())
            )


def cached_fetch(config, client, state, now=time.time):
    # Bind tickets to credentials, region, app version and patient; never reuse across accounts.
    identity = hashlib.sha256(
        json.dumps(
            [
                config.email,
                config.password,
                config.region,
                config.version,
                config.patient_id,
            ]
        ).encode()
    ).hexdigest()
    if state.get("identity") != identity:
        state.clear()
        state["identity"] = identity
    if state.get("retry_at", 0) > now():
        raise PollDeferred("Libre collection is waiting for its saved retry cooldown.")
    allowed_domains = {
        f"api-{config.region}.libreview.io",
        ".libreview.io",
        "libreview.io",
    }
    for cookie in state.get("cookies", []):
        if cookie.get("domain") in allowed_domains:
            client.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie["domain"],
                path=cookie["path"],
            )
    wrapped = SessionClient(client, state, now)
    try:
        try:
            result = fetch_readings(config, wrapped)
        except ExpiredSession:
            # One renewal only. Do not retry indefinitely or bypass a 403/consent challenge.
            state.pop("login", None)
            result = fetch_readings(config, wrapped)
    except (SyncError, ExpiredSession, httpx.HTTPError) as exc:
        failures = min(int(state.get("failures", 0)) + 1, 8)
        delay = min(900 * 2 ** (failures - 1), 21600)
        if isinstance(exc, RateLimited):
            delay = max(delay, exc.seconds)
        state.update(failures=failures, retry_at=now() + delay)
        if isinstance(exc, ExpiredSession):
            raise SyncError(
                "Libre authentication expired again; collection is paused until retry."
            )
        raise
    state["cookies"] = [
        dict(name=c.name, value=c.value, domain=c.domain, path=c.path)
        for c in client.cookies.jar
        if c.domain in allowed_domains
    ]
    state.update(failures=0, retry_at=0)
    return result


@contextmanager
def session_state(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SyncError("Libre session lock must be owner-only.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PollDeferred("Another Libre collection is already running.")
        state = private_read(path)
        try:
            yield state
        finally:
            private_write(path, state)
    finally:
        os.close(fd)
