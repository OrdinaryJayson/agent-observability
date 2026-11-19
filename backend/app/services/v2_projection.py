"""Database-boundary checks, not a workflow executor or journal reducer."""

from app.core.errors import AppError
from app.repositories.v2 import one


def validate(conn, execution, spans, links, final_status):
    if not spans:
        if links:
            raise AppError(
                422, "VALIDATION_ERROR", "Empty projection cannot have links"
            )
        return
    by_id = {s["span_id"]: s for s in spans}
    definition = one(
        conn,
        "SELECT definition FROM workflow_versions WHERE version_id=:id",
        id=execution["version_id"],
    )["definition"]
    nodes = {n["node_key"]: n for n in definition["nodes"]}
    roles = {r["role_key"] for r in definition["roles"]}
    root = next(s for s in spans if s["parent_span_id"] is None)

    def invalid(message):
        raise AppError(422, "VALIDATION_ERROR", message)

    if (
        root["operation_type"] != "WORKFLOW"
        or root["agent_id"] is not None
        or root["status"] != ("SUCCESS" if final_status == "SUCCESS" else "ERROR")
    ):
        invalid("Root identity or terminal state is invalid")
    containers = {}
    for span in spans:
        attrs = span["attributes"]
        if span["operation_type"] == "AGENT":
            role = attrs.get("role_key")
            if (
                role not in roles
                or role in containers
                or attrs.get("node_key") is not None
                or span["parent_span_id"] != root["span_id"]
            ):
                invalid("Invalid role container")
            containers[role] = span["span_id"]
    for span in spans:
        attrs = span["attributes"]
        node, role = attrs.get("node_key"), attrs.get("role_key")
        expected = execution["agent_bindings"].get(role) if role else None
        actual = str(span["agent_id"]) if span["agent_id"] is not None else None
        if actual != expected:
            invalid("Span identity differs from the accepted role binding")
        if span is root:
            if node is not None or role is not None:
                invalid("Root cannot claim a node or role identity")
        elif span["operation_type"] != "AGENT":
            if node not in nodes or role != nodes[node]["role_key"]:
                invalid("Step does not match the published definition")
            parent = containers.get(role) if role else root["span_id"]
            if span["parent_span_id"] != parent:
                invalid("Step has an incorrect role parent")
    if len(links) > 5000:
        invalid("Link budget exhausted")
    seen, edges = set(), {s: set() for s in by_id}
    indegree = dict.fromkeys(by_id, 0)
    for link in links:
        source, target, kind = (
            link["source_span_id"],
            link["target_span_id"],
            link["link_type"],
        )
        key = source, target, kind
        if (
            source not in by_id
            or target not in by_id
            or source == target
            or key in seen
            or kind not in {"DEPENDS_ON", "RETRY_OF", "HANDOFF"}
        ):
            invalid("Invalid or duplicate dependency link")
        seen.add(key)
        if kind == "DEPENDS_ON" and target not in edges[source]:
            edges[source].add(target)
            indegree[target] += 1
    ready = [key for key, count in indegree.items() if count == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for target in edges[current]:
            indegree[target] -= 1
            if not indegree[target]:
                ready.append(target)
    if visited != len(by_id):
        invalid("Dependency links contain a cycle")
