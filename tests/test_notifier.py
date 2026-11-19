"""Unit tests for Telegram deal-alert triggers and message formatting."""

from __future__ import annotations

from config import SearchConfig
from notifier import classify_alert_reasons, format_telegram_message


def _sample_snapshot(min_price: int = 1420, delta: int | None = -95) -> dict:
    return {
        "run_date": "2026-11-19",
        "summary": {
            "strict_total_count": 4,
            "min_strict_price_usd": min_price,
            "min_ideal_price_usd": min_price,
        },
        "daily_trend": [
            {"run_date": "2026-11-18", "min_strict_price_usd": 2213},
            {"run_date": "2026-11-19", "min_strict_price_usd": min_price},
        ],
        "strict_matches": [
            {
                "price_usd": min_price,
                "price_delta_usd": delta,
                "outbound_date": "2027-10-07",
                "inbound_date": "2027-10-24",
                "taiwan_arrival_airport": "TPE",
                "taiwan_departure_airport": "TPE",
                "badges": ["Ideal 2–4h Layovers", "Single Airline Ticket"],
                "booking_url": "https://www.kiwi.com/en/booking/?direct=true",
                "outbound": {
                    "segments": [
                        {"origin_code": "TLV", "dest_code": "BKK"},
                        {"origin_code": "BKK", "dest_code": "TPE"},
                    ]
                },
                "inbound": {
                    "segments": [
                        {"origin_code": "TPE", "dest_code": "BKK"},
                        {"origin_code": "BKK", "dest_code": "TLV"},
                    ]
                },
                "outbound_layovers": [{"arrival_airport": "BKK", "duration_hours": 3.2}],
                "inbound_layovers": [{"arrival_airport": "BKK", "duration_hours": 3.2}],
            }
        ],
        "providers": {"google_flights": {"google_flights_return_unlocks_on": "2026-11-26"}},
    }


def test_classify_alert_reasons_detects_target_all_time_low_and_drop() -> None:
    cfg = SearchConfig(alert_target_usd=1500, alert_min_drop_usd=50)
    reasons = classify_alert_reasons(_sample_snapshot(1420, -95), cfg)
    assert any("Target price hit" in r for r in reasons)
    assert any("New all-time low" in r for r in reasons)
    assert any("Fare dropped $95" in r for r in reasons)


def test_format_telegram_message_renders_valid_html_and_links() -> None:
    snap = _sample_snapshot(1420, -95)
    reasons = classify_alert_reasons(snap)
    msg = format_telegram_message(snap, reasons, is_test=False)
    assert "Flight Deal Alert!" in msg
    assert "TLV→BKK→TPE" in msg
    assert "Book</a>" in msg
    assert "Google Flights</a>" in msg
