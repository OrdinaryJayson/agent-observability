"""Future Agent updates must be reachable from the separately hosted frontend."""

from fastapi.testclient import TestClient

from app.core.config import cors_origins
from app.main import app


def test_agent_patch_preflight():
    # No lifespan: a CORS preflight must not require a database or existing resource.
    client = TestClient(app)
    origin = cors_origins()[0]
    response = client.options(
        "/api/v1/agents/00000000-0000-0000-0000-000000000000",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "PATCH" in response.headers["access-control-allow-methods"]
    client.close()
