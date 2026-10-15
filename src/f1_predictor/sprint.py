"""Optional, same-weekend sprint classifications from OpenF1 (2023 onward)."""
from __future__ import annotations

import json
import urllib.request
import warnings
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .data import Race


class SprintClient:
    def __init__(self, cache_dir: Path, refresh_cache: bool = False):
        self.cache_dir = cache_dir
        self.refresh_cache = refresh_cache
        self.sessions: dict[int, list[dict]] = {}
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, endpoint: str, **params) -> list[dict]:
        query = urlencode(params)
        path = self.cache_dir / f"openf1_{endpoint}_{query}.json"
        # Short TTL keeps upcoming session lists and unpublished results fresh.
        if path.exists() and not self.refresh_cache and datetime.now().timestamp() - path.stat().st_mtime < 3600:
            return json.loads(path.read_text())
        request = urllib.request.Request(
            f"https://api.openf1.org/v1/{endpoint}?{query}",
            headers={"User-Agent": "f1-result-predictor/0.1"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            rows = json.load(response)
        if rows:  # Never cache results that have not been published yet.
            path.write_text(json.dumps(rows))
        return rows

    def enrich(self, race: Race) -> Race:
        if race.season < 2023:
            return race
        try:
            if race.season not in self.sessions:
                self.sessions[race.season] = self.get("sessions", year=race.season)
            sessions = self.sessions[race.season]
            # Match the GP date, then its meeting key; never use a nearby weekend.
            gps = [s for s in sessions if s["session_name"] == "Race"
                   and s["date_start"][:10] == race.date]
            if len(gps) != 1:
                return race
            gp = gps[0]
            now = datetime.now(timezone.utc)
            positions = {}
            for session in sessions:
                name = session["session_name"]
                if session["meeting_key"] != gp["meeting_key"] or name not in {"Sprint", "Sprint Qualifying", "Sprint Shootout"}:
                    continue
                if session.get("is_cancelled"):
                    continue
                end = datetime.fromisoformat(session["date_end"].replace("Z", "+00:00"))
                gp_start = datetime.fromisoformat(gp["date_start"].replace("Z", "+00:00"))
                if end > now or end >= gp_start:
                    continue
                try:
                    rows = self.get("session_result", session_key=session["session_key"])
                    if not rows:
                        continue
                    drivers = self.get("drivers", session_key=session["session_key"])
                    codes = {d["driver_number"]: (d.get("name_acronym") or "").upper() for d in drivers}
                    standings = {
                        codes[row["driver_number"]]: int(row["position"])
                        for row in rows
                        if row.get("position") and codes.get(row["driver_number"])
                    }
                    positions["sprint_results" if name == "Sprint" else "sprint_qualifying"] = standings
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    warnings.warn(f"Sprint data unavailable for {race.race_name} {name}: {exc}")
            return replace(race, **positions)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.warn(f"Sprint data unavailable for {race.season} {race.race_name}: {exc}")
            return race
