import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_model import make_result
from f1_predictor.data import Race
from f1_predictor.model import F1Predictor
from f1_predictor.predict import write_prediction_report
from f1_predictor.sprint import SprintClient


def race():
    return Race(2025, 1, 'Test GP', 'test', '2025-03-23', 0, 0, [
        make_result(2025, 1, 'Test GP', 'test', 'AAA', 'a', 1, 25),
        make_result(2025, 1, 'Test GP', 'test', 'BBB', 'b', 2, 18),
    ])


class SprintTests(unittest.TestCase):
    def test_each_signal_changes_ranking_without_using_gp_finish(self):
        model = F1Predictor()
        for field in ('sprint_qualifying', 'sprint_results'):
            target = replace(race(), **{field: {'AAA': 2, 'BBB': 1}})
            self.assertEqual(model.predict_race(target)[0].driver_code, 'BBB')
        self.assertEqual(model.predict_race(race())[0].driver_code, 'AAA')
        self.assertEqual(list(model.state.recent_finishes['BBB']), [])

    def test_same_meeting_only_and_sessions_independently_available(self):
        sessions = [
            dict(session_name='Race', date_start='2025-03-23T07:00:00+00:00', meeting_key=1),
            dict(session_name='Sprint Qualifying', date_start='2025-03-21T07:00:00+00:00',
                 date_end='2025-03-21T08:00:00+00:00', meeting_key=1, session_key=2),
            dict(session_name='Sprint', date_end='2025-03-22T08:00:00+00:00', meeting_key=1, session_key=3),
            dict(session_name='Sprint', date_end='2025-03-22T08:00:00+00:00', meeting_key=99, session_key=4),
        ]
        def get(endpoint, **params):
            if endpoint == 'sessions':
                return sessions
            if endpoint == 'drivers':
                return [dict(driver_number=1, name_acronym='AAA')]
            return [dict(driver_number=1, position=1)] if params['session_key'] == 2 else []
        with tempfile.TemporaryDirectory() as directory:
            client = SprintClient(Path(directory))
            with patch.object(client, 'get', side_effect=get) as fetch:
                enriched = client.enrich(race())
            self.assertEqual(enriched.sprint_qualifying, {'AAA': 1})
            self.assertEqual(enriched.sprint_results, {})
            self.assertFalse(any(call.kwargs.get('session_key') == 4 for call in fetch.call_args_list))
            predictions = F1Predictor().predict_race(enriched)
            write_prediction_report(enriched, predictions, Path(directory))
            report = json.loads((Path(directory) / 'next_race_prediction.json').read_text())
            self.assertTrue(report['sprint_qualifying_results_used'])
            self.assertFalse(report['sprint_race_results_used'])

    def test_future_and_wrong_weekend_are_not_used(self):
        with tempfile.TemporaryDirectory() as directory:
            client = SprintClient(Path(directory))
            sessions = [dict(session_name='Race', date_start='2025-03-23T07:00:00Z', meeting_key=1),
                        dict(session_name='Sprint', date_end='2099-03-22T08:00:00Z', meeting_key=1)]
            with patch.object(client, 'get', return_value=sessions) as fetch:
                self.assertEqual(client.enrich(race()).sprint_results, {})
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(client.enrich(replace(race(), date='2025-03-30')).sprint_results, {})

    def test_api_failure_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            client = SprintClient(Path(directory))
            with patch.object(client, 'get', side_effect=OSError('offline')):
                with self.assertWarns(UserWarning):
                    self.assertEqual(client.enrich(race()), race())
