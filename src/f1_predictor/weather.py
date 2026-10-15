from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .data import Race


ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"


def build_weather_csv(races: list[Race], output_csv: Path, cache_dir: Path, refresh_cache: bool = False) -> Path:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    seen: set[tuple[int, int]] = set()
    today = date.today()
    for race in races:
        key = (race.season, race.round)
        if key in seen or race.latitude is None or race.longitude is None or not race.date:
            continue
        seen.add(key)
        race_date = date.fromisoformat(race.date)
        if race_date >= today - timedelta(days=5):
            data = _fetch_forecast(race, cache_dir, refresh_cache=refresh_cache)
            rows.append(_forecast_row(race, data))
        else:
            data = _fetch_archive(race, cache_dir, refresh_cache=refresh_cache)
            rows.append(_archive_row(race, data))

    with output_csv.open("w", newline="") as handle:
        fieldnames = ["season", "round", "rain_probability", "track_temp_c", "air_temp_c", "wind_kph"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_csv


def _fetch_archive(race: Race, cache_dir: Path, refresh_cache: bool) -> dict[str, Any]:
    params = {
        "latitude": race.latitude,
        "longitude": race.longitude,
        "start_date": race.date,
        "end_date": race.date,
        "daily": "precipitation_sum,temperature_2m_max,wind_speed_10m_max",
        "timezone": "UTC",
    }
    return _get_json(
        ARCHIVE_BASE,
        params,
        cache_dir / f"weather_archive_{race.season}_{race.round}.json",
        refresh_cache=refresh_cache,
    )


def _fetch_forecast(race: Race, cache_dir: Path, refresh_cache: bool) -> dict[str, Any]:
    params = {
        "latitude": race.latitude,
        "longitude": race.longitude,
        "start_date": race.date,
        "end_date": race.date,
        "daily": "precipitation_probability_max,temperature_2m_max,wind_speed_10m_max",
        "timezone": "UTC",
    }
    return _get_json(
        FORECAST_BASE,
        params,
        cache_dir / f"weather_forecast_{race.season}_{race.round}.json",
        refresh_cache=refresh_cache,
    )


def _get_json(
    base_url: str,
    params: dict[str, object],
    cache_file: Path,
    refresh_cache: bool,
) -> dict[str, Any]:
    if cache_file.exists() and not refresh_cache:
        return json.loads(cache_file.read_text())
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "f1-result-predictor/0.1"})
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = response.read().decode("utf-8")
    cache_file.write_text(payload)
    time.sleep(0.1)
    return json.loads(payload)


def _archive_row(race: Race, data: dict[str, Any]) -> dict[str, float | int]:
    daily = data.get("daily", {})
    precipitation = _first(daily.get("precipitation_sum"), 0.0)
    return {
        "season": race.season,
        "round": race.round,
        "rain_probability": min(float(precipitation) / 10.0, 1.0),
        "track_temp_c": _first(daily.get("temperature_2m_max"), 25.0),
        "air_temp_c": _first(daily.get("temperature_2m_max"), 20.0),
        "wind_kph": _first(daily.get("wind_speed_10m_max"), 0.0),
    }


def _forecast_row(race: Race, data: dict[str, Any]) -> dict[str, float | int]:
    daily = data.get("daily", {})
    return {
        "season": race.season,
        "round": race.round,
        "rain_probability": _first(daily.get("precipitation_probability_max"), 0.0) / 100.0,
        "track_temp_c": _first(daily.get("temperature_2m_max"), 25.0),
        "air_temp_c": _first(daily.get("temperature_2m_max"), 20.0),
        "wind_kph": _first(daily.get("wind_speed_10m_max"), 0.0),
    }


def _first(values: list[float] | None, default: float) -> float:
    if not values or values[0] is None:
        return default
    return float(values[0])
