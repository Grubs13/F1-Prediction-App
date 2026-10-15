"""Local, change-triggered prediction updater and dashboard server."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import warnings
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import JolpicaClient, load_weather
from .model import F1Predictor
from .predict import _build_prediction_race, _load_tuned_weights, write_prediction_report
from .sprint import SprintClient
from .weather import build_weather_csv


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


class LiveClient(JolpicaClient):
    """Refresh mutable current-season data; keep historical seasons cached."""
    def __init__(self, cache_dir: Path, season: int):
        super().__init__(cache_dir)
        self.live_season = season

    def get_json(self, path: str) -> dict:
        self.refresh_cache = path.startswith(f'{self.live_season}.') or path.startswith(f'{self.live_season}/')
        return super().get_json(path)


def select_race(rows: list[dict], now: datetime) -> dict | None:
    # A race stays current through its scheduled start. Afterwards show the next GP,
    # but wait for the completed GP classification before publishing its forecast.
    upcoming = [r for r in rows if datetime.fromisoformat(
        r['date'] + 'T' + r.get('time', '23:59:59Z').replace('Z', '+00:00')) > now]
    return min(upcoming, key=lambda r: (r['date'], int(r['round']))) if upcoming else None


class PredictionWorker:
    def __init__(self, root: Path, train_from: int = 2023, auto_weather: bool = True):
        self.root = root
        self.cache = root / 'data/cache'
        self.output = root / 'reports'
        self.train_from = train_from
        self.auto_weather = auto_weather

    def check(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        status = {'checked_at': now.isoformat(), 'status': 'checking'}
        status_path = self.output / 'update_status.json'
        atomic_json(status_path, status)
        try:
            year = now.astimezone(ZoneInfo('America/Edmonton')).year
            client = LiveClient(self.cache, year)
            schedule_data = client.get_json(f'{year}.json?limit=100')
            rows = schedule_data['MRData']['RaceTable'].get('Races', [])
            target = select_race(rows, now)
            if target is None:
                # Check the next season after the final GP, without returning to past races.
                year += 1
                client.live_season = year
                schedule_data = client.get_json(f'{year}.json?limit=100')
                rows = schedule_data['MRData']['RaceTable'].get('Races', [])
                target = select_race(rows, now)
            if target is None:
                status.update(status='off_season', message='Waiting for the next race schedule.')
                atomic_json(status_path, status)
                return False
            status['race'] = target
            # Browser consumes this fresh schedule rather than a potentially old cache file.
            atomic_json(self.output / 'current_schedule.json', schedule_data)
            completed = []
            for season in range(self.train_from, year + 1):
                completed.extend(client.season_results(season))
            completed.sort(key=lambda r: (r.season, r.round))
            keys = {(r.season, r.round) for r in completed}
            missing = [r for r in rows if int(r['round']) < int(target['round'])
                       and (year, int(r['round'])) not in keys]
            if missing or not completed:
                status.update(status='pending', message='Waiting for previous Grand Prix results before generating predictions.')
                atomic_json(status_path, status)
                return False
            scheduled = next(r for r in client.season_schedule(year) if r.round == int(target['round']))
            race = _build_prediction_race(scheduled, completed[-1])
            with warnings.catch_warnings(record=True) as notices:
                warnings.simplefilter('always')
                race = SprintClient(self.cache, refresh_cache=True).enrich(race)
            if notices:
                raise RuntimeError(str(notices[0].message))
            start = datetime.fromisoformat(target['date'] + 'T' + target.get('time', '23:59:59Z').replace('Z', '+00:00'))
            final_weather = self.auto_weather and start - now <= timedelta(hours=24)
            fingerprint = hashlib.sha256(json.dumps({
                'race': asdict(race), 'history': [asdict(r) for r in completed],
                'weights': asdict(_load_tuned_weights(self.output)) if _load_tuned_weights(self.output) else None,
                'final_weather': final_weather,
            }, sort_keys=True).encode()).hexdigest()
            report_path = self.output / 'next_race_prediction.json'
            previous = json.loads(report_path.read_text()) if report_path.exists() else {}
            if (previous.get('season'), previous.get('round')) == (race.season, race.round) and (
                previous.get('sprint_race_results_used') and not race.sprint_results or
                previous.get('sprint_qualifying_results_used') and not race.sprint_qualifying):
                raise RuntimeError('Previously published sprint results are temporarily unavailable')
            if previous.get('input_fingerprint') == fingerprint:
                status.update(status='current', message='Predictions are current; no new inputs.')
                atomic_json(status_path, status)
                return False
            stamp = now.strftime('%Y%m%dT%H%M%S%fZ')
            version_dir = self.output / 'versions' / f'{year}-{race.round}' / stamp
            version_dir.mkdir(parents=True, exist_ok=True)
            weather_path = None
            weather_warning = None
            if self.auto_weather:
                try:
                    # Refresh only the upcoming forecast, never the historical weather archive.
                    forecast = self.cache / f'weather_forecast_{year}_{race.round}.json'
                    if forecast.exists():
                        forecast.unlink()
                    weather_path = build_weather_csv(completed + [race], version_dir / 'prediction_weather.csv', self.cache)
                except Exception as exc:
                    weather_warning = str(exc)
                    if previous.get('weather_path'):
                        import shutil
                        weather_path = version_dir / 'prediction_weather.csv'
                        shutil.copyfile(self.root / previous['weather_path'].lstrip('/'), weather_path)
            weather = load_weather(weather_path)
            model = F1Predictor(weights=_load_tuned_weights(self.output))
            for past in completed:
                model.update(past, weather=weather)
            predictions = model.predict_race(race, weather=weather)
            write_prediction_report(race, predictions, version_dir)
            report = json.loads((version_dir / 'next_race_prediction.json').read_text())
            stage = 'After sprint race' if race.sprint_results else 'After sprint qualifying' if race.sprint_qualifying else 'Baseline'
            report.update(generated_at=now.isoformat(), stage=stage,
                          final_weather_update=final_weather, input_fingerprint=fingerprint,
                          sprint_scheduled=bool(target.get('Sprint')),
                          top10_path='/' + str((version_dir / 'next_race_top10_prediction.csv').relative_to(self.root)),
                          weather_path='/' + str(weather_path.relative_to(self.root)) if weather_path else None,
                          weather_warning=weather_warning)
            atomic_json(version_dir / 'next_race_prediction.json', report)
            # Publish one atomic pointer after all immutable version files are complete.
            atomic_json(report_path, report)
            status.update(status='current', message='Updated predictions.', generated_at=report['generated_at'])
            if weather_warning:
                status['message'] += ' Weather unavailable; using previous weather where available.'
            atomic_json(status_path, status)
            return True
        except Exception as exc:
            status.update(status='error', message=f'Update failed; retrying automatically: {exc}')
            atomic_json(status_path, status)
            return False

    def run(self, interval: int = 900) -> None:
        while True:
            self.check()
            time.sleep(interval)


def serve(root: Path, port: int, interval: int, train_from: int, auto_weather: bool) -> None:
    worker = PredictionWorker(root, train_from, auto_weather)
    threading.Thread(target=worker.run, args=(interval,), daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', port), partial(SimpleHTTPRequestHandler, directory=str(root)))
    print(f'Dashboard: http://localhost:{port}/web/index.html (checks every {interval}s)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
