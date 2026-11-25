# TLV ↔ Taiwan Daily Flight Price Agent (Oct 2027)

Autonomous daily real-fare flight monitoring agent for **1 Adult, Economy** round-trip / Taiwan open-jaw flights from **Tel Aviv (`TLV`)** to **Taiwan (`TPE`, `TSA`, `KHH`, `RMQ`)**, departing **Oct 5–9, 2027** and returning **Oct 22–24, 2027**.

## Why 06:15 `Asia/Jerusalem` Was Chosen as the Daily Run Hour

Airline GDS systems (Amadeus, Sabre, Travelport) and carrier revenue-management batch jobs recalculate fare-class availability (`Y/B/M/H/Q/V/S/L`) and publish newly opened `T-330` / `T-355` calendar inventory between `00:00` and `03:30 UTC` across European and East Asian hubs, while expired 24-hour unpaid booking holds return to inventory overnight. Running at **06:15 `Asia/Jerusalem`** (`04:15 UTC` winter / `03:15 UTC` summer) captures fresh inventory right before morning in Israel.

## Enforced Flight Rules

1. **Dates & Route**: Outbound `TLV` → Taiwan (`TPE`, `TSA`, `KHH`, `RMQ`) on `2027-10-05..2027-10-09`; Return Taiwan (`TPE`, `TSA`, `KHH`, `RMQ`) → `TLV` on `2027-10-22..2027-10-24`. Open-jaw Taiwan trips (e.g., land in `RMQ` or `TPE`, fly out of `KHH` or `TPE`) are automatically included.
2. **Zero Persian Gulf or Turkey**: Server-side and segment-by-segment blocklists reject any stopover or carrier in `TR`, `AE`, `QA`, `BH`, `KW`, `OM`, `SA`, `IR`, or `IQ`.
3. **Layover Windows & Self-Transfer Policy (`USD`)**:
   - **2.0–4.0h (Preferred)**: Single airline-protected ticket only (checked luggage transferred). Self-transfers under 4h are strictly blocked.
   - **4.0–6.0h (Acceptable)**: Benchmarked directly against the lowest `2–4h` fare; `≥4h` self-transfers are permitted and flagged.
   - **8.0–10.0h (Daytime Quick City Explore)** & **18.0–20.0h (Overnight Explore + Sleep in East Europe / `HKG` / `BKK`/`DMK`)**: Highlighted and ranked ahead of generic long layovers.
   - **Long Layovers up to 28.0h**: Accepted at any non-blocked hub (excluding Turkey, Persian Gulf, and landside-restricted self-transfer airports such as `KUL`/`CGK`).
4. **100% Real Data**: Queries live airline/OTA inventory via Kiwi's Umbrella GraphQL engine (multi-pass round-trip, hub-targeted, per-date, and independent one-way sector pairing up to 28h layovers) plus Google Flights' live protobuf engine with SOCS consent cookie support (automatically unlocking return-window fares as `2027-10-22..24` enters Google's 330-day calendar on `2026-11-26..28`).

## Quick Start

```bash
# Run an immediate live scan (updates SQLite DB, JSON snapshot, Markdown digest & HTML dashboard)
.venv/bin/python agent.py --run-now

# Run the continuous daily scheduler (06:15 Asia/Jerusalem) + live dashboard server on port 8765
.venv/bin/python agent.py --daemon --port 8765

# Check status & next scheduled run
.venv/bin/python agent.py --status

# Run unit tests
.venv/bin/pytest -q
```

## Portable Scheduling Options

- **Crontab**: `crontab deploy/cron.example`
- **systemd Timer**: Copy `deploy/flight-agent.service` and `deploy/flight-agent.timer` to `~/.config/systemd/user/` and run `systemctl --user enable --now flight-agent.timer`
- **GitHub Actions**: `.github/workflows/daily-flight-check.yml` runs automatically every day at `04:15 UTC` (`06:15 IST`), uploads HTML/JSON artifacts, and commits daily price history back to your repository.
