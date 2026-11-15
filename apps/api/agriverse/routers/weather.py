import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from agriverse.db import get_db
from agriverse.dependencies import require_permissions
from agriverse.models import WeatherAlert, WeatherSnapshot
from agriverse.routers.soil import authorize_field
from agriverse.schemas import ForecastRead
from agriverse.security import Principal
from agriverse.services.weather import WeatherUnavailableError, weather_service

router = APIRouter(tags=["weather"])


@router.get("/fields/{field_id}/weather", response_model=ForecastRead)
async def field_weather(
    field_id: uuid.UUID,
    principal: Principal = Depends(require_permissions("field:read")),
    db: AsyncSession = Depends(get_db),
) -> ForecastRead:
    field = await authorize_field(db, principal, field_id)
    try:
        forecast = await weather_service.get_current(
            cache_region=f"{field.state}:{field.district}",
            latitude=float(field.latitude),
            longitude=float(field.longitude),
        )
    except (httpx.HTTPError, WeatherUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weather service is temporarily unavailable. Please try again later.",
            headers={"Retry-After": "60"},
        ) from exc
    db.add(
        WeatherSnapshot(
            field_id=field.id,
            organization_id=principal.organization_id,
            source=forecast.source,
            forecast=forecast.model_dump(mode="json"),
            fetched_at=forecast.fetched_at,
        )
    )
    for alert in forecast.alerts:
        db.add(
            WeatherAlert(
                field_id=field.id,
                organization_id=principal.organization_id,
                alert_type=alert.alert_type,
                severity=alert.severity,
                payload=alert.model_dump(mode="json"),
            )
        )
    await db.commit()
    return forecast
