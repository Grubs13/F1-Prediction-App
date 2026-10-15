from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict
from pathlib import Path

from .data import JolpicaClient, Race, load_odds, load_weather
from .model import F1Predictor, ModelWeights, Prediction
from .sprint import SprintClient

TOP_K = 10


def fetch_races(train_from: int, seasons: list[int], cache_dir: Path, refresh_cache: bool = False) -> list[Race]:
    client = JolpicaClient(cache_dir=cache_dir, refresh_cache=refresh_cache)
    last_season = max(seasons)
    races: list[Race] = []
    for season in range(train_from, last_season + 1):
        races.extend(client.season_results(season))
    sprint_client = SprintClient(cache_dir, refresh_cache)
    return [sprint_client.enrich(race) for race in sorted(races, key=lambda race: (race.season, race.round))]


def run_backtest(
    races: list[Race],
    target_seasons: set[int],
    odds_csv: Path | None = None,
    weather_csv: Path | None = None,
    weights: ModelWeights | None = None,
) -> tuple[list[Prediction], dict[str, float]]:
    predictor = F1Predictor(weights=weights)
    odds = load_odds(odds_csv)
    weather = load_weather(weather_csv)
    predictions: list[Prediction] = []

    for race in races:
        if race.season in target_seasons:
            predictions.extend(predictor.predict_race(race, odds=odds, weather=weather))
        predictor.update(race, weather=weather)

    return predictions, summarize(predictions)


def summarize(predictions: list[Prediction]) -> dict[str, float]:
    if not predictions:
        return {
            "races": 0,
            "top10_precision": 0.0,
            "top10_recall": 0.0,
            "top10_f1": 0.0,
            "top10_exact_match_rate": 0.0,
            "mean_average_precision_at_10": 0.0,
            "points_weighted_ndcg_at_10": 0.0,
            "points_capture": 0.0,
            "mean_top10_rank_error": 0.0,
            "winner_accuracy": 0.0,
            "winner_log_loss": 0.0,
        }

    by_race: dict[tuple[int, int], list[Prediction]] = {}
    for prediction in predictions:
        by_race.setdefault((prediction.season, prediction.round), []).append(prediction)

    winner_hits = 0
    top10_precisions = []
    top10_recalls = []
    top10_f1s = []
    top10_exact_matches = 0
    average_precisions = []
    ndcgs = []
    points_captures = []
    top10_rank_errors = []
    log_losses = []
    for race_predictions in by_race.values():
        race_predictions = sorted(race_predictions, key=lambda row: row.predicted_rank)
        predicted_winner = min(race_predictions, key=lambda row: row.predicted_rank)
        actual_winner = min(race_predictions, key=lambda row: row.actual_finish)
        if predicted_winner.driver_code == actual_winner.driver_code:
            winner_hits += 1

        predicted_top10 = {row.driver_code for row in race_predictions if row.predicted_top10}
        actual_top10 = {row.driver_code for row in race_predictions if row.actual_top10}
        hits = len(predicted_top10 & actual_top10)
        precision = hits / max(len(predicted_top10), 1)
        recall = hits / max(len(actual_top10), 1)
        top10_precisions.append(precision)
        top10_recalls.append(recall)
        top10_f1s.append(0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall))
        if predicted_top10 == actual_top10:
            top10_exact_matches += 1

        average_precisions.append(_average_precision_at_k(race_predictions, TOP_K))
        ndcgs.append(_points_weighted_ndcg_at_k(race_predictions, TOP_K))
        points_captures.append(_points_capture(race_predictions))
        top10_rank_errors.extend(_top10_rank_errors(race_predictions))

        for row in race_predictions:
            if row.actual_finish == 1:
                probability = max(min(row.predicted_win_probability, 0.999), 0.001)
                log_losses.append(-math.log(probability))

    races = len(by_race)
    return {
        "races": float(races),
        "top10_precision": sum(top10_precisions) / len(top10_precisions),
        "top10_recall": sum(top10_recalls) / len(top10_recalls),
        "top10_f1": sum(top10_f1s) / len(top10_f1s),
        "top10_exact_match_rate": top10_exact_matches / races,
        "mean_average_precision_at_10": sum(average_precisions) / len(average_precisions),
        "points_weighted_ndcg_at_10": sum(ndcgs) / len(ndcgs),
        "points_capture": sum(points_captures) / len(points_captures),
        "mean_top10_rank_error": sum(top10_rank_errors) / len(top10_rank_errors),
        "winner_accuracy": winner_hits / races,
        "winner_log_loss": sum(log_losses) / len(log_losses),
    }


def write_reports(
    predictions: list[Prediction],
    summary: dict[str, float],
    output_dir: Path,
    prefix: str = "backtest",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_file = output_dir / f"{prefix}_predictions.csv"
    with predictions_file.open("w", newline="") as handle:
        fieldnames = list(asdict(predictions[0]).keys()) if predictions else list(Prediction.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for prediction in predictions:
            writer.writerow(asdict(prediction))

    top10_file = output_dir / f"{prefix}_top10_predictions.csv"
    _write_top10_file(top10_file, predictions)
    if prefix == "backtest":
        _write_top10_file(output_dir / "top10_predictions.csv", predictions)

    (output_dir / f"{prefix}_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))


def _write_top10_file(path: Path, predictions: list[Prediction]) -> None:
    with path.open("w", newline="") as handle:
        fieldnames = list(asdict(predictions[0]).keys()) if predictions else list(Prediction.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for prediction in predictions:
            if prediction.predicted_top10:
                writer.writerow(asdict(prediction))


def _average_precision_at_k(race_predictions: list[Prediction], k: int) -> float:
    hits = 0
    precision_sum = 0.0
    actual_relevant = sum(1 for row in race_predictions if row.actual_top10)
    for index, row in enumerate(race_predictions[:k], start=1):
        if row.actual_top10:
            hits += 1
            precision_sum += hits / index
    return precision_sum / max(min(actual_relevant, k), 1)


def _points_weighted_ndcg_at_k(race_predictions: list[Prediction], k: int) -> float:
    predicted_relevance = [max(row.actual_points, 0.0) for row in race_predictions[:k]]
    ideal_relevance = sorted((max(row.actual_points, 0.0) for row in race_predictions), reverse=True)[:k]
    ideal = _dcg(ideal_relevance)
    if ideal == 0:
        return 0.0
    return _dcg(predicted_relevance) / ideal


def _dcg(relevance: list[float]) -> float:
    return sum(value / math.log2(index + 1) for index, value in enumerate(relevance, start=1))


def _points_capture(race_predictions: list[Prediction]) -> float:
    available = sum(row.actual_points for row in race_predictions if row.actual_top10)
    captured = sum(row.actual_points for row in race_predictions if row.predicted_top10)
    return captured / available if available else 0.0


def _top10_rank_errors(race_predictions: list[Prediction]) -> list[int]:
    errors = []
    rows_by_code = {row.driver_code: row for row in race_predictions}
    codes = {
        row.driver_code
        for row in race_predictions
        if row.predicted_top10 or row.actual_top10
    }
    for code in codes:
        row = rows_by_code[code]
        predicted_rank = row.predicted_rank if row.predicted_top10 else TOP_K + 1
        actual_rank = row.actual_finish if row.actual_top10 else TOP_K + 1
        errors.append(abs(predicted_rank - actual_rank))
    return errors
