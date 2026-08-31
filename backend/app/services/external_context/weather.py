"""Site-scoped weather context. Uses DB site coordinates only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import monotonic

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Site
from app.services.external_context.cache import weather_cache
from app.services.external_context.models import WeatherContext, WeatherStatus
from app.services.external_context.provider import (
    WeatherProvider,
    WeatherProviderError,
    create_weather_provider,
)

logger = logging.getLogger(__name__)
NEGATIVE_CACHE_SECONDS = 60.0


def _unavailable(
    *,
    reason: str,
    provider: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    status: WeatherStatus = WeatherStatus.UNAVAILABLE,
    cache_hit: bool = False,
) -> WeatherContext:
    return WeatherContext(
        status=status,
        provider=provider,
        latitude=latitude,
        longitude=longitude,
        unavailableReason=reason,
        isDemo=False,
        cacheHit=cache_hit,
    )


def get_weather_context(
    session: Session,
    site_id: int,
    *,
    settings: Settings | None = None,
    provider: WeatherProvider | None = None,
    now: datetime | None = None,
    clock: float | None = None,
) -> WeatherContext:
    configured = settings or get_settings()
    started = monotonic()
    site = session.get(Site, site_id)
    if site is None:
        logger.info("weather_context status=UNAVAILABLE reason=site_not_found site_id=%s cache=miss", site_id)
        return _unavailable(reason="site_not_found")
    latitude = site.latitude
    longitude = site.longitude
    if latitude is None or longitude is None:
        logger.info(
            "weather_context status=UNAVAILABLE reason=missing_site_coordinates site_id=%s cache=miss",
            site_id,
        )
        return _unavailable(reason="missing_site_coordinates")

    cache_key = (site_id, "weather")
    stamp = clock if clock is not None else monotonic()
    cached = weather_cache.get(cache_key, now=stamp)
    if cached is not None:
        duration_ms = int((monotonic() - started) * 1000)
        logger.info(
            "weather_context status=%s provider=%s site_id=%s cache=hit duration_ms=%s",
            cached.status.value,
            cached.provider,
            site_id,
            duration_ms,
        )
        return cached.model_copy(update={"cacheHit": True})

    try:
        adapter = provider if provider is not None else create_weather_provider(configured)
    except WeatherProviderError as exc:
        result = _unavailable(reason=exc.category, status=WeatherStatus.ERROR, latitude=latitude, longitude=longitude)
        weather_cache.set(cache_key, result, NEGATIVE_CACHE_SECONDS, now=stamp)
        logger.info(
            "weather_context status=ERROR reason=%s site_id=%s cache=miss duration_ms=%s",
            exc.category,
            site_id,
            int((monotonic() - started) * 1000),
        )
        return result
    if adapter is None:
        result = _unavailable(
            reason="provider_not_configured",
            latitude=latitude,
            longitude=longitude,
        )
        logger.info(
            "weather_context status=UNAVAILABLE reason=provider_not_configured site_id=%s cache=miss",
            site_id,
        )
        return result

    try:
        observed_at, current, forecast = adapter.fetch(
            latitude,
            longitude,
            forecast_hours=configured.weather_forecast_hours,
        )
    except WeatherProviderError as exc:
        status = WeatherStatus.UNAVAILABLE if exc.category in {"unavailable", "timeout"} else WeatherStatus.ERROR
        result = _unavailable(
            reason=exc.category,
            provider=getattr(adapter, "provider_name", None),
            latitude=latitude,
            longitude=longitude,
            status=status,
        )
        weather_cache.set(cache_key, result, NEGATIVE_CACHE_SECONDS, now=stamp)
        logger.info(
            "weather_context status=%s reason=%s provider=%s site_id=%s cache=miss duration_ms=%s",
            status.value,
            exc.category,
            getattr(adapter, "provider_name", None),
            site_id,
            int((monotonic() - started) * 1000),
        )
        return result

    observed = now or datetime.now(timezone.utc)
    at = observed_at or observed
    freshness = max((observed - at).total_seconds(), 0.0)
    result = WeatherContext(
        status=WeatherStatus.AVAILABLE,
        provider=adapter.provider_name,
        observedAt=at,
        latitude=latitude,
        longitude=longitude,
        current=current,
        forecast=forecast,
        sourceFreshnessSeconds=freshness,
        isDemo=False,
        cacheHit=False,
    )
    weather_cache.set(cache_key, result, configured.weather_cache_ttl_seconds, now=stamp)
    logger.info(
        "weather_context status=AVAILABLE provider=%s site_id=%s cache=miss duration_ms=%s",
        adapter.provider_name,
        site_id,
        int((monotonic() - started) * 1000),
    )
    return result
