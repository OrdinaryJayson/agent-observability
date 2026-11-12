import pytest


@pytest.mark.parametrize(
    "path,parameter",
    [
        ("/runs", "start_time"),
        ("/runs", "end_time"),
        ("/events", "from"),
        ("/analytics/overview", "to"),
    ],
)
@pytest.mark.parametrize(
    "value", ["0001-01-01T00:00:00+08:00", "9999-12-31T23:59:59-08:00"]
)
def test_utc_overflow_is_a_validation_error(client, path, parameter, value):
    response = client.get("/api/v1" + path, params={parameter: value})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
