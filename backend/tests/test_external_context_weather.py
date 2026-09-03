from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from app.ai.contracts import (
    EvidenceKind,
    EvidenceRequest,
    EvidenceRequestType,
    EvidenceStatus,
    InvestigationTrigger,
    TriggerSource,
    TriggerType,
)
from app.ai.tools import external as external_tools
from app.ai.tools.registry import EvidenceToolRegistry
from app.api.deps import operational_context
from app.config import Settings
from app.db.database import get_db
from app.db.models import Site
from app.main import app
from app.services.external_context.cache import weather_cache
from app.services.external_context.models import WeatherHorizon, WeatherStatus
from app.services.external_context.provider import (
    OPEN_METEO_URL,
    OpenMeteoWeatherProvider,
    WeatherProviderError,
    create_weather_provider,
    map_openmeteo_payload,
)
from app.services.external_context.weather import get_weather_context
from app.services.operational.context import OperationalContext

NOW = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
OPENMETEO_PAYLOAD = {
    "current": {
        "time": "2026-08-31T12:00",
        "temperature_2m": 28.4,
        "apparent_temperature": 29.1,
        "relative_humidity_2m": 41,
        "precipitation": 0.0,
        "weather_code": 1,
        "cloud_cover": 18,
        "wind_speed_10m": 22.0,
        "wind_direction_10m": 250,
        "wind_gusts_10m": 35.5,
        "visibility": 12000,
    },
    "hourly": {
        "time": ["2026-08-31T13:00", "2026-08-31T14:00", "2026-08-31T15:00"],
        "temperature_2m": [27.0, 26.2, 25.1],
        "apparent_temperature": [27.4, 26.0, 24.8],
        "relative_humidity_2m": [44, 48, 52],
        "precipitation": [0.2, 1.4, 0.0],
        "precipitation_probability": [20, 55, 10],
        "weather_code": [61, 63, 2],
        "cloud_cover": [40, 80, 30],
        "wind_speed_10m": [24.0, 28.0, 18.0],
        "wind_direction_10m": [240, 230, 220],
        "wind_gusts_10m": [38.0, 44.0, 26.0],
        "visibility": [8000, 2000, 10000],
    },
}
PACKAGE = Path(__file__).resolve().parents[1] / "app" / "services" / "external_context"


class SiteSession:
    def __init__(self, *sites: Site):
        self.sites = {site.site_id: site for site in sites}

    def get(self, model, key):
        if model is Site:
            return self.sites.get(key)
        return None


class ScriptedWeather:
    provider_name = "openmeteo"

    def __init__(self):
        self.calls = []

    def fetch(self, latitude, longitude, *, forecast_hours):
        self.calls.append((latitude, longitude, forecast_hours))
        return map_openmeteo_payload(OPENMETEO_PAYLOAD, forecast_hours=forecast_hours)


def _site(*, site_id=1, lat=32.6618173, lon=-6.6735342):
    return Site(
        site_id=site_id,
        code=f"SITE-{site_id}",
        name="Merah",
        latitude=lat,
        longitude=lon,
        timezone="Africa/Casablanca",
        active=True,
        created_at=NOW,
    )


def _settings(**overrides):
    values = {
        "weather_provider": "openmeteo",
        "weather_timeout_seconds": 5,
        "weather_cache_ttl_seconds": 600,
        "weather_forecast_hours": 3,
    }
    values.update(overrides)
    return Settings(**values)


def _context(site=None):
    site = site or _site()
    return OperationalContext(
        site=site,
        shift=None,
        sim_now=NOW,
        shift_window_start=NOW,
        shift_window_end=NOW,
    )


def setup_function():
    weather_cache.clear()


def test_openmeteo_maps_to_canonical_model_and_keeps_missing_null():
    observed, current, forecast = map_openmeteo_payload(OPENMETEO_PAYLOAD, forecast_hours=3)
    assert observed.hour == 12
    assert current.temperatureC == 28.4
    assert current.visibilityKm == 12.0
    assert current.horizon == WeatherHorizon.CURRENT
    assert current.notObservedFact is False
    assert current.precipitationProbabilityPercent is None
    assert current.condition == "Mainly clear"
    assert len(forecast) == 3
    assert forecast[0].horizon == WeatherHorizon.FORECAST
    assert forecast[0].notObservedFact is True
    assert forecast[1].precipitationProbabilityPercent == 55
    assert forecast[1].visibilityKm == 2.0
    _observed, sparse, hours = map_openmeteo_payload(
        {"current": {"time": "2026-08-31T12:00", "temperature_2m": 10}},
        forecast_hours=3,
    )
    assert sparse.windSpeedKmh is None
    assert sparse.condition is None
    assert hours == []
    assert "current_weather" not in current.model_dump()


def test_malformed_timeout_and_unavailable_provider_errors():
    try:
        map_openmeteo_payload({"hourly": {}}, forecast_hours=3)
    except WeatherProviderError as exc:
        assert exc.category == "malformed"
    else:
        raise AssertionError("expected malformed")

    class TimeoutClient:
        def get(self, *args, **kwargs):
            raise httpx.TimeoutException("timed out")

        def close(self):
            return None

    try:
        OpenMeteoWeatherProvider(timeout_seconds=1, client=TimeoutClient()).fetch(32.6, -6.6, forecast_hours=3)
    except WeatherProviderError as exc:
        assert exc.category == "timeout"
    else:
        raise AssertionError("expected timeout")

    class DownClient:
        def get(self, *args, **kwargs):
            raise httpx.ConnectError("offline")

        def close(self):
            return None

    try:
        OpenMeteoWeatherProvider(timeout_seconds=1, client=DownClient()).fetch(32.6, -6.6, forecast_hours=3)
    except WeatherProviderError as exc:
        assert exc.category == "unavailable"
    else:
        raise AssertionError("expected unavailable")


def test_provider_does_not_send_or_log_api_keys():
    captured = {}

    class Client:
        def get(self, url, params):
            captured["url"] = url
            captured["params"] = params
            request = httpx.Request("GET", url)
            return httpx.Response(200, json=OPENMETEO_PAYLOAD, request=request)

        def close(self):
            return None

    OpenMeteoWeatherProvider(timeout_seconds=5, client=Client()).fetch(32.66, -6.67, forecast_hours=3)
    assert captured["url"] == OPEN_METEO_URL
    assert "api_key" not in captured["params"]
    source = (PACKAGE / "provider.py").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in source
    assert "api_key=" not in source
    assert "sk-" not in str(captured)


def test_authoritative_site_coordinates_and_missing_coords():
    provider = ScriptedWeather()
    located = get_weather_context(SiteSession(_site()), 1, settings=_settings(), provider=provider, now=NOW)
    assert located.status == WeatherStatus.AVAILABLE
    assert located.latitude == 32.6618173
    assert located.longitude == -6.6735342
    assert provider.calls[0][:2] == (32.6618173, -6.6735342)

    missing = get_weather_context(
        SiteSession(_site(lat=None, lon=None)),
        1,
        settings=_settings(),
        provider=provider,
        now=NOW,
    )
    assert missing.status == WeatherStatus.UNAVAILABLE
    assert missing.unavailableReason == "missing_site_coordinates"
    assert len(provider.calls) == 1


def test_cache_hit_expiry_and_site_isolation():
    provider = ScriptedWeather()
    settings = _settings(weather_cache_ttl_seconds=100)
    first = get_weather_context(SiteSession(_site()), 1, settings=settings, provider=provider, now=NOW, clock=0)
    second = get_weather_context(SiteSession(_site()), 1, settings=settings, provider=provider, now=NOW, clock=50)
    assert first.cacheHit is False
    assert second.cacheHit is True
    assert len(provider.calls) == 1
    expired = get_weather_context(SiteSession(_site()), 1, settings=settings, provider=provider, now=NOW, clock=101)
    assert expired.cacheHit is False
    assert len(provider.calls) == 2

    other = get_weather_context(
        SiteSession(_site(site_id=2, lat=32.7, lon=-6.7)),
        2,
        settings=settings,
        provider=provider,
        now=NOW,
        clock=50,
    )
    assert other.cacheHit is False
    assert len(provider.calls) == 3
    assert provider.calls[-1][:2] == (32.7, -6.7)


def test_weather_evidence_is_fact_with_forecast_labeled_and_provenance(monkeypatch):
    provider = ScriptedWeather()
    session = SiteSession(_site())
    monkeypatch.setattr(
        "app.ai.tools.external.get_weather_context",
        lambda s, site_id, **kwargs: get_weather_context(
            s, site_id, settings=_settings(), provider=provider, now=NOW
        ),
    )
    item = external_tools.weather_context(session, _context())
    assert item.kind == EvidenceKind.FACT
    assert item.source_tool == "weather_context"
    assert item.source_service.endswith("get_weather_context")
    assert item.available is True
    assert item.value["current"]["horizon"] == "CURRENT"
    assert item.value["forecast"][0]["horizon"] == "FORECAST"
    assert item.value["forecast"][0]["notObservedFact"] is True
    assert item.metadata["contextType"] == "CURRENT_WEATHER"
    assert item.metadata["forecastIsNotObservedFact"] is True
    assert item.metadata["authoritativeRoadStatusWins"] is True
    assert "site:1" in item.source_record_ids
    blob = item.model_dump_json()
    assert "current_weather" not in blob


def test_unavailable_weather_does_not_fail_investigation():
    site = _site(lat=None)
    item = external_tools.weather_context(SiteSession(site), _context(site))
    assert item.available is False
    assert item.status == EvidenceStatus.UNAVAILABLE
    assert item.value is None


def test_relevance_includes_congestion_and_haul_not_mechanical():
    captured = []

    def fake_safe(self, ctx, name, call, **kwargs):
        captured.append(name)
        return SimpleNamespace(kind=EvidenceKind.FACT, source_tool=name)

    original = EvidenceToolRegistry._safe_call
    EvidenceToolRegistry._safe_call = fake_safe
    try:
        EvidenceToolRegistry(object()).gather_initial(
            _context(),
            InvestigationTrigger(
                trigger_type=TriggerType.CONGESTION_RISK,
                trigger_source=TriggerSource.AUTOMATIC_MONITORING,
                site_id=1,
                occurred_at=NOW,
                payload={"reason": "haul wait"},
            ),
        )
        congestion = list(captured)
        captured.clear()
        EvidenceToolRegistry(object()).gather_initial(
            _context(),
            InvestigationTrigger(
                trigger_type=TriggerType.EQUIPMENT_ANOMALY,
                trigger_source=TriggerSource.EXISTING_ALERT,
                site_id=1,
                equipment_id=7,
                occurred_at=NOW,
                payload={"title": "Engine oil pressure low"},
            ),
        )
        mechanical = list(captured)
        captured.clear()
        EvidenceToolRegistry(object()).gather_initial(
            _context(),
            InvestigationTrigger(
                trigger_type=TriggerType.EQUIPMENT_ANOMALY,
                trigger_source=TriggerSource.EXISTING_ALERT,
                site_id=1,
                equipment_id=7,
                occurred_at=NOW,
                payload={"title": "Low visibility after rain on haul"},
            ),
        )
        weather_mentioned = list(captured)
    finally:
        EvidenceToolRegistry._safe_call = original
    assert "weather_context" in congestion
    assert "weather_context" not in mechanical
    assert "weather_context" in weather_mentioned


def test_weather_package_does_not_import_simulator_or_road_mutations():
    forbidden = (
        "from simulator",
        "app.simulator",
        "app.services.operational.roads",
        "create_road",
        "update_road",
        "delete_road",
        "SITE_CENTER",
    )
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} contains {token}"
    ai_source = (Path(__file__).resolve().parents[1] / "app" / "ai" / "tools" / "external.py").read_text(
        encoding="utf-8"
    )
    assert "app.services.external_context.weather" in ai_source
    assert "app.services.operational.roads" not in ai_source
    assert "simulator" not in ai_source


def test_disabled_provider_and_api_canonical_error(monkeypatch):
    site = _site()
    session = SiteSession(site)
    disabled = get_weather_context(session, 1, settings=_settings(weather_provider=None), now=NOW)
    assert disabled.status == WeatherStatus.UNAVAILABLE
    assert disabled.unavailableReason == "provider_not_configured"
    assert disabled.isDemo is False

    failing = ScriptedWeather()
    failing.fetch = lambda *args, **kwargs: (_ for _ in ()).throw(WeatherProviderError("unavailable", "down"))
    errored = get_weather_context(session, 1, settings=_settings(), provider=failing, now=NOW)
    assert errored.status == WeatherStatus.UNAVAILABLE
    assert "current_weather" not in errored.model_dump()

    monkeypatch.setattr("app.api.routes.external_context.get_weather_context", lambda session, site_id: errored)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[operational_context] = lambda: _context(site)
    try:
        response = TestClient(app).get("/api/external-context/weather")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "UNAVAILABLE"
        assert body["unavailableReason"] == "unavailable"
        assert "current_weather" not in body
        assert "hourly" not in body
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(operational_context, None)


def test_registry_dispatches_weather_context(monkeypatch):
    from app.ai.contracts import EvidenceItem

    def fake(session, ctx):
        return EvidenceItem(
            kind=EvidenceKind.FACT,
            source_tool="weather_context",
            source_service="app.services.external_context.weather.get_weather_context",
            metric="weather_context",
            value={"status": "AVAILABLE", "isDemo": False},
        )

    monkeypatch.setattr("app.ai.tools.registry.external_tools.weather_context", fake)
    request = EvidenceRequest(
        request_type=EvidenceRequestType.WEATHER_CONTEXT,
        reason="Need weather for haul visibility.",
    )
    evidence = EvidenceToolRegistry(object()).dispatch(_context(), request)
    assert evidence.source_tool == "weather_context"
    assert EvidenceRequestType.WEATHER_CONTEXT.value == "WEATHER_CONTEXT"


def test_create_provider_none_when_unset():
    assert create_weather_provider(_settings(weather_provider=None)) is None
    assert create_weather_provider(_settings(weather_provider="none")) is None


def test_openmeteo_aliases_are_supported_and_unknown_names_are_unsupported():
    assert create_weather_provider(_settings(weather_provider="openmeteo")) is not None
    assert create_weather_provider(_settings(weather_provider="open-meteo")) is not None
    assert create_weather_provider(_settings(weather_provider="open_meteo")) is not None
    try:
        create_weather_provider(_settings(weather_provider="not-a-provider"))
    except WeatherProviderError as exc:
        assert exc.category == "unsupported_provider"
    else:
        raise AssertionError("expected unsupported_provider")

