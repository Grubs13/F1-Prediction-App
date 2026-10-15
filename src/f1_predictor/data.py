from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"


@dataclass(frozen=True)
class DriverResult:
    season: int
    round: int
    race_name: str
    circuit_id: str
    driver_id: str
    driver_code: str
    constructor_id: str
    finish_position: int
    classified: bool
    points: float


@dataclass(frozen=True)
class Race:
    season: int
    round: int
    race_name: str
    circuit_id: str
    date: str
    latitude: float | None
    longitude: float | None
    results: list[DriverResult]
    sprint_qualifying: dict[str, int] = field(default_factory=dict)
    sprint_results: dict[str, int] = field(default_factory=dict)


class JolpicaClient:
    def __init__(
        self,
        cache_dir: Path = Path("data/cache"),
        sleep_s: float = 0.15,
        refresh_cache: bool = False,
    ):
        self.cache_dir = cache_dir
        self.sleep_s = sleep_s
        self.refresh_cache = refresh_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, path: str) -> dict[str, Any]:
        safe_name = path.strip("/").replace("/", "__").replace("?", "_").replace("&", "_")
        cache_file = self.cache_dir / f"{safe_name}.json"
        if cache_file.exists() and not self.refresh_cache:
            return json.loads(cache_file.read_text())

        url = f"{JOLPICA_BASE}/{path.lstrip('/')}"
        req = urllib.request.Request(url, headers={"User-Agent": "f1-result-predictor/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Unable to fetch {url}: {exc}") from exc

        cache_file.write_text(payload)
        time.sleep(self.sleep_s)
        return json.loads(payload)

    def season_results(self, season: int) -> list[Race]:
        races = self._season_result_pages(season)
        return [_parse_race(race) for race in races if race.get("Results")]

    def season_schedule(self, season: int) -> list[Race]:
        data = self.get_json(f"{season}.json?limit=100")
        races = data["MRData"]["RaceTable"].get("Races", [])
        return [_parse_race(race) for race in races]

    def _season_result_pages(self, season: int) -> list[dict[str, Any]]:
        limit = 100
        offset = 0
        races_by_round: dict[int, dict[str, Any]] = {}
        total = None
        while total is None or offset < total:
            data = self.get_json(f"{season}/results.json?limit={limit}&offset={offset}")
            mrdata = data["MRData"]
            total = int(mrdata["total"])
            for race in mrdata["RaceTable"].get("Races", []):
                round_i = int(race["round"])
                if round_i not in races_by_round:
                    races_by_round[round_i] = race
                else:
                    races_by_round[round_i].setdefault("Results", []).extend(race.get("Results", []))
            offset += limit

        return [races_by_round[round_i] for round_i in sorted(races_by_round)]


def _parse_race(race: dict[str, Any]) -> Race:
    season_i = int(race["season"])
    round_i = int(race["round"])
    race_name = race["raceName"]
    circuit = race["Circuit"]
    circuit_id = circuit["circuitId"]
    location = circuit.get("Location", {})
    results: list[DriverResult] = []
    for row in race.get("Results", []):
        driver = row["Driver"]
        constructor = row["Constructor"]
        driver_code = driver.get("code") or driver.get("familyName", driver["driverId"])[:3].upper()
        status = row.get("status", "")
        results.append(
            DriverResult(
                season=season_i,
                round=round_i,
                race_name=race_name,
                circuit_id=circuit_id,
                driver_id=driver["driverId"],
                driver_code=driver_code.upper(),
                constructor_id=constructor["constructorId"],
                finish_position=int(row.get("position", 99)),
                classified=_is_classified(status),
                points=float(row.get("points", 0.0)),
            )
        )
    return Race(
        season=season_i,
        round=round_i,
        race_name=race_name,
        circuit_id=circuit_id,
        date=race.get("date", ""),
        latitude=_parse_float(location.get("lat")),
        longitude=_parse_float(location.get("long")),
        results=results,
    )


def load_odds(path: Path | None) -> dict[tuple[int, int, str], float]:
    if path is None or not path.exists():
        return {}
    odds: dict[tuple[int, int, str], float] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            decimal_odds = float(row["decimal_odds"])
            if decimal_odds <= 1:
                continue
            key = (int(row["season"]), int(row["round"]), row["driver_code"].upper())
            odds[key] = 1.0 / decimal_odds
    return odds


def load_weather(path: Path | None) -> dict[tuple[int, int], dict[str, float]]:
    if path is None or not path.exists():
        return {}
    weather: dict[tuple[int, int], dict[str, float]] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            key = (int(row["season"]), int(row["round"]))
            weather[key] = {
                "rain_probability": float(row.get("rain_probability") or 0.0),
                "track_temp_c": float(row.get("track_temp_c") or 25.0),
                "air_temp_c": float(row.get("air_temp_c") or 20.0),
                "wind_kph": float(row.get("wind_kph") or 0.0),
            }
    return weather


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _is_classified(status: str) -> bool:
    status_lower = status.lower()
    return status_lower in {"finished"} or "lap" in status_lower
