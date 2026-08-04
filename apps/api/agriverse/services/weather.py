import json
from contextlib import suppress
from datetime import UTC, datetime

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from agriverse.config import get_settings
from agriverse.schemas import ForecastRead, WeatherPoint
from agriverse.services.agronomy import evaluate_weather_alerts

settings = get_settings()


class WeatherUnavailableError(Exception):
    pass


class OpenMeteoProvider:
    async def current(self, latitude: float, longitude: float) -> ForecastRead:
        params: dict[str, str | float] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ("temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"),
            "hourly": ("temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"),
            "forecast_days": 3,
            "timezone": "auto",
        }
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{settings.open_meteo_base_url}/forecast", params=params)
            response.raise_for_status()
        current = response.json().get("current")
        if not isinstance(current, dict):
            raise WeatherUnavailableError("Weather provider returned no current conditions")
        observed_at = datetime.fromisoformat(str(current["time"]))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        point = WeatherPoint(
            observed_at=observed_at,
            temperature_c=float(current["temperature_2m"]),
            relative_humidity_pct=float(current["relative_humidity_2m"]),
            precipitation_mm=float(current["precipitation"]),
            wind_speed_kph=float(current["wind_speed_10m"]),
        )
        hourly = response.json().get("hourly", {})
        forecast: list[WeatherPoint] = []
        if isinstance(hourly, dict):
            times = hourly.get("time", [])
            temperatures = hourly.get("temperature_2m", [])
            humidities = hourly.get("relative_humidity_2m", [])
            precipitation = hourly.get("precipitation", [])
            winds = hourly.get("wind_speed_10m", [])
            for index, raw_time in enumerate(times):
                try:
                    forecast_at = datetime.fromisoformat(str(raw_time))
                    if forecast_at.tzinfo is None:
                        forecast_at = forecast_at.replace(tzinfo=UTC)
                    forecast.append(
                        WeatherPoint(
                            observed_at=forecast_at,
                            temperature_c=float(temperatures[index]),
                            relative_humidity_pct=float(humidities[index]),
                            precipitation_mm=float(precipitation[index]),
                            wind_speed_kph=float(winds[index]),
                        )
                    )
                except (IndexError, TypeError, ValueError):
                    continue
        return ForecastRead(
            source="open-meteo",
            fetched_at=datetime.now(UTC),
            current=point,
            forecast=forecast,
            alerts=evaluate_weather_alerts(point),
        )


class IMDProvider:
    """Adapter for a normalized IMD gateway managed by the platform team."""

    async def current(self, latitude: float, longitude: float) -> ForecastRead:
        if not settings.imd_api_base_url:
            raise WeatherUnavailableError("IMD gateway is not configured")
        headers = {}
        if settings.imd_api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {settings.imd_api_key.get_secret_value()}"
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{settings.imd_api_base_url.rstrip('/')}/forecast",
                params={"latitude": latitude, "longitude": longitude},
                headers=headers,
            )
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise WeatherUnavailableError("IMD gateway returned an invalid response")
        forecast = ForecastRead.model_validate(payload)
        return forecast.model_copy(update={"source": "imd", "fetched_at": datetime.now(UTC)})


class CachedWeatherService:
    def __init__(self) -> None:
        self._imd = IMDProvider()
        self._fallback = OpenMeteoProvider()
        self._redis = Redis.from_url(settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        await self._redis.aclose()

    async def get_current(
        self,
        *,
        cache_region: str,
        latitude: float,
        longitude: float,
    ) -> ForecastRead:
        cache_key = f"agriverse:weather:{cache_region.casefold()}"
        try:
            cached = await self._redis.get(cache_key)
        except RedisError:
            cached = None
        if cached:
            return ForecastRead.model_validate_json(cached)
        try:
            forecast = await self._imd.current(latitude, longitude)
        except (httpx.HTTPError, ValueError, WeatherUnavailableError):
            forecast = await self._fallback.current(latitude, longitude)
        with suppress(RedisError):
            await self._redis.set(cache_key, json.dumps(forecast.model_dump(mode="json")), ex=600)
        return forecast


weather_service = CachedWeatherService()
