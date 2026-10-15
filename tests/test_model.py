import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from f1_predictor.backtest import run_backtest
from f1_predictor.data import DriverResult, Race
from f1_predictor.model import F1Predictor


def make_result(season, round_, race, circuit, code, constructor, finish, points, classified=True):
    return DriverResult(
        season=season,
        round=round_,
        race_name=race,
        circuit_id=circuit,
        driver_id=code.lower(),
        driver_code=code,
        constructor_id=constructor,
        finish_position=finish,
        classified=classified,
        points=points,
    )


class PredictorTests(unittest.TestCase):
    def test_predictor_ranks_strong_recent_driver_first(self):
        race_1 = Race(
            season=2024,
            round=1,
            race_name="Opening GP",
            circuit_id="test",
            date="2024-01-01",
            latitude=0.0,
            longitude=0.0,
            results=[
                make_result(2024, 1, "Opening GP", "test", "AAA", "team_a", 1, 25),
                make_result(2024, 1, "Opening GP", "test", "BBB", "team_b", 2, 18),
            ],
        )
        race_2 = Race(
            season=2024,
            round=2,
            race_name="Second GP",
            circuit_id="test2",
            date="2024-01-08",
            latitude=0.0,
            longitude=0.0,
            results=[
                make_result(2024, 2, "Second GP", "test2", "AAA", "team_a", 1, 25),
                make_result(2024, 2, "Second GP", "test2", "BBB", "team_b", 2, 18),
            ],
        )

        predictor = F1Predictor()
        predictor.update(race_1)
        predictions = predictor.predict_race(race_2)

        self.assertEqual(predictions[0].driver_code, "AAA")
        self.assertGreater(predictions[0].predicted_win_probability, predictions[1].predicted_win_probability)

    def test_backtest_summary_counts_target_season_only(self):
        races = [
            Race(
                season=2024,
                round=1,
                race_name="Training GP",
                circuit_id="a",
                date="2024-01-01",
                latitude=0.0,
                longitude=0.0,
                results=[
                    make_result(2024, 1, "Training GP", "a", "AAA", "team_a", 1, 25),
                    make_result(2024, 1, "Training GP", "a", "BBB", "team_b", 2, 18),
                ],
            ),
            Race(
                season=2025,
                round=1,
                race_name="Target GP",
                circuit_id="b",
                date="2025-01-01",
                latitude=0.0,
                longitude=0.0,
                results=[
                    make_result(2025, 1, "Target GP", "b", "AAA", "team_a", 1, 25),
                    make_result(2025, 1, "Target GP", "b", "BBB", "team_b", 2, 18),
                ],
            ),
        ]

        predictions, summary = run_backtest(races, {2025})

        self.assertEqual(len(predictions), 2)
        self.assertEqual(summary["races"], 1.0)
        self.assertEqual(summary["top10_recall"], 1.0)
        self.assertEqual(summary["mean_average_precision_at_10"], 1.0)
        self.assertEqual(summary["winner_accuracy"], 1.0)

    def test_isolated_dnf_does_not_damage_strength_history(self):
        predictor = F1Predictor()
        race = Race(
            season=2025,
            round=1,
            race_name="DNF GP",
            circuit_id="a",
            date="2025-01-01",
            latitude=0.0,
            longitude=0.0,
            results=[
                make_result(2025, 1, "DNF GP", "a", "AAA", "team_a", 20, 0, classified=False),
                make_result(2025, 1, "DNF GP", "a", "BBB", "team_b", 1, 25),
            ],
        )

        predictor.update(race)

        self.assertEqual(list(predictor.state.recent_finishes["AAA"]), [])
        self.assertEqual(list(predictor.state.recent_non_classifications["AAA"]), [True])

    def test_repeated_dnf_counts_as_reliability_pattern(self):
        predictor = F1Predictor()
        for round_ in range(1, 4):
            race = Race(
                season=2025,
                round=round_,
                race_name=f"DNF GP {round_}",
                circuit_id="a",
                date="2025-01-01",
                latitude=0.0,
                longitude=0.0,
                results=[
                    make_result(2025, round_, f"DNF GP {round_}", "a", "AAA", "team_a", 20, 0, classified=False),
                    make_result(2025, round_, f"DNF GP {round_}", "a", "BBB", "team_b", 1, 25),
                ],
            )
            predictor.update(race)

        self.assertEqual(list(predictor.state.recent_finishes["AAA"]), [20])
        self.assertEqual(list(predictor.state.recent_non_classifications["AAA"]), [True, True, True])


if __name__ == "__main__":
    unittest.main()
