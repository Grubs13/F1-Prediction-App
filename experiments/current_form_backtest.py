"""Offline ablation experiment; leaves production model and reports untouched.

Run: PYTHONPATH=src python3 experiments/current_form_backtest.py
"""
import csv
import hashlib
import json
import random
import statistics
from collections import defaultdict
from dataclasses import asdict, replace
from pathlib import Path

from f1_predictor.backtest import run_backtest, summarize
from f1_predictor.data import JolpicaClient, load_weather
from f1_predictor.model import F1Predictor, ModelWeights
from f1_predictor.predict import _build_prediction_race
from f1_predictor.tuning import _objective

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'data/cache'
OUTPUT = ROOT / 'reports/current_form_experiment'


class OfflineClient(JolpicaClient):
    def get_json(self, path):
        name = path.strip('/').replace('/', '__').replace('?', '_').replace('&', '_')
        return json.loads((self.cache_dir / f'{name}.json').read_text())


def sprint_from_cache(race):
    path = CACHE / f'openf1_sessions_year={race.season}.json'
    if not path.exists():
        return race
    sessions = json.loads(path.read_text())
    gps = [s for s in sessions if s['session_name'] == 'Race' and s['date_start'][:10] == race.date]
    if len(gps) != 1:
        return race
    signals = {}
    for s in sessions:
        if s['meeting_key'] != gps[0]['meeting_key'] or s['session_name'] not in {'Sprint', 'Sprint Qualifying', 'Sprint Shootout'}:
            continue
        if s.get('is_cancelled') or s['date_end'] >= gps[0]['date_start']:
            continue
        result_path = CACHE / f"openf1_session_result_session_key={s['session_key']}.json"
        driver_path = CACHE / f"openf1_drivers_session_key={s['session_key']}.json"
        if not result_path.exists() or not driver_path.exists():
            continue
        codes = {d['driver_number']: (d.get('name_acronym') or '').upper() for d in json.loads(driver_path.read_text())}
        signals['sprint_results' if s['session_name'] == 'Sprint' else 'sprint_qualifying'] = {
            codes[r['driver_number']]: int(r['position'])
            for r in json.loads(result_path.read_text()) if r.get('position') and codes.get(r['driver_number'])
        }
    return replace(race, **signals)


class ExperimentalModel(F1Predictor):
    def __init__(self, shift=0., retention=1., relative=False):
        super().__init__(ModelWeights(driver_elo=.36-shift, recent_form=.16+shift))
        self.retention = retention
        self.relative = relative
        self.year = None

    def enter_season(self, year):
        if self.year is not None and year != self.year:
            for ratings in (self.state.driver_elo, self.state.constructor_elo):
                for key in ratings:
                    ratings[key] = 1500 + (ratings[key] - 1500) * self.retention
        self.year = year

    def _score_driver(self, result, race, odds, weather_row):
        score = super()._score_driver(result, race, odds, weather_row)
        if self.relative:
            points = self.state.season_points[(race.season, result.driver_code)]
            leader = max((v for (year, _), v in self.state.season_points.items() if year == race.season), default=0)
            relative = points / leader if leader else 0.
            score += self.weights.season_points * (relative - min(points / 250, 1.))
        return score


def evaluate(config, races, weather, year):
    model = ExperimentalModel(**config)
    predictions = []
    for race in races:
        model.enter_season(race.season)
        if race.season == year:
            predictions.extend(model.predict_race(race, weather=weather))
        if race.season <= year:
            model.update(race, weather=weather)
    return predictions, summarize(predictions)


def main():
    OUTPUT.mkdir(exist_ok=True)
    client = OfflineClient(CACHE)
    races = [sprint_from_cache(r) for year in range(2023, 2027) for r in client.season_results(year)]
    races.sort(key=lambda r: (r.season, r.round))
    published = json.loads((ROOT / 'reports/next_race_prediction.json').read_text())
    weather_path = ROOT / published['weather_path'].lstrip('/')
    weather = load_weather(weather_path)
    baseline = dict(shift=0., retention=1., relative=False)
    families = {
        'baseline': [baseline],
        'stronger_recent_form': [dict(shift=s, retention=1., relative=False) for s in (.06, .12, .18)],
        'seasonal_elo_decay': [dict(shift=0., retention=r, relative=False) for r in (.75, .5, .25)],
        'relative_season_points': [dict(shift=0., retention=1., relative=True)],
        'combined': [dict(shift=s, retention=r, relative=True) for s in (.06, .12, .18) for r in (.75, .5, .25)],
    }
    # Select each family's setting on 2025 only, before evaluating any 2026 races.
    selections = {}
    trials = []
    for family, configs in families.items():
        candidates = []
        for config in configs:
            _, summary = evaluate(config, races, weather, 2025)
            candidates.append((_objective(summary), config, summary))
            trials.append(dict(family=family, config=config, summary=summary, objective=_objective(summary)))
        _, config, summary = min(candidates, key=lambda row: row[0])
        selections[family] = dict(config=config, tuning_2025=summary)
    upcoming = sprint_from_cache(_build_prediction_race(
        next(r for r in client.season_schedule(2026) if r.round == published['round']), races[-1]))
    for family, row in selections.items():
        predictions, summary = evaluate(row['config'], races, weather, 2026)
        row['evaluation_2026'] = summary
        by_race = defaultdict(list)
        for p in predictions:
            by_race[p.round].append(p)
        row['per_race'] = [{
            'round': rnd, 'race_name': ps[0].race_name, **summarize(ps),
            'kimi_predicted_rank': next((p.predicted_rank for p in ps if p.driver_code == 'ANT'), None),
            'kimi_actual_rank': next((p.actual_finish for p in ps if p.driver_code == 'ANT'), None),
        } for rnd, ps in sorted(by_race.items())]
        model = ExperimentalModel(**row['config'])
        for race in races:
            model.enter_season(race.season)
            model.update(race, weather)
        model.enter_season(upcoming.season)
        next_predictions = model.predict_race(upcoming, weather=weather)
        row['upcoming_top10'] = [dict(driver=p.driver_code, rank=p.predicted_rank, score=p.score) for p in next_predictions[:10]]
        with (OUTPUT / f'{family}_predictions.csv').open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(predictions[0])))
            writer.writeheader()
            writer.writerows(asdict(p) for p in predictions)
    reproduced = selections['baseline']['upcoming_top10']
    assert all(a['driver'] == b['driver_code'] and abs(a['score'] - b['score']) < 1e-12
               for a, b in zip(reproduced, published['predicted_top10']))
    _, production_summary = run_backtest(races, {2026}, weather_csv=weather_path)
    assert production_summary == selections['baseline']['evaluation_2026']
    assert len({(r.season, r.round) for r in races}) == len(races)
    assert all(len({x.driver_code for x in r.results}) == len(r.results) for r in races)
    rng = random.Random(42)
    base_rows = selections['baseline']['per_race']
    for row in selections.values():
        rows = row['per_race']
        changes = [(r['top10_precision'] - b['top10_precision']) * 10 for r, b in zip(rows, base_rows)]
        samples = sorted(sum(changes[rng.randrange(len(changes))] for _ in changes) / len(changes) for _ in range(10000))
        row['paired_top10_hits'] = dict(
            more=sum(x > 1e-9 for x in changes), same=sum(abs(x) < 1e-9 for x in changes),
            fewer=sum(x < -1e-9 for x in changes), mean_delta=statistics.mean(changes),
            bootstrap_95_interval=[samples[250], samples[9750]])
        row['kimi_summary'] = dict(
            mean_predicted_rank=statistics.mean(r['kimi_predicted_rank'] for r in rows),
            mean_absolute_rank_error=statistics.mean(abs(r['kimi_predicted_rank'] - r['kimi_actual_rank']) for r in rows),
            predicted_wins=sum(r['kimi_predicted_rank'] == 1 for r in rows),
            correctly_predicted_wins=sum(r['kimi_predicted_rank'] == 1 and r['kimi_actual_rank'] == 1 for r in rows))
    result = dict(
        method='Walk-forward: predict before updating GP result; settings chosen on 2025 only.',
        training_start=2023, tuning_season=2025, evaluation_season=2026,
        race_counts={year: sum(r.season == year for r in races) for year in range(2023, 2027)},
        sprint_coverage={year: dict(qualifying=sum(bool(r.sprint_qualifying) for r in races if r.season == year),
                                    race=sum(bool(r.sprint_results) for r in races if r.season == year)) for year in (2025, 2026)},
        limitations=['Cached GP entrant list is known retrospectively.',
                     'Historical weather uses observed race-day precipitation, not archived pre-race forecasts.',
                     'Only cached sprint classifications are used; absent cache contributes no sprint signal.',
                     '2026 was already inspected to motivate these changes, so this is a retrospective holdout, not an untouched prospective test.'],
        input_sha256=hashlib.sha256(json.dumps([asdict(r) for r in races], sort_keys=True).encode()).hexdigest(),
        weather_sha256=hashlib.sha256(weather_path.read_bytes()).hexdigest(),
        upcoming_baseline_matches_published=True, trials=trials, models=selections,
        verification=['Baseline matches unmodified production backtester exactly.',
                      'Upcoming baseline scores and ranks match published Singapore report exactly.',
                      'Race keys and driver entries are unique.'],
    )
    (OUTPUT / 'results.json').write_text(json.dumps(result, indent=2))
    for family, row in selections.items():
        print(family, row['config'], row['evaluation_2026'], 'Kimi upcoming', next(p['rank'] for p in row['upcoming_top10'] if p['driver']=='ANT'))
    print('coverage', result['sprint_coverage'])


if __name__ == '__main__':
    main()
