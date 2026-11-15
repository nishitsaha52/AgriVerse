from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from agriverse.schemas import CropScore, SoilTestCreate, WeatherAlertRead, WeatherPoint

ALGORITHM_VERSION = "2026.07.1"
SOIL_HEALTH_MANUAL_URL = (
    "https://soilhealth.dac.gov.in/files/Manual/140723DraftTeacherManual_PDF.pdf"
)
TNAU_SOIL_RATING_URL = "https://agritech.tnau.ac.in/agriculture/agri_soil_soilratingchart.html"
TNAU_RICE_URL = "https://www.agritech.tnau.ac.in/org_farm/orgfarm_prac_agri_paddy_climate.html"
TNAU_WHEAT_URL = "https://www.agritech.tnau.ac.in/agriculture/agri_faqs_cropproduction.html"
TNAU_TOMATO_URL = "https://agritech.tnau.ac.in/horticulture/horti_vegetables_tomato_Soil.html"
FERTILITY_SOURCES = [SOIL_HEALTH_MANUAL_URL, TNAU_SOIL_RATING_URL]
SOURCE_NOTE = (
    "Status thresholds follow the Government of India Soil Health manual and TNAU soil "
    "rating chart. Weights are the transparent AgriVerse v1 index policy; the index is "
    "descriptive and never a fertilizer or dosage recommendation."
)


@dataclass(frozen=True)
class NutrientRange:
    minimum: Decimal
    maximum: Decimal
    weight: Decimal
    penalize_excess: bool = False


NUTRIENT_RANGES: Mapping[str, NutrientRange] = {
    "n": NutrientRange(Decimal("240"), Decimal("480"), Decimal("0.14")),
    "p": NutrientRange(Decimal("11"), Decimal("22"), Decimal("0.10")),
    "k": NutrientRange(Decimal("110"), Decimal("280"), Decimal("0.12")),
    "ph": NutrientRange(Decimal("6.0"), Decimal("8.5"), Decimal("0.16"), True),
    "ec": NutrientRange(Decimal("0.0"), Decimal("1.0"), Decimal("0.08"), True),
    "oc": NutrientRange(Decimal("0.5"), Decimal("0.75"), Decimal("0.10")),
    "s": NutrientRange(Decimal("10"), Decimal("10000"), Decimal("0.06")),
    "zn": NutrientRange(Decimal("0.6"), Decimal("10000"), Decimal("0.06")),
    "fe": NutrientRange(Decimal("4.5"), Decimal("10000"), Decimal("0.05")),
    "cu": NutrientRange(Decimal("0.2"), Decimal("10000"), Decimal("0.03")),
    "mn": NutrientRange(Decimal("2.5"), Decimal("10000"), Decimal("0.05")),
    "b": NutrientRange(Decimal("0.5"), Decimal("10000"), Decimal("0.05")),
}


def _range_score(value: Decimal, target: NutrientRange) -> Decimal:
    if target.minimum <= value <= target.maximum:
        return Decimal("100")
    if value < target.minimum:
        if target.minimum == 0:
            return Decimal("100")
        return max(Decimal("0"), Decimal("100") * value / target.minimum)
    if target.maximum == 0:
        return Decimal("0")
    if not target.penalize_excess:
        return Decimal("100")
    overshoot = (value - target.maximum) / target.maximum
    return max(Decimal("0"), Decimal("100") * (Decimal("1") - overshoot))


def compute_fertility_index(soil: SoilTestCreate) -> Decimal:
    weighted = Decimal("0")
    total_weight = Decimal("0")
    values = soil.model_dump()
    for nutrient, target in NUTRIENT_RANGES.items():
        weighted += _range_score(Decimal(values[nutrient]), target) * target.weight
        total_weight += target.weight
    return (weighted / total_weight).quantize(Decimal("0.01"))


CropName = Literal["rice", "wheat", "tomato"]


@dataclass(frozen=True)
class CropPreference:
    ph: tuple[Decimal, Decimal]
    nitrogen: tuple[Decimal, Decimal]
    rainfall: tuple[float, float]
    temperature: tuple[float, float]
    source_url: str


CROP_PREFERENCES: dict[CropName, CropPreference] = {
    "rice": CropPreference(
        ph=(Decimal("5.0"), Decimal("6.5")),
        nitrogen=(Decimal("280"), Decimal("600")),
        rainfall=(1100.0, 1250.0),
        temperature=(21.0, 35.0),
        source_url=TNAU_RICE_URL,
    ),
    "wheat": CropPreference(
        ph=(Decimal("6.0"), Decimal("7.5")),
        nitrogen=(Decimal("280"), Decimal("560")),
        rainfall=(400.0, 1000.0),
        temperature=(20.0, 26.0),
        source_url=TNAU_WHEAT_URL,
    ),
    "tomato": CropPreference(
        ph=(Decimal("6.5"), Decimal("7.5")),
        nitrogen=(Decimal("250"), Decimal("500")),
        rainfall=(600.0, 1500.0),
        temperature=(15.0, 27.0),
        source_url=TNAU_TOMATO_URL,
    ),
}


def _bounded_fit(value: Decimal, lower: Decimal, upper: Decimal) -> float:
    if lower <= value <= upper:
        return 100.0
    distance = lower - value if value < lower else value - upper
    span = max(upper - lower, Decimal("0.01"))
    return max(0.0, 100.0 - float(distance / span) * 50.0)


def rank_crop_suitability(
    soil: SoilTestCreate,
    *,
    temperature_c: float | None = None,
    rainfall_mm: float | None = None,
) -> list[CropScore]:
    results: list[CropScore] = []
    for crop, preference in CROP_PREFERENCES.items():
        ph_score = _bounded_fit(soil.ph, *preference.ph)
        n_score = _bounded_fit(soil.n, *preference.nitrogen)
        components = [ph_score, n_score]
        reasons = [
            f"Soil pH fit: {ph_score:.0f}/100",
            f"Nitrogen fit: {n_score:.0f}/100",
            f"Source: {preference.source_url}",
        ]
        if temperature_c is not None:
            low, high = preference.temperature
            temp_score = _bounded_fit(
                Decimal(str(temperature_c)), Decimal(str(low)), Decimal(str(high))
            )
            components.append(temp_score)
            reasons.append(f"Temperature fit: {temp_score:.0f}/100")
        if rainfall_mm is not None:
            low, high = preference.rainfall
            rain_score = _bounded_fit(
                Decimal(str(rainfall_mm)), Decimal(str(low)), Decimal(str(high))
            )
            components.append(rain_score)
            reasons.append(f"Rainfall fit: {rain_score:.0f}/100")
        results.append(
            CropScore(crop=crop, score=round(sum(components) / len(components), 2), reasons=reasons)
        )
    return sorted(results, key=lambda result: result.score, reverse=True)


def evaluate_weather_alerts(point: WeatherPoint) -> list[WeatherAlertRead]:
    """Apply AgriVerse alert thresholds to provider conditions."""
    alerts: list[WeatherAlertRead] = []
    if point.temperature_c >= 40:
        alerts.append(
            WeatherAlertRead(
                alert_type="extreme_heat",
                severity="critical",
                message="Extreme heat risk. Avoid midday field work and review irrigation.",
            )
        )
    elif point.temperature_c >= 35:
        alerts.append(
            WeatherAlertRead(
                alert_type="heat",
                severity="warning",
                message="High temperature may increase crop water stress.",
            )
        )
    if point.precipitation_mm >= 64.5:
        alerts.append(
            WeatherAlertRead(
                alert_type="heavy_rain",
                severity="critical",
                message="Heavy rainfall may cause waterlogging and disease pressure.",
            )
        )
    elif point.precipitation_mm >= 20:
        alerts.append(
            WeatherAlertRead(
                alert_type="rain",
                severity="warning",
                message="Significant rainfall expected; review spraying and drainage plans.",
            )
        )
    if point.wind_speed_kph >= 40:
        alerts.append(
            WeatherAlertRead(
                alert_type="high_wind",
                severity="warning",
                message="High winds make spraying unsafe and may damage unsupported crops.",
            )
        )
    return alerts
