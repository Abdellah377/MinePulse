from app.main import app


def test_investigation_api_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/ai/investigations" in paths
    assert "/api/ai/investigations/{investigation_id}" in paths
