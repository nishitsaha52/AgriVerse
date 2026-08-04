from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agriverse.schemas import SoilTestCreate, WeatherPoint
from agriverse.services.agronomy import (
    NutrientRange,
    _bounded_fit,
    _range_score,
    compute_fertility_index,
    evaluate_weather_alerts,
    rank_crop_suitability,
)


def soil(**overrides: str) -> SoilTestCreate:
    values = {
        "n": "350",
        "p": "32",
        "k": "210",
        "ph": "6.5",
        "ec": "0.7",
        "oc": "0.9",
        "s": "14",
        "zn": "0.8",
        "fe": "6",
        "cu": "0.4",
        "mn": "3",
        "b": "0.7",
    }
    values.update(overrides)
    return SoilTestCreate(**values)


def test_fertility_index_is_perfect_inside_all_ranges() -> None:
    assert compute_fertility_index(soil()) == Decimal("100.00")


def test_fertility_index_penalizes_deficiency_and_excess_salinity() -> None:
    deficient = compute_fertility_index(soil(n="140"))
    excessive = compute_fertility_index(soil(ec="3"))
    assert deficient < Decimal("100")
    assert excessive < Decimal("100")
    assert deficient > Decimal("0")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("15", "100"),
        ("5", "50"),
        ("30", "100"),
    ],
)
def test_range_score(value: str, expected: str) -> None:
    target = NutrientRange(Decimal("10"), Decimal("20"), Decimal("1"))
    assert _range_score(Decimal(value), target) == Decimal(expected)


def test_range_score_handles_zero_bounds() -> None:
    zero_target = NutrientRange(Decimal("0"), Decimal("0"), Decimal("1"))
    assert _range_score(Decimal("-1"), zero_target) == Decimal("100")
    assert _range_score(Decimal("1"), zero_target) == Decimal("0")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("6.5", 100.0),
        ("5.0", 50.0),
        ("9.0", 0.0),
    ],
)
def test_bounded_fit(value: str, expected: float) -> None:
    assert _bounded_fit(Decimal(value), Decimal("6"), Decimal("7")) == expected


def test_crop_ranking_uses_optional_climate_inputs() -> None:
    soil_only = rank_crop_suitability(soil())
    with_climate = rank_crop_suitability(soil(), temperature_c=23.0, rainfall_mm=80.0)
    assert {entry.crop for entry in soil_only} == {"rice", "wheat", "tomato"}
    assert with_climate[0].crop in {"wheat", "tomato"}
    assert all(len(entry.reasons) == 5 for entry in with_climate)
    assert soil_only == sorted(soil_only, key=lambda entry: entry.score, reverse=True)


def weather(
    temperature: float,
    precipitation: float = 0,
    wind: float = 0,
) -> WeatherPoint:
    return WeatherPoint(
        observed_at=datetime.now(UTC),
        temperature_c=temperature,
        relative_humidity_pct=70,
        precipitation_mm=precipitation,
        wind_speed_kph=wind,
    )


def test_weather_alerts_cover_warning_and_critical_thresholds() -> None:
    critical = evaluate_weather_alerts(weather(41, precipitation=65, wind=45))
    warning = evaluate_weather_alerts(weather(36, precipitation=25))
    safe = evaluate_weather_alerts(weather(28))
    assert {alert.alert_type for alert in critical} == {
        "extreme_heat",
        "heavy_rain",
        "high_wind",
    }
    assert {alert.alert_type for alert in warning} == {"heat", "rain"}
    assert safe == []
