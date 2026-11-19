from uuid import UUID

from app.contracts.v2 import digest
from app.services import v2_journal


def test_workflow_revision_and_cursor(client, samples, monkeypatch):
    from app.services import v2_engine

    monkeypatch.setattr(
        v2_engine, "validate_workflow", lambda d: {"valid": True, "errors": []}
    )
    body = {"name": "Draft", "draft": samples["workflow_definitions"]["parallel"]}
    workflows = []
    for _ in range(3):
        response = client.post("/api/v2/workflows", json=body)
        assert response.status_code == 201, response.text
        workflows.append(response.json()["data"])
    first = client.get("/api/v2/workflows?limit=2").json()
    second = client.get(
        "/api/v2/workflows", params={"limit": 2, "cursor": first["meta"]["next_cursor"]}
    ).json()
    assert len(first["data"] + second["data"]) == 3
    assert len({w["workflow_id"] for w in first["data"] + second["data"]}) == 3
    path = "/api/v2/workflows/" + workflows[0]["workflow_id"]
    assert client.patch(path, json={"name": "Changed"}).status_code == 428
    assert (
        client.patch(
            path, json={"name": "Changed"}, headers={"If-Match": '"1"'}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            path, json={"name": "Lost"}, headers={"If-Match": '"1"'}
        ).status_code
        == 412
    )
    assert (
        client.post(
            path + "/versions",
            json={"expected_definition_hash": digest(body["draft"])},
            headers={"If-Match": '"2"'},
        ).status_code
        == 201
    )
    assert client.get("/api/v2/workflows?unknown=1").status_code == 422


def test_cancelled_stream_replays_and_closes(client, prepared):
    run = prepared["start"]()["data"]
    v2_journal.cancel(UUID(run["run_id"]))
    path = "/api/v2/runs/" + run["run_id"]
    snapshot = client.get(path + "/snapshot")
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["data"]["seq"] == 3
    stream = client.get(path + "/stream?after_seq=0")
    assert stream.status_code == 200 and "event: run.finished" in stream.text
    assert [s for s in stream.text.splitlines() if s.startswith("id:")] == [
        "id: 1",
        "id: 2",
        "id: 3",
    ]
    ended = client.get(path + "/stream?after_seq=3")
    assert "event: stream.end" in ended.text and "id:" not in ended.text
    assert client.get(path + "/stream?after_seq=4").status_code == 422
    assert (
        client.get(
            path + "/stream?after_seq=0", headers={"Last-Event-ID": "3"}
        ).status_code
        == 422
    )
