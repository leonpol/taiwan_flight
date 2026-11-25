"""Live Google Flights provider (via protobuf ?tfs= queries & ds:1 payload parser)."""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any

from fast_flights import FlightQuery, Passengers, create_query, fetch_flights_html
from fast_flights.integrations.base import FetchIntegration
from primp import Client
from selectolax.lexbor import LexborHTMLParser

from airports import AIRPORT_CITY_PROFILES, OVERNIGHT_18_20H_AIRPORTS, TAIWAN_AIRPORTS
from config import DEFAULT_CONFIG, SearchConfig
from evaluator import evaluate_sector
from models import FlightSector, FlightSegment, RawItinerary

_DS1_RE = re.compile(r"data:(\[.*\]),\s*(?:sideChannel|errorHasStatus)", re.DOTALL)
GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"
GOOGLE_FLIGHTS_MAX_ADVANCE_DAYS = 330
# Essential-only Google consent cookie so EU/EEA runners skip the consent.google.com
# interstitial and receive the ds:1 flight payload.
DEFAULT_GOOGLE_SOCS_COOKIE = "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg"


class _SocsFetchIntegration(FetchIntegration):
    """fast-flights FetchIntegration that attaches Google's SOCS consent cookie."""

    def __init__(self, timeout: int = 28, socs_cookie: str | None = None) -> None:
        self.timeout = timeout
        if socs_cookie is None:
            socs_cookie = os.environ.get("GOOGLE_SOCS_COOKIE", DEFAULT_GOOGLE_SOCS_COOKIE).strip()
        self.socs_cookie = socs_cookie

    def fetch_html(self, q: Any, /) -> str:
        cookies = {"SOCS": self.socs_cookie} if self.socs_cookie else None
        client = Client(
            impersonate="chrome_145",
            impersonate_os="macos",
            referer=True,
            cookie_store=True,
            cookies=cookies,
            timeout=self.timeout,
        )
        params = q.params() if hasattr(q, "params") else {"q": str(q)}
        res = client.get(GOOGLE_FLIGHTS_URL, params=params)
        return res.text


def build_google_flights_url(
    out_date: str,
    in_date: str,
    out_dest: str,
    in_orig: str,
    origin: str = "TLV",
    currency: str = "USD",
) -> str:
    """Build a direct clickable Google Flights round-trip or open-jaw multi-city URL."""
    if out_dest == in_orig:
        q = create_query(
            flights=[
                FlightQuery(date=out_date, from_airport=origin, to_airport=out_dest),
                FlightQuery(date=in_date, from_airport=in_orig, to_airport=origin),
            ],
            seat="economy",
            trip="round-trip",
            passengers=Passengers(adults=1),
            currency=currency,
            language="en",
        )
    else:
        q = create_query(
            flights=[
                FlightQuery(date=out_date, from_airport=origin, to_airport=out_dest),
                FlightQuery(date=in_date, from_airport=in_orig, to_airport=origin),
            ],
            seat="economy",
            trip="multi-city",
            passengers=Passengers(adults=1),
            currency=currency,
            language="en",
        )
    return q.url()


def _fmt_dt(date_arr: list[int], time_arr: list[int | None] | None) -> str:
    padded = [*(time_arr or []), None, None]
    hh = padded[0] or 0
    mm = padded[1] or 0
    return f"{date_arr[0]:04d}-{date_arr[1]:02d}-{date_arr[2]:02d}T{hh:02d}:{mm:02d}:00"


def _infer_city_country(code: str, fallback_name: str = "") -> tuple[str, str]:
    if code in AIRPORT_CITY_PROFILES:
        p = AIRPORT_CITY_PROFILES[code]
        return p.city, p.country
    if code in OVERNIGHT_18_20H_AIRPORTS:
        return OVERNIGHT_18_20H_AIRPORTS[code], ""
    if code in TAIWAN_AIRPORTS:
        return TAIWAN_AIRPORTS[code], "TW"
    if code == "TLV":
        return "Tel Aviv", "IL"
    return fallback_name, ""


def _parse_gf_oneway_html(
    html: str,
    query_url: str,
    is_single_ticket_query: bool,
) -> tuple[list[tuple[int, int, FlightSector, str]], str | None]:
    parser = LexborHTMLParser(html)
    script = parser.css_first(r"script.ds\:1")
    if not script:
        if "consent.google.com" in html:
            return [], "google_consent_wall"
        return [], "missing_ds1_script"
    m = _DS1_RE.search(script.text())
    if not m:
        return [], "ds1_regex_miss"
    payload = json.loads(m.group(1))
    if len(payload) <= 3:
        return [], "outside_330d_google_horizon"

    best = (payload[2] or [None])[0] or []
    other = (payload[3] or [None])[0] or []
    items = best + other

    results: list[tuple[int, int, FlightSector, str]] = []
    for item in items:
        try:
            fl = item[0]
            price_block = item[1]
            if not price_block or not price_block[0] or price_block[0][1] is None:
                continue
            price_usd = int(round(float(price_block[0][1])))
            layovers_raw = fl[13] if len(fl) > 13 and fl[13] else []

            segs: list[FlightSegment] = []
            for idx, s in enumerate(fl[2]):
                orig_code = s[3]
                orig_name = s[4] or orig_code
                dest_name = s[5] or s[6]
                dest_code = s[6]
                dep_iso = _fmt_dt(s[20], s[8])
                arr_iso = _fmt_dt(s[21], s[10])
                dur_min = int(s[11] or 0)
                c_info = s[22] if len(s) > 22 and s[22] else ["", "", None, ""]
                c_code = str(c_info[0] or "")
                f_num = str(c_info[1] or "")
                c_name = str(c_info[3] or "")

                lv_min: int | None = None
                is_recheck = False
                if idx > 0 and (idx - 1) < len(layovers_raw):
                    lv_entry = layovers_raw[idx - 1]
                    lv_min = int(lv_entry[0])
                    if lv_entry[1] != lv_entry[2]:
                        is_recheck = True
                if not is_single_ticket_query and idx > 0:
                    # Only mark self-transfer if Google flagged separate tickets
                    sep_flag = bool(fl[12]) if len(fl) > 12 and fl[12] else False
                    is_recheck = is_recheck or sep_flag

                orig_city, orig_cc = _infer_city_country(orig_code, orig_name)
                dest_city, dest_cc = _infer_city_country(dest_code, dest_name)

                segs.append(
                    FlightSegment(
                        carrier_code=c_code,
                        carrier_name=c_name,
                        flight_number=f_num,
                        operating_carrier=c_code,
                        origin_code=orig_code,
                        origin_name=orig_name,
                        origin_city=orig_city,
                        origin_country=orig_cc,
                        dest_code=dest_code,
                        dest_name=dest_name,
                        dest_city=dest_city,
                        dest_country=dest_cc,
                        departure_local=dep_iso,
                        arrival_local=arr_iso,
                        duration_minutes=dur_min,
                        layover_before_minutes=lv_min,
                        is_baggage_recheck_before=is_recheck,
                    )
                )

            total_dur = int(fl[9] or sum(sg.duration_minutes + (sg.layover_before_minutes or 0) for sg in segs))
            pnr = 1 if is_single_ticket_query else 2
            results.append((price_usd, pnr, FlightSector(segments=segs, total_duration_minutes=total_dur), query_url))
        except Exception:
            continue
    return results, None


def _query_gf_oneway(
    dep_date: str,
    orig: str,
    dest: str,
    hide_self_transfer: bool,
    cfg: SearchConfig,
) -> tuple[str, list[tuple[int, int, FlightSector, str]], str | None]:
    label = f"{orig}>{dest}@{dep_date}{'_single' if hide_self_transfer else '_all'}"
    try:
        q = create_query(
            flights=[FlightQuery(date=dep_date, from_airport=orig, to_airport=dest, max_stops=2)],
            seat="economy",
            trip="one-way",
            passengers=Passengers(adults=cfg.passengers_adults),
            currency=cfg.currency,
            language="en",
            hide_separate_and_self_transfer=hide_self_transfer,
        )
        fetcher = _SocsFetchIntegration(timeout=cfg.request_timeout_sec)
        secs: list[tuple[int, int, FlightSector, str]] = []
        status_err: str | None = None
        for attempt in range(2):
            html = fetch_flights_html(q, fetch_integration=fetcher)
            secs, status_err = _parse_gf_oneway_html(html, q.url(), hide_self_transfer)
            if status_err != "missing_ds1_script" or attempt == 1:
                break
            time.sleep(0.6)
        return label, secs, status_err
    except Exception as exc:
        return label, [], str(exc)


def fetch_google_flights_itineraries(
    cfg: SearchConfig = DEFAULT_CONFIG,
    today: date | None = None,
) -> tuple[list[RawItinerary], dict[str, Any]]:
    """Query Google Flights for outbound + inbound sectors when within 330-day window."""
    today = today or date.today()
    days_to_out_start = (cfg.outbound_start - today).days
    days_to_in_start = (cfg.inbound_start - today).days
    days_to_in_end = (cfg.inbound_end - today).days

    in_unlock_date = cfg.inbound_start - timedelta(days=GOOGLE_FLIGHTS_MAX_ADVANCE_DAYS)
    full_unlock_date = cfg.inbound_end - timedelta(days=GOOGLE_FLIGHTS_MAX_ADVANCE_DAYS)

    tasks: list[tuple[str, str, str, bool]] = []
    # Check primary Taiwan gateways (TPE & KHH) on dates inside 330-day horizon
    primary_tw = ("TPE", "KHH")

    cur = cfg.outbound_start
    while cur <= cfg.outbound_end:
        if (cur - today).days <= GOOGLE_FLIGHTS_MAX_ADVANCE_DAYS:
            for tw in primary_tw:
                tasks.append((cur.isoformat(), cfg.origin_airport, tw, True))
        cur += timedelta(days=1)

    cur_in = cfg.inbound_start
    while cur_in <= cfg.inbound_end:
        if (cur_in - today).days <= GOOGLE_FLIGHTS_MAX_ADVANCE_DAYS:
            for tw in primary_tw:
                tasks.append((cur_in.isoformat(), tw, cfg.origin_airport, True))
        cur_in += timedelta(days=1)

    out_secs: list[tuple[int, int, FlightSector, str]] = []
    in_secs: list[tuple[int, int, FlightSector, str]] = []
    notes: list[str] = []

    if tasks:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [
                pool.submit(_query_gf_oneway, d_str, orig, dst, hide_st, cfg)
                for (d_str, orig, dst, hide_st) in tasks
            ]
            for fut in as_completed(futs):
                lbl, secs, err = fut.result()
                if err and err not in ("outside_330d_google_horizon",):
                    notes.append(f"{lbl}: {err}")
                if lbl.startswith(f"{cfg.origin_airport}>"):
                    out_secs.extend(secs)
                else:
                    in_secs.extend(secs)

    valid_out = [x for x in out_secs if evaluate_sector(x[2], cfg)[1]]
    valid_in = [x for x in in_secs if evaluate_sector(x[2], cfg)[1]]

    paired: list[RawItinerary] = []
    for o_price, o_pnr, o_sec, o_url in sorted(valid_out, key=lambda x: x[0])[:12]:
        for i_price, i_pnr, i_sec, i_url in sorted(valid_in, key=lambda x: x[0])[:12]:
            paired.append(
                RawItinerary(
                    source_provider="google_flights",
                    price_usd=o_price + i_price,
                    pnr_count=o_pnr + i_pnr,
                    ticket_structure="split_outbound_inbound",
                    outbound=o_sec,
                    inbound=i_sec,
                    booking_url=o_url,
                    inbound_booking_url=i_url,
                )
            )

    if days_to_in_start > GOOGLE_FLIGHTS_MAX_ADVANCE_DAYS:
        horizon_status = (
            f"Return window ({cfg.inbound_start}..{cfg.inbound_end}) is {days_to_in_start}–{days_to_in_end} days out; "
            f"Google Flights' 330-day window unlocks {in_unlock_date.isoformat()} through {full_unlock_date.isoformat()}."
        )
    else:
        horizon_status = "Outbound and inbound windows active inside Google Flights 330-day horizon."

    meta = {
        "provider": "google_flights",
        "status": "ok" if paired else ("awaiting_330d_return_window" if days_to_in_start > GOOGLE_FLIGHTS_MAX_ADVANCE_DAYS else "no_pairs_yet"),
        "days_until_outbound_start": days_to_out_start,
        "days_until_inbound_start": days_to_in_start,
        "google_flights_return_unlocks_on": in_unlock_date.isoformat(),
        "google_flights_full_window_unlocks_on": full_unlock_date.isoformat(),
        "horizon_note": horizon_status,
        "outbound_candidates": len(out_secs),
        "inbound_candidates": len(in_secs),
        "paired_itineraries": len(paired),
        "notes": notes[:5],
    }
    return paired, meta
