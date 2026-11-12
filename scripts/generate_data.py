"""Generate persisted traces using only the standard library and prototype HTTP API."""

import argparse
from http.client import HTTPException
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request
from uuid import UUID

REQUEST_TIMEOUT = 15
RUN_TIMEOUT = 120
POLL_INTERVAL = 0.2
GET_ATTEMPTS = 3


class GenerationError(RuntimeError):
    pass


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _agent_ids(value: str) -> list[str]:
    try:
        ids = [str(UUID(item.strip())) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "agent IDs must be comma-separated UUIDs"
        ) from exc
    if not 1 <= len(ids) <= 3 or len(set(ids)) != len(ids):
        raise argparse.ArgumentTypeError("provide 1–3 unique agent IDs")
    return ids


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--runs", type=_positive, default=200)
    parser.add_argument("--spans-per-run", type=_positive, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--agent-ids", type=_agent_ids)
    args = parser.parse_args(argv)
    if args.spans_per_run > 500:
        parser.error("--spans-per-run must be at most 500")
    url = urlsplit(args.base_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.query
        or url.fragment
    ):
        parser.error("--base-url must be an HTTP(S) API URL without query or fragment")
    args.base_url = args.base_url.rstrip("/")
    return args


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        # Redirects of POST requests could create resources at unintended endpoints.
        from urllib.request import HTTPRedirectHandler, build_opener

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        self.opener = build_opener(NoRedirect())

    def request(self, method: str, path: str, body=None, *, deadline=None) -> dict:
        expected = 200 if method == "GET" else (201 if path == "/tasks" else 202)
        attempts = GET_ATTEMPTS if method == "GET" else 1
        request = Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method=method,
        )
        for attempt in range(attempts):
            timeout = REQUEST_TIMEOUT
            if deadline is not None:
                timeout = min(timeout, deadline - time.monotonic())
                if timeout <= 0:
                    raise GenerationError(f"Timed out waiting for {path}")
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    if response.status != expected:
                        raise GenerationError(
                            f"{method} {path} returned {response.status}"
                        )
                    result = json.load(response)
                if not isinstance(result, dict) or not isinstance(
                    result.get("data"), dict
                ):
                    raise GenerationError(
                        f"{method} {path} returned an invalid envelope"
                    )
                return result["data"]
            except HTTPError as exc:
                exc.close()
                if exc.code != 429 and not 500 <= exc.code < 600:
                    raise GenerationError(
                        f"{method} {path} returned HTTP {exc.code}"
                    ) from exc
                error = f"HTTP {exc.code}"
            except (URLError, OSError, HTTPException) as exc:
                error = type(exc).__name__
            except (ValueError, UnicodeError) as exc:
                raise GenerationError(f"{method} {path} returned invalid JSON") from exc
            if attempt + 1 < attempts:
                time.sleep(
                    min(0.2 * (attempt + 1), max(0, deadline - time.monotonic()))
                    if deadline is not None
                    else 0.2 * (attempt + 1)
                )
        raise GenerationError(
            f"{method} {path} failed after {attempts} attempt(s): {error}"
        )


def _uuid(data: dict, field: str) -> str:
    try:
        return str(UUID(data[field]))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise GenerationError(f"Response has invalid {field}") from exc


def generate(args: argparse.Namespace, summary: dict) -> None:
    client = ApiClient(args.base_url)
    task = client.request(
        "POST",
        "/tasks",
        {
            "title": f"Generated research traces (seed {args.seed})",
            "scenario_type": "research",
        },
    )
    summary["task_id"] = _uuid(task, "task_id")
    for index in range(args.runs):
        config = {
            "scenario": "research",
            "agent_count": len(args.agent_ids) if args.agent_ids else 3,
            "min_spans": args.spans_per_run,
            "max_spans": args.spans_per_run,
            "failure_rate": 0.1,
            "seed": args.seed + index,
        }
        if args.agent_ids is not None:
            config["agent_ids"] = args.agent_ids
        run = client.request(
            "POST",
            f"/tasks/{summary['task_id']}/runs",
            {
                "source_type": "SIMULATED",
                "simulation_config": config,
            },
        )
        summary["accepted_runs"] += 1
        run_id = _uuid(run, "run_id")
        summary["last_run_id"] = run_id
        trace_id = run.get("trace_id")
        if not isinstance(trace_id, str) or not re.fullmatch(r"[0-9a-f]{32}", trace_id):
            raise GenerationError("Response has invalid trace_id")
        deadline = time.monotonic() + RUN_TIMEOUT
        while True:
            state = client.request("GET", f"/runs/{run_id}", deadline=deadline)
            if state.get("status") in {"SUCCESS", "FAILED"}:
                break
            if state.get("status") != "RUNNING":
                raise GenerationError(f"Run {run_id} has unexpected status")
            time.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
        trace = client.request("GET", f"/traces/{trace_id}", deadline=deadline)
        if (
            trace.get("run_id") != run_id
            or trace.get("trace_id") != trace_id
            or trace.get("status") != state["status"]
        ):
            raise GenerationError("Trace overview does not match the completed Run")
        count = trace.get("span_count")
        if type(count) is not int or not 0 <= count <= 500:
            raise GenerationError("Trace overview has invalid span_count")
        summary["completed_runs"] += 1
        summary["success_runs" if state["status"] == "SUCCESS" else "failed_runs"] += 1
        summary["actual_spans"] += count
        if count != args.spans_per_run:
            raise GenerationError(
                f"Run {run_id} persisted {count} spans, expected {args.spans_per_run}"
            )
    if summary["actual_spans"] != args.runs * args.spans_per_run:
        raise GenerationError(
            "Persisted span total does not match the requested dataset"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = {
        "parameters": vars(args),
        "task_id": None,
        "accepted_runs": 0,
        "completed_runs": 0,
        "success_runs": 0,
        "failed_runs": 0,
        "actual_spans": 0,
        "last_run_id": None,
        "complete": False,
    }
    code = 0
    try:
        generate(args, summary)
        summary["complete"] = True
    except (GenerationError, KeyboardInterrupt) as exc:
        summary["error"] = str(exc) or "Interrupted"
        print(summary["error"], file=sys.stderr)
        code = 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
