"""SQLite + JSON historical persistence for daily flight price checks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from config import DATA_DIR
from models import EvaluatedItinerary

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    checked_at_utc TEXT NOT NULL,
    checked_at_local TEXT NOT NULL,
    raw_candidates INTEGER NOT NULL,
    strict_ideal_count INTEGER NOT NULL,
    strict_acceptable_count INTEGER NOT NULL,
    watchlist_count INTEGER NOT NULL,
    min_strict_price_usd INTEGER,
    min_ideal_price_usd INTEGER,
    min_acceptable_price_usd INTEGER,
    provider_meta_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    run_date TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    tier TEXT NOT NULL,
    price_usd INTEGER NOT NULL,
    score REAL NOT NULL,
    outbound_date TEXT NOT NULL,
    inbound_date TEXT NOT NULL,
    taiwan_arr TEXT NOT NULL,
    taiwan_dep TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_obs_fp ON observations(fingerprint);
CREATE INDEX IF NOT EXISTS idx_obs_run_date ON observations(run_date);
"""


class FlightHistoryStore:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.runs_dir = self.data_dir / "runs"
        self.db_path = self.data_dir / "flight_history.db"
        self.latest_json_path = self.data_dir / "latest_report.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def get_previous_prices(self) -> dict[str, int]:
        """Return fingerprint -> latest observed USD price from the most recent run."""
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return {}
            rows = conn.execute(
                "SELECT fingerprint, price_usd FROM observations WHERE run_id = ?",
                (row["id"],),
            ).fetchall()
            return {r["fingerprint"]: int(r["price_usd"]) for r in rows}

    def get_daily_trend(self) -> list[dict[str, Any]]:
        """Return daily minimum price history across runs (one point per calendar date)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    run_date,
                    MAX(checked_at_local) AS checked_at_local,
                    MIN(min_strict_price_usd) AS min_strict_price_usd,
                    MIN(min_ideal_price_usd) AS min_ideal_price_usd,
                    MIN(min_acceptable_price_usd) AS min_acceptable_price_usd,
                    MAX(strict_ideal_count + strict_acceptable_count) AS strict_total_count
                FROM runs
                GROUP BY run_date
                ORDER BY run_date ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def has_run_for_local_date(self, run_date: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM runs WHERE run_date = ? LIMIT 1",
                (run_date,),
            ).fetchone()
            return row is not None

    def save_run(
        self,
        *,
        run_date: str,
        checked_at_utc: str,
        checked_at_local: str,
        raw_candidates: int,
        evaluated: list[EvaluatedItinerary],
        provider_meta: dict[str, Any],
        schedule_info: dict[str, Any],
    ) -> dict[str, Any]:
        strict_ideal = [x for x in evaluated if x.tier == "STRICT_IDEAL"]
        strict_acc = [x for x in evaluated if x.tier == "STRICT_ACCEPTABLE"]
        watchlist = [x for x in evaluated if x.tier == "WATCHLIST"]
        strict_all = [x for x in evaluated if x.tier in ("STRICT_IDEAL", "STRICT_ACCEPTABLE")]

        min_strict = min((x.price_usd for x in strict_all), default=None)
        min_ideal = min((x.price_usd for x in strict_ideal), default=None)
        min_acc = min((x.price_usd for x in strict_acc), default=None)

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (
                    run_date, checked_at_utc, checked_at_local, raw_candidates,
                    strict_ideal_count, strict_acceptable_count, watchlist_count,
                    min_strict_price_usd, min_ideal_price_usd, min_acceptable_price_usd,
                    provider_meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_date,
                    checked_at_utc,
                    checked_at_local,
                    raw_candidates,
                    len(strict_ideal),
                    len(strict_acc),
                    len(watchlist),
                    min_strict,
                    min_ideal,
                    min_acc,
                    json.dumps(provider_meta),
                ),
            )
            run_id = int(cur.lastrowid)

            obs_rows = [
                (
                    run_id,
                    run_date,
                    it.fingerprint,
                    it.tier,
                    it.price_usd,
                    it.score,
                    it.outbound_date,
                    it.inbound_date,
                    it.taiwan_arrival_airport,
                    it.taiwan_departure_airport,
                    json.dumps(it.to_dict()),
                )
                for it in evaluated[:80]
            ]
            conn.executemany(
                """
                INSERT INTO observations (
                    run_id, run_date, fingerprint, tier, price_usd, score,
                    outbound_date, inbound_date, taiwan_arr, taiwan_dep, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                obs_rows,
            )

        trend = self.get_daily_trend()
        snapshot: dict[str, Any] = {
            "run_id": run_id,
            "run_date": run_date,
            "checked_at_utc": checked_at_utc,
            "checked_at_local": checked_at_local,
            "schedule": schedule_info,
            "summary": {
                "raw_candidates_scanned": raw_candidates,
                "strict_total_count": len(strict_all),
                "strict_ideal_count": len(strict_ideal),
                "strict_acceptable_count": len(strict_acc),
                "watchlist_count": len(watchlist),
                "min_strict_price_usd": min_strict,
                "min_ideal_price_usd": min_ideal,
                "min_acceptable_price_usd": min_acc,
            },
            "providers": provider_meta,
            "daily_trend": trend,
            "strict_matches": [it.to_dict() for it in strict_all[:40]],
            "watchlist_matches": [it.to_dict() for it in watchlist[:25]],
        }

        serialized = json.dumps(snapshot, indent=2)
        self.latest_json_path.write_text(serialized, encoding="utf-8")
        (self.runs_dir / f"{run_date}.json").write_text(serialized, encoding="utf-8")
        return snapshot
