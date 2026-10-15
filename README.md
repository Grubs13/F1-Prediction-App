# F1 Result Predictor

This project builds a walk-forward Formula 1 top-10 finisher model using public historical data.

Data sources:

- Jolpica F1 API for schedules, race results, circuits, drivers, and constructors.
- [OpenF1](https://openf1.org/docs/) for same-weekend sprint qualifying and sprint race classifications (2023 onward).
- Optional local betting-odds CSV for bookmaker-implied probabilities.
- Optional local weather CSV for forecast or historical track conditions.

The backtester predicts each race using information available before the Grand Prix: prior race history, current-season form, circuit history, optional weather, optional betting odds, and completed sprint sessions from that weekend. It then compares the predicted points-paying top 10 to the actual top 10 classification.

## Quick Start

```bash
PYTHONPATH=src python3 -m f1_predictor.cli backtest --seasons 2025 2026 --train-from 2023 --auto-weather
```

The command writes:

- `data/cache/*.json` API cache files
- `reports/backtest_predictions.csv`
- `reports/backtest_top10_predictions.csv`
- `reports/top10_predictions.csv`, a compatibility alias for the baseline top-10 file
- `reports/backtest_summary.json`
- `reports/weather.csv` when `--auto-weather` is used
- `reports/tuning_report.json` when the tuning command is used
- `reports/tuned_eval_top10_predictions.csv` when the tuning command is used

## Optional Odds CSV

Historical F1 race-winner odds are not consistently available from free public APIs. The model accepts odds when available:

```csv
season,round,driver_code,decimal_odds,bookmaker,timestamp
2025,1,NOR,3.5,example,2025-03-15T22:00:00Z
```

Run with:

```bash
PYTHONPATH=src python3 -m f1_predictor.cli backtest --seasons 2025 2026 --train-from 2023 --odds-csv data/manual/odds.csv
```

## Optional Weather CSV

Weather can represent race forecast or observed conditions:

```csv
season,round,rain_probability,track_temp_c,air_temp_c,wind_kph
2025,1,0.35,38.0,26.0,12.0
```

Run with:

```bash
PYTHONPATH=src python3 -m f1_predictor.cli backtest --seasons 2025 2026 --train-from 2023 --weather-csv data/manual/weather.csv
```

You can also fetch public historical weather and near-race forecasts automatically:

```bash
PYTHONPATH=src python3 -m f1_predictor.cli backtest --seasons 2025 2026 --train-from 2023 --auto-weather
```

## Tune Weights

Tune on 2025 and evaluate on completed 2026 races:

```bash
PYTHONPATH=src python3 -m f1_predictor.cli tune --tuning-seasons 2025 --eval-seasons 2026 --train-from 2023 --auto-weather
```

The tuner uses coordinate search over the transparent feature weights and minimizes:

```text
(1 - mean_average_precision_at_10) + (1 - points_weighted_ndcg_at_10) + 0.03 * mean_top10_rank_error
```

That objective rewards naming the correct top-10 drivers and putting the higher-scoring actual finishers nearer the front of the predicted top 10.

## Model

The model blends:

- Driver Elo
- Constructor Elo
- Recent form over the last five races
- Current-season points before the race
- Circuit-specific driver history
- Optional bookmaker implied probability
- Optional weather interaction for wet-weather and volatility history

The score for each driver is a weighted blend of these normalized signals. Drivers are sorted by score, and the first ten are the predicted points finishers. Sprint qualifying (weight 0.08) and sprint race results (weight 0.12) are centered position signals, fetched automatically for the same weekend when published. Missing sessions leave the original scores unchanged; missing driver entries receive a neutral signal. These weights are tunable. Main Grand Prix qualifying/grid data remains excluded. Historical backtests now represent predictions after available sprint sessions, before the Grand Prix. API failures emit warnings and fall back to the existing inputs. The next-race JSON report records whether each sprint session was used. It also emits a rough top-10 inclusion probability by comparing each score with the tenth-place score cutoff.

Summary metrics:

- `top10_precision`, `top10_recall`, `top10_f1`: how many predicted top-10 drivers were actual top-10 drivers.
- `mean_average_precision_at_10`: rewards retrieving actual top-10 drivers earlier in the predicted list.
- `points_weighted_ndcg_at_10`: rewards putting the most valuable actual points finishers higher.
- `points_capture`: actual race points captured by the predicted top 10.
- `mean_top10_rank_error`: average ordered-position error for drivers in either predicted or actual top 10.
- `winner_accuracy` and `winner_log_loss`: secondary diagnostics, not the primary objective.

It is intentionally transparent and tunable. See `src/f1_predictor/model.py` for weights.

## Automatic dashboard updates

Run the local server and updater together:

```bash
PYTHONPATH=src python3 -m f1_predictor.cli serve --port 8002
```

Open http://localhost:8002/web/index.html. Keep this process running; updates pause while the Mac sleeps or the process stops. The worker checks every 15 minutes (`--interval` in seconds, minimum 60). The browser reloads reports every minute.

The worker selects the next GP by its scheduled UTC start time, uses the Edmonton calendar year, and waits for previous GP results. It generates a baseline, then reruns when sprint qualifying or sprint race classifications change, including corrections. GP qualifying is excluded. With weather enabled, one additional refresh happens within 24 hours of the GP. Use `--no-weather` to omit weather. No AI API is called.

Historical results/weather stay cached; current-season schedules/results and sprint sessions refresh on checks. Forecasts refresh when generating a version. Failed updates keep the last published report and retry automatically; missing weather uses prior weather when available. Updates beyond the forecast provider's horizon may have no weather input.

Immutable snapshots are saved under `reports/versions/<season>-<round>/`; `next_race_prediction.json` points to the matching snapshot CSV/weather files so the browser does not mix versions. Worker status is saved to `reports/update_status.json`. The UI hides old predictions when the next race is pending. Historical backtest stats are not recomputed by this worker.
