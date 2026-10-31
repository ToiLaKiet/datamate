"""Resolve lunar dates and Tết periods from calendar.csv."""

import csv
from datetime import date
from pathlib import Path
from typing import Any


class CalendarResolver:
    def __init__(self, path: Path) -> None:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            self.rows = list(csv.DictReader(stream))

    def _match(self, *, day: int, month: int, year: int, leap: bool = False) -> date:
        matches = [date.fromisoformat(row["date"]) for row in self.rows
                   if int(row["lunar_day"]) == day
                   and int(row["lunar_month"]) == month
                   and int(row["lunar_year"]) == year
                   and row["lunar_leap"].lower() == str(leap).lower()]
        if len(matches) != 1:
            raise ValueError(f"calendar has {len(matches)} matches for lunar {day}/{month}/{year}")
        return matches[0]

    @staticmethod
    def _leap(value: Any) -> bool:
        if value in (True, False):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError("lunar leap must be true or false")

    def resolve(self, request: dict[str, Any]) -> dict[str, str]:
        """Return inclusive Gregorian start/end dates for one calendar request."""
        kind = request.get("kind")
        if kind == "lunar_date":
            day = self._match(day=int(request["day"]), month=int(request["month"]),
                              year=int(request["year"]), leap=self._leap(request.get("leap", False)))
            return {"start": day.isoformat(), "end": day.isoformat()}
        if kind == "lunar_month":
            matches = [date.fromisoformat(row["date"]) for row in self.rows
                       if int(row["lunar_month"]) == int(request["month"])
                       and int(row["lunar_year"]) == int(request["year"])
                       and row["lunar_leap"].lower() == str(self._leap(request.get("leap", False))).lower()]
            if not matches:
                raise ValueError("lunar month is outside calendar.csv")
            return {"start": min(matches).isoformat(), "end": max(matches).isoformat()}
        if kind == "tet":
            year = int(request["year"])
            start = self._match(day=23, month=12, year=year - 1)
            end = self._match(day=10, month=1, year=year)
            return {"start": start.isoformat(), "end": end.isoformat()}
        raise ValueError(f"unsupported calendar request: {kind!r}")
