"""Read-only external operational context. Weather is the V1 source.

Does not mutate roads, equipment, or hidden simulation state.
"""

from app.services.external_context.models import WeatherContext
from app.services.external_context.weather import get_weather_context

__all__ = ["WeatherContext", "get_weather_context"]
