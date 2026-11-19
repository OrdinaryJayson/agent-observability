"""Bounded DAG validation, postdominators and budget estimation."""

from collections import deque

from .protocol import check_shape, schema

OPERATIONS = {"LLM", "TOOL", "RETRIEVAL"}


def graph(definition: dict):
    nodes = {node["node_key"]: node for node in definition["nodes"]}
    incoming = {key: [] for key in nodes}
    outgoing = {key: [] for key in nodes}
    for edge in definition["edges"]:
        incoming[edge["target"]].append(edge)
        outgoing[edge["source"]].append(edge)
    return nodes, incoming, outgoing


def topological(nodes, incoming, outgoing) -> list[str]:
    degree = {key: len(incoming[key]) for key in nodes}
    ready = deque(key for key in nodes if not degree[key])
    order = []
    while ready:
        key = ready.popleft()
        order.append(key)
        for edge in outgoing[key]:
            target = edge["target"]
            degree[target] -= 1
            if not degree[target]:
                ready.append(target)
    if len(order) != len(nodes):
        raise ValueError("Graph contains a cycle")
    return order


def estimate_budget(definition: dict) -> dict:
    # Two whole-worker recoveries may each restart every in-flight operation.
    attempts = sum(
        1 + node["config"].get("max_retries", 0) for node in definition["nodes"]
    )
    containers = 1 + len(definition["roles"])
    operations = [node for node in definition["nodes"] if node["type"] in OPERATIONS]
    logical = sum(
        node["config"]["duration_ms"] * (node["config"]["max_retries"] + 1)
        + sum((100, 200)[: int(node["config"]["max_retries"])])
        for node in operations
    )
    recovery_attempts = 2 * min(4, len(operations))
    logical += 2 * sum(
        sorted((node["config"]["duration_ms"] for node in operations), reverse=True)[:4]
    )
    spans = containers + attempts + recovery_attempts
    return {
        "spans": spans,
        "events": 2 * spans + 16,
        "journal": 8 * spans + len(definition["edges"]) + 64,
        "logical_ms": logical,
    }


def validate_workflow(definition: dict) -> dict:
    errors = []

    def error(message, node_key=None, edge_index=None, path=None):
        errors.append(
            {
                "code": "WORKFLOW_INVALID",
                "node_key": node_key,
                "edge_index": edge_index,
                "path": path,
                "message": message,
            }
        )

    try:
        check_shape(definition, schema("workflow.schema.json"))
    except (ValueError, TypeError) as exc:
        error(str(exc), path="$")
        return {"valid": False, "errors": errors}
    nodes = {node["node_key"]: node for node in definition["nodes"]}
    roles = {role["role_key"] for role in definition["roles"]}
    if len(nodes) != len(definition["nodes"]):
        error("Duplicate node key")
    if len(roles) != len(definition["roles"]):
        error("Duplicate role key")
    for key, node in nodes.items():
        if node["role_key"] is not None and node["role_key"] not in roles:
            error("Unknown role", key)
    pairs = set()
    for index, edge in enumerate(definition["edges"]):
        pair = (edge["source"], edge["target"], edge["route"])
        if (
            pair in pairs
            or pair[0] == pair[1]
            or any(key not in nodes for key in pair[:2])
        ):
            error(
                "Duplicate, self-referencing or missing edge endpoint", edge_index=index
            )
        pairs.add(pair)
    starts = [key for key in nodes if nodes[key]["type"] == "START"]
    ends = [key for key in nodes if nodes[key]["type"] == "END"]
    if len(starts) != 1 or len(ends) != 1:
        error("Exactly one START and END are required")
    if errors:
        return {"valid": False, "errors": errors}
    nodes, incoming, outgoing = graph(definition)
    start, end = starts[0], ends[0]
    if incoming[start] or outgoing[end]:
        error("START/END edges point in the wrong direction")
    for key, node in nodes.items():
        if node["type"] != "MERGE" and len(incoming[key]) > 1:
            error("Multiple inputs require MERGE", key)
        routes = [edge["route"] for edge in outgoing[key]]
        if node["type"] == "CONDITION":
            if sorted(routes) != ["FAIL", "PASS"]:
                error("CONDITION requires PASS and FAIL routes", key)
        elif any(route != "ALWAYS" for route in routes):
            error("Only CONDITION may have labelled routes", key)
    try:
        order = topological(nodes, incoming, outgoing)
    except ValueError as exc:
        error(str(exc))
        return {"valid": False, "errors": errors}
    reachable = {start}
    for key in order:
        if key in reachable:
            reachable.update(edge["target"] for edge in outgoing[key])
    postdom = {}
    for key in reversed(order):
        targets = [edge["target"] for edge in outgoing[key]]
        postdom[key] = {key} | (
            set.intersection(*(postdom[target] for target in targets))
            if targets
            else set()
        )
    if len(reachable) != len(nodes) or any(end not in postdom[key] for key in nodes):
        error("Every node must be reachable from START and lead to END")
    regions = []
    for key in order:
        if nodes[key]["type"] != "CONDITION" or len(outgoing[key]) != 2:
            continue
        candidates = postdom[key] - {key}
        nearest = next((target for target in order if target in candidates), None)
        if nearest is None or nodes[nearest]["type"] != "MERGE":
            error("Branches require a nearest common postdominating MERGE", key)
            continue
        branches = []
        for edge in outgoing[key]:
            seen, pending = set(), [edge["target"]]
            while pending:
                current = pending.pop()
                if current == nearest or current in seen:
                    continue
                seen.add(current)
                pending.extend(item["target"] for item in outgoing[current])
            branches.append(seen)
        if branches[0] & branches[1]:
            error("Branches cross before their structured MERGE", key)
        regions.append((key, branches[0] | branches[1]))
    for key in nodes:
        if sum(key in region for _, region in regions) > 4:
            error("Condition nesting exceeds four", key)
    budget = estimate_budget(definition)
    if any(
        budget[key] > limit
        for key, limit in {
            "spans": 500,
            "events": 2000,
            "journal": 5000,
            "logical_ms": 60000,
        }.items()
    ):
        error("Worst-case execution exceeds the run budget")
    return {"valid": not errors, "errors": errors}
