#!/usr/bin/env python3
"""TLV <-> Taiwan Daily Flight Price Agent & Live Dashboard Daemon."""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from zoneinfo import ZoneInfo

from config import DEFAULT_CONFIG, REPORTS_DIR, SearchConfig
from evaluator import evaluate_itineraries
from notifier import (
    discover_chat_id,
    load_telegram_credentials,
    save_telegram_credentials,
    send_telegram_notification,
)
from providers.google_flights import fetch_google_flights_itineraries
from providers.kiwi_graphql import fetch_kiwi_itineraries
from report_generator import generate_html_dashboard, generate_markdown_report
from storage import FlightHistoryStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("flight-agent")

_RUN_LOCK = threading.Lock()


def compute_next_run(now_local: datetime, cfg: SearchConfig = DEFAULT_CONFIG) -> datetime:
    """Compute the next daily execution timestamp in cfg.schedule_timezone."""
    candidate = now_local.replace(
        hour=cfg.schedule_hour,
        minute=cfg.schedule_minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate


def run_daily_check(cfg: SearchConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    """Execute one full live flight check, persist history, and render reports."""
    with _RUN_LOCK:
        tz = ZoneInfo(cfg.schedule_timezone)
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(tz)
        next_run = compute_next_run(now_local, cfg)

        log.info(
            "Starting live flight check for TLV <-> Taiwan (%s..%s -> %s..%s)",
            cfg.outbound_start,
            cfg.outbound_end,
            cfg.inbound_start,
            cfg.inbound_end,
        )

        store = FlightHistoryStore()
        prev_prices = store.get_previous_prices()

        kiwi_raw, kiwi_meta = fetch_kiwi_itineraries(cfg)
        gf_raw, gf_meta = fetch_google_flights_itineraries(cfg, today=now_local.date())

        combined_raw = kiwi_raw + gf_raw
        evaluated = evaluate_itineraries(combined_raw, previous_prices=prev_prices, cfg=cfg)

        schedule_info = {
            "timezone": cfg.schedule_timezone,
            "daily_time": f"{cfg.schedule_hour:02d}:{cfg.schedule_minute:02d}",
            "next_scheduled_run_local": next_run.isoformat(),
            "rationale": (
                "06:15 Asia/Jerusalem captures overnight European & East Asian airline GDS "
                "fare-bucket recalculations, T-330 schedule rollovers, and expired 24h ticket holds "
                "before morning in Israel."
            ),
        }

        snapshot = store.save_run(
            run_date=now_local.date().isoformat(),
            checked_at_utc=now_utc.isoformat(),
            checked_at_local=now_local.isoformat(),
            raw_candidates=len(combined_raw),
            evaluated=evaluated,
            provider_meta={"kiwi": kiwi_meta, "google_flights": gf_meta},
            schedule_info=schedule_info,
        )

        md_path = generate_markdown_report(snapshot)
        html_path = generate_html_dashboard(snapshot)
        notify_res = send_telegram_notification(snapshot, cfg)
        snapshot["notification"] = notify_res

        s = snapshot["summary"]
        log.info(
            "Check complete: scanned=%d strict=%d (ideal=%d, acceptable=%d) watchlist=%d best_strict=$%s telegram_sent=%s",
            s["raw_candidates_scanned"],
            s["strict_total_count"],
            s["strict_ideal_count"],
            s["strict_acceptable_count"],
            s["watchlist_count"],
            s["min_strict_price_usd"],
            notify_res.get("sent"),
        )
        log.info("Reports updated: %s | %s", md_path, html_path)
        return snapshot


class DashboardHandler(BaseHTTPRequestHandler):
    cfg: SearchConfig = DEFAULT_CONFIG

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("HTTP " + fmt, *args)

    def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        store = FlightHistoryStore()
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html", "/dashboard.html"):
            dash_file = REPORTS_DIR / "dashboard.html"
            if not dash_file.exists():
                run_daily_check(self.cfg)
            body = dash_file.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/latest":
            if not store.latest_json_path.exists():
                snap = run_daily_check(self.cfg)
                self._send_json(snap)
            else:
                self._send_json(json.loads(store.latest_json_path.read_text(encoding="utf-8")))
            return

        if path == "/api/history":
            self._send_json({"daily_trend": store.get_daily_trend()})
            return

        if path == "/api/status":
            tz = ZoneInfo(self.cfg.schedule_timezone)
            now_local = datetime.now(tz)
            self._send_json(
                {
                    "status": "running",
                    "now_local": now_local.isoformat(),
                    "next_scheduled_run_local": compute_next_run(now_local, self.cfg).isoformat(),
                    "schedule": f"{self.cfg.schedule_hour:02d}:{self.cfg.schedule_minute:02d} {self.cfg.schedule_timezone}",
                }
            )
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/run-check":
            snap = run_daily_check(self.cfg)
            self._send_json(snap)
            return
        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)


def _scheduler_loop(cfg: SearchConfig) -> None:
    tz = ZoneInfo(cfg.schedule_timezone)
    store = FlightHistoryStore()

    # Run immediately on daemon boot if today's check hasn't run yet
    today_str = datetime.now(tz).date().isoformat()
    if not store.has_run_for_local_date(today_str):
        try:
            run_daily_check(cfg)
        except Exception:
            log.exception("Initial startup flight check failed")

    last_triggered_date: str | None = today_str if store.has_run_for_local_date(today_str) else None

    while True:
        try:
            now_local = datetime.now(tz)
            d_str = now_local.date().isoformat()
            due = (now_local.hour, now_local.minute) >= (cfg.schedule_hour, cfg.schedule_minute)
            if due and last_triggered_date != d_str and not store.has_run_for_local_date(d_str):
                log.info("Scheduled daily trigger reached (%s)", now_local.isoformat())
                run_daily_check(cfg)
                last_triggered_date = d_str
        except Exception:
            log.exception("Error inside daily scheduler loop")
        time.sleep(20)


def _telegram_bot_loop(cfg: SearchConfig) -> None:
    """Long-poll Telegram getUpdates so tapping Start (or sending /check) responds instantly."""
    import requests as _requests

    offset: int | None = None
    store = FlightHistoryStore()

    while True:
        try:
            token, saved_chat_id = load_telegram_credentials()
            if not token:
                time.sleep(15)
                continue

            params: dict[str, Any] = {"timeout": 20}
            if offset is not None:
                params["offset"] = offset

            resp = _requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params=params,
                timeout=26,
            )
            data = resp.json()
            if not data.get("ok"):
                time.sleep(10)
                continue

            for upd in data.get("result") or []:
                offset = int(upd["update_id"]) + 1
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                cid = str(chat.get("id") or "").strip()
                text = (msg.get("text") or "").strip().lower()
                if not cid:
                    continue

                is_first_link = not saved_chat_id
                if saved_chat_id != cid:
                    save_telegram_credentials(token, cid)
                    saved_chat_id = cid
                    log.info("Linked Telegram chat_id=%s automatically via bot message", cid)

                if is_first_link or text.startswith("/start") or text.startswith("/status"):
                    snap = (
                        json.loads(store.latest_json_path.read_text(encoding="utf-8"))
                        if store.latest_json_path.exists()
                        else run_daily_check(cfg)
                    )
                    send_telegram_notification(snap, cfg, force=True, is_test=True)
                elif text.startswith("/check"):
                    snap = run_daily_check(cfg)
                    if not snap.get("notification", {}).get("sent"):
                        send_telegram_notification(snap, cfg, force=True, is_test=False)
        except Exception:
            time.sleep(8)


def run_daemon(cfg: SearchConfig = DEFAULT_CONFIG, port: int | None = None) -> None:
    listen_port = port or cfg.dashboard_port
    sched_thread = threading.Thread(target=_scheduler_loop, args=(cfg,), daemon=True)
    sched_thread.start()
    tg_thread = threading.Thread(target=_telegram_bot_loop, args=(cfg,), daemon=True)
    tg_thread.start()

    DashboardHandler.cfg = cfg
    server = ThreadingHTTPServer(("0.0.0.0", listen_port), DashboardHandler)
    tz = ZoneInfo(cfg.schedule_timezone)
    next_run = compute_next_run(datetime.now(tz), cfg)
    log.info(
        "Flight Agent Daemon listening on http://localhost:%d | Daily check @ %02d:%02d %s (next: %s)",
        listen_port,
        cfg.schedule_hour,
        cfg.schedule_minute,
        cfg.schedule_timezone,
        next_run.isoformat(),
    )
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="TLV <-> Taiwan Daily Flight Price Agent")
    parser.add_argument("--run-now", action="store_true", help="Run a single live check immediately and exit")
    parser.add_argument("--daemon", action="store_true", help="Run daily scheduler + live HTTP dashboard server")
    parser.add_argument("--port", type=int, default=DEFAULT_CONFIG.dashboard_port, help="HTTP port for dashboard")
    parser.add_argument("--status", action="store_true", help="Print latest stored summary and next run time")
    parser.add_argument(
        "--setup-telegram",
        metavar="BOT_TOKEN",
        help="Auto-discover your Telegram chat_id from @BotFather token, save credentials, and send a test alert",
    )
    parser.add_argument("--chat-id", help="Optional explicit Telegram chat_id to pair with --setup-telegram")
    parser.add_argument("--test-telegram", action="store_true", help="Send a test Telegram alert using latest snapshot")
    args = parser.parse_args()

    cfg = DEFAULT_CONFIG
    if args.setup_telegram:
        token = args.setup_telegram.strip()
        chat_id = (args.chat_id or "").strip()
        if not chat_id:
            discovered, msg = discover_chat_id(token)
            print(msg)
            if not discovered:
                raise SystemExit(1)
            chat_id = discovered
        save_telegram_credentials(token, chat_id)
        store = FlightHistoryStore()
        snap = (
            json.loads(store.latest_json_path.read_text(encoding="utf-8"))
            if store.latest_json_path.exists()
            else run_daily_check(cfg)
        )
        res = send_telegram_notification(snap, cfg, force=True, is_test=True)
        print(json.dumps(res, indent=2))
        return

    if args.test_telegram:
        store = FlightHistoryStore()
        snap = (
            json.loads(store.latest_json_path.read_text(encoding="utf-8"))
            if store.latest_json_path.exists()
            else run_daily_check(cfg)
        )
        res = send_telegram_notification(snap, cfg, force=True, is_test=True)
        print(json.dumps(res, indent=2))
        return

    if args.status:
        store = FlightHistoryStore()
        tz = ZoneInfo(cfg.schedule_timezone)
        now_local = datetime.now(tz)
        tok, cid = load_telegram_credentials()
        print(f"Current time ({cfg.schedule_timezone}): {now_local.isoformat()}")
        print(f"Next scheduled run: {compute_next_run(now_local, cfg).isoformat()}")
        print(f"Telegram configured: {'yes (chat_id=' + cid + ')' if (tok and cid) else 'pending token'}")
        if store.latest_json_path.exists():
            snap = json.loads(store.latest_json_path.read_text(encoding="utf-8"))
            print(json.dumps(snap["summary"], indent=2))
        else:
            print("No runs recorded yet.")
        return

    if args.daemon:
        run_daemon(cfg, port=args.port)
        return

    # Default / --run-now
    snap = run_daily_check(cfg)
    print(json.dumps(snap["summary"], indent=2))


if __name__ == "__main__":
    main()
