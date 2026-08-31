from app.main import app


def test_alert_and_optimizer_routes_registered():
    paths = {route.path for route in app.routes}
    assert "/api/alerts" in paths
    assert "/api/alerts/active-count" in paths
    assert "/api/alerts/{alert_id}" in paths
    assert "/api/actions/inbox" in paths
    assert "/api/actions/inbox/{alert_id}" in paths
    assert "/api/optimization/runs" in paths
