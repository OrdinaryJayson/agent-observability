"""SSE continuation with duplicate suppression and journal gap repair."""

from datetime import datetime, timezone
from http.client import HTTPException
import json
import time
from urllib.error import URLError
from urllib.request import Request

from _common import ToolError
from app.execution_v2.protocol import timestamp


def consume_stream(client, run_id, *, deadline):
    snapshot = client.request("GET", f"/runs/{run_id}/snapshot", deadline=deadline)
    last_seq = snapshot["seq"]
    delays, received = [], 0
    terminal = snapshot["run"]["status"] != "RUNNING"

    def accept(event):
        nonlocal last_seq, received, terminal
        seq = event["seq"]
        if seq <= last_seq:
            return
        if seq != last_seq + 1:
            raise ToolError("Journal repair did not close an SSE gap")
        last_seq = seq
        received += 1
        delays.append(
            (
                datetime.now(timezone.utc) - timestamp(event["recorded_at"])
            ).total_seconds()
            * 1000
        )
        terminal |= event["kind"] == "run.finished"

    for _ in range(3):
        if time.monotonic() >= deadline:
            break
        request = Request(
            client.url + f"/runs/{run_id}/stream?after_seq={last_seq}",
            headers={"Accept": "text/event-stream"},
        )
        try:
            with client.opener.open(
                request, timeout=min(20, max(0.1, deadline - time.monotonic()))
            ) as response:
                event_type, data_lines = None, []
                for raw_line in response:
                    if time.monotonic() >= deadline:
                        raise ToolError("SSE level deadline exceeded")
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                    elif not line:
                        if event_type == "stream.error":
                            break
                        if event_type == "stream.end":
                            if not terminal:
                                raise ToolError("Stream ended before a terminal fact")
                            return {
                                "last_seq": last_seq,
                                "received_events": received,
                                "propagation_ms": delays,
                            }
                        if data_lines:
                            event = json.loads("\n".join(data_lines))
                            while event["seq"] > last_seq + 1:
                                page = client.request(
                                    "GET",
                                    f"/runs/{run_id}/journal?after_seq={last_seq}&limit=100",
                                    raw=True,
                                    deadline=deadline,
                                )
                                before = last_seq
                                for missing in page["data"]:
                                    if missing["seq"] < event["seq"]:
                                        accept(missing)
                                if before == last_seq:
                                    raise ToolError(
                                        "SSE gap cannot be repaired from durable journal"
                                    )
                            accept(event)
                            if terminal:
                                return {
                                    "last_seq": last_seq,
                                    "received_events": received,
                                    "propagation_ms": delays,
                                }
                        event_type, data_lines = None, []
        except (OSError, URLError, HTTPException):
            continue
    raise ToolError("SSE disconnected without a terminal event after three attempts")
