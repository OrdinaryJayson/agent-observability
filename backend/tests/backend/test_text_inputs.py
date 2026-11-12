import pytest


@pytest.mark.parametrize(
    "path,body,field",
    [
        ("/agents", {"name": "Agent", "role": "research"}, field)
        for field in ("name", "role", "provider", "model_name")
    ]
    + [
        ("/tasks", {"title": "Task"}, field)
        for field in ("title", "description", "scenario_type")
    ],
)
def test_zero_byte_text_returns_validation_error_without_writing(
    client, path, body, field
):
    response = client.post("/api/v1" + path, json={**body, field: "invalid\x00text"})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1" + path).json()["meta"]["total"] == 0


@pytest.mark.parametrize("field", ["name", "role", "provider", "model_name"])
def test_invalid_patch_preserves_original_agent(client, field):
    agent = client.post(
        "/api/v1/agents", json={"name": "Agent", "role": "research"}
    ).json()["data"]
    path = "/api/v1/agents/" + agent["agent_id"]
    response = client.patch(path, json={field: "invalid\x00text"})
    assert response.status_code == 422, response.text
    assert client.get(path).json()["data"] == agent


def test_invalid_error_filter_is_rejected(client):
    response = client.get("/api/v1/events", params={"error_type": "invalid\x00text"})
    assert response.status_code == 422, response.text


def test_unicode_and_multiline_text_round_trip(client):
    body = {"title": "中文任务 🧪", "description": "第一行\n第二行\t备注"}
    task = client.post("/api/v1/tasks", json=body)
    assert task.status_code == 201, task.text
    saved = client.get("/api/v1/tasks/" + task.json()["data"]["task_id"]).json()["data"]
    assert saved["title"] == body["title"]
    assert saved["description"] == body["description"]
