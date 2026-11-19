"""The three frozen scenarios, copied on request so callers can edit safely."""

from copy import deepcopy
import json
from pathlib import Path


def workflow_templates() -> dict:
    path = Path(__file__).resolve().parents[3] / "contracts/v2/examples.json"
    return deepcopy(
        json.loads(path.read_text(encoding="utf-8"))["workflow_definitions"]
    )


def load_workflow() -> dict:
    nodes = [
        {
            "node_key": "start",
            "name": "Start",
            "type": "START",
            "role_key": None,
            "config": {},
        }
    ]
    for index in range(16):
        nodes.append(
            {
                "node_key": f"step_{index:02d}",
                "name": f"Step {index}",
                "type": "LLM" if index % 3 == 0 else "TOOL",
                "role_key": "operator",
                "config": {
                    "duration_ms": 100,
                    "failure_probability": 0,
                    "max_retries": 0,
                },
            }
        )
    nodes.extend(
        [
            {
                "node_key": "merge",
                "name": "Merge",
                "type": "MERGE",
                "role_key": None,
                "config": {},
            },
            {
                "node_key": "generate",
                "name": "Generate",
                "type": "LLM",
                "role_key": "operator",
                "config": {
                    "duration_ms": 100,
                    "failure_probability": 0,
                    "max_retries": 0,
                },
            },
            {
                "node_key": "end",
                "name": "End",
                "type": "END",
                "role_key": None,
                "config": {},
            },
        ]
    )
    edges = []
    for branch in range(4):
        chain = [
            "start",
            *(f"step_{index:02d}" for index in range(branch * 4, branch * 4 + 4)),
            "merge",
        ]
        edges.extend(
            {"source": first, "target": second, "route": "ALWAYS"}
            for first, second in zip(chain, chain[1:])
        )
    edges.extend(
        [
            {"source": "merge", "target": "generate", "route": "ALWAYS"},
            {"source": "generate", "target": "end", "route": "ALWAYS"},
        ]
    )
    return {
        "schema_version": "2.0",
        "scenario": "RESEARCH_PIPELINE",
        "roles": [{"role_key": "operator", "name": "Load operator"}],
        "nodes": nodes,
        "edges": edges,
    }
