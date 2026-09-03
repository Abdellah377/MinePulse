"""Weather provider protocol and Open-Meteo adapter.

Consumers must use the canonical WeatherContext, never Open-Meteo keys.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.services.external_context.models import WeatherForecastHour, WeatherHorizon, WeatherObservation

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_CURRENT = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,"
    "weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility"
)
OPEN_METEO_HOURLY = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,"
    "precipitation_probability,weather_code,cloud_cover,wind_speed_10m,"
    "wind_direction_10m,wind_gusts_10m,visibility"
)

# Known WMO codes only. Unknown codes stay null — never invent a condition.
_WMO_CONDITION = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Slight rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherProviderError(RuntimeError):
    """Provider call failed. Callers map this to ERROR, never raise into LangGraph."""

    def __init__(self, category: str, message: str = ""):
        super().__init__(message or category)
        self.category = category


class WeatherProvider(Protocol):
    provider_name: str

    def fetch(
        self,
        latitude: float,
        longitude: float,
        *,
        forecast_hours: int,
    ) -> tuple[datetime | None, WeatherObservation | None, list[WeatherForecastHour]]: ...


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _visibility_km(value) -> float | None:
    meters = _num(value)
    if meters is None:
        return None
    return meters / 1000.0


def condition_for_code(code: int | None) -> str | None:
    if code is None:
        return None
    return _WMO_CONDITION.get(code)


def _parse_time(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def map_openmeteo_payload(
    payload: dict,
    *,
    forecast_hours: int,
) -> tuple[datetime | None, WeatherObservation | None, list[WeatherForecastHour]]:
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    observed_at = _parse_time(current.get("time"))
    code = _int(current.get("weather_code"))
    observation = WeatherObservation(
        horizon=WeatherHorizon.CURRENT,
        notObservedFact=False,
        temperatureC=_num(current.get("temperature_2m")),
        apparentTemperatureC=_num(current.get("apparent_temperature")),
        humidityPercent=_num(current.get("relative_humidity_2m")),
        precipitationMm=_num(current.get("precipitation")),
        precipitationProbabilityPercent=None,
        windSpeedKmh=_num(current.get("wind_speed_10m")),
        windGustKmh=_num(current.get("wind_gusts_10m")),
        windDirectionDeg=_num(current.get("wind_direction_10m")),
        visibilityKm=_visibility_km(current.get("visibility")),
        weatherCode=code,
        condition=condition_for_code(code),
        cloudCoverPercent=_num(current.get("cloud_cover")),
    )
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
    limit = max(1, min(forecast_hours, 3))
    forecast: list[WeatherForecastHour] = []
    for index, raw_time in enumerate(times[:limit]):
        hour_code = _int(_hourly_at(hourly, "weather_code", index))
        forecast.append(
            WeatherForecastHour(
                horizon=WeatherHorizon.FORECAST,
                notObservedFact=True,
                validAt=_parse_time(raw_time if isinstance(raw_time, str) else None),
                temperatureC=_num(_hourly_at(hourly, "temperature_2m", index)),
                apparentTemperatureC=_num(_hourly_at(hourly, "apparent_temperature", index)),
                humidityPercent=_num(_hourly_at(hourly, "relative_humidity_2m", index)),
                precipitationMm=_num(_hourly_at(hourly, "precipitation", index)),
                precipitationProbabilityPercent=_num(_hourly_at(hourly, "precipitation_probability", index)),
                windSpeedKmh=_num(_hourly_at(hourly, "wind_speed_10m", index)),
                windGustKmh=_num(_hourly_at(hourly, "wind_gusts_10m", index)),
                windDirectionDeg=_num(_hourly_at(hourly, "wind_direction_10m", index)),
                visibilityKm=_visibility_km(_hourly_at(hourly, "visibility", index)),
                weatherCode=hour_code,
                condition=condition_for_code(hour_code),
                cloudCoverPercent=_num(_hourly_at(hourly, "cloud_cover", index)),
            )
        )
    if observation.temperatureC is None and observation.weatherCode is None and not forecast:
        raise WeatherProviderError("malformed", "Open-Meteo payload had no usable weather fields")
    return observed_at, observation, forecast


def _hourly_at(hourly: dict, key: str, index: int):
    series = hourly.get(key)
    if not isinstance(series, list) or index >= len(series):
        return None
    return series[index]


class OpenMeteoWeatherProvider:
    provider_name = "openmeteo"

    def __init__(self, *, timeout_seconds: float, client: httpx.Client | None = None):
        self._timeout = timeout_seconds
        self._client = client

    def fetch(
        self,
        latitude: float,
        longitude: float,
        *,
        forecast_hours: int,
    ) -> tuple[datetime | None, WeatherObservation | None, list[WeatherForecastHour]]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": OPEN_METEO_CURRENT,
            "hourly": OPEN_METEO_HOURLY,
            "forecast_hours": max(1, min(forecast_hours, 3)),
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "timezone": "UTC",
        }
        client = self._client or httpx.Client(timeout=self._timeout)
        close = self._client is None
        try:
            response = client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise WeatherProviderError("timeout", "Weather provider timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise WeatherProviderError("http_error", "Weather provider returned an error status") from exc
        except httpx.HTTPError as exc:
            raise WeatherProviderError("unavailable", "Weather provider is unavailable") from exc
        except ValueError as exc:
            raise WeatherProviderError("malformed", "Weather provider returned invalid JSON") from exc
        finally:
            if close:
                client.close()
        if not isinstance(payload, dict):
            raise WeatherProviderError("malformed", "Weather provider returned a non-object payload")
        try:
            return map_openmeteo_payload(payload, forecast_hours=forecast_hours)
        except WeatherProviderError:
            raise
        except Exception as exc:
            raise WeatherProviderError("malformed", "Weather provider payload could not be mapped") from exc


def create_weather_provider(settings: Settings | None = None, *, client: httpx.Client | None = None) -> WeatherProvider | None:
    configured = settings or get_settings()
    name = (configured.weather_provider or "").strip().lower()
    if not name or name in {"none", "off", "disabled"}:
        return None
    if name not in {"openmeteo", "open-meteo", "open_meteo"}:
        raise WeatherProviderError("unsupported_provider", f"Unsupported WEATHER_PROVIDER: {name}")
    return OpenMeteoWeatherProvider(timeout_seconds=configured.weather_timeout_seconds, client=client)
