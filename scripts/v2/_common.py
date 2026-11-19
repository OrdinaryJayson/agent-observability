"""Standard-library HTTP, durable request identities and bounded CLI failures."""

import argparse
import hashlib
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import sys
from threading import RLock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution_v2.protocol import encoded  # noqa: E402


class ToolError(RuntimeError):
    pass


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return number


def base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise argparse.ArgumentTypeError(
            "Expected an HTTP(S) API URL without credentials/query/fragment"
        )
    return value.rstrip("/")


class StateFile:
    """Persist identities before network writes so unknown outcomes can be resumed."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = RLock()
        self.data = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else {"keys": {}, "resources": {}}
        )

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_bytes(encoded(self.data))
            os.replace(temporary, self.path)

    def bind(self, parameters):
        if self.data.get("parameters", parameters) != parameters:
            raise ToolError(
                "State file belongs to different parameters. Use another state file."
            )
        self.data["parameters"] = parameters
        self.save()

    def key(self, identity: str) -> str:
        with self.lock:
            if identity not in self.data["keys"]:
                self.data["keys"][identity] = str(uuid4())
                self.save()
            return self.data["keys"][identity]

    def resource(self, identity, resource=None):
        with self.lock:
            if resource is not None:
                self.data["resources"][identity] = resource
                self.save()
            return self.data["resources"].get(identity)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpClient:
    def __init__(self, url, *, state=None, timeout=15):
        self.url, self.state, self.timeout = base_url(url), state, timeout
        self.opener = build_opener(NoRedirect())

    def request(
        self,
        method,
        path,
        body=None,
        *,
        identity=None,
        raw=False,
        headers=None,
        deadline=None,
    ):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        }
        if identity is not None:
            if self.state is None:
                raise ToolError("An idempotent request requires a durable state file")
            identity = self.url + path + ":" + identity
            key = self.state.key(identity)
            headers["Idempotency-Key"] = key
            body_hash = hashlib.sha256(encoded(body)).hexdigest()
            with self.state.lock:
                saved = self.state.data.setdefault("requests", {}).get(identity)
                if saved is not None and saved != body_hash:
                    raise ToolError("Saved request identity has different content")
                self.state.data["requests"][identity] = body_hash
                self.state.save()
        attempts = 3 if method == "GET" or identity is not None else 1
        request = Request(
            self.url + path,
            data=None if body is None else encoded(body),
            headers=headers,
            method=method,
        )
        for index in range(attempts):
            timeout = (
                self.timeout
                if deadline is None
                else min(self.timeout, deadline - time.monotonic())
            )
            if timeout <= 0:
                raise ToolError(f"Request deadline exceeded for {path}")
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    result = json.load(response)
                if raw:
                    return result
                if not isinstance(result, dict) or "data" not in result:
                    raise ToolError("Invalid response envelope")
                return result["data"]
            except HTTPError as exc:
                code = exc.code
                exc.close()
                if code != 429 and not 500 <= code < 600:
                    raise ToolError(f"{method} {path} returned HTTP {code}") from exc
                error = f"HTTP {code}"
            except (URLError, OSError, HTTPException) as exc:
                error = type(exc).__name__
            except (ValueError, UnicodeError) as exc:
                raise ToolError(f"{method} {path} returned invalid JSON") from exc
            if index + 1 < attempts:
                pause = 0.1 * (index + 1)
                time.sleep(
                    pause
                    if deadline is None
                    else min(pause, max(0, deadline - time.monotonic()))
                )
        raise ToolError(f"{method} {path} failed after {attempts} attempts ({error})")

    def poll(self, path, *, timeout=180, terminal=("SUCCESS", "FAILED", "CANCELLED")):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.request("GET", path, deadline=deadline)
            if result.get("status") in terminal:
                return result
            time.sleep(0.2)
        raise ToolError(f"Polling timed out for {path}")


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument(
        "--base-url", type=base_url, default="http://127.0.0.1:8000/api/v2"
    )
    return result


def run_cli(action, args) -> int:
    summary = {"complete": False, "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        action(args, summary)
        summary["complete"] = True
        code = 0
    except (
        ToolError,
        ValueError,
        KeyError,
        TypeError,
        OSError,
        ImportError,
        KeyboardInterrupt,
    ) as exc:
        summary["error"] = str(exc) or "Interrupted"
        print(summary["error"], file=sys.stderr)
        code = 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    return code
