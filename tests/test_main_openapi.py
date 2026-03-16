import main


def test_openapi_builds_with_signal_run_request():
    schema = main.app.openapi()

    assert "/api/signals/run" in schema["paths"]
    assert "/api/proposals/build" in schema["paths"]
    assert "/api/proposals/latest" in schema["paths"]
    assert "/api/candidates/latest" in schema["paths"]
    request_body = schema["paths"]["/api/signals/run"]["post"]["requestBody"]
    assert request_body["required"] is True
