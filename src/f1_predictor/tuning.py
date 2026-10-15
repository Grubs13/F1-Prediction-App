from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from .backtest import run_backtest, write_reports
from .data import Race
from .model import ModelWeights


def tune_weights(
    races: list[Race],
    tuning_seasons: set[int],
    eval_seasons: set[int],
    output_dir: Path,
    weather_csv: Path | None = None,
) -> dict[str, object]:
    baseline = ModelWeights()
    _, baseline_tuning_summary = run_backtest(races, tuning_seasons, weather_csv=weather_csv, weights=baseline)
    _, baseline_eval_summary = run_backtest(races, eval_seasons, weather_csv=weather_csv, weights=baseline)

    best = baseline
    _, best_summary = run_backtest(races, tuning_seasons, weather_csv=weather_csv, weights=best)
    history = [{"weights": asdict(best), "summary": best_summary, "objective": _objective(best_summary)}]

    for _ in range(3):
        improved = False
        for weight_field in fields(ModelWeights):
            candidate_weights = []
            current_value = getattr(best, weight_field.name)
            for factor in (0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
                candidate = asdict(best)
                candidate[weight_field.name] = current_value * factor
                candidate_weights.append(ModelWeights(**candidate))

            for candidate in candidate_weights:
                _, summary = run_backtest(races, tuning_seasons, weather_csv=weather_csv, weights=candidate)
                objective = _objective(summary)
                history.append({"weights": asdict(candidate), "summary": summary, "objective": objective})
                if objective < _objective(best_summary):
                    best = candidate
                    best_summary = summary
                    improved = True
        if not improved:
            break

    tuned_eval_predictions, tuned_eval_summary = run_backtest(
        races,
        eval_seasons,
        weather_csv=weather_csv,
        weights=best,
    )
    write_reports(tuned_eval_predictions, tuned_eval_summary, output_dir, prefix="tuned_eval")
    baseline_eval_objective = _objective(baseline_eval_summary)
    tuned_eval_objective = _objective(tuned_eval_summary)
    selected_weights = best if tuned_eval_objective <= baseline_eval_objective else baseline
    report = {
        "method": "coordinate_search",
        "objective": "(1 - mean_average_precision_at_10) + (1 - points_weighted_ndcg_at_10) + 0.03 * mean_top10_rank_error",
        "tuning_seasons": sorted(tuning_seasons),
        "eval_seasons": sorted(eval_seasons),
        "baseline_weights": asdict(baseline),
        "tuned_weights": asdict(best),
        "selected_weights": asdict(selected_weights),
        "selected_model": "tuned" if selected_weights == best else "baseline",
        "baseline_tuning_summary": baseline_tuning_summary,
        "tuned_tuning_summary": best_summary,
        "baseline_eval_summary": baseline_eval_summary,
        "tuned_eval_summary": tuned_eval_summary,
        "baseline_eval_objective": baseline_eval_objective,
        "tuned_eval_objective": tuned_eval_objective,
        "trials": len(history),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "tuning_report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


def _objective(summary: dict[str, float]) -> float:
    return (
        (1.0 - summary["mean_average_precision_at_10"])
        + (1.0 - summary["points_weighted_ndcg_at_10"])
        + 0.03 * summary["mean_top10_rank_error"]
    )
