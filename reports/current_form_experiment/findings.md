# Current-form backtest findings

The combined changes improved 2026 results modestly, but every modified family scored worse than the baseline on the 2025 tuning objective. Evidence is insufficient to replace the production model automatically.

## Method

Used cached 2023–2026 Grand Prix results, with chronological prediction before each GP result updates the model. Chose settings within each experimental family using 24 races in 2025 and the existing objective: `(1 - MAP@10) + (1 - points-weighted NDCG@10) + 0.03 * mean top-ten rank error`. Evaluated those settings on 16 completed 2026 races. No bookmaker odds were supplied.

Recent-form experiments transferred 0.06, 0.12, or 0.18 of driver Elo weight into recent form, keeping the weight sum constant. Seasonal-decay experiments retained 75%, 50%, or 25% of both driver and constructor Elo's deviation from 1500 at each season boundary. Relative-points experiments used pre-race driver points divided by the pre-race championship leader's points; zero points for the entire field gives zero. Combined experiments tried all nine form/decay combinations with relative points.

## Selected settings and 2026 results

| Model | Correct top-ten drivers/race | Points captured | Rank error, lower better | Correct winners | Singapore Kimi rank |
|---|---:|---:|---:|---:|---:|
| Baseline | 7.125 | 89.48% | 3.068 | 0/16 | 6 |
| Recent form: driver Elo 0.30, form 0.22 | 7.125 | 88.92% | 3.078 | 0/16 | 4 |
| Seasonal Elo: retain 25% | 7.313 | 90.28% | 3.005 | 1/16 | 1 |
| Relative season points | 7.125 | 88.92% | 3.068 | 0/16 | 5 |
| Combined: driver Elo 0.18, form 0.34, retain 75%, relative points | 7.313 | 90.22% | 2.975 | 1/16 | 1 |

Combined points-weighted ranking quality increased from 0.6908 to 0.7292. Across the 16 races it selected one additional correct top-ten driver in three races, with unchanged hit counts in the other thirteen. A paired race bootstrap (10,000 samples, seed 42) gives an approximate 95% interval of 0.000–0.375 additional correct drivers per race. This interval reaches zero and does not demonstrate a robust gain.

Kimi's mean predicted rank improved from 6.375 to 3.500 with the combined model, and mean absolute finishing-position error fell from 5.375 to 4.250. Only one of his eight wins was correctly predicted by the combined model. More current-form weight alone slightly worsened his average position error.

2025 objective values (lower is better): baseline 0.63792; recent form 0.64241; seasonal decay 0.64992; relative points 0.64696; combined 0.64116. Including baseline as an eligible choice would select baseline on 2025.

## Limits and verification

- No historical sprint classifications exist in the local cache for evaluated races. All historical comparisons omit sprint signals equally. The Singapore comparison includes cached sprint sessions and reproduces the published baseline exactly.
- Historical weather uses observed race-day precipitation rather than pre-race forecast archives. This limits claims about real-world pre-race performance.
- Entrants are taken from historical GP classifications, so participation is known retrospectively.
- Changes were motivated by already-inspected 2026 performance; this evaluation is retrospective rather than a pristine prospective holdout.
- Baseline metrics match the unmodified production backtester exactly. Historical race keys and driver entries were checked for duplicates.

Production code, selected weights, and published dashboard predictions remain unchanged. The experiment is reproducible with `PYTHONPATH=src python3 experiments/current_form_backtest.py`. Full settings, trial metrics, race-level comparisons, input hashes, and bootstrap results are in `results.json`; prediction CSVs are saved for every model.
