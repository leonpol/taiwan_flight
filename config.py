"""Configuration for the TLV <-> Taiwan Daily Flight Price Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FLIGHT_AGENT_DATA_DIR", BASE_DIR / "data"))
REPORTS_DIR = Path(os.environ.get("FLIGHT_AGENT_REPORTS_DIR", BASE_DIR / "reports"))


@dataclass(frozen=True)
class SearchConfig:
    # Origin and destinations (Requirement 2 & 8)
    origin_airport: str = "TLV"
    taiwan_airports: tuple[str, ...] = ("TPE", "TSA", "KHH", "RMQ")
    passengers_adults: int = 1
    cabin_class: str = "ECONOMY"
    currency: str = "USD"

    # Travel window (Requirement 3: Leave TLV Oct 5-9 2027, Return Oct 22-24 2027)
    outbound_start: date = date(2027, 10, 5)
    outbound_end: date = date(2027, 10, 9)
    inbound_start: date = date(2027, 10, 22)
    inbound_end: date = date(2027, 10, 24)

    # Daily schedule (Requirement 1: 06:15 Asia/Jerusalem)
    # Chosen because:
    # 1. Overnight GDS fare-bucket recalculations & T-330/T-355 airline schedule
    #    releases (00:00-03:30 UTC across Europe & East Asia) have settled.
    # 2. Expired 24-hour unpaid booking holds return to inventory overnight.
    # 3. Fresh daily report is ready right before morning in Israel (TLV origin).
    schedule_timezone: str = os.environ.get("FLIGHT_AGENT_TZ", "Asia/Jerusalem")
    schedule_hour: int = int(os.environ.get("FLIGHT_AGENT_HOUR", "6"))
    schedule_minute: int = int(os.environ.get("FLIGHT_AGENT_MINUTE", "15"))

    # Layover rules in hours (Requirements 5, 6, 7)
    ideal_short_min_h: float = 2.0
    ideal_short_max_h: float = 4.0
    acceptable_short_max_h: float = 6.0
    min_self_transfer_h: float = 4.0
    max_layover_h: float = 28.0

    day_explore_min_h: float = 8.0
    day_explore_max_h: float = 10.0
    day_explore_min_city_h: float = 5.0  # Must allow ~5-8h actual city exploration

    overnight_explore_min_h: float = 18.0
    overnight_explore_max_h: float = 20.0

    # Price-goodness threshold: a 4-6h layover is considered "price is good"
    # if it is at least $100 cheaper than the cheapest 2-4h itinerary, OR <= $1,350 RT.
    good_price_absolute_usd: int = 1350
    good_price_savings_vs_ideal_usd: int = 100

    # Near-miss tolerance for secondary watchlist (never mixed into strict matches)
    watchlist_layover_slack_h: float = 1.25

    # HTTP / provider settings
    request_timeout_sec: int = 28
    dashboard_port: int = int(os.environ.get("FLIGHT_AGENT_PORT", "8765"))
    excluded_countries: tuple[str, ...] = field(
        default_factory=lambda: ("TR", "AE", "QA", "BH", "KW", "OM", "SA", "IR", "IQ")
    )

    # Notification / Deal-Alert settings
    alert_target_usd: int = int(os.environ.get("FLIGHT_ALERT_TARGET_USD", "1500"))
    alert_min_drop_usd: int = int(os.environ.get("FLIGHT_ALERT_MIN_DROP_USD", "50"))
    telegram_daily_digest: bool = os.environ.get("TELEGRAM_DAILY_DIGEST", "true").lower() in ("1", "true", "yes")


TELEGRAM_CREDENTIALS_FILE = BASE_DIR / ".telegram_credentials.json"
DEFAULT_CONFIG = SearchConfig()
