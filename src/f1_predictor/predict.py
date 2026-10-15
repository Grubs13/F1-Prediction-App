from __future__ import annotations

import json
from dataclasses import fields
from datetime import date
from pathlib import Path
import csv

from .data import DriverResult, JolpicaClient, Race, load_weather
from .model import F1Predictor, ModelWeights, Prediction
from .weather import build_weather_csv
from .sprint import SprintClient


def predict_next_race(
    season: int,
    train_from: int,
    cache_dir: Path,
    output_dir: Path,
    auto_weather: bool = False,
    refresh_cache: bool = False,
    weights: ModelWeights | None = None,
) -> tuple[Race, list[Prediction]]:
    client = JolpicaClient(cache_dir=cache_dir, refresh_cache=refresh_cache)
    completed_races = []
    for year in range(train_from, season + 1):
        completed_races.extend(client.season_results(year))
    completed_races.sort(key=lambda race: (race.season, race.round))

    schedule = client.season_schedule(season)
    next_race = _next_scheduled_race(schedule, completed_races, today=date.today())
    latest_completed = max(completed_races, key=lambda race: (race.season, race.round))
    prediction_race = _build_prediction_race(next_race, latest_completed)
    prediction_race = SprintClient(cache_dir, refresh_cache).enrich(prediction_race)

    weather_csv = None
    if auto_weather:
        weather_csv = build_weather_csv(
            completed_races + [prediction_race],
            output_dir / "prediction_weather.csv",
            cache_dir,
            refresh_cache=refresh_cache,
        )
    weather = load_weather(weather_csv)

    predictor = F1Predictor(weights=weights or _load_tuned_weights(output_dir))
    for race in completed_races:
        predictor.update(race, weather=weather)
    predictions = predictor.predict_race(prediction_race, weather=weather)

    write_prediction_report(prediction_race, predictions, output_dir, qualifying_results_used=False)
    return prediction_race, predictions


def write_prediction_report(
    race: Race,
    predictions: list[Prediction],
    output_dir: Path,
    prefix: str = "next_race",
    qualifying_results_used: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    top10 = [row for row in predictions if row.predicted_top10]
    with (output_dir / f"{prefix}_top10_prediction.csv").open("w", newline="") as handle:
        fieldnames = [
            "season",
            "round",
            "race_name",
            "date",
            "predicted_rank",
            "driver_code",
            "driver_id",
            "constructor_id",
            "predicted_top10_probability",
            "predicted_win_probability",
            "score",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in top10:
            writer.writerow(
                {
                    "season": race.season,
                    "round": race.round,
                    "race_name": race.race_name,
                    "date": race.date,
                    "predicted_rank": row.predicted_rank,
                    "driver_code": row.driver_code,
                    "driver_id": row.driver_id,
                    "constructor_id": row.constructor_id,
                    "predicted_top10_probability": row.predicted_top10_probability,
                    "predicted_win_probability": row.predicted_win_probability,
                    "score": row.score,
                }
            )

    summary = {
        "season": race.season,
        "round": race.round,
        "race_name": race.race_name,
        "date": race.date,
        "qualifying_results_used": qualifying_results_used,
        "sprint_qualifying_results_used": bool(race.sprint_qualifying),
        "sprint_race_results_used": bool(race.sprint_results),
        "predicted_top10": [
            {
                "rank": row.predicted_rank,
                "driver_code": row.driver_code,
                "constructor_id": row.constructor_id,
                "top10_probability": row.predicted_top10_probability,
                "score": row.score,
            }
            for row in top10
        ],
    }
    (output_dir / f"{prefix}_prediction.json").write_text(json.dumps(summary, indent=2, sort_keys=True))


def _next_scheduled_race(schedule: list[Race], completed_races: list[Race], today: date) -> Race:
    completed_keys = {(race.season, race.round) for race in completed_races}
    future = [
        race
        for race in schedule
        if (race.season, race.round) not in completed_keys and date.fromisoformat(race.date) >= today
    ]
    if future:
        return min(future, key=lambda race: (race.date, race.round))
    remaining = [race for race in schedule if (race.season, race.round) not in completed_keys]
    if remaining:
        return min(remaining, key=lambda race: race.round)
    raise RuntimeError(f"No upcoming race found in the {schedule[0].season if schedule else 'requested'} schedule.")


def _build_prediction_race(
    next_race: Race,
    latest_completed: Race,
) -> Race:
    entrants = []
    for previous in latest_completed.results:
        entrants.append(
            DriverResult(
                season=next_race.season,
                round=next_race.round,
                race_name=next_race.race_name,
                circuit_id=next_race.circuit_id,
                driver_id=previous.driver_id,
                driver_code=previous.driver_code,
                constructor_id=previous.constructor_id,
                finish_position=99,
                classified=False,
                points=0.0,
            )
        )
    return Race(
        season=next_race.season,
        round=next_race.round,
        race_name=next_race.race_name,
        circuit_id=next_race.circuit_id,
        date=next_race.date,
        latitude=next_race.latitude,
        longitude=next_race.longitude,
        results=entrants,
    )


def _load_tuned_weights(output_dir: Path) -> ModelWeights | None:
    report_path = output_dir / "tuning_report.json"
    if not report_path.exists():
        return None
    data = json.loads(report_path.read_text())
    tuned = data.get("selected_weights") or data.get("tuned_weights")
    if not tuned:
        return None
    valid_fields = {field.name for field in fields(ModelWeights)}
    return ModelWeights(**{key: value for key, value in tuned.items() if key in valid_fields})
