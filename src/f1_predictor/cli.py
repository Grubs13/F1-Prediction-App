from __future__ import annotations

import argparse
from pathlib import Path

from .backtest import fetch_races, run_backtest, write_reports
from .predict import predict_next_race
from .tuning import tune_weights
from .weather import build_weather_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict and backtest Formula 1 race results.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest = subparsers.add_parser("backtest", help="Run walk-forward backtest.")
    backtest.add_argument("--seasons", nargs="+", type=int, required=True)
    backtest.add_argument("--train-from", type=int, default=2023)
    backtest.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    backtest.add_argument("--output-dir", type=Path, default=Path("reports"))
    backtest.add_argument("--odds-csv", type=Path)
    backtest.add_argument("--weather-csv", type=Path)
    backtest.add_argument("--auto-weather", action="store_true")
    backtest.add_argument("--refresh-cache", action="store_true")

    tune = subparsers.add_parser("tune", help="Tune weights on one season and evaluate on another.")
    tune.add_argument("--tuning-seasons", nargs="+", type=int, required=True)
    tune.add_argument("--eval-seasons", nargs="+", type=int, required=True)
    tune.add_argument("--train-from", type=int, default=2023)
    tune.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    tune.add_argument("--output-dir", type=Path, default=Path("reports"))
    tune.add_argument("--auto-weather", action="store_true")
    tune.add_argument("--refresh-cache", action="store_true")

    predict = subparsers.add_parser("predict-next", help="Predict the next upcoming race top 10.")
    predict.add_argument("--season", type=int, required=True)
    predict.add_argument("--train-from", type=int, default=2023)
    predict.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    predict.add_argument("--output-dir", type=Path, default=Path("reports"))
    predict.add_argument("--auto-weather", action="store_true")
    predict.add_argument("--refresh-cache", action="store_true")

    live = subparsers.add_parser("serve", help="Serve the dashboard and automatically update predictions.")
    live.add_argument("--port", type=int, default=8002)
    live.add_argument("--interval", type=int, default=900)
    live.add_argument("--train-from", type=int, default=2023)
    live.add_argument("--no-weather", action="store_true")
    live.add_argument("--root", type=Path, default=Path.cwd())

    args = parser.parse_args()
    if args.command == "serve":
        if args.interval < 60:
            parser.error("--interval must be at least 60 seconds")
        from .worker import serve
        serve(args.root.resolve(), args.port, args.interval, args.train_from, not args.no_weather)
        return
    if args.command == "backtest":
        races = fetch_races(args.train_from, args.seasons, args.cache_dir, refresh_cache=args.refresh_cache)
        if args.auto_weather and args.weather_csv is None:
            args.weather_csv = build_weather_csv(
                races,
                args.output_dir / "weather.csv",
                args.cache_dir,
                refresh_cache=args.refresh_cache,
            )
        predictions, summary = run_backtest(
            races,
            set(args.seasons),
            odds_csv=args.odds_csv,
            weather_csv=args.weather_csv,
        )
        write_reports(predictions, summary, args.output_dir)
        print("Backtest summary")
        for key, value in summary.items():
            print(f"{key}: {value:.4f}")
    elif args.command == "tune":
        seasons = args.tuning_seasons + args.eval_seasons
        races = fetch_races(args.train_from, seasons, args.cache_dir, refresh_cache=args.refresh_cache)
        weather_csv = None
        if args.auto_weather:
            weather_csv = build_weather_csv(
                races,
                args.output_dir / "weather.csv",
                args.cache_dir,
                refresh_cache=args.refresh_cache,
            )
        report = tune_weights(
            races,
            set(args.tuning_seasons),
            set(args.eval_seasons),
            args.output_dir,
            weather_csv=weather_csv,
        )
        print("Tuning summary")
        print(f"trials: {report['trials']}")
        print(f"baseline_eval_top10_recall: {report['baseline_eval_summary']['top10_recall']:.4f}")
        print(f"tuned_eval_top10_recall: {report['tuned_eval_summary']['top10_recall']:.4f}")
        print(f"baseline_eval_map_at_10: {report['baseline_eval_summary']['mean_average_precision_at_10']:.4f}")
        print(f"tuned_eval_map_at_10: {report['tuned_eval_summary']['mean_average_precision_at_10']:.4f}")
        print(f"baseline_eval_ndcg_at_10: {report['baseline_eval_summary']['points_weighted_ndcg_at_10']:.4f}")
        print(f"tuned_eval_ndcg_at_10: {report['tuned_eval_summary']['points_weighted_ndcg_at_10']:.4f}")
    elif args.command == "predict-next":
        race, predictions = predict_next_race(
            season=args.season,
            train_from=args.train_from,
            cache_dir=args.cache_dir,
            output_dir=args.output_dir,
            auto_weather=args.auto_weather,
            refresh_cache=args.refresh_cache,
        )
        print(f"Next race: {race.season} round {race.round} - {race.race_name} ({race.date})")
        print("Predicted top 10")
        for row in predictions[:10]:
            print(
                f"{row.predicted_rank:>2}. {row.driver_code:<3} "
                f"{row.constructor_id:<14} top10_prob={row.predicted_top10_probability:.3f} "
                f"score={row.score:.4f}"
            )


if __name__ == "__main__":
    main()
