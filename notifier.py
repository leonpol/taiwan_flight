"""Telegram Bot push notification & auto-chat-ID discovery module."""

from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

from config import DEFAULT_CONFIG, TELEGRAM_CREDENTIALS_FILE, SearchConfig
from providers.google_flights import build_google_flights_url

log = logging.getLogger("flight-agent.notifier")


def load_telegram_credentials(cred_file: Path = TELEGRAM_CREDENTIALS_FILE) -> tuple[str, str]:
    """Load (bot_token, chat_id) from env vars or local gitignored credentials file."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id

    if cred_file.exists():
        try:
            saved = json.loads(cred_file.read_text(encoding="utf-8"))
            token = token or str(saved.get("bot_token", "")).strip()
            chat_id = chat_id or str(saved.get("chat_id", "")).strip()
        except Exception as exc:
            log.warning("Could not read %s: %s", cred_file, exc)

    return token, chat_id


def save_telegram_credentials(
    bot_token: str,
    chat_id: str,
    cred_file: Path = TELEGRAM_CREDENTIALS_FILE,
) -> None:
    payload = json.dumps({"bot_token": bot_token.strip(), "chat_id": str(chat_id).strip()}, indent=2)
    cred_file.write_text(payload, encoding="utf-8")
    os.chmod(cred_file, 0o600)


def discover_chat_id(bot_token: str, timeout: int = 15) -> tuple[str | None, str]:
    """Discover the user's numeric chat_id via getUpdates after they send /start to their bot."""
    url = f"https://api.telegram.org/bot{bot_token.strip()}/getUpdates"
    resp = requests.get(url, timeout=timeout)
    data = resp.json()
    if not data.get("ok"):
        return None, f"Telegram API error: {data.get('description', 'invalid token')}"

    results = data.get("result") or []
    for upd in reversed(results):
        msg = upd.get("message") or upd.get("edited_message") or upd.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            username = chat.get("username") or chat.get("first_name") or "Telegram user"
            return str(chat["id"]), f"Matched chat with {username} (chat_id={chat['id']})"

    return None, "No messages found yet — open your bot in Telegram and tap Start (or send 'hi'), then retry."


def classify_alert_reasons(snapshot: dict[str, Any], cfg: SearchConfig = DEFAULT_CONFIG) -> list[str]:
    """Determine whether this run triggered high-priority deal alerts."""
    reasons: list[str] = []
    summary = snapshot.get("summary") or {}
    min_strict = summary.get("min_strict_price_usd")
    if min_strict is None:
        return reasons

    if min_strict <= cfg.alert_target_usd:
        reasons.append(f"Target price hit (${min_strict} ≤ ${cfg.alert_target_usd})")

    trend = snapshot.get("daily_trend") or []
    prior_mins = [
        int(pt["min_strict_price_usd"])
        for pt in trend[:-1]
        if pt.get("min_strict_price_usd") is not None
    ]
    if prior_mins:
        historical_low = min(prior_mins)
        if min_strict < historical_low:
            reasons.append(f"New all-time low (${min_strict}, down ${historical_low - min_strict} vs prior low ${historical_low})")

    strict_matches = snapshot.get("strict_matches") or []
    biggest_drop = min(
        (int(m["price_delta_usd"]) for m in strict_matches if m.get("price_delta_usd") is not None),
        default=0,
    )
    if biggest_drop <= -cfg.alert_min_drop_usd:
        reasons.append(f"Fare dropped ${-biggest_drop} since previous check")

    return reasons


def format_telegram_message(
    snapshot: dict[str, Any],
    alert_reasons: list[str],
    cfg: SearchConfig = DEFAULT_CONFIG,
    is_test: bool = False,
) -> str:
    """Build a crisp HTML-formatted Telegram message with direct booking links."""
    s = snapshot.get("summary") or {}
    strict = snapshot.get("strict_matches") or []

    if is_test:
        header = "✅ <b>TLV ↔ Taiwan Flight Agent Connected!</b>"
    elif alert_reasons:
        header = "🔥 <b>TLV ↔ Taiwan Flight Deal Alert!</b>"
    else:
        header = f"✈️ <b>TLV ↔ Taiwan Daily Fare Check ({html.escape(snapshot.get('run_date', ''))})</b>"

    lines = [header]
    if alert_reasons:
        for r in alert_reasons:
            lines.append(f"• <b>{html.escape(r)}</b>")

    min_strict = s.get("min_strict_price_usd")
    min_ideal = s.get("min_ideal_price_usd")
    lines.append(
        f"\n<b>Summary:</b> {s.get('strict_total_count', 0)} strict matches "
        f"(Best: <b>${min_strict if min_strict else '—'}</b> | Ideal 2–4h: <b>${min_ideal if min_ideal else '—'}</b>)"
    )

    for idx, it in enumerate(strict[:3], 1):
        out_chain = "→".join(
            [it["outbound"]["segments"][0]["origin_code"]]
            + [sg["dest_code"] for sg in it["outbound"]["segments"]]
        )
        in_chain = "→".join(
            [it["inbound"]["segments"][0]["origin_code"]]
            + [sg["dest_code"] for sg in it["inbound"]["segments"]]
        )
        out_lv = ", ".join(f"{lv['arrival_airport']} {lv['duration_hours']:.1f}h" for lv in it.get("outbound_layovers", []))
        in_lv = ", ".join(f"{lv['arrival_airport']} {lv['duration_hours']:.1f}h" for lv in it.get("inbound_layovers", []))
        delta = it.get("price_delta_usd")
        delta_txt = f" ({'+' if delta > 0 else ''}${delta})" if delta else ""

        gf_url = it.get("google_flights_url") or build_google_flights_url(
            out_date=it["outbound_date"],
            in_date=it["inbound_date"],
            out_dest=it["taiwan_arrival_airport"],
            in_orig=it["taiwan_departure_airport"],
        )
        link_parts: list[str] = []
        if it.get("booking_url"):
            link_parts.append(f'<a href="{html.escape(it["booking_url"], quote=True)}">Book</a>')
        if gf_url:
            link_parts.append(f'<a href="{html.escape(gf_url, quote=True)}">Google Flights</a>')
        links_str = " · ".join(link_parts)

        badges_str = html.escape(", ".join(it.get("badges", [])[:2]))
        lines.append(
            f"\n<b>{idx}. ${it['price_usd']}{html.escape(delta_txt)}</b> · {html.escape(it['outbound_date'])} → {html.escape(it['inbound_date'])}\n"
            f"  Out: <code>{html.escape(out_chain)}</code> ({html.escape(out_lv or 'direct')})\n"
            f"  Ret: <code>{html.escape(in_chain)}</code> ({html.escape(in_lv or 'direct')})\n"
            f"  <i>{badges_str}</i>" + (f" — {links_str}" if links_str else "")
        )

    gf_horizon = ((snapshot.get("providers") or {}).get("google_flights") or {}).get("google_flights_return_unlocks_on")
    if gf_horizon:
        lines.append(f"\n<i>Daily schedule: 06:15 Asia/Jerusalem · GF 330d window opens {html.escape(gf_horizon)}</i>")

    return "\n".join(lines)


def send_telegram_notification(
    snapshot: dict[str, Any],
    cfg: SearchConfig = DEFAULT_CONFIG,
    *,
    force: bool = False,
    is_test: bool = False,
    cred_file: Path = TELEGRAM_CREDENTIALS_FILE,
) -> dict[str, Any]:
    """Send Telegram notification if configured and triggered (or forced)."""
    token, chat_id = load_telegram_credentials(cred_file)
    if not token:
        return {"sent": False, "reason": "telegram_not_configured"}

    if not chat_id:
        discovered_id, msg = discover_chat_id(token)
        if not discovered_id:
            return {"sent": False, "reason": msg}
        chat_id = discovered_id
        save_telegram_credentials(token, chat_id, cred_file)

    reasons = classify_alert_reasons(snapshot, cfg)
    should_send = force or is_test or bool(reasons) or cfg.telegram_daily_digest
    if not should_send:
        return {"sent": False, "reason": "no_deal_trigger_today"}

    text = format_telegram_message(snapshot, reasons, cfg, is_test=is_test)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    body = resp.json()
    if not body.get("ok"):
        err_desc = body.get("description", "unknown Telegram error")
        log.error("Telegram sendMessage failed: %s", err_desc)
        return {"sent": False, "reason": err_desc}

    log.info("Telegram notification sent to chat_id=%s (deal_alerts=%d)", chat_id, len(reasons))
    return {"sent": True, "chat_id": chat_id, "alert_reasons": reasons}
