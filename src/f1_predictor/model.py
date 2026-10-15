from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .data import DriverResult, Race


@dataclass
class ModelWeights:
    driver_elo: float = 0.36
    constructor_elo: float = 0.24
    recent_form: float = 0.16
    season_points: float = 0.08
    circuit_history: float = 0.08
    odds: float = 0.18
    weather: float = 0.04
    sprint_qualifying: float = 0.08
    sprint_race: float = 0.12


@dataclass
class PredictorState:
    driver_elo: defaultdict[str, float] = field(default_factory=lambda: defaultdict(lambda: 1500.0))
    constructor_elo: defaultdict[str, float] = field(default_factory=lambda: defaultdict(lambda: 1500.0))
    recent_finishes: defaultdict[str, deque[int]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=5)))
    recent_non_classifications: defaultdict[str, deque[bool]] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=6))
    )
    season_points: defaultdict[tuple[int, str], float] = field(default_factory=lambda: defaultdict(float))
    circuit_finishes: defaultdict[tuple[str, str], deque[int]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=4)))
    wet_finishes: defaultdict[str, deque[int]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=6)))


@dataclass(frozen=True)
class Prediction:
    season: int
    round: int
    race_name: str
    driver_code: str
    driver_id: str
    constructor_id: str
    predicted_rank: int
    predicted_win_probability: float
    predicted_top10_probability: float
    predicted_top10: bool
    actual_top10: bool
    actual_finish: int
    actual_points: float
    score: float


class F1Predictor:
    def __init__(self, weights: ModelWeights | None = None):
        self.weights = weights or ModelWeights()
        self.state = PredictorState()

    def predict_race(
        self,
        race: Race,
        odds: dict[tuple[int, int, str], float] | None = None,
        weather: dict[tuple[int, int], dict[str, float]] | None = None,
    ) -> list[Prediction]:
        odds = odds or {}
        weather = weather or {}
        weather_row = weather.get((race.season, race.round), {})
        scores = []
        for result in race.results:
            code = result.driver_code
            score = self._score_driver(result, race, odds, weather_row)
            scores.append((result, score))

        probabilities = _softmax([score for _, score in scores])
        ranked = sorted(zip(scores, probabilities), key=lambda item: item[0][1], reverse=True)
        cutoff_score = ranked[min(9, len(ranked) - 1)][0][1] if ranked else 0.0
        return [
            Prediction(
                season=race.season,
                round=race.round,
                race_name=race.race_name,
                driver_code=result.driver_code,
                driver_id=result.driver_id,
                constructor_id=result.constructor_id,
                predicted_rank=index + 1,
                predicted_win_probability=probability,
                predicted_top10_probability=_sigmoid((score - cutoff_score) * 8.0),
                predicted_top10=index < 10,
                actual_top10=result.finish_position <= 10,
                actual_finish=result.finish_position,
                actual_points=result.points,
                score=score,
            )
            for index, ((result, score), probability) in enumerate(ranked)
        ]

    def update(self, race: Race, weather: dict[tuple[int, int], dict[str, float]] | None = None) -> None:
        weather = weather or {}
        weather_row = weather.get((race.season, race.round), {})
        results = sorted(race.results, key=lambda item: item.finish_position)
        strength_results: list[DriverResult] = []
        for result in results:
            include_for_strength = result.classified or self._has_repeat_non_classification(result.driver_code)
            if include_for_strength:
                strength_results.append(result)
                self.state.recent_finishes[result.driver_code].append(result.finish_position)
                self.state.circuit_finishes[(race.circuit_id, result.driver_code)].append(result.finish_position)
                if weather_row.get("rain_probability", 0.0) >= 0.35:
                    self.state.wet_finishes[result.driver_code].append(result.finish_position)

            self.state.season_points[(race.season, result.driver_code)] += result.points
            self.state.recent_non_classifications[result.driver_code].append(not result.classified)

        self._update_elo(strength_results, lambda row: row.driver_code, self.state.driver_elo, k=18.0)
        self._update_elo(strength_results, lambda row: row.constructor_id, self.state.constructor_elo, k=10.0)

    def _has_repeat_non_classification(self, driver_code: str) -> bool:
        return sum(self.state.recent_non_classifications[driver_code]) >= 2

    def _score_driver(
        self,
        result: DriverResult,
        race: Race,
        odds: dict[tuple[int, int, str], float],
        weather_row: dict[str, float],
    ) -> float:
        odds_probability = odds.get((race.season, race.round, result.driver_code), 0.0)
        recent_score = _finish_score(self.state.recent_finishes[result.driver_code], default=0.45)
        circuit_score = _finish_score(self.state.circuit_finishes[(race.circuit_id, result.driver_code)], default=0.5)
        season_score = min(self.state.season_points[(race.season, result.driver_code)] / 250.0, 1.0)
        rain_probability = weather_row.get("rain_probability", 0.0)
        wet_score = _finish_score(self.state.wet_finishes[result.driver_code], default=0.5)
        weather_score = rain_probability * wet_score

        return (
            self.weights.driver_elo * _elo_score(self.state.driver_elo[result.driver_code])
            + self.weights.constructor_elo * _elo_score(self.state.constructor_elo[result.constructor_id])
            + self.weights.recent_form * recent_score
            + self.weights.season_points * season_score
            + self.weights.circuit_history * circuit_score
            + self.weights.odds * odds_probability
            + self.weights.weather * weather_score
            + self.weights.sprint_qualifying * _session_score(race.sprint_qualifying, result.driver_code)
            + self.weights.sprint_race * _session_score(race.sprint_results, result.driver_code)
        )

    @staticmethod
    def _update_elo(
        results: list[DriverResult],
        key_fn,
        ratings: defaultdict[str, float],
        k: float,
    ) -> None:
        deltas: defaultdict[str, float] = defaultdict(float)
        for i, better in enumerate(results):
            better_key = key_fn(better)
            for worse in results[i + 1 :]:
                worse_key = key_fn(worse)
                if better_key == worse_key:
                    continue
                expected = 1.0 / (1.0 + 10.0 ** ((ratings[worse_key] - ratings[better_key]) / 400.0))
                change = k * (1.0 - expected) / max(len(results) - 1, 1)
                deltas[better_key] += change
                deltas[worse_key] -= change
        for key, delta in deltas.items():
            ratings[key] += delta


def _elo_score(rating: float) -> float:
    return 1.0 / (1.0 + math.exp(-(rating - 1500.0) / 140.0))


def _finish_score(finishes: deque[int], default: float) -> float:
    if not finishes:
        return default
    avg = sum(finishes) / len(finishes)
    return 1.0 - (min(avg, 20.0) - 1.0) / 19.0


def _softmax(scores: list[float]) -> list[float]:
    if not scores:
        return []
    scale = 7.5
    max_score = max(scores)
    exp_scores = [math.exp((score - max_score) * scale) for score in scores]
    total = sum(exp_scores)
    return [score / total for score in exp_scores]


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _session_score(positions: dict[str, int], code: str) -> float:
    # Missing drivers receive a neutral signal; absent sessions change no scores.
    if not positions:
        return 0.0
    position = positions.get(code)
    if position is None:
        return 0.0
    field_size = max(max(positions.values()), len(positions), 2)
    return 0.5 - (position - 1) / (field_size - 1)
