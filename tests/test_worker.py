import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from test_sprint import race
from f1_predictor.worker import PredictionWorker, select_race


class WorkerTests(unittest.TestCase):
    def test_select_by_start_time_and_never_return_past_race(self):
        rows = [{'round': '1', 'date': '2025-03-23', 'time': '07:00:00Z'},
                {'round': '2', 'date': '2025-04-06', 'time': '07:00:00Z'}]
        self.assertEqual(select_race(rows, datetime(2025, 3, 23, 6, tzinfo=timezone.utc))['round'], '1')
        self.assertEqual(select_race(rows, datetime(2025, 3, 23, 8, tzinfo=timezone.utc))['round'], '2')
        self.assertIsNone(select_race(rows, datetime(2025, 5, 1, tzinfo=timezone.utc)))

    def test_change_triggered_versions_pending_and_failure(self):
        target = replace(race(), round=2, date='2025-04-06')
        row = {'season': '2025', 'round': '2', 'raceName': 'Test GP', 'date': target.date, 'time': '07:00:00Z'}
        first = {'season': '2025', 'round': '1', 'date': '2025-03-23', 'time': '07:00:00Z'}
        schedule = {'MRData': {'RaceTable': {'season': '2025', 'Races': [first, row]}}}
        now = datetime(2025, 4, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, patch('f1_predictor.worker.LiveClient') as client, patch('f1_predictor.worker.SprintClient') as sprint:
            client.return_value.get_json.return_value = schedule
            client.return_value.season_results.return_value = [race()]
            client.return_value.season_schedule.return_value = [target]
            sprint.return_value.enrich.side_effect = lambda r: r
            worker = PredictionWorker(Path(directory), train_from=2025, auto_weather=False)
            self.assertTrue(worker.check(now))
            self.assertFalse(worker.check(now))
            sprint.return_value.enrich.side_effect = lambda r: replace(r, sprint_qualifying={'AAA': 2, 'BBB': 1})
            self.assertTrue(worker.check(now.replace(hour=1)))
            sprint.return_value.enrich.side_effect = lambda r: replace(r, sprint_qualifying={'AAA': 2, 'BBB': 1}, sprint_results={'AAA': 2, 'BBB': 1})
            self.assertTrue(worker.check(now.replace(hour=2)))
            report_path = Path(directory) / 'reports/next_race_prediction.json'
            report = json.loads(report_path.read_text())
            self.assertEqual(report['stage'], 'After sprint race')
            self.assertTrue((Path(directory) / report['top10_path'].lstrip('/')).exists())
            self.assertEqual(len(list((Path(directory) / 'reports/versions/2025-2').iterdir())), 3)
            sprint.return_value.enrich.side_effect = OSError('offline')
            self.assertFalse(worker.check(now.replace(hour=3)))
            self.assertEqual(json.loads(report_path.read_text()), report)
            client.return_value.season_results.return_value = []
            self.assertFalse(worker.check(now.replace(hour=4)))
            status = json.loads((Path(directory) / 'reports/update_status.json').read_text())
            self.assertEqual(status['status'], 'pending')
